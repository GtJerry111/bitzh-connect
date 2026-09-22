import os
import tempfile
import threading
import time

from privileged_helper import protocol as hp
from privileged_helper.server import HelperServer
from utils import helper_client as hc


def _short_socket_path():
    fd, path = tempfile.mkstemp(prefix="hz-", suffix=".sock", dir="/tmp")
    os.close(fd)
    os.unlink(path)
    return path


def _fake_kernel(tmp_path):
    script = os.path.join(tmp_path, "fake-kernel.sh")
    with open(script, "w") as f:
        f.write("#!/bin/sh\nexec sleep 300\n")
    os.chmod(script, 0o755)
    return script


def _running_server(tmp_path):
    sock = _short_socket_path()
    server = HelperServer(
        socket_path=sock, allowed_uid=os.getuid(), kernel_path=_fake_kernel(tmp_path)
    )
    server._peer_uid = staticmethod(lambda conn: os.getuid())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.time() + 5
    while not os.path.exists(sock) and time.time() < deadline:
        time.sleep(0.05)
    return server, sock


def test_hello_returns_version(tmp_path):
    server, sock = _running_server(tmp_path)
    assert hc.helper_version(sock) == hp.PROTOCOL_VERSION
    assert hc.is_available(sock) is True
    server.stop_kernel()


def test_start_stop_roundtrip(tmp_path):
    server, sock = _running_server(tmp_path)
    log_path = os.path.join(tmp_path, "k.log")
    pid_path = os.path.join(tmp_path, "k.pid")
    stop_path = os.path.join(tmp_path, "k.stop")

    resp = hc.start([], log_path, pid_path, stop_path, socket_path=sock)
    assert resp["ok"] is True
    assert hc.status(sock)["running"] is True
    assert hc.stop(sock)["ok"] is True


def test_unavailable_socket_returns_none(tmp_path):
    assert hc.helper_version("/tmp/definitely-not-there.sock") is None
    assert hc.is_available("/tmp/definitely-not-there.sock") is False


def test_non_dict_response_returns_none(monkeypatch):
    monkeypatch.setattr(hc, "_request", lambda *args, **kwargs: 123)
    assert hc.helper_version("/any") is None
    assert hc.is_available("/any") is False
