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
