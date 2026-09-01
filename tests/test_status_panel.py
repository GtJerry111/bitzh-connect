import pytest


@pytest.fixture(autouse=True)
def _instant(monkeypatch):
    """颜色动画退化为即时切换，便于断言样式。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)


@pytest.fixture
def panel(qtbot):
    from views.status_panel import StatusPanel

    p = StatusPanel(server_text="112.91.150.228")
    # Qt 语义：父窗口未 show 时子控件 isVisible() 恒为 False，
    # 必须 show 才能断言 spinner 的可见性
    p.show()
    qtbot.addWidget(p)
    return p


def test_initial_state(panel):
    assert "未连接" in panel.status_text.text()
    assert panel.ip_value.text() == "—"
    assert panel.duration_value.text() == "00:00:00"
    assert not panel.spinner.isVisible()


def test_connecting_shows_spinner(panel, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    panel.set_connecting()
    assert "连接中" in panel.status_text.text()
    assert panel.spinner.isVisible()


def test_connected_shows_ip_and_starts_timer(panel):
    from common import theme

    panel.set_connecting()
    panel.set_connected("10.0.43.17")
    assert "已连接" in panel.status_text.text()
    assert panel.ip_value.text() == "10.0.43.17"
    assert panel._duration_timer.isActive()
    assert not panel.spinner.isVisible()
    assert theme.semantic_color("connected").lower() in panel.status_dot.styleSheet().lower()


def test_disconnected_resets(panel):
    panel.set_connected("10.0.43.17")
    panel.set_disconnected()
    assert "未连接" in panel.status_text.text()
    assert panel.ip_value.text() == "—"
    assert not panel._duration_timer.isActive()


def test_reconnecting_countdown_decrements(panel, qtbot):
    panel.set_reconnecting(1, 3)
    assert "3" in panel.status_text.text()
    assert "第 1 次" in panel.status_text.text()
    qtbot.wait(1300)
    assert "2" in panel.status_text.text()  # 倒计时递减，持续反馈


def test_paused_message(panel):
    from common import theme

    panel.set_reconnect_paused()
    assert "暂停" in panel.status_text.text()
    assert theme.semantic_color("error").lower() in panel.status_dot.styleSheet().lower()


def test_proxy_mode_rates_placeholder(panel):
    panel.set_connected("10.0.43.17")
    assert panel.up_rate_value.text() == "—"
    assert panel.down_rate_value.text() == "—"


def test_card_title_color_refreshes_with_theme(panel):
    """深浅色切换（refresh_theme）须刷新卡片标题色，不能只刷卡片底色。"""
    from common import theme

    for label in panel._card_title_labels:
        label.setStyleSheet("")
    panel.refresh_theme()
    for label in panel._card_title_labels:
        assert theme.semantic_color("secondary_text").lower() in label.styleSheet().lower()
