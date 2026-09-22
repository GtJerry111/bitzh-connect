import json

from privileged_helper import protocol as hp


def test_socket_and_install_paths_are_absolute():
    assert hp.SOCKET_PATH.startswith("/")
    assert hp.HELPER_DIR.startswith("/Library/PrivilegedHelperTools")
    assert hp.HELPER_BIN.startswith(hp.HELPER_DIR)
    assert hp.KERNEL_BIN.startswith(hp.HELPER_DIR)
    assert hp.LAUNCHD_PLIST.startswith("/Library/LaunchDaemons")


def test_encode_is_single_newline_terminated_json():
    data = hp.encode({"cmd": "start", "args": ["-a", "b"]})
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1
    assert json.loads(data.decode("utf-8"))["args"] == ["-a", "b"]


def test_command_constants_distinct():
    cmds = {hp.CMD_HELLO, hp.CMD_PING, hp.CMD_STATUS, hp.CMD_START, hp.CMD_STOP}
    assert len(cmds) == 5


def test_protocol_version_is_int():
    assert isinstance(hp.PROTOCOL_VERSION, int)
    assert hp.PROTOCOL_VERSION >= 1
