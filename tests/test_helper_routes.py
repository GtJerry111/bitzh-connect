import json
import subprocess

from privileged_helper.routes import DirectRouteManager, parse_default_route


def _cp(args, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, code, stdout=stdout, stderr=stderr)


def test_parse_default_route():
    text = "route to: default\ngateway: 10.0.0.1\ninterface: en0\n"
    assert parse_default_route(text) == ("10.0.0.1", "en0")


def test_apply_success_and_state_file(tmp_path):
    calls = []

    def runner(args):
        calls.append(args)
        if args[:4] == ["route", "-n", "get", "default"]:
            return _cp(args, stdout="gateway: 10.0.0.1\ninterface: en0\n")
        return _cp(args, 0)

    state = tmp_path / "routes.json"
    manager = DirectRouteManager(state_path=str(state), runner=runner)
    attempts, gateway, interface, error = manager.apply(
        ["10.182.37.18", "10.182.37.19"]
    )
    assert error is None
    assert gateway == "10.0.0.1"
    assert interface == "en0"
    assert all(a.ok for a in attempts)
    assert json.loads(state.read_text())["ips"] == ["10.182.37.18", "10.182.37.19"]


def test_apply_rejects_tun_default_gateway(tmp_path):
    def runner(args):
        return _cp(args, stdout="gateway: 198.18.0.1\ninterface: utun5\n")

    manager = DirectRouteManager(state_path=str(tmp_path / "r.json"), runner=runner)
    attempts, gateway, interface, error = manager.apply(["10.182.37.18"])
    assert attempts == []
    assert gateway is None
    assert interface == "utun5"
    assert error == "no_physical_default_gateway"


def test_apply_treats_file_exists_with_same_gateway_as_success(tmp_path):
    def runner(args):
        if args[:4] == ["route", "-n", "get", "default"]:
            return _cp(args, stdout="gateway: 10.0.0.1\ninterface: en0\n")
        if args[3] == "add":
            return _cp(args, 1, stderr="route: writing to routing socket: File exists")
        if args[3] == "get":
            return _cp(args, stdout="gateway: 10.0.0.1\ninterface: en0\n")
        return _cp(args, 0)

    manager = DirectRouteManager(state_path=str(tmp_path / "r.json"), runner=runner)
    attempts, _, _, error = manager.apply(["10.182.37.18"])
    assert error is None
    assert attempts[0].ok is True


def test_cleanup_stale_deletes_state_ips(tmp_path):
    state = tmp_path / "routes.json"
    state.write_text(json.dumps({"gateway": "10.0.0.1", "ips": ["10.182.37.18"]}))
    calls = []

    def runner(args):
        calls.append(args)
        return _cp(args, 0)

    manager = DirectRouteManager(state_path=str(state), runner=runner)
    manager.cleanup_stale()
    assert ["route", "-n", "delete", "-host", "10.182.37.18"] in calls
    assert not state.exists()
