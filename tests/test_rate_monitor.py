from services.rate_monitor import _fmt_rate, find_tun_interface


def test_fmt_rate():
    assert _fmt_rate(512) == "512 B/s"
    assert _fmt_rate(2048) == "2.0 KB/s"
    assert _fmt_rate(3 * 1024 * 1024) == "3.0 MB/s"


def test_find_tun_interface(monkeypatch):
    import services.rate_monitor as rm

    class A:
        def __init__(self, address):
            self.address = address

    monkeypatch.setattr(
        rm.psutil, "net_if_addrs",
        lambda: {"en0": [A("192.168.1.2")], "utun4": [A("10.0.43.17")]},
    )
    assert find_tun_interface("10.0.43.17") == "utun4"
    assert find_tun_interface("9.9.9.9") is None


# ---- ProxyRateMonitor（macOS nettop 按进程采样）----

NETTOP_SAMPLE = """\
,bytes_in,bytes_out,
.4242,4461,619,
tcp4 192.168.8.145:64439<->112.91.150.228:443,4461,619,
tcp4 127.0.0.1:1081<->127.0.0.1:65432,4461,619,
tcp4 127.0.0.1:1081<->127.0.0.1:65433,8000,1200,
"""


def test_parse_nettop_filters_loopback_and_summary():
    """只统计进程↔服务端的真实流量：汇总行(.pid)与 loopback 镜像行都剔除"""
    from services.rate_monitor import parse_nettop_output

    assert parse_nettop_output(NETTOP_SAMPLE) == (4461, 619)


def test_parse_nettop_empty_returns_none():
    """进程无连接（已退出/无流量）→ None（调用方停止监控）"""
    from services.rate_monitor import parse_nettop_output

    assert parse_nettop_output(",bytes_in,bytes_out,\n") is None


def test_proxy_monitor_tick_reports_rates(qtbot, monkeypatch):
    """差值即速率：bytes_in=下行、bytes_out=上行；双通道（格式化字符串 + 原始数值）"""
    from services.rate_monitor import ProxyRateMonitor

    readings = iter([(4461, 619), (4461 + 2048, 619 + 1024)])
    monkeypatch.setattr(ProxyRateMonitor, "_read", lambda self: next(readings))

    rates, samples = [], []
    m = ProxyRateMonitor(
        4242,
        lambda u, d: rates.append((u, d)),
        lambda u, d: samples.append((u, d)),
    )
    m.start()  # 首次读数建立基准
    m._tick()
    assert rates == [("1.0 KB/s", "2.0 KB/s")]
    assert samples == [(1024.0, 2048.0)]
    m.stop()


def test_proxy_monitor_stops_when_process_gone(qtbot, monkeypatch):
    """进程消失（nettop 无有效行）→ 监控停止，不喂假数据"""
    from services.rate_monitor import ProxyRateMonitor

    monkeypatch.setattr(ProxyRateMonitor, "_read", lambda self: None)
    rates = []
    m = ProxyRateMonitor(4242, lambda u, d: rates.append((u, d)))
    m.start()
    m._tick()
    assert not m._timer.isActive()
    assert rates == []
