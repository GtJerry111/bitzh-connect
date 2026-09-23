def test_format_and_gate(qtbot):
    """确保：断开/未启用时不显示速率；启用且连接时显示两行（上=上行 下=下行）。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.menu_bar_speed = True

    calls = []
    win._mac_status_item = type(
        "S", (), {
            "set_speed": lambda self, up, down: calls.append(("speed", up, down)),
            "restore_icon": lambda self: calls.append(("icon",)),
        },
    )()

    # 未连接（无虚拟 IP）→ 不显示
    win.virtual_ip = None
    win._update_menu_bar_speed("1.0 KB/s", "2.0 KB/s")
    assert calls == []

    # 已连接 → 显示（上行在前）
    win.virtual_ip = "10.0.43.5"
    win._update_menu_bar_speed("1.0 KB/s", "2.0 KB/s")
    assert calls == [("speed", "1.0 KB/s", "2.0 KB/s")]

    # 关闭开关 → 恢复图标
    win.menu_bar_speed = False
    win._update_menu_bar_speed("1.0 KB/s", "2.0 KB/s")
    assert calls[-1] == ("icon",)

    win.reconnect_manager.cancel()


def test_on_rates_feeds_panel_and_menubar(qtbot, monkeypatch):
    """on_rates 包装是核心数据路径：一次速率回调须同时喂状态面板与菜单栏；
    stop_rate_monitor 断连收尾须清 _last_rates 并恢复默认图标。"""
    import services.rate_monitor as rm

    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.menu_bar_speed = True
    win.tun_mode = True
    win.virtual_ip = "10.0.43.5"

    panel_calls = []
    monkeypatch.setattr(
        win.status_panel, "set_rates",
        lambda up, down: panel_calls.append((up, down)),
    )

    item_calls = []
    win._mac_status_item = type(
        "S", (), {
            "set_speed": lambda self, up, down: item_calls.append(("speed", up, down)),
            "restore_icon": lambda self: item_calls.append(("icon",)),
        },
    )()

    captured = {}

    class _FakeMonitor:
        def __init__(self, interface, on_rates, on_sample, parent):
            captured["on_rates"] = on_rates

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(rm, "find_tun_interface", lambda ip: "utun0")
    monkeypatch.setattr(rm, "RateMonitor", _FakeMonitor)

    win.start_rate_monitor("10.0.43.5")
    assert "on_rates" in captured  # 监控已建且回调已捕获

    captured["on_rates"]("1.0 KB/s", "2.0 KB/s")
    assert panel_calls == [("1.0 KB/s", "2.0 KB/s")]  # 面板拿到两行
    assert ("speed", "1.0 KB/s", "2.0 KB/s") in item_calls  # 菜单栏同样被喂到

    win.stop_rate_monitor()
    assert win._last_rates is None
    assert item_calls[-1] == ("icon",)  # 断连恢复默认图标

    win.reconnect_manager.cancel()


def test_set_menu_bar_speed_persists_roundtrip(qtbot):
    """set_menu_bar_speed(True) 立即写回配置：重新 load_config() 可见。"""
    from utils.config_utils import load_config
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert load_config()["menu_bar_speed"] is False

    win.set_menu_bar_speed(True)
    assert load_config()["menu_bar_speed"] is True

    win.reconnect_manager.cancel()


def test_set_menu_bar_speed_backfills_last_rates(qtbot):
    """连接中开启开关：用最近一次 _last_rates 立即回填菜单栏（不等下次采样）。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.virtual_ip = "10.0.43.5"
    win._last_rates = ("1 KB/s", "2 KB/s")
    win.menu_bar_speed = False

    calls = []
    win._mac_status_item = type(
        "S", (), {
            "set_speed": lambda self, up, down: calls.append(("speed", up, down)),
            "restore_icon": lambda self: calls.append(("icon",)),
        },
    )()

    win.set_menu_bar_speed(True)
    assert calls == [("speed", "1 KB/s", "2 KB/s")]
    assert win._speed_visible is True

    win.reconnect_manager.cancel()


def test_update_menu_bar_speed_off_restores_once(qtbot):
    """显示态守卫：处于速率显示态的图标在关闭后仅恢复一次，
    后续同态采样（默认关、1Hz）不再重复 restore_icon。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.menu_bar_speed = False
    win._speed_visible = True  # 此前已显示速率（需跨越边界才会触发恢复）

    calls = []
    win._mac_status_item = type(
        "S", (), {
            "set_speed": lambda self, up, down: calls.append(("speed", up, down)),
            "restore_icon": lambda self: calls.append(("icon",)),
        },
    )()

    win._update_menu_bar_speed("1 KB/s", "2 KB/s")  # 首次跨越边界 → 恢复
    win._update_menu_bar_speed("1 KB/s", "2 KB/s")  # 已恢复 → 不再重复

    assert calls == [("icon",)]
    assert win._speed_visible is False

    win.reconnect_manager.cancel()
