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


def test_log_toggle_reveals_output(window, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    assert not window.output_text.isVisible()
    window.log_toggle.setChecked(True)
    assert window.output_text.isVisible()
    window.log_toggle.setChecked(False)
    assert not window.output_text.isVisible()


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
    assert window.resource_area.isVisible()
    window.status_panel.set_disconnected()
    assert window.cred_area.isVisible()
    assert not window.resource_area.isVisible()


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


def test_log_toggle_shows_text_beside_arrow(window):
    """回归：日志折叠开关必须显示"运行日志"文字（默认 IconOnly 会吞掉文字只剩裸箭头）"""
    from PySide6.QtCore import Qt

    assert window.log_toggle.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    assert window.log_toggle.text() == "运行日志"


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
