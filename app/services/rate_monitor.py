# app/services/rate_monitor.py
"""速率监控：
- TUN 模式（RateMonitor）：psutil 每秒读虚拟网卡计数差值
- 代理模式（ProxyRateMonitor，仅 macOS）：nettop 按进程采样 zju-connect 流量，
  过滤 loopback 连接行（本地代理回环是真实流量的镜像，重复计费必须剔除）

两个通道：on_rates(格式化字符串) 喂统计行数字；on_sample(原始 B/s 数值) 喂波形图
——不从格式化字符串反向解析（"2.4 MB/s" 精度已损）。
"""
import subprocess

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
    def __init__(self, interface: str, on_rates, on_sample=None, parent=None):
        super().__init__(parent)
        self._interface = interface
        self._on_rates = on_rates
        self._on_sample = on_sample
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
            up = max(current[0] - self._last[0], 0)
            down = max(current[1] - self._last[1], 0)
            self._on_rates(_fmt_rate(up), _fmt_rate(down))
            if self._on_sample is not None:
                self._on_sample(float(up), float(down))
        self._last = current


def parse_nettop_output(text: str) -> tuple[int, int] | None:
    """解析 `nettop -x -L 1 -J bytes_in,bytes_out` 输出，返回 (bytes_in, bytes_out) 累计值。

    只统计非 loopback 连接行（进程↔VPN 服务端的真实流量）；汇总行（.pid）与
    本地代理回环行（127.0.0.1/::1）都剔除。无有效行（进程无连接/已退出）返回 None。
    """
    total_in = 0
    total_out = 0
    found = False
    for line in text.splitlines()[1:]:  # 首行是表头
        fields = line.split(",")
        if len(fields) < 3:
            continue
        name = fields[0].strip()
        if not name or name.startswith("."):
            continue  # 汇总行（".pid"）/ 空行
        if "127.0.0.1" in name or "::1" in name:
            continue  # loopback 镜像行
        try:
            total_in += int(fields[1])
            total_out += int(fields[2])
        except ValueError:
            continue
        found = True
    return (total_in, total_out) if found else None


class ProxyRateMonitor(QObject):
    """代理模式速率监控（macOS）：每秒一次 nettop 快照，差值即速率。

    连接频繁断开重建时累计值会回落（旧连接计数消失）——负差值钳为 0，
    代价是关闭瞬间的字节少计，近似可接受。
    """

    def __init__(self, pid: int, on_rates, on_sample=None, parent=None):
        super().__init__(parent)
        self._pid = pid
        self._on_rates = on_rates
        self._on_sample = on_sample
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
        try:
            out = subprocess.run(
                ["nettop", "-p", str(self._pid), "-x", "-L", "1",
                 "-J", "bytes_in,bytes_out"],
                capture_output=True, text=True, timeout=3,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return parse_nettop_output(out)

    def _tick(self):
        current = self._read()
        if current is None:
            # 进程连接全消失（已断开）→ 停止监控；状态收尾由 worker finished 驱动
            self.stop()
            return
        if self._last is not None:
            # bytes_in = 下行（服务器→本机），bytes_out = 上行（本机→服务器）
            down = max(current[0] - self._last[0], 0)
            up = max(current[1] - self._last[1], 0)
            self._on_rates(_fmt_rate(up), _fmt_rate(down))
            if self._on_sample is not None:
                self._on_sample(float(up), float(down))
        self._last = current
