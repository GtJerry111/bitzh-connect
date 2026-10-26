from views.direct_ip_banner import DirectIpBanner


def test_banner_message_and_dismiss(qtbot):
    banner = DirectIpBanner()
    qtbot.addWidget(banner)
    banner.show_message(1, 2, ["10.182.37.19"])
    assert not banner.isHidden()
    assert "1/2" in banner.message.text()
    assert "10.182.37.19" in banner.message.text()
    banner.close_btn.click()
    assert banner.isHidden()


def test_banner_open_logs_signal(qtbot):
    banner = DirectIpBanner()
    qtbot.addWidget(banner)
    emitted = []
    banner.open_logs.connect(lambda: emitted.append(1))
    banner.logs_btn.click()
    assert emitted == [1]
