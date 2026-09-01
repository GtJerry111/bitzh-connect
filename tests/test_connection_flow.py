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
