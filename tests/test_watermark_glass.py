def test_glass_widgets_registered(qtbot):
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    container = win.centralWidget()
    assert win.mode_switch in container.glass_controls()
    assert win.connect_button in container.glass_controls()
    win.reconnect_manager.cancel()


def test_blur_cache_reused(qtbot):
    """同一张缩放水印只模糊一次（缓存命中）。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    container = win.centralWidget()
    scaled = container._watermark.scaledToHeight(120)
    b1 = container._blurred(scaled)
    b2 = container._blurred(scaled)
    assert b1 is b2  # 命中缓存返回同一对象
    win.reconnect_manager.cancel()
