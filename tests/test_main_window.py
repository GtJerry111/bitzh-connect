import pytest


@pytest.fixture
def window(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    # Qt 语义：顶层窗口未 show 时子控件 isVisible() 恒为 False，
    # 必须 show 才能断言 output_text 的可见性
    w.show()
    qtbot.addWidget(w)
    yield w
    w.reconnect_manager.cancel()


def test_connect_button_disabled_without_credentials(window):
    window.username_input.setText("")
    window.password_input.setText("")
    assert not window.connect_button.isEnabled()
    assert window.connect_button.toolTip() != ""


def test_connect_button_enabled_after_filling_credentials(window):
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    assert window.connect_button.isEnabled()


def test_log_not_on_main_window(window):
    """运行日志已从主窗口撤除（收进设置对话框帮助 tab）；
    output_text 缓冲保留为隐藏存储（各处 append 路径不动）"""
    assert not hasattr(window, "log_toggle")
    assert window.output_text.isVisible() is False


def test_accent_button_uses_bit_green(window):
    from common import theme

    assert theme.semantic_color("accent").lower() in window.connect_button.styleSheet().lower()


def test_area_animation_on_connect_disconnect(window, monkeypatch):
    """连接成功：凭据收起+资源展开；断开：还原（一收一放）"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    # 初始：凭据可见、资源隐藏（布局显隐以标志位为准，offscreen 下 isVisible 依赖父链 show）
    assert window._cred_visible is True
    assert window._res_visible is False
    window.status_panel.set_connected("10.0.43.17")
    assert not window.cred_area.isVisible()
    assert window.nav_area.isVisible()
    window.status_panel.set_disconnected()
    assert window.cred_area.isVisible()
    assert not window.nav_area.isVisible()


def test_area_visibility_idempotent(window, monkeypatch):
    """重复状态信号不重复触发动画（幂等守卫）"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.status_panel.set_connected("10.0.43.17")
    window.status_panel.set_disconnected()
    assert window._cred_visible is True and window._res_visible is False
    # 再次 set_disconnected 不应改变状态（也不会动画重跳）
    window.status_panel.set_disconnected()
    assert window.cred_area.isVisible()


def test_disabled_button_tooltip_via_event_filter(window):
    """Qt 不向 disabled widget 派发 tooltip 事件，eventFilter 须拦截补发。"""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent

    window.username_input.setText("")
    window.password_input.setText("")
    assert not window.connect_button.isEnabled()
    ev = QHelpEvent(QEvent.ToolTip, QPoint(), QPoint())
    assert window.eventFilter(window.connect_button, ev) is True

    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    assert window.connect_button.isEnabled()
    ev2 = QHelpEvent(QEvent.ToolTip, QPoint(), QPoint())
    assert window.eventFilter(window.connect_button, ev2) is False


def test_mode_switch_defaults_to_tun(window):
    """TUN 默认开启 → 分段选择器初始落在 TUN 段"""
    assert window.tun_mode is True
    assert window.mode_switch.currentIndex() == 1


def test_mode_switch_click_persists(window, qtbot):
    """主界面切模式：立即写回配置（与高级设置的 TUN 开关同一配置键）"""
    from PySide6.QtCore import QPoint, Qt

    qtbot.mouseClick(window.mode_switch, Qt.LeftButton, pos=QPoint(5, 15))
    assert window.mode_switch.currentIndex() == 0
    assert window.tun_mode is False
    from utils.config_utils import load_config

    assert load_config()["tun_mode"] is False


def test_mode_switch_bounces_when_connected(window, monkeypatch):
    """已连接时切换模式：先断后连，新模式立即生效（不是禁用/下个周期再说）"""
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))
    delayed = []
    monkeypatch.setattr(
        "views.main_window.QTimer.singleShot", lambda ms, fn: delayed.append(fn)
    )
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window.connect_button.setChecked(True)  # 模拟已连接（start 已 mock）
    fired.clear()

    window.mode_switch._set_current(0)  # 切到代理模式
    assert window.tun_mode is False
    assert fired == ["stop"]  # 先完整断开
    delayed[0]()  # 1s 后重连
    assert fired == ["stop", "start"]
    assert window.connect_button.isChecked() is True


def test_sleep_cancels_pending_reconnect(window):
    """休眠：在途重连退避取消（盒盖期间重连只会无人理会地弹授权框）"""
    window._manual_stop = False
    window._auth_failed = False
    window.reconnect_manager.on_process_exited(manual=False, auth_failed=False)
    assert window.reconnect_manager._retry_timer.isActive()
    window._on_system_sleep()
    assert not window.reconnect_manager._retry_timer.isActive()
    assert window.reconnect_manager.retry_count == 0


def test_wake_bounces_active_connection(window, monkeypatch):
    """唤醒且处于"应连接"态：先断后连（bounce），TUN 断开零弹窗、重连一次授权"""
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window._manual_stop = False
    window._auth_failed = False
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))
    delayed = []
    monkeypatch.setattr(
        "views.main_window.QTimer.singleShot", lambda ms, fn: delayed.append(fn)
    )

    window.connect_button.setChecked(True)  # 模拟已连接（start 已 mock 不真实连接）
    fired.clear()
    window._on_system_wake()
    assert fired == ["stop"]  # 先完整断开
    assert window.connect_button.isChecked() is False
    delayed[0]()  # 1s 后的重连回调
    assert window.connect_button.isChecked() is True
    assert fired == ["stop", "start"]


def test_wake_noop_when_manually_disconnected(window):
    """手动断开状态下唤醒：不得自作主张重连"""
    window._manual_stop = True
    window._auth_failed = False
    window._on_system_wake()
    assert "休眠唤醒" not in window.output_text.toPlainText()


def test_app_activate_shows_hidden_window(window):
    """Dock 激活兜底入口：主窗口隐藏时被唤出（托盘图标被拥挤菜单栏挤出时的
    唯一入口）；启动宽限期（静默启动）与退出流程中不响应"""
    window.hide()
    window._ready = False  # 启动宽限期内：静默启动不得弹窗
    window._on_app_activate()
    assert not window.isVisible()
    window._ready = True
    window._on_app_activate()
    assert window.isVisible()


def test_return_pressed_triggers_connect(window, qtbot, monkeypatch):
    """凭据齐全时输入框回车直接发起连接（桌面表单惯例）；空凭据不触发"""
    from PySide6.QtCore import Qt

    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append(True))
    window.username_input.setText("")
    window.password_input.setText("")
    qtbot.keyClick(window.password_input, Qt.Key_Return)
    assert fired == []  # disabled 态不响应
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    qtbot.keyClick(window.password_input, Qt.Key_Return)
    assert fired == [True]


def test_watermark_container_with_motto_pixmap(window):
    """中央容器即水印层：校训素材加载成功（绘制在内容之下）"""
    from views.main_window import WatermarkContainer

    assert isinstance(window.centralWidget(), WatermarkContainer)
    assert not window.centralWidget()._watermark.isNull()


def test_underline_input_style(window):
    """凭据输入框为下划线式（无边框 + 底部 1px 线，spec 定稿）"""
    style = window.username_input.styleSheet()
    assert "border-bottom" in style and "background: transparent" in style


def test_settings_button_opens_advanced_dialog(window, monkeypatch):
    """窗口内设置入口：点击"设置"打开高级设置对话框"""
    opened = []
    monkeypatch.setattr(
        "views.main_window.show_advanced_settings", lambda w: opened.append(w)
    )
    window.settings_button.click()
    assert opened == [window]


def test_motto_visibility_follows_credential_area(window, monkeypatch):
    """校训水印与凭据区联动：凭据可见时水印隐藏（防遮挡），凭据收起时淡入"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    container = window.centralWidget()
    assert container._motto_visible is False  # 未连接：凭据可见 → 水印隐藏
    window.status_panel.set_connected("10.0.43.17")
    assert container._motto_visible is True   # 凭据收起 → 水印淡入
    window.status_panel.set_disconnected()
    assert container._motto_visible is False


def test_connect_button_narrowed_and_centered(window):
    """主按钮收窄定宽 240px（不再是全宽大色块），与资源胶囊组视觉成组"""
    assert window.connect_button.minimumWidth() == 240
    assert window.connect_button.maximumWidth() == 240
