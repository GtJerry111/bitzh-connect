"""Task 7 迁移：原 test_menu_bar_mode.py 中仍然有效的 macOS 背景/状态栏用例。

取消"浮动窗口 ↔ 菜单栏面板"二选一后，玻璃/毛玻璃、面板圆角、原生状态栏项、
托盘点击补丁等工具层行为不变，故从废弃的 menu_bar_mode 测试文件迁出集中在此。
"""
from platform import system

import pytest


@pytest.fixture
def window(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    qtbot.addWidget(w)
    yield w
    w.reconnect_manager.cancel()


# ---- macOS 27 QSystemTrayIcon 点击崩溃补丁（utils/macos_tray_fix.py） ----


def test_tray_click_fix_skipped_offscreen(qtbot):
    """offscreen 测试环境（非 cocoa）不打补丁，且不抛异常。"""
    from utils import macos_tray_fix

    macos_tray_fix._applied = False  # 重置幂等标志，隔离其他测试
    assert macos_tray_fix.apply_tray_click_fix() is False


def test_tray_click_fix_idempotent(qtbot):
    """重复调用安全（幂等）：无论是否打上补丁，第二次调用不抛异常。"""
    from utils import macos_tray_fix

    macos_tray_fix._applied = False
    macos_tray_fix.apply_tray_click_fix()
    macos_tray_fix.apply_tray_click_fix()  # 第二次不抛异常即通过


def test_tray_click_fix_non_darwin_noop(monkeypatch, qtbot):
    """非 macOS 平台直接跳过（打补丁无意义且可能误伤）。"""
    from utils import macos_tray_fix

    monkeypatch.setattr(macos_tray_fix, "system", lambda: "Windows")
    macos_tray_fix._applied = False
    assert macos_tray_fix.apply_tray_click_fix() is False


# ---- 液态玻璃（utils/macos_glass.py） ----


def test_glass_available_false_offscreen(qtbot):
    """offscreen 测试环境（非 cocoa）玻璃不可用。"""
    from utils.macos_glass import glass_available

    assert glass_available() is False


def test_glass_available_false_non_darwin(monkeypatch, qtbot):
    from utils import macos_glass

    monkeypatch.setattr(macos_glass, "system", lambda: "Windows")
    assert macos_glass.glass_available() is False


def test_glass_available_false_without_qapp(monkeypatch):
    """无 QApplication 实例时 platformName 恒返回 cocoa（编译期默认），必须挡掉。"""
    from utils import macos_glass

    class _FakeQApp:
        @staticmethod
        def instance():
            return None

        @staticmethod
        def platformName():
            return "cocoa"

    # 整体替换模块级 QApplication 引用：Shiboken 类的静态方法不适合逐方法打补丁
    monkeypatch.setattr(macos_glass, "QApplication", _FakeQApp)
    assert macos_glass.glass_available() is False


def test_install_glass_offscreen_returns_false(qtbot):
    from PySide6.QtWidgets import QWidget
    from utils.macos_glass import install_glass

    w = QWidget()
    qtbot.addWidget(w)
    assert install_glass(w) is False
    assert getattr(w, "_glass_view", None) is None


def test_remove_glass_noop_when_not_installed(qtbot):
    from PySide6.QtWidgets import QWidget
    from utils.macos_glass import remove_glass

    w = QWidget()
    qtbot.addWidget(w)
    remove_glass(w)  # 未安装：安静返回，不抛异常


def test_update_glass_appearance_noop_when_not_installed(qtbot):
    from PySide6.QtWidgets import QWidget
    from utils.macos_glass import update_glass_appearance

    w = QWidget()
    qtbot.addWidget(w)
    update_glass_appearance(w)  # 未安装：安静返回，不抛异常


def test_backdrop_update_dispatches_both(window, monkeypatch):
    """深浅色切换回调同时分发玻璃与毛玻璃更新（未安装一侧安静返回）。"""
    updated = []
    monkeypatch.setattr(
        "utils.macos_glass.update_glass_appearance", lambda w: updated.append("g")
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.update_vibrancy_appearance",
        lambda w: updated.append("v"),
    )
    window._update_backdrop()
    assert updated == ["g", "v"]


# ---- 面板窗口圆角阴影（utils/macos_panel_shape.py）+ 原生右键菜单 ----


def test_round_panel_window_noop_offscreen(window):
    """offscreen（非 cocoa）不触碰原生窗口：安静返回 False / 无异常。"""
    from utils.macos_panel_shape import restore_window_shape, round_panel_window

    assert round_panel_window(window) is False
    restore_window_shape(window)  # 未圆角过：安静返回


def test_native_status_item_disabled_offscreen():
    """非 cocoa / 非 macOS：原生状态栏项不创建（返回 None），调用方回退托盘。"""
    from utils.macos_status_item import create

    assert create(on_toggle=lambda: None, menu_spec=[]) is None


def test_detach_qt_tray_sync_clears_action(window):
    """切原生菜单前清掉旧 QAction 与同步槽，防陈旧 lambda 命中已销毁对象。"""
    from utils.tray_utils import _detach_qt_tray_sync, build_tray_menu

    build_tray_menu(window)
    assert window.tray_connect_action is not None
    _detach_qt_tray_sync(window)
    assert window.tray_connect_action is None
    assert window._tray_connect_sync is None


@pytest.mark.skipif(system() != "Darwin", reason="原生状态栏项仅 macOS")
def test_panel_tray_passes_native_menu_spec(qtbot, monkeypatch):
    """Darwin 下 init_tray_icon 恒尝试原生状态栏项（不再依赖 menu_bar_mode 配置），
    菜单首项即"打开主窗口"，左键回调为快捷面板开关。"""
    import utils.macos_status_item as msi

    captured = {}

    def fake_create(on_toggle, menu_spec):
        captured["on_toggle"] = on_toggle
        captured["spec"] = menu_spec
        return object()

    monkeypatch.setattr(msi, "create", fake_create)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    titles = [e["title"] for e in captured["spec"] if "title" in e]
    assert titles == ["打开主窗口", "VPN 连接", "退出"]
    connect_entry = captured["spec"][1]
    assert callable(connect_entry["action"])
    assert callable(connect_entry["is_checked"])
    assert captured["on_toggle"] == w.toggle_panel
    assert w._mac_status_item is not None
    assert w.tray_icon is None
    w.reconnect_manager.cancel()
