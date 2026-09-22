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
