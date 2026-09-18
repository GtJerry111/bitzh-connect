# tests/test_menu_bar_panel.py
"""菜单栏快捷面板（offscreen：玻璃/状态栏项桥接自动回退，结构行为全可测）。"""
import pytest
from PySide6.QtCore import QSignalBlocker


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
