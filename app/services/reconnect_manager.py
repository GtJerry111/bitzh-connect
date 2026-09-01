# app/services/reconnect_manager.py
"""自动重连状态机。

策略：
- 手动断开 / 认证失败 / 功能被禁用 → 不重连
- 其余进程退出 → 按 backoff 退避重连，最多 max_retries 次
- 连接建立且稳定存活 stability_window 秒 → 重置重试计数
  （防止"连上秒掉"抖动场景下无限重试）
"""
from PySide6.QtCore import QObject, QTimer, Signal


class ReconnectManager(QObject):
    retry_scheduled = Signal(int, float)  # (第几次重试, 延迟秒数)
    retry_triggered = Signal(int)         # 即将发起第 n 次重连
    retries_exhausted = Signal()          # 达到上限，暂停自动重连
    counter_reset = Signal()              # 计数被重置

    def __init__(
        self,
        reconnect_action,
        max_retries: int = 3,
        backoff: list[float] | None = None,
        stability_window: float = 60,
        parent=None,
    ):
        super().__init__(parent)
        self._reconnect_action = reconnect_action
        self._max_retries = max_retries
        self._backoff = backoff or [5, 10, 30]
        self._stability_window = stability_window
        self._enabled = True
        self._retry_count = 0

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._fire_retry)

        self._stability_timer = QTimer(self)
        self._stability_timer.setSingleShot(True)
        self._stability_timer.timeout.connect(self._reset_counter)

    @property
    def retry_count(self) -> int:
        return self._retry_count

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled:
            self.cancel()

    def on_connection_established(self):
        """连接建立（看到 Client IP）。启动稳定期计时，存活足够久才重置计数。"""
        self._retry_timer.stop()
        self._stability_timer.start(int(self._stability_window * 1000))

    def on_process_exited(self, manual: bool, auth_failed: bool):
        """连接进程退出。决定是否安排重连。"""
        self._stability_timer.stop()
        if manual or auth_failed or not self._enabled:
            return
        if self._retry_count >= self._max_retries:
            self._reset_counter()
            self.retries_exhausted.emit()
            return
        delay = self._backoff[min(self._retry_count, len(self._backoff) - 1)]
        self._retry_count += 1
        self._retry_timer.start(int(delay * 1000))
        self.retry_scheduled.emit(self._retry_count, delay)

    def cancel(self):
        """用户手动断开/退出应用时调用：停止一切待执行的重连并重置计数。"""
        self._retry_timer.stop()
        self._stability_timer.stop()
        self._reset_counter()

    def _fire_retry(self):
        self.retry_triggered.emit(self._retry_count)
        self._reconnect_action()

    def _reset_counter(self):
        if self._retry_count != 0:
            self._retry_count = 0
            self.counter_reset.emit()
