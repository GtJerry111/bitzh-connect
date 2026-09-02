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
