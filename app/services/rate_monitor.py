# app/services/rate_monitor.py
"""TUN 模式速率监控：psutil 每秒读虚拟网卡计数差值，喂给仪表盘。"""
import psutil
from PySide6.QtCore import QObject, QTimer


def find_tun_interface(virtual_ip: str) -> str | None:
    """按虚拟 IP 定位 tun 网卡名（如 utun4）。"""
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.address == virtual_ip:
                return name
    return None


def _fmt_rate(bytes_per_sec: float) -> str:
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f} B/s"
    if bytes_per_sec < 1024**2:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    return f"{bytes_per_sec / 1024**2:.1f} MB/s"


class RateMonitor(QObject):
    def __init__(self, interface: str, on_rates, parent=None):
        super().__init__(parent)
        self._interface = interface
        self._on_rates = on_rates
        self._last = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._last = self._read()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _read(self):
        counters = psutil.net_io_counters(pernic=True).get(self._interface)
        return (counters.bytes_sent, counters.bytes_recv) if counters else None

    def _tick(self):
        current = self._read()
        if current is None:
            self.stop()
            return
        if self._last is not None:
            up = current[0] - self._last[0]
            down = current[1] - self._last[1]
            self._on_rates(_fmt_rate(max(up, 0)), _fmt_rate(max(down, 0)))
        self._last = current
