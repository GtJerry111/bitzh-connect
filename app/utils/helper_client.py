"""GUI 侧特权 helper 客户端：Unix socket 短连接 + JSON 行协议。

所有函数在 socket 不可用/超时时返回 None（调用方据此判断 helper 是否可用、
决定是否回退到 osascript 授权路径）——绝不抛异常打断连接流程。
"""
import json
import socket

from privileged_helper.protocol import (
    CMD_HELLO,
    CMD_START,
    CMD_STATUS,
    CMD_STOP,
    SOCKET_PATH,
    encode,
)


def _request(payload: dict, socket_path: str = SOCKET_PATH, timeout: float = 5.0):
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(socket_path)
        sock.sendall(encode(payload))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if not data:
            return None
        return json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def helper_version(socket_path: str = SOCKET_PATH):
    resp = _request({"cmd": CMD_HELLO}, socket_path)
    return resp.get("version") if isinstance(resp, dict) else None


def is_available(socket_path: str = SOCKET_PATH) -> bool:
    return helper_version(socket_path) is not None


def start(args, log_path, pid_path, stop_path, socket_path: str = SOCKET_PATH):
    return _request(
        {
            "cmd": CMD_START,
            "args": list(args),
            "log_path": log_path,
            "pid_path": pid_path,
            "stop_path": stop_path,
        },
        socket_path,
    )


def stop(socket_path: str = SOCKET_PATH):
    return _request({"cmd": CMD_STOP}, socket_path)


def status(socket_path: str = SOCKET_PATH):
    return _request({"cmd": CMD_STATUS}, socket_path)
