from views.direct_ip_reconnect_dialog import DirectIpReconnectDialog


def test_dialog_default_is_later_and_buttons(qtbot):
    d = DirectIpReconnectDialog()
    qtbot.addWidget(d)
    assert d.keep_btn.text() == "稍后"
    assert d.reconnect_btn.text() == "现在重连"
    assert d.keep_btn.isDefault() is True
