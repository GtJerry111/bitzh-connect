# app/utils/tun_worker.py
"""TUN 模式 worker：内核以 root 后台运行，本 worker 尾随日志文件并监视 pid 存活。

与 CommandWorker 保持同一输出契约（output(str) / finished(int)），
handle_output / handle_connection_finished 无需区分模式。
"""
import time

from PySide6.QtCore import QThread, Signal

from utils.tun_utils import _pid_alive, kill_elevated_async, read_pid


class TunWorker(QThread):
    output = Signal(str)
    finished = Signal(int)

    # pidfile 出现前最长等待（覆盖用户输入授权密码的时间）
    PID_WAIT_TIMEOUT_S = 120

    def __init__(self, log_path: str, pid_path: str, on_kill_failed=None, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._pid_path = pid_path
        self._on_kill_failed = on_kill_failed
        self._stop_requested = False

    def run(self):
        pid = None
        deadline = time.time() + self.PID_WAIT_TIMEOUT_S
        while pid is None and time.time() < deadline and not self._stop_requested:
            pid = read_pid(self._pid_path)
            if pid is None:
                self.msleep(200)

        position = 0
        while not self._stop_requested:
            position = self._emit_new_content(position)
            if pid is None or not _pid_alive(pid):
                break
            self.msleep(300)
        # 循环退出前补读一次：进程死亡瞬间写入的尾部日志可能还没被 tail 到
        self._emit_new_content(position)
        self.finished.emit(-1)

    def _emit_new_content(self, position: int) -> int:
        """从 position 起读日志增量并逐行 emit，返回新的文件位置。"""
        try:
            with open(self._log_path, "r", errors="replace") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
            if chunk:
                for line in chunk.splitlines(keepends=True):
                    self.output.emit(line)
        except FileNotFoundError:
            pass
        return position

    def stop(self):
        """非阻塞停止：置标志 + 异步提权 kill；收尾在 run() 循环退出后由 finished 完成。"""
        self._stop_requested = True
        pid = read_pid(self._pid_path)
        if pid is not None:
            kill_elevated_async(pid, on_done=self._on_kill_done)

    def _on_kill_done(self, ok: bool):
        if not ok and self._on_kill_failed is not None:
            # kill 失败（典型：用户取消二次授权；或内核本已退出、kill 返回非 0）。
            # 告警走注入的 window 级 sink 而非 output.emit：真实时序下本 worker
            # 已 finished 并被 handle_connection_finished 断开/销毁，emit 不可达
            self._on_kill_failed()
