# 特权 Helper 核心 Implementation Plan（阶段 2a）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个以 root 常驻的特权 helper（独立小程序）+ 本地 Unix socket 协议，GUI 通过它拉起/停止 `zju-connect`，替代每次连接的 `osascript` 授权。

**Architecture:** helper（纯标准库，独立 Nuitka 打包）由 LaunchDaemon 常驻，监听 `/var/run/bitzh-connect-helper.sock`（`0600`、owner=安装者），只接受 `hello/ping/status/start/stop`。`start` 时 helper 用写死的内核路径 spawn `zju-connect`、写 pidfile、并起一个 watcher 线程监听"停止标记文件"——这样 GUI 侧**完全复用现有 `TunWorker`**（tail 日志 + 写停止标记），集成时只需把"osascript 启动"换成"socket start"。密码经 socket 传给 helper；但 helper 仍把它作为内核 argv（`-password`，见 `server.py`），因此密码依然会出现在 root 内核命令行——helper 免除的是每次连接的授权弹窗，不是命令行泄漏。

**Tech Stack:** Python 3.11 标准库（socket/struct/subprocess/threading）；PySide6（仅 GUI 侧 client）；pytest。

**Spec:** 本会话 grilling 结论（问题 3，档 2，仅 macOS）。安装/UI/集成见姊妹计划 `2026-09-22-privileged-helper-install.md`（阶段 2b）。

---

## 背景（给零上下文的工程师）

- 现状：TUN 模式用 `osascript ... with administrator privileges` 启动内核（`app/utils/tun_utils.py:174`），**每次连接都弹授权框**。
- 目标：一次安装常驻 root 服务，之后只发本地 socket 指令。
- 现有 TUN 生命周期约定（本计划严格沿用，以便复用 `TunWorker`）：
  - GUI 生成三个临时文件：`log_path`（内核输出）、`pid_path`（内核 pid）、`stop_path`（停止标记）。
  - `TunWorker`（`app/utils/tun_worker.py`）负责 tail `log_path`、轮询 `pid_path` 判断存活；`stop()` 只写 `stop_path`。
  - 内核被谁启动不是 `TunWorker` 关心的——本计划让 helper 承担"启动 + 监听停止标记杀内核"的角色，`TunWorker` 原样复用。
- helper 是**独立程序**（`app/privileged_helper/`），用 Nuitka 单独打包（不含 PySide6），安装时复制到系统目录；打包工作流改动见阶段 2b。
- 运行测试：`.venv/bin/python -m pytest <path> -q`。测试环境 `QT_QPA_PLATFORM=offscreen`。

## File Structure

- `app/privileged_helper/__init__.py` — 空包标记
- `app/privileged_helper/protocol.py` — **单一真源**：socket 路径、安装路径、命令常量、`encode()`；GUI 与 helper 都从这里 import
- `app/privileged_helper/server.py` — `HelperServer`：socket 服务 + 内核生命周期（纯逻辑，可注入依赖，易测）
- `app/privileged_helper/main.py` — helper 可执行入口（Nuitka 打包目标）
- `app/utils/helper_client.py` — GUI 侧短连接客户端
- `tests/test_helper_protocol.py` — 协议常量/编解码
- `tests/test_helper_server.py` — server 行为（假内核脚本 + 临时 socket）
- `tests/test_helper_client.py` — client 对 server 的端到端

---

## Task 1: 协议常量与编解码

**Files:**
- Create: `app/privileged_helper/__init__.py`
- Create: `app/privileged_helper/protocol.py`
- Test: `tests/test_helper_protocol.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_helper_protocol.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_protocol.py -q`
Expected: FAIL/collection error（`privileged_helper` 不存在）。

- [ ] **Step 3: 创建包与协议模块**

创建空的 `app/privileged_helper/__init__.py`（0 字节）。

创建 `app/privileged_helper/protocol.py`：

```python
"""GUI 与特权 helper 之间的共享协议（纯标准库，无任何第三方依赖）。

单一真源：socket 位置、安装位置、命令常量、JSON 行编解码都定义在这里；
GUI 侧（`from privileged_helper.protocol import ...`）与 helper 侧
（`from protocol import ...`，同目录运行）共用本文件。
"""
import json

# 协议版本：GUI 与 helper 握手比对；不兼容时提示用户更新特权服务
PROTOCOL_VERSION = 1

# ---- 运行时通信 ----
SOCKET_PATH = "/var/run/bitzh-connect-helper.sock"

# ---- 安装位置（安装脚本、helper 自检、卸载都以这里为准）----
HELPER_DIR = "/Library/PrivilegedHelperTools/bitzh-connect"
HELPER_BIN = HELPER_DIR + "/bitzh-helper"
KERNEL_BIN = HELPER_DIR + "/zju-connect"
LAUNCHD_LABEL = "com.bitzh-connect.helper"
LAUNCHD_PLIST = "/Library/LaunchDaemons/" + LAUNCHD_LABEL + ".plist"

# ---- 命令 ----
CMD_HELLO = "hello"
CMD_PING = "ping"
CMD_STATUS = "status"
CMD_START = "start"
CMD_STOP = "stop"


def encode(obj: dict) -> bytes:
    """把请求/响应编码为单行 JSON（换行结尾，便于按行读取）。"""
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_protocol.py -q`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/privileged_helper/__init__.py app/privileged_helper/protocol.py tests/test_helper_protocol.py
git commit -m "feat(helper): 协议常量与 JSON 行编解码"
```

---

## Task 2: HelperServer —— socket 服务与内核生命周期

**Files:**
- Create: `app/privileged_helper/server.py`
- Test: `tests/test_helper_server.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_helper_server.py`：

```python
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
    assert server.start_kernel(*args)["ok"] is False
    server.stop_kernel()


def test_dispatch_hello_and_unknown(tmp_path):
    fake = _FakeKernel(tmp_path)
    server = _server(tmp_path, fake)
    assert server.dispatch({"cmd": hp.CMD_HELLO})["version"] == hp.PROTOCOL_VERSION
    assert server.dispatch({"cmd": "bogus"})["ok"] is False


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
            data += s.recv(4096)
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
        data += s.recv(4096)
    s.close()
    assert json.loads(data.decode("utf-8"))["ok"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_server.py -q`
Expected: collection error（`server` 不存在）。

- [ ] **Step 3: 实现 server.py**

创建 `app/privileged_helper/server.py`：

```python
"""特权 helper 服务端：监听 Unix socket，按窄接口启停 zju-connect。

以 root 由 LaunchDaemon 常驻。安全约束：
- 只认 hello/ping/status/start/stop 五个命令；
- 内核可执行路径写死在 protocol.KERNEL_BIN，不接受外部传入；
- 每次连接校验对端 uid == 安装者 uid（默认取本进程 uid，即安装/root 启动时的显式配置）。
"""
import json
import os
import signal
import socket
import struct
import subprocess
import threading
import time

from privileged_helper.protocol import (
    CMD_HELLO,
    CMD_PING,
    CMD_START,
    CMD_STATUS,
    CMD_STOP,
    KERNEL_BIN,
    PROTOCOL_VERSION,
    SOCKET_PATH,
    encode,
)

# macOS LOCAL_PEERCRED：SOL_LOCAL 通常为 0，选项号 0x001
_SOL_LOCAL = getattr(socket, "SOL_LOCAL", 0)
_LOCAL_PEERCRED = 0x001
_PEER_CRED_SIZE = struct.calcsize("2i")


class HelperServer:
    def __init__(self, socket_path=SOCKET_PATH, allowed_uid=None,
                 kernel_path=KERNEL_BIN, version=PROTOCOL_VERSION):
        self._socket_path = socket_path
        # 默认用本进程 uid（LaunchDaemon 以 root 跑时会显式传入安装者 uid）
        self._allowed_uid = os.getuid() if allowed_uid is None else allowed_uid
        self._kernel_path = kernel_path
        self._version = version
        self._proc = None
        self._log_f = None
        self._lock = threading.Lock()
        self._sock = None

    # ---------------- 内核生命周期 ----------------

    def _kernel_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start_kernel(self, args, log_path, pid_path, stop_path):
        with self._lock:
            if self._kernel_alive():
                return {"ok": False, "error": "already_running"}
            try:
                log_f = open(log_path, "ab", buffering=0)
            except OSError as e:
                return {"ok": False, "error": f"log_open_failed: {e}"}
            try:
                self._proc = subprocess.Popen(
                    [self._kernel_path, *[str(a) for a in args]],
                    stdout=log_f,
                    stderr=log_f,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,  # 脱离 helper 进程组，独立存活
                )
            except OSError as e:
                log_f.close()
                return {"ok": False, "error": f"spawn_failed: {e}"}
            self._log_f = log_f
            try:
                with open(pid_path, "w") as f:
                    f.write(str(self._proc.pid))
            except OSError:
                pass
            threading.Thread(
                target=self._watch_stop, args=(stop_path,), daemon=True
            ).start()
            return {"ok": True, "pid": self._proc.pid}

    def _watch_stop(self, stop_path):
        """停止标记出现即杀内核（GUI 断开走此路径，零权限）。"""
        while self._kernel_alive():
            if stop_path and os.path.exists(stop_path):
                self.stop_kernel()
                return
            time.sleep(0.3)

    def stop_kernel(self):
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return {"ok": True, "note": "not_running"}
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            return {"ok": True}

    def status(self):
        return {
            "ok": True,
            "running": self._kernel_alive(),
            "pid": self._proc.pid if self._proc is not None else None,
        }

    # ---------------- socket 服务 ----------------

    def serve_forever(self):
        self._prepare_socket()
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            try:
                self._handle_conn(conn)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _prepare_socket(self):
        try:
            os.unlink(self._socket_path)
        except OSError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._socket_path)
        os.chmod(self._socket_path, 0o600)
        try:
            os.chown(self._socket_path, self._allowed_uid, -1)
        except OSError:
            pass
        self._sock.listen(8)

    def _handle_conn(self, conn):
        if not self._peer_allowed(conn):
            conn.sendall(encode({"ok": False, "error": "forbidden"}))
            return
        data = b""
        while not data.endswith(b"\n") and len(data) < 1_000_000:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        if not data:
            return
        try:
            req = json.loads(data.decode("utf-8"))
        except ValueError:
            conn.sendall(encode({"ok": False, "error": "bad_json"}))
            return
        conn.sendall(encode(self.dispatch(req)))

    def dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd in (CMD_HELLO, CMD_PING):
            return {"ok": True, "version": self._version}
        if cmd == CMD_STATUS:
            return self.status()
        if cmd == CMD_START:
            return self.start_kernel(
                req.get("args") or [],
                req.get("log_path"),
                req.get("pid_path"),
                req.get("stop_path"),
            )
        if cmd == CMD_STOP:
            return self.stop_kernel()
        return {"ok": False, "error": "unknown_command"}

    def _peer_allowed(self, conn) -> bool:
        uid = self._peer_uid(conn)
        return uid is not None and uid == self._allowed_uid

    @staticmethod
    def _peer_uid(conn):
        """取对端 uid（macOS getsockopt LOCAL_PEERCRED）；不可用返回 None。"""
        try:
            creds = conn.getsockopt(_SOL_LOCAL, _LOCAL_PEERCRED, _PEER_CRED_SIZE)
            _version, uid = struct.unpack("2i", creds)
            return uid
        except (OSError, AttributeError, struct.error):
            return None
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_server.py -q`
Expected: 6 passed。

> 若 `test_socket_end_to_end...` 因 `/var/run` 无关（用 /tmp）或线程时序偶发失败，可重跑一次；仍失败则检查 `_short_socket_path` 路径长度。测试通过后进入下一步。

- [ ] **Step 5: 提交**

```bash
git add app/privileged_helper/server.py tests/test_helper_server.py
git commit -m "feat(helper): socket 服务端与内核生命周期"
```

---

## Task 3: helper 可执行入口

**Files:**
- Create: `app/privileged_helper/main.py`
- Test: 由 Task 2 覆盖（入口本身只做组装，用冒烟测试）

- [ ] **Step 1: 写入口**

创建 `app/privileged_helper/main.py`：

```python
"""特权 helper 可执行入口（Nuitka 单独打包为 bitzh-helper）。

以 root 常驻运行，由 LaunchDaemon 管理；安装者 uid 通过命令行传入，
用于 socket 权限与 peer 校验（默认 0，即仅 root，属保守兜底）。
"""
import os
import sys

# 源码树中 main.py 位于 app/privileged_helper/；把 app/ 加入 path 以 import 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from privileged_helper.server import HelperServer  # noqa: E402


def _parse_allowed_uid(argv) -> int:
    # 支持：bitzh-helper --allowed-uid 501
    if "--allowed-uid" in argv:
        idx = argv.index("--allowed-uid")
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                pass
    return 0


def main():
    allowed_uid = _parse_allowed_uid(sys.argv[1:])
    HelperServer(allowed_uid=allowed_uid).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 冒烟测试（模块可导入、参数解析正确）**

创建 `tests/test_helper_main.py`：

```python
from privileged_helper.main import _parse_allowed_uid


def test_parse_allowed_uid():
    assert _parse_allowed_uid(["--allowed-uid", "501"]) == 501
    assert _parse_allowed_uid([]) == 0
    assert _parse_allowed_uid(["--allowed-uid", "abc"]) == 0
```

Run: `.venv/bin/python -m pytest tests/test_helper_main.py -q`
Expected: 1 passed。

- [ ] **Step 3: 提交**

```bash
git add app/privileged_helper/main.py tests/test_helper_main.py
git commit -m "feat(helper): 可执行入口与 allowed-uid 参数"
```

---

## Task 4: GUI 侧 helper 客户端

**Files:**
- Create: `app/utils/helper_client.py`
- Test: `tests/test_helper_client.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_helper_client.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_client.py -q`
Expected: collection error（`helper_client` 不存在）。

- [ ] **Step 3: 实现 helper_client.py**

创建 `app/utils/helper_client.py`：

```python
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
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
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
        try:
            sock.close()
        except OSError:
            pass


def helper_version(socket_path: str = SOCKET_PATH):
    resp = _request({"cmd": CMD_HELLO}, socket_path)
    return resp.get("version") if resp else None


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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_client.py -q`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add app/utils/helper_client.py tests/test_helper_client.py
git commit -m "feat(helper): GUI 侧 socket 客户端"
```

---

## Task 5: 全量回归

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS，无既有用例回归。

- [ ] **Step 2: 无代码提交（验证任务）**

---

## 完成标准（2a）

- helper 协议、服务端、入口、GUI 客户端全部就位并有单测覆盖（含 peer uid 拒绝、停止标记杀内核、双启动拒绝）。
- 与现有 `TunWorker` 约定（log/pid/stop 三文件）完全兼容——阶段 2b 集成时无需改 `TunWorker`。
- 尚未接入真实连接流程（集成在 2b）。
