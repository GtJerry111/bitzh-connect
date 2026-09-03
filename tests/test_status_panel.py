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
    # 空态不陈列假数据：时长/速率统一 "—" 占位符
    assert panel.duration_text == "—"
    assert panel.up_text == "—" and panel.down_text == "—"
    assert not panel.spinner.isVisible()
    assert panel.status_dot.isVisible()
    # 统计行仅已连接态展开（未连接不陈列空数据）
    assert panel.stats_area.isHidden()


def test_dot_initial_color_is_idle_not_black(panel):
    """回归：启动第一眼圆点必须是 idle 灰，不是默认黑（原字形方案无人给初始态上色）"""
    from common import theme

    expected = theme.semantic_color("idle").lower()
    assert panel.status_dot._color.name() == expected


def test_dot_glow_only_when_connected(panel):
    """spec 的"绿+柔光"：已连接挂 QGraphicsDropShadowEffect，其余态无"""
    assert panel.status_dot.graphicsEffect() is None
    panel.set_connected("10.0.43.17")
    assert panel.status_dot.graphicsEffect() is not None
    panel.set_disconnected()
    assert panel.status_dot.graphicsEffect() is None


def test_hero_word_takes_state_color(panel):
    """状态词本身着色：已连接绿 / 未连接 ink（26pt 大字带色，一眼可读状态）"""
    from common import theme

    assert theme.semantic_color("ink").lower() in panel.status_text.styleSheet().lower()
    panel.set_connected("10.0.43.17")
    assert theme.semantic_color("connected").lower() in panel.status_text.styleSheet().lower()


def test_stats_row_expand_collapse_with_connection(panel):
    """统计行：连接成功展开、断开收起（空态不陈列）"""
    panel.set_connected("10.0.43.17")
    assert not panel.stats_area.isHidden()
    panel.set_disconnected()
    assert panel.stats_area.isHidden()


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
    # 副标题只给用户语言"内网 IP"（服务器地址挪 tooltip，不再双裸 IP 并排）
    assert panel.subtitle.text() == "内网 IP 10.0.43.17"
    assert panel.subtitle.toolTip() == "112.91.150.228"
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


def test_connecting_hides_dot_even_when_window_hidden(qtbot, monkeypatch):
    """回归：主窗口隐藏（托盘发起连接/silent_mode 自连）时 dot 也必须让位 spinner。
    isVisible() 受祖先隐藏影响恒 False，互斥谓词必须用控件自身的 isHidden。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    monkeypatch.setattr("views.busy_spinner.reduce_motion", lambda: False)
    from views.status_panel import StatusPanel

    p = StatusPanel(server_text="112.91.150.228")  # 不 show：模拟窗口隐藏
    qtbot.addWidget(p)
    p.set_connecting()
    assert not p.spinner.isHidden()
    assert p.status_dot.isHidden()


def test_refresh_theme_colors_stat_labels(panel):
    """深浅色切换（refresh_theme）须刷新统计行标题与副标题颜色。"""
    from common import theme

    for label in panel._stat_labels:
        label.setStyleSheet("")
    panel.subtitle.setStyleSheet("")
    panel.refresh_theme()
    expected = theme.semantic_color("secondary_text").lower()
    for label in panel._stat_labels:
        assert expected in label.styleSheet().lower()
    assert expected in panel.subtitle.styleSheet().lower()


def test_set_rates(panel):
    panel.set_rates("1.2 MB/s", "3.4 MB/s")
    assert panel.up_text == "↑ 1.2 MB/s"
    assert panel.down_text == "↓ 3.4 MB/s"
    panel.set_disconnected()
    assert panel.up_text == "—"
    assert panel.down_text == "—"


def test_placeholder_gray_data_ink(panel):
    """"—" 占位符染次要色退后；真数据按语义着色（数字与波形颜色自映射）"""
    from common import theme

    secondary = theme.semantic_color("secondary_text").lower()
    working = theme.semantic_color("working").lower()
    accent = theme.semantic_color("accent").lower()
    ink = theme.semantic_color("ink").lower()
    assert secondary in panel.up_value.styleSheet().lower()
    panel.set_connected("10.0.43.17")
    panel.set_rates("1.2 MB/s", "3.4 MB/s")
    # 上行赭石、下行绿（与波形一致），时长保持 ink
    assert working in panel.up_value.styleSheet().lower()
    assert accent in panel.down_value.styleSheet().lower()
    assert ink in panel.duration_value.styleSheet().lower()


def test_graph_visibility_follows_support_and_connection(panel):
    """波形图：有数据源且已连接才显示；断开清空样本并随统计区收起"""
    assert panel.rate_graph.isHidden()
    panel.set_graph_supported(True)
    panel.set_connected("10.0.43.17")
    assert not panel.rate_graph.isHidden()
    panel.append_rate_sample(100.0, 200.0)
    assert len(panel.rate_graph._samples) == 1
    panel.set_disconnected()
    assert len(panel.rate_graph._samples) == 0


def test_graph_hidden_when_unsupported(panel):
    """无数据源（如 Windows/Linux 代理模式）：连接后波形图不显示（不陈列空数据）"""
    panel.set_graph_supported(False)
    panel.set_connected("10.0.43.17")
    assert panel.rate_graph.isHidden()  # offscreen：父链已 show，isHidden 只看自身标志
    # tooltip 提供克制提示（零常驻像素）
    assert "TUN" in panel.up_value.toolTip()


def test_dark_mode_card_surface(panel):
    """深色分层：仪表盘垫一层 card_background 微亮表面；浅色保持透明"""
    from common import theme

    theme.set_appearance("dark")
    panel.refresh_theme()
    assert "background-color" in panel.styleSheet()
    theme.set_appearance("light")
    panel.refresh_theme()
    assert panel.styleSheet() == ""
    theme.set_appearance("system")
