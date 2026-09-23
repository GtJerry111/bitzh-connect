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
