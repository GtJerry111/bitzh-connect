# app/utils/tun_worker.py
"""TUN 模式 worker：内核以 root 后台运行，本 worker 尾随日志文件并监视 pid 存活。

与 CommandWorker 保持同一输出契约（output(str) / finished(int)），
handle_output / handle_connection_finished 无需区分模式。

断连零弹窗：stop() 只写停止标记文件（零权限），包装脚本里的 root 守护循环
收标后杀内核——不再走提权 kill，断开/退出全程不弹授权框。
"""
import time

from PySide6.QtCore import QThread, QTimer, Signal

from utils.tun_utils import _pid_alive, read_pid, request_stop


class TunWorker(QThread):
    output = Signal(str)
    finished = Signal(int)

    # pidfile 出现前最长等待（覆盖用户输入授权密码的时间）
    PID_WAIT_TIMEOUT_S = 120
    # 停止标记发出后内核退出的宽限期；超时未死则告警（不弹授权框补杀）
    KILL_GRACE_MS = 3000

    def __init__(self, log_path: str, pid_path: str, stop_path: str,
                 on_kill_failed=None, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._pid_path = pid_path
        self._stop_path = stop_path
        self._on_kill_failed = on_kill_failed
        self._stop_requested = False
        # 内核是否真正拉起来过（pidfile 出现且 pid 存活）——从未拉起属启动失败，
        # 此时自动重连只会再弹授权框骚扰用户，connection_utils 据此跳过重连
        self.kernel_started = False

    @property
    def log_path(self) -> str:
        """日志文件路径（连接收尾时由 connection_utils 清理）。"""
        return self._log_path

    @property
    def pid_path(self) -> str:
        """pidfile 路径（连接收尾时由 connection_utils 清理）。"""
        return self._pid_path

    @property
    def stop_path(self) -> str:
        """停止标记文件路径（连接收尾时由 connection_utils 清理）。"""
        return self._stop_path

    def run(self):
        pid = None
        deadline = time.time() + self.PID_WAIT_TIMEOUT_S
        while pid is None and time.time() < deadline and not self._stop_requested:
            pid = read_pid(self._pid_path)
            if pid is None:
                self.msleep(200)
        # pidfile 出现不代表内核活着（launcher 写进的是它后台子进程的 pid，
        # 启动命令本身失败时 pid 即刻死亡）——存活过才算"拉起来了"
        if pid is not None and _pid_alive(pid):
            self.kernel_started = True

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
        """非阻塞停止：置标志 + 写停止标记（守护循环收标杀内核）；收尾在 finished。

        授权期间用户断开（pidfile 尚为空）同样安全：守护循环首次轮询即收标，
        内核刚拉起就被杀，不会产生 root 孤儿进程。
        """
        self._stop_requested = True
        request_stop(self._stop_path)
        pid = read_pid(self._pid_path)
        if pid is not None and self._on_kill_failed is not None:
            # 宽限期后仍存活（典型：守护循环没能启动）→ window 级 sink 留痕。
            # 静态 singleShot 不挂 worker 上下文：worker 销毁后告警仍必达
            QTimer.singleShot(
                self.KILL_GRACE_MS,
                lambda p=pid, cb=self._on_kill_failed: self._warn_if_alive(p, cb),
            )

    @staticmethod
    def _warn_if_alive(pid: int, on_kill_failed):
        if _pid_alive(pid):
            on_kill_failed()
