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
    from common import panel_material
    from views.menu_bar_panel import MenuBarPanel

    p = MenuBarPanel(main)
    qtbot.addWidget(p)
    # 材质参数会从磁盘读（真机调参留档），测试里固定回默认值保证确定性
    p.apply_material(panel_material.defaults())
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


def test_esc_on_subpage_returns_home(panel, qtbot, monkeypatch):
    """Esc：二级页 → 返回主页（不收起）；主页 → 收起。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    panel._nav_row.clicked.emit()
    assert panel._stack.currentIndex() == 1
    panel._esc.activated.emit()
    assert panel._stack.currentIndex() == 0
    assert panel.isVisible()  # 返回主页而非收起
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


def test_mode_row_opens_mode_page(panel, main, monkeypatch):
    """模式行点击 → 模式页（内联聚焦页，radio 同步当前模式）。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    panel._mode_row.clicked.emit()
    assert panel._stack.currentIndex() == 2
    # radio 选中态镜像当前模式
    assert panel._mode_radios[1].is_on() == bool(main.tun_mode)


def test_mode_radio_switches_and_returns(panel, main, monkeypatch, qtbot):
    """radio 选择 → set_connection_mode；250ms 后自动回主页。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    panel._switch_page(2)
    old = main.tun_mode
    panel._mode_radios[0].clicked.emit()  # 代理
    assert main.tun_mode is False
    qtbot.waitUntil(lambda: panel._stack.currentIndex() == 0, timeout=1500)
    # 再选 TUN 还原
    panel._switch_page(2)
    panel._mode_radios[1].clicked.emit()
    assert main.tun_mode is True
    qtbot.waitUntil(lambda: panel._stack.currentIndex() == 0, timeout=1500)


def test_nav_row_opens_nav_page(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    assert panel._stack.currentIndex() == 0
    panel._nav_row.clicked.emit()
    assert panel._stack.currentIndex() == 1
    # 标题行返回主页
    from views.menu_bar_panel import _Row

    header_row = panel._nav_header.findChildren(_Row)[0]
    header_row.clicked.emit()
    assert panel._stack.currentIndex() == 0


def test_nav_chip_opens_url(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    opened = []
    monkeypatch.setattr(
        "views.menu_bar_panel.QDesktopServices.openUrl",
        lambda url: opened.append(url),
    )
    panel._nav_row.clicked.emit()
    first_chip = panel._nav_card.findChildren(QPushButton)[0]
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
    """回归（I1）：切深浅色后面板分隔线颜色随之刷新，不停留旧主题色。

    alpha 现在来自材质参数（panel_material.hairline），浅深各一套。
    """
    from common import theme

    alpha = panel._m["light"]["hairline"]
    theme.set_appearance("light")
    try:
        light = theme.with_alpha("separator", alpha)
        assert light.startswith("rgba(209,209,214,")  # 锁住浅色换算，避免断言空转
        assert light in panel._card_hairline.styleSheet()

        theme.set_appearance("dark")
        dark_alpha = panel._m["dark"]["hairline"]
        dark = theme.with_alpha("separator", dark_alpha)
        assert dark.startswith("rgba(58,58,60,")  # 锁住深色 token
        assert dark in panel._card_hairline.styleSheet()
        assert theme.with_alpha("separator", dark_alpha * 0.75) in panel._row_sep.styleSheet()
    finally:
        theme.set_appearance("system")


def test_apply_material_changes_geometry(panel, qapp):
    """调参入口：材质参数即时驱动面板几何（行高/内边距/块间距）。"""
    from common import panel_material, theme

    params = panel_material.defaults()
    params["light"]["row_height"] = 40
    params["light"]["pad"] = 16
    params["light"]["gap"] = 12
    theme.set_appearance("light")
    try:
        panel.apply_material(params)
        assert panel._root_layout.contentsMargins().left() == 16
        assert panel._main_layout.spacing() == 12
        assert panel._mode_row.height() == 40
    finally:
        theme.set_appearance("system")


def test_row_click_emits_on_release_inside(panel):
    """按下并释放在行内才触发点击；拖出取消（与系统控件一致）。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    fired = []
    panel._mode_row.clicked.connect(lambda: fired.append(1))

    def _mouse(kind, pos):
        return QMouseEvent(
            kind, QPointF(*pos), panel._mode_row.mapToGlobal(QPointF(*pos)),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )

    inside = (10, 10)
    panel._mode_row.mousePressEvent(_mouse(QEvent.MouseButtonPress, inside))
    panel._mode_row.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, inside))
    assert fired == [1]

    panel._mode_row.mousePressEvent(_mouse(QEvent.MouseButtonPress, inside))
    panel._mode_row.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, (9999, 9999)))
    assert fired == [1]  # 释放在行外不算点击


def test_pinned_panel_ignores_deactivate(panel, monkeypatch):
    """调参期间钉住：失焦不收起。"""
    from PySide6.QtCore import QEvent

    monkeypatch.setattr("views.menu_bar_panel.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    panel.set_pinned(True)
    panel.event(QEvent(QEvent.WindowDeactivate))
    assert panel.isVisible()
    panel.set_pinned(False)
    panel.event(QEvent(QEvent.WindowDeactivate))
    assert not panel.isVisible()


def test_panel_material_roundtrip(tmp_path, monkeypatch):
    """材质参数写盘/读回（调参窗定稿路径）。"""
    from common import panel_material

    monkeypatch.setattr(panel_material, "_path", lambda: tmp_path / "m.json")
    params = panel_material.defaults()
    params["glass_style"] = "clear"
    params["corner_radius"] = 18.0
    params["dark"]["chip_fill"] = 0.33
    panel_material.save(params)
    loaded = panel_material.load()
    assert loaded["glass_style"] == "clear"
    assert loaded["corner_radius"] == 18.0
    assert loaded["dark"]["chip_fill"] == 0.33


def test_panel_material_load_falls_back_on_garbage(tmp_path, monkeypatch):
    from common import panel_material

    bad = tmp_path / "m.json"
    bad.write_text("{not json")
    monkeypatch.setattr(panel_material, "_path", lambda: bad)
    assert panel_material.load() == panel_material.defaults()


def test_panel_tuner_drives_real_panel_and_commits(panel, qapp, tmp_path, monkeypatch):
    """调参窗：滑杆实时改真面板；定稿写盘；关闭解除钉住。"""
    from common import panel_material as pm
    from views.panel_tuner import PanelTuner

    monkeypatch.setattr(pm, "_path", lambda: tmp_path / "m.json")
    monkeypatch.setattr(
        "views.menu_bar_panel.reduce_motion", lambda: True,
    )
    tuner = PanelTuner(panel)
    assert panel._tuner_pinned is True

    tuner._rows["row_height"]["slider"].setValue(900)  # 24→44 区间的 90%
    assert panel._m["light"]["row_height"] == 42

    tuner._commit()
    assert (tmp_path / "m.json").exists()
    assert pm.load()["light"]["row_height"] == 42

    tuner.close()
    assert panel._tuner_pinned is False
