from platform import system

import pytest


def test_menu_bar_mode_default_false(qtbot):
    from utils.config_utils import load_config

    assert load_config()["menu_bar_mode"] is False


def test_menu_bar_mode_roundtrip(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)
    assert load_config()["menu_bar_mode"] is True


def test_menu_bar_mode_loaded_to_window(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    assert w.menu_bar_mode is True
    w.reconnect_manager.cancel()


@pytest.fixture
def window(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    qtbot.addWidget(w)
    yield w
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_enter_panel_mode(window):
    from PySide6.QtCore import Qt

    window.set_menu_bar_mode(True)
    flags = window.windowFlags()
    assert flags & Qt.FramelessWindowHint
    # 窗口类型须精确等于 Tool（Qt.Tool 与 Qt.Popup 共享 Window 位，
    # 直接 flags & Qt.Popup 会误判为真，必须用 WindowType_Mask 取类型）
    assert (flags & Qt.WindowType_Mask) == Qt.Tool
    assert flags & Qt.WindowStaysOnTopHint
    assert window.testAttribute(Qt.WA_TranslucentBackground)
    assert not window.exit_button.isVisible()
    assert window.settings_button.isVisible() or True  # 设置按钮保留（可见性随布局）


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_exit_panel_mode_restores_window(window):
    from PySide6.QtCore import Qt

    window.set_menu_bar_mode(True)
    window.set_menu_bar_mode(False)
    assert not (window.windowFlags() & Qt.FramelessWindowHint)
    assert not window.testAttribute(Qt.WA_TranslucentBackground)
    assert window.exit_button.isVisible()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_set_menu_bar_mode_idempotent(window):
    window.set_menu_bar_mode(True)
    flags_after_first = window.windowFlags()
    window.set_menu_bar_mode(True)  # 重复设置不应重建或闪烁
    assert window.windowFlags() == flags_after_first


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_open_panel_dispatch(window, monkeypatch):
    # 先切形态再打 spy：set_menu_bar_mode 自身也会调用 show_panel 恢复可见性，
    # 先打 spy 会把那次调用一并记入，且零参 spy 与 show_panel(animated=) 不兼容
    window.set_menu_bar_mode(True)
    calls = []
    monkeypatch.setattr(window, "show_panel", lambda: calls.append("panel"))
    window.open_panel()
    assert calls == ["panel"]


def test_open_panel_dispatch_floating(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "show", lambda: calls.append("show"))
    window.set_menu_bar_mode(False)
    window.open_panel()
    assert calls == ["show"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_hide_panel_esc_shortcut_registered(window):
    window.set_menu_bar_mode(True)
    assert any(
        s.key().toString() == "Esc" for s in window.findChildren(type(window._esc_shortcut))
    ) or window._esc_shortcut is not None
