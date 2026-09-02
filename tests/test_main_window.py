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
