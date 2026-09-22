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
    # idle_timeout 短到 50ms，循环总时长约 100ms > 50ms：
    # 若 note_activity() 未真正复位 _last_activity，中途必然越过超时发出 suspected_dead。
    events = []
    wd = _watchdog(lambda: None, idle_timeout_s=0.05)
    wd.suspected_dead.connect(lambda: events.append(True))
    wd.start()
    for _ in range(10):
        wd.note_activity()
        qtbot.wait(10)
    assert events == []
    wd.stop()


def test_suspected_dead_when_idle_exceeds_short_timeout(qtbot):
    # 对照用例：同样 50ms 超时，但不打点 —— 必须收到 suspected_dead，
    # 证明上面的"无事件"来自会话保持，而非超时检测恒不触发。
    events = []
    wd = _watchdog(lambda: None, idle_timeout_s=0.05)
    wd.suspected_dead.connect(lambda: events.append(True))
    wd.start()
    qtbot.waitUntil(lambda: bool(events), timeout=1000)
    wd.stop()


def test_route_probe_exception_treated_as_none(qtbot):
    # 探测每拍抛异常时应被吞掉并继续走完 _tick，因此空闲检查仍然生效：
    # 有区分度——若实现里的 try/except 缺失，异常会中断 _tick，
    # idle 检查永不执行、suspected_dead 永不发，本用例即失败。
    route_events = []
    dead_events = []

    def boom():
        raise RuntimeError("boom")

    wd = _watchdog(boom, idle_timeout_s=0.05)
    wd.route_captured.connect(route_events.append)
    wd.suspected_dead.connect(lambda: dead_events.append(True))
    wd.start()
    qtbot.waitUntil(lambda: bool(dead_events), timeout=1000)
    assert route_events == []  # 异常按 None 处理，不发 route_captured
    wd.stop()


def test_stop_halts_signals(qtbot):
    # stop() 后即使时间流逝也不再发任何信号（停表语义）。
    route_events = []
    dead_events = []
    wd = _watchdog(lambda: "utun5", idle_timeout_s=0.05)
    wd.route_captured.connect(route_events.append)
    wd.suspected_dead.connect(lambda: dead_events.append(True))
    wd.start()
    wd.stop()
    qtbot.wait(120)  # 跨越多拍 route_interval 与 idle_timeout
    assert route_events == []
    assert dead_events == []
    wd.stop()
