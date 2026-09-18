# tests/test_menu_bar_panel.py
"""菜单栏快捷面板（offscreen：玻璃/状态栏项桥接自动回退，结构行为全可测）。"""
import pytest
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def main(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def panel(main, qtbot):
    from views.menu_bar_panel import MenuBarPanel

    p = MenuBarPanel(main)
    qtbot.addWidget(p)
    return p


def test_panel_structure(panel):
    assert panel.width() == 300
    assert panel._toggle is not None
    assert panel._status.text() == "未连接"


def test_toolbar_uses_glass_buttons(panel):
    """工具条按钮为自绘玻璃 chip（QSS 半透描边在透明底窗口上出毛刺）。"""
    from views.menu_bar_panel import _GlassButton

    for btn in (panel._open_btn, panel._settings_btn, panel._quit_btn):
        assert isinstance(btn, _GlassButton)
    assert panel._settings_btn._icon_kind == "gear"  # 设置入口 = 齿轮按钮
    assert panel._quit_btn.width() == 28  # 圆形 28×28
    assert panel._open_btn.sizeHint().width() > 28  # pill 含文字，比圆钮宽


def test_glass_button_paint_offscreen(panel, qtbot):
    """自绘路径冒烟：hover/pressed 态离屏渲染不抛异常。"""
    from PySide6.QtGui import QPixmap

    btn = panel._settings_btn
    pm = QPixmap(56, 56)
    pm.fill()
    btn._hover = True
    btn.render(pm)  # render 即走 paintEvent
    btn._hover = False
    btn.setDown(True)
    btn.render(pm)
    btn.setDown(False)


def test_mirror_connected(panel, main, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    main.status_panel.set_connected("10.0.43.17")
    assert panel._status.text() == "已连接"
    assert panel._subtitle.text() == "内网 IP 10.0.43.17"
    assert not panel._stats_area.isHidden()


def test_mirror_disconnected_hides_stats(panel, main, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    main.status_panel.set_connected("10.0.43.17")
    main.status_panel.set_disconnected()
    assert panel._status.text() == "未连接"
    assert panel._stats_area.isHidden()


def test_toggle_drives_connect_button(panel, main, monkeypatch):
    called = []
    monkeypatch.setattr(main, "start_connection", lambda: called.append(1))
    main.username_input.setText("u")
    main.password_input.setText("p")
    panel._toggle.click()
    assert main.connect_button.isChecked()
    assert called


def test_no_credentials_hint_and_open_main(panel, main, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    opened = []
    monkeypatch.setattr(
        main, "open_main_window",
        lambda focus_credentials=False: opened.append(focus_credentials),
    )
    panel._toggle.click()  # 凭据为空 → start_connection 早退复位
    assert not panel._toggle.isChecked()  # 弹回
    assert panel._hint_active
    assert panel._subtitle.text() == "请先在主窗口填写凭据"
    assert opened == [True]


def test_sync_metrics_heals_toggle_desync_after_silent_reset(panel, main):
    # 复现 QSignalBlocker 静默复位 connect_button 后的错位：
    # connect_button 实际未勾选，但面板 toggle 仍卡在 ON（toggled 被屏蔽不回环）。
    with QSignalBlocker(panel._toggle):
        panel._toggle.setChecked(True)
    with QSignalBlocker(main.connect_button):
        main.connect_button.setChecked(False)
    assert panel._toggle.isChecked()  # 面板显示 ON
    assert not main.connect_button.isChecked()  # 实际未连接

    panel._sync_metrics()  # 1s 轮询

    assert not panel._toggle.isChecked()  # 自愈到实际态


def test_panel_window_flags(panel):
    from PySide6.QtCore import Qt

    flags = panel.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.Tool
    assert flags & Qt.WindowStaysOnTopHint
    assert panel.testAttribute(Qt.WA_TranslucentBackground)


def test_esc_hides_panel(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    assert panel.isVisible()
    panel._esc.activated.emit()
    assert not panel.isVisible()


def test_hide_on_deactivate(panel, qtbot, monkeypatch):
    from PySide6.QtCore import QEvent

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    panel.event(QEvent(QEvent.WindowDeactivate))
    assert not panel.isVisible()


def test_show_panel_anchors_on_screen(panel, qtbot, monkeypatch):
    """无状态栏项（offscreen）退化到屏幕右上角可见区域内。"""
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    geo = QApplication.primaryScreen().availableGeometry()
    assert geo.contains(panel.geometry().topLeft())
    panel.hide_panel()


def test_mode_row_fallback_toggles_mode(panel, main, monkeypatch):
    """原生菜单不可用（offscreen 抛 RuntimeError）→ 点击直接切换模式。"""
    old = main.tun_mode
    panel._on_mode_row()
    assert main.tun_mode == (not old)
    panel._on_mode_row()
    assert main.tun_mode == old


def test_nav_expand_toggle(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    assert panel._nav_area.isHidden()
    panel._nav_row.clicked.emit()
    assert not panel._nav_area.isHidden()
    assert panel._nav_chevron._angle == 270.0
    panel._nav_row.clicked.emit()
    assert panel._nav_area.isHidden()


def test_nav_chip_opens_url(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    opened = []
    monkeypatch.setattr(
        "views.menu_bar_panel.QDesktopServices.openUrl",
        lambda url: opened.append(url),
    )
    panel._nav_row.clicked.emit()
    first_chip = panel._nav_area.findChildren(QPushButton)[0]
    first_chip.click()
    assert opened and str(opened[0].url()).startswith("http")


def test_toggle_panel_lazy_creates(main, qtbot, monkeypatch):
    # 面板模块直接 from-import reduce_motion：两处都打桩，避免依赖模块导入顺序
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    assert main._menu_bar_panel is None
    main.toggle_panel()
    assert main._menu_bar_panel is not None
    assert main._menu_bar_panel.isVisible()
    main.toggle_panel()
    assert not main._menu_bar_panel.isVisible()


def test_close_hides_to_status_item(main, qtbot):
    """macOS NSStatusItem 存在 = 后台驻留：关窗隐藏而非退出。"""
    main._mac_status_item = object()  # 哨兵：非 None 即驻留
    from PySide6.QtGui import QCloseEvent

    event = QCloseEvent()
    main.closeEvent(event)
    assert not event.isAccepted()


def test_menu_bar_mode_config_removed(qtbot):
    from utils.config_utils import load_config

    assert "menu_bar_mode" not in load_config()


def test_nav_group_label_refreshes_on_theme_change(panel, qapp):
    """回归：切深浅色后导航组标题颜色随之刷新，不停留旧 secondary_text。"""
    from common import theme

    assert panel._nav_group_labels  # 组标题已收集
    # 切深色会触发 theme 刷新回调（_apply_styles → _refresh_nav_chips）
    theme.set_appearance("dark")
    try:
        dark = theme.semantic_color("secondary_text")
        assert dark == "#98989D"  # 锁住深色 token 值，避免断言空转
        assert any(dark in lbl.styleSheet() for lbl in panel._nav_group_labels)
    finally:
        theme.set_appearance("system")


def test_panel_hairline_refreshes_on_theme_change(panel, qapp):
    """回归（I1）：切深浅色后面板分隔线颜色随之刷新，不停留旧主题色。"""
    from common import theme

    theme.set_appearance("light")
    try:
        light = theme.with_alpha("separator", 0.6)
        assert light == "rgba(209,209,214,0.6)"  # 锁住浅色换算，避免断言空转
        assert light in panel._card_hairline.styleSheet()

        theme.set_appearance("dark")
        dark = theme.with_alpha("separator", 0.6)
        assert dark == "rgba(58,58,60,0.6)"  # 锁住深色 token 值
        assert dark in panel._card_hairline.styleSheet()
        assert theme.with_alpha("separator", 0.4) in panel._row_sep.styleSheet()
    finally:
        theme.set_appearance("system")
