"""连接看门狗：服务器路由被抢 + 内核假死监测。

- 路由被抢：周期调用 route_probe()（返回占用服务器路由的他方 TUN 名或 None），
  非 None 即发 route_captured（带冷却，避免连续刷屏/反复重连）。
- 假死：连接建立后若超过 idle_timeout_s 没有收到任何 keepalive 输出（note_activity 打点），
  发 suspected_dead（同样带冷却）。
"""
import time

from PySide6.QtCore import QObject, QTimer, Signal


class ConnectionWatchdog(QObject):
    route_captured = Signal(str)
    suspected_dead = Signal()

    def __init__(self, route_probe, route_interval_ms: int = 30000,
                 idle_timeout_s: float = 180.0, cooldown_s: float = 60.0,
                 parent=None):
        super().__init__(parent)
        self._route_probe = route_probe
        self._idle_timeout_s = idle_timeout_s
        self._cooldown_s = cooldown_s
        self._timer = QTimer(self)
        self._timer.setInterval(route_interval_ms)
        self._timer.timeout.connect(self._tick)
        # 告警门控：由调用方按连接模式/共存绑定/保活设置；关掉后对应分支不再发信号
        self.route_enabled = True
        self.dead_enabled = True
        self._last_route_alert = 0.0
        self._last_dead_alert = 0.0
        self._last_activity = 0.0
        self._running = False

    def start(self):
        # 跨连接复位冷却戳：否则上一连接残留的冷却会吞掉新连接的首个真实告警
        self._last_route_alert = 0.0
        self._last_dead_alert = 0.0
        self._last_activity = time.time()
        self._running = True
        self._timer.start()

    def stop(self):
        self._running = False
        self._timer.stop()

    def note_activity(self):
        self._last_activity = time.time()

    def _tick(self):
        if not self._running:
            return
        now = time.time()
        if self.route_enabled:
            try:
                captured = self._route_probe()
            except Exception:
                captured = None
            if captured and now - self._last_route_alert >= self._cooldown_s:
                self._last_route_alert = now
                self.route_captured.emit(captured)
        if self.dead_enabled and now - self._last_activity >= self._idle_timeout_s:
            if now - self._last_dead_alert >= self._cooldown_s:
                self._last_dead_alert = now
                self._last_activity = now  # 避免每拍都报
                self.suspected_dead.emit()
