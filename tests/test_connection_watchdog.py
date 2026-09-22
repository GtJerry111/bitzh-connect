import time

from services.connection_watchdog import ConnectionWatchdog


def _watchdog(route_probe, **kw):
    return ConnectionWatchdog(
        route_probe=route_probe,
        route_interval_ms=10,
        idle_timeout_s=kw.pop("idle_timeout_s", 100),
        cooldown_s=kw.pop("cooldown_s", 0),
    )


def test_route_captured_emits_once_then_observes_cooldown(qtbot):
    events = []
    probe = lambda: "utun5"
    wd = _watchdog(probe, cooldown_s=100)
    wd.route_captured.connect(lambda iface: events.append(iface))
    wd.start()
    qtbot.waitUntil(lambda: len(events) >= 1, timeout=1000)
    qtbot.wait(80)  # 等几个周期
    assert events == ["utun5"]  # 冷却内只报一次
    wd.stop()


def test_no_route_signal_when_probe_none(qtbot):
    events = []
    wd = _watchdog(lambda: None)
    wd.route_captured.connect(events.append)
    wd.start()
    qtbot.wait(80)
    assert events == []
    wd.stop()


def test_suspected_dead_when_no_activity(qtbot):
    events = []
    wd = _watchdog(lambda: None, idle_timeout_s=0)
    wd.suspected_dead.connect(lambda: events.append(True))
    wd.start()
    qtbot.waitUntil(lambda: bool(events), timeout=1000)
    wd.stop()


def test_activity_resets_idle_timer(qtbot):
    events = []
    wd = _watchdog(lambda: None, idle_timeout_s=100)
    wd.suspected_dead.connect(lambda: events.append(True))
    wd.start()
    for _ in range(5):
        wd.note_activity()
        qtbot.wait(10)
    assert events == []
    wd.stop()
