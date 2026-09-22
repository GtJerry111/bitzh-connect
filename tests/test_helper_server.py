import json
import os
import socket
import tempfile
import time

import pytest

from privileged_helper import protocol as hp
from privileged_helper.server import HelperServer


def _short_socket_path():
    # macOS AF_UNIX 路径上限 104 字节，pytest tmp_path 过长，直接放 /tmp
    fd, path = tempfile.mkstemp(prefix="hz-", suffix=".sock", dir="/tmp")
    os.close(fd)
    os.unlink(path)
    return path


class _FakeKernel:
    """假内核脚本：被 SIGTERM 杀死前一直存活。"""

    def __init__(self, tmp_path):
        self.script = os.path.join(tmp_path, "fake-kernel.sh")
        with open(self.script, "w") as f:
            f.write("#!/bin/sh\necho fake-kernel-started\nexec sleep 300\n")
        os.chmod(self.script, 0o755)


def _server(tmp_path, fake):
    return HelperServer(
        socket_path=_short_socket_path(),
        allowed_uid=os.getuid(),
        kernel_path=fake.script,
    )


def test_start_launches_kernel_writes_pid_and_log(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    log_path = os.path.join(tmp_path, "k.log")
    pid_path = os.path.join(tmp_path, "k.pid")
    stop_path = os.path.join(tmp_path, "k.stop")

    resp = server.start_kernel([], log_path, pid_path, stop_path)
    assert resp["ok"] is True
    pid = resp["pid"]
    assert os.path.exists(pid_path)
    with open(pid_path) as f:
        assert int(f.read()) == pid
    server.stop_kernel()


def test_stop_marker_terminates_kernel(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    log_path = os.path.join(tmp_path, "k.log")
    pid_path = os.path.join(tmp_path, "k.pid")
    stop_path = os.path.join(tmp_path, "k.stop")

    server.start_kernel([], log_path, pid_path, stop_path)
    assert server.status()["running"] is True
    with open(stop_path, "w"):
        pass
    deadline = time.time() + 5
    while time.time() < deadline and server.status()["running"]:
        time.sleep(0.1)
    assert server.status()["running"] is False


def test_double_start_returns_error(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    args = ([], os.path.join(tmp_path, "k.log"),
            os.path.join(tmp_path, "k.pid"), os.path.join(tmp_path, "k.stop"))
    assert server.start_kernel(*args)["ok"] is True
    second = server.start_kernel(*args)
    assert second["ok"] is False
    assert second["error"] == "already_running"
    server.stop_kernel()


def test_dispatch_hello_and_unknown(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    assert server.dispatch({"cmd": hp.CMD_HELLO})["version"] == hp.PROTOCOL_VERSION
    bogus = server.dispatch({"cmd": "bogus"})
    assert bogus["ok"] is False
    assert bogus["error"] == "unknown_command"


def test_socket_end_to_end_and_peer_uid(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    # 单测环境无法保证 macOS 原生 peer-cred 可用 → 注入返回本进程 uid
    server._peer_uid = staticmethod(lambda conn: os.getuid())

    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.time() + 5
    while not os.path.exists(server._socket_path) and time.time() < deadline:
        time.sleep(0.05)

    def rpc(payload):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(server._socket_path)
        s.sendall(hp.encode(payload))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data.decode("utf-8"))

    assert rpc({"cmd": hp.CMD_HELLO})["version"] == hp.PROTOCOL_VERSION
    log_path = os.path.join(tmp_path, "k.log")
    pid_path = os.path.join(tmp_path, "k.pid")
    stop_path = os.path.join(tmp_path, "k.stop")
    assert rpc({
        "cmd": hp.CMD_START, "args": [],
        "log_path": log_path, "pid_path": pid_path, "stop_path": stop_path,
    })["ok"] is True
    assert rpc({"cmd": hp.CMD_STATUS})["running"] is True
    assert rpc({"cmd": hp.CMD_STOP})["ok"] is True


def test_forbidden_when_peer_uid_mismatch(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    server._peer_uid = staticmethod(lambda conn: os.getuid() + 12345)

    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.time() + 5
    while not os.path.exists(server._socket_path) and time.time() < deadline:
        time.sleep(0.05)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(server._socket_path)
    s.sendall(hp.encode({"cmd": hp.CMD_HELLO}))
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    forbidden = json.loads(data.decode("utf-8"))
    assert forbidden["ok"] is False
    assert forbidden["error"] == "forbidden"
