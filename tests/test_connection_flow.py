from unittest.mock import patch


def _make_window(qtbot):
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_auth_failure_blocks_reconnect(qtbot):
    win = _make_window(qtbot)
    fired = []
    win.reconnect_manager._reconnect_action = lambda: fired.append(True)
    win._manual_stop = False
    win._auth_failed = True
    win.reconnect_manager.on_process_exited(
        manual=win._manual_stop, auth_failed=win._auth_failed
    )
    qtbot.wait(300)
    assert fired == []


def test_output_parsing_sets_virtual_ip(qtbot):
    win = _make_window(qtbot)
    from utils.connection_utils import handle_output

    handle_output(win, "2026/09/01 12:00:00 Client IP: 10.0.43.17\n")
    assert win.virtual_ip == "10.0.43.17"


def test_cleanup_residue_proxy_noop_when_not_ours(qtbot):
    win = _make_window(qtbot)
    from utils.set_proxy import cleanup_residue_proxy

    with patch("utils.set_proxy.proxy_points_to_us", return_value=False):
        assert cleanup_residue_proxy(win) is False


def test_tray_action_unchecked_on_connection_finished(qtbot):
    """认证失败收尾时托盘"VPN 连接"勾选态必须复位。

    handle_connection_finished 用 QSignalBlocker 复位按钮，toggled 被屏蔽，
    托盘勾选无法靠 button.toggled 联动，必须显式同步（否则掉线后托盘仍显示已连接）。
    """
    from utils.connection_utils import handle_connection_finished

    win = _make_window(qtbot)
    win.tray_connect_action.setChecked(True)  # 模拟连接期间的托盘勾选
    win._manual_stop = False
    win._auth_failed = True  # 走认证失败路径，避免安排自动重连
    handle_connection_finished(win, 1)
    assert win.tray_connect_action.isChecked() is False
    assert win.connect_button.isChecked() is False


def test_empty_credentials_rolls_back_fake_connected_state(qtbot):
    """空凭据触发连接的早退必须复位按钮勾选/文案/输入框，不留"假连接"态。

    可达路径：空凭据点托盘"VPN 连接"（托盘 action 不受主窗口内联校验禁用影响）。
    """
    win = _make_window(qtbot)
    win.username_input.clear()
    win.password_input.clear()
    win.connect_button.setChecked(True)  # 模拟托盘触发
    assert win.connect_button.isChecked() is False
    assert win.connect_button.text() == "连接"
    assert win.username_input.isEnabled()
    assert win.password_input.isEnabled()
    assert "请输入用户名和密码" in win.status_panel.status_text.text()
