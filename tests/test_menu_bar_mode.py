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
    assert w.menu_bar_mode is (system() == "Darwin")  # 非 Darwin 强制 False
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
    assert not window.settings_button.isHidden()  # 设置按钮保留（仅退出按钮收起）


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
    assert window._esc_shortcut is not None
    assert window._esc_shortcut.key().toString() == "Esc"


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_reinit_tray_disconnects_stale_sync(window):
    """形态切换重建托盘必须先撤销旧 QAction 的同步连接。

    否则旧 QMenu/QAction 随旧托盘销毁后，陈旧 lambda 仍挂在长寿的
    connect_button.toggled 上，每次连接开关都命中已删除 C++ 对象（RuntimeError）。
    用信号接收者数量守恒来验证（PySide6 QObject.receivers 接受 SIGNAL 字符串）。
    """
    from utils.tray_utils import reinit_tray

    sig = "2toggled(bool)"
    before = window.connect_button.receivers(sig)
    reinit_tray(window)
    reinit_tray(window)
    assert window.connect_button.receivers(sig) == before


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_show_panel_positions_under_icon(window, monkeypatch):
    """面板顶部钉在图标下缘（reduce-motion 直出路径，无动画干扰）。

    图标坐标取自 offscreen 屏幕（800x800）内部，避免触发 panel_geometry
    的屏幕边缘夹紧——否则测试失败是夹紧所致而非定位 bug。
    """
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    from PySide6.QtCore import QRect

    fake_item = type("FakeItem", (), {"icon_global_rect": lambda self: QRect(400, 0, 24, 22)})()
    window.set_menu_bar_mode(True)
    # 形态切换链会 reinit_tray → teardown 旧 _mac_status_item 并置 None；
    # 故 fake 必须在切换之后注入，否则 show_panel 拿不到图标坐标
    window._mac_status_item = fake_item
    window.show_panel()
    # QRect.bottom() 是闭区间：高 22 的图标底边是 21（与 panel_geometry 的
    # icon.bottom()+4 口径一致，见 tests/test_panel_geometry.py）
    assert window.frameGeometry().top() == 21 + 4
    assert abs(window.frameGeometry().center().x() - (400 + 12)) <= 2


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_hide_panel_immediate_under_reduce_motion(window, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.set_menu_bar_mode(True)
    window.show_panel()
    window.hide_panel()
    assert not window.isVisible()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_content_resize_keeps_top_anchored(window, monkeypatch):
    """内容高度变化（凭据区收放→adjustSize）后顶边位置不变。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.set_menu_bar_mode(True)
    window.show_panel()
    top_before = window.frameGeometry().top()
    window._on_content_resize()
    assert window.frameGeometry().top() == top_before


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_hides_on_window_deactivate(window, monkeypatch):
    """失焦手动收起（Tool 形态无 Popup 自隐）：窗口失活事件 → 面板隐藏。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QGuiApplication

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.set_menu_bar_mode(True)
    window.show_panel()
    assert window.isVisible()
    QGuiApplication.sendEvent(window, QEvent(QEvent.WindowDeactivate))
    assert not window.isVisible()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_show_panel_cancels_pending_hide(window, monkeypatch):
    """展开须使在途收起动画失效：陈旧 finished 不得隐藏刚展开的面板
    （失焦收起 + Dock/Cmd-Tab 快速激活会命中该竞态）。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    window.set_menu_bar_mode(True)
    window.show_panel(animated=False)
    assert window.isVisible()
    window.hide_panel()
    assert window._panel_hide_anim is not None  # 在途收起动画
    window.show_panel(animated=False)
    assert window.isVisible()
    assert window._panel_hide_anim is None  # 已被 show 停掉/清空，陈旧回调失效


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_tray_routing_in_panel_mode(qtbot):
    """面板模式托盘路由按平台分支：
    - cocoa（真机）：走原生 NSStatusItem，不建 QSystemTrayIcon；
    - 非 cocoa（offscreen 测试）：原生被守卫关闭，回退 QSystemTrayIcon。
    两条路径都不得创建残留原生状态栏项。"""
    from PySide6.QtWidgets import QApplication
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    if QApplication.platformName() == "cocoa":
        assert w._mac_status_item is not None
        assert w.tray_icon is None
    else:
        assert w._mac_status_item is None
        assert w.tray_icon is not None
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_close_event_panel_mode_hides(qtbot, monkeypatch):
    """面板模式 closeEvent = 收起（不退出）。"""
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    from PySide6.QtGui import QCloseEvent

    w.closeEvent(QCloseEvent())
    assert not w.isVisible()
    assert not getattr(w, "_quitting", False)
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_settings_dialog_has_panel_switch(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    from views.advanced_panel import AdvancedSettingsDialog

    dialog = AdvancedSettingsDialog(w)
    assert hasattr(dialog, "menu_bar_mode_switch")
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_switch_forces_hide_dock(qtbot):
    """勾选菜单栏面板 → 隐藏 Dock 自动勾上且禁用（面板形态 Dock 无意义）。"""
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    from views.advanced_panel import AdvancedSettingsDialog

    dialog = AdvancedSettingsDialog(w)
    dialog.menu_bar_mode_switch.setChecked(True)
    assert dialog.hide_dock_icon_switch.isChecked()
    assert not dialog.hide_dock_icon_switch.isEnabled()
    settings = dialog.get_settings()
    assert settings["menu_bar_mode"] is True
    # 强制的是 UI 勾选态；持久化保留用户原偏好（取消面板模式时还原，见 I2 回归测试）
    assert settings["hide_dock_icon"] is False
    dialog.menu_bar_mode_switch.setChecked(False)
    assert dialog.hide_dock_icon_switch.isEnabled()
    w.reconnect_manager.cancel()


def test_quit_helpers_tolerate_no_tray_icon(qtbot, monkeypatch):
    """面板模式原生状态栏项路径 tray_icon 为 None（托盘职责在 _mac_status_item）：
    handle_close_event/quit_app 不得触碰 None。shiboken6.isValid(None) 实为 True，
    只靠 isValid 会 AttributeError（真实 cocoa 面板模式下退出即崩）。"""
    from PySide6.QtGui import QCloseEvent

    class FakeTimer:
        @staticmethod
        def singleShot(*args):
            pass  # 拦截延迟 quit，避免遗留定时器

    monkeypatch.setattr("utils.tray_utils.QTimer", FakeTimer)
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.tray_icon = None  # 浮动形态下 closeEvent → handle_close_event(None) → quit_app(None)
    w.closeEvent(QCloseEvent())
    assert getattr(w, "_quitting", False) is True


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_mode_startup_does_not_show(qtbot):
    """面板模式启动不得闪窗（main.py 面板模式不 show；构造只 winId 真实化）。"""
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    assert not w.isVisible()
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_disable_panel_restores_hide_dock_preference(qtbot):
    """取消面板模式须还原用户原本的隐藏 Dock 偏好（不被强制 True 覆盖）。"""
    from views.main_window import MainWindow
    from views.advanced_panel import AdvancedSettingsDialog

    w = MainWindow()
    qtbot.addWidget(w)
    dialog = AdvancedSettingsDialog(w)
    assert dialog.get_settings()["hide_dock_icon"] is False  # 用户原偏好
    dialog.menu_bar_mode_switch.setChecked(True)
    assert dialog.get_settings()["hide_dock_icon"] is False  # 面板开启保留原偏好
    assert dialog.hide_dock_icon_switch.isChecked() and not dialog.hide_dock_icon_switch.isEnabled()
    dialog.menu_bar_mode_switch.setChecked(False)
    assert dialog.hide_dock_icon_switch.isChecked() is False  # 还原
    assert dialog.get_settings()["hide_dock_icon"] is False
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_effective_dock_policy_follows_panel_mode(qtbot, monkeypatch):
    """面板模式开启时 Dock 恒隐藏；关闭后按用户原偏好（panel_mode or hide_dock_icon）。"""
    calls = []
    monkeypatch.setattr("views.advanced_panel.hide_dock_icon", lambda hide=True: calls.append(hide))
    monkeypatch.setattr("views.advanced_panel.save_config", lambda *a, **k: None)
    monkeypatch.setattr("views.advanced_panel.set_launch_at_login", lambda *a, **k: None)
    from views.main_window import MainWindow
    from views.advanced_panel import AdvancedSettingsDialog

    w = MainWindow()
    qtbot.addWidget(w)
    w.hide_dock_icon = False
    dialog = AdvancedSettingsDialog(w)
    dialog.menu_bar_mode_switch.setChecked(True)
    dialog.accept()
    assert calls and calls[-1] is True  # 面板开启 → 强制隐藏
    calls.clear()
    dialog2 = AdvancedSettingsDialog(w)
    dialog2.menu_bar_mode_switch.setChecked(False)
    dialog2.accept()
    assert calls and calls[-1] is False  # 原偏好 False → 恢复显示
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


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_chrome_prefers_glass_when_available(window, monkeypatch):
    """玻璃可用时安装玻璃、不装毛玻璃。"""
    calls = []
    monkeypatch.setattr("utils.macos_glass.glass_available", lambda: True)
    monkeypatch.setattr(
        "utils.macos_glass.install_glass", lambda w: calls.append("glass") or True
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.install_vibrancy",
        lambda w: calls.append("vibrancy") or True,
    )
    window.set_menu_bar_mode(True)
    assert calls == ["glass"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_chrome_falls_back_to_vibrancy(window, monkeypatch):
    """玻璃不可用（macOS ≤ 15）时回退现有毛玻璃路径。"""
    calls = []
    monkeypatch.setattr("utils.macos_glass.glass_available", lambda: False)
    monkeypatch.setattr(
        "utils.macos_glass.install_glass", lambda w: calls.append("glass") or True
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.install_vibrancy",
        lambda w: calls.append("vibrancy") or True,
    )
    window.set_menu_bar_mode(True)
    assert calls == ["vibrancy"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_chrome_falls_back_when_glass_install_fails(window, monkeypatch):
    """玻璃类存在但安装失败：回退毛玻璃，绝不留下透明底窗口。"""
    calls = []
    monkeypatch.setattr("utils.macos_glass.glass_available", lambda: True)
    monkeypatch.setattr(
        "utils.macos_glass.install_glass", lambda w: calls.append("glass") or False
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.install_vibrancy",
        lambda w: calls.append("vibrancy") or True,
    )
    window.set_menu_bar_mode(True)
    assert calls == ["glass", "vibrancy"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_exit_panel_mode_removes_both_backdrops(window, monkeypatch):
    """切回浮动模式：玻璃与毛玻璃都拆除（幂等安静，防御同会话残留）。

    install 也打桩：否则真 cocoa 下会真的装上原生背景视图，而打桩的
    remove 永远拆不掉它，污染原生状态。
    """
    events = []
    monkeypatch.setattr(
        "utils.macos_glass.install_glass",
        lambda w: events.append("install_glass") or True,
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.install_vibrancy",
        lambda w: events.append("install_vibrancy") or True,
    )
    monkeypatch.setattr(
        "utils.macos_glass.remove_glass", lambda w: events.append("remove_glass")
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.remove_vibrancy", lambda w: events.append("remove_vibrancy")
    )
    window.set_menu_bar_mode(True)
    window.set_menu_bar_mode(False)
    # offscreen 下 glass_available() 为 False → 走 vibrancy 安装；退出双拆
    assert events == ["install_vibrancy", "remove_glass", "remove_vibrancy"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
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


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_show_panel_animation_params(window, monkeypatch):
    """展开动效定稿：下滑 8px + 淡入，220ms OutCubic（"慢开快收"的开）。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    window.set_menu_bar_mode(True)
    window.show_panel()
    anim_pos, anim_opacity = window._panel_anims
    assert anim_pos.duration() == 220
    # 下滑 8px：起点在终点上方 8px
    assert anim_pos.startValue().y() == anim_pos.endValue().y() - 8
    assert anim_pos.startValue().x() == anim_pos.endValue().x()
    assert anim_opacity.duration() == 220
    assert anim_opacity.startValue() == 0.0
    assert anim_opacity.endValue() == 1.0


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_hide_panel_animation_params(window, monkeypatch):
    """收起动效定稿：160ms 淡出（比展开快，收起要利落）。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    window.set_menu_bar_mode(True)
    window.show_panel(animated=False)
    window.hide_panel()
    anim = window._panel_hide_anim
    assert anim is not None
    assert anim.duration() == 160
    assert anim.endValue() == 0.0


# ---- 面板窗口圆角阴影（utils/macos_panel_shape.py）+ 原生右键菜单 ----


def test_round_panel_window_noop_offscreen(window):
    """offscreen（非 cocoa）不触碰原生窗口：安静返回 False / 无异常。"""
    from utils.macos_panel_shape import restore_window_shape, round_panel_window

    assert round_panel_window(window) is False
    restore_window_shape(window)  # 未圆角过：安静返回


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_mode_rounds_and_restores_frame(window, monkeypatch):
    """进面板给窗口 frame 套圆角（修四角方形阴影残角），切回浮动还原。"""
    import utils.macos_panel_shape as shape

    calls = []
    monkeypatch.setattr(
        shape, "round_panel_window", lambda w: calls.append("round") or True
    )
    monkeypatch.setattr(
        shape, "restore_window_shape", lambda w: calls.append("restore")
    )
    window.set_menu_bar_mode(True)
    window.set_menu_bar_mode(False)
    assert calls == ["round", "restore"]


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


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_tray_passes_native_menu_spec(qtbot, monkeypatch):
    """面板形态把声明式 menu_spec（含勾选回调）交给原生状态栏项。"""
    import utils.macos_status_item as msi
    from utils.config_utils import load_config, save_config

    captured = {}

    def fake_create(on_toggle, menu_spec):
        captured["on_toggle"] = on_toggle
        captured["spec"] = menu_spec
        return object()

    monkeypatch.setattr(msi, "create", fake_create)
    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    titles = [e["title"] for e in captured["spec"] if "title" in e]
    assert titles == ["打开面板", "VPN 连接", "退出"]
    connect_entry = captured["spec"][1]
    assert callable(connect_entry["action"])
    assert callable(connect_entry["is_checked"])
    assert w._mac_status_item is not None
    assert w.tray_icon is None
    w.reconnect_manager.cancel()
