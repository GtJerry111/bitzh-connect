import pytest


@pytest.fixture(autouse=True)
def _instant(monkeypatch):
    """颜色动画退化为即时切换，便于断言样式。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)


@pytest.fixture
def panel(qtbot):
    from views.status_panel import StatusPanel

    p = StatusPanel(server_text="112.91.150.228")
    qtbot.addWidget(p)
    p.show()  # Qt 语义：顶层未 show 时子控件 isVisible() 恒 False
    return p


def test_initial_state(panel):
    assert panel.status_text.text() == "未连接"
    assert panel.subtitle.text() == "112.91.150.228"
    assert panel.ip_text == "—"
    assert panel.duration_text == "00:00:00"
    assert not panel.spinner.isVisible()
    assert panel.status_dot.isVisible()


def test_connecting_shows_spinner_hides_dot(panel, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    monkeypatch.setattr("views.busy_spinner.reduce_motion", lambda: False)
    panel.set_connecting()
    assert "连接中" in panel.status_text.text()
    assert panel.spinner.isVisible()
    assert not panel.status_dot.isVisible()


def test_connected_state_and_areas_signal(panel):
    fired = []
    panel.areas_changed.connect(lambda c, r: fired.append((c, r)))
    panel.set_connecting()
    fired.clear()
    panel.set_connected("10.0.43.17")
    assert panel.status_text.text() == "已连接"
    assert panel.subtitle.text() == "10.0.43.17 · 112.91.150.228"
    assert panel.ip_text == "10.0.43.17"
    assert panel._duration_timer.isActive()
    assert not panel.spinner.isVisible()
    assert panel.status_dot.isVisible()
    assert fired == [(False, True)]  # 凭据收起、资源展开


def test_auth_failure_hero_and_detail(panel):
    """F3 回归：认证失败 hero 只放短词，原因进副标题（不再截断）"""
    panel.set_disconnected(hero="认证失败", detail="请检查用户名和密码")
    assert panel.status_text.text() == "认证失败"
    assert panel.subtitle.text() == "请检查用户名和密码"


def test_reconnecting_countdown_in_subtitle(panel, qtbot):
    fired = []
    panel.areas_changed.connect(lambda c, r: fired.append((c, r)))
    panel.set_reconnecting(1, 3)
    assert panel.status_text.text() == "连接中断"
    assert "3" in panel.subtitle.text()
    assert "第 1 次" in panel.subtitle.text()
    qtbot.wait(1300)
    assert "2" in panel.subtitle.text()
    assert fired == [(False, False)]  # 重连等待：凭据不收起、资源收起


def test_paused_message_and_areas(panel):
    fired = []
    panel.areas_changed.connect(lambda c, r: fired.append((c, r)))
    panel.set_reconnect_paused()
    assert panel.status_text.text() == "自动重连已暂停"
    assert "手动连接" in panel.subtitle.text()
    assert fired == [(True, False)]  # 暂停后用户要操作：凭据展开


def test_disconnected_resets(panel):
    panel.set_connected("10.0.43.17")
    panel.set_disconnected()
    assert panel.status_text.text() == "未连接"
    assert panel.subtitle.text() == "112.91.150.228"
    assert panel.ip_text == "—"
    assert not panel._duration_timer.isActive()


def test_set_rates(panel):
    panel.set_rates("1.2 MB/s", "3.4 MB/s")
    assert panel.up_text == "1.2 MB/s"
    assert panel.down_text == "3.4 MB/s"
    panel.set_disconnected()
    assert panel.up_text == "—"
    assert panel.down_text == "—"
