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


def test_tun_never_started_does_not_reconnect(qtbot):
    """TUN 内核从未拉起（启动失败）时不自动重连——重连只会再弹授权框骚扰用户"""
    from utils.connection_utils import handle_connection_finished
    from utils.tun_worker import TunWorker

    win = _make_window(qtbot)
    win._manual_stop = False
    win._auth_failed = False
    worker = TunWorker("/tmp/bitzh-test-nonexistent.log", "/tmp/bitzh-test-nonexistent.pid")
    # 与真实启动路径一致：信号先连上（handle_connection_finished 里会 disconnect）
    worker.output.connect(lambda _t: None)
    worker.finished.connect(lambda _c: None)
    win.worker = worker
    assert worker.kernel_started is False

    fired = []
    win.reconnect_manager._reconnect_action = lambda: fired.append(True)
    handle_connection_finished(win, -1)
    qtbot.wait(300)
    assert fired == []
    assert win.reconnect_manager.retry_count == 0


def test_tun_kernel_started_does_schedule_reconnect(qtbot):
    """TUN 内核拉起过再掉线（如断网），应正常进入自动重连"""
    from utils.connection_utils import handle_connection_finished
    from utils.tun_worker import TunWorker

    win = _make_window(qtbot)
    win._manual_stop = False
    win._auth_failed = False
    worker = TunWorker("/tmp/bitzh-test-nonexistent.log", "/tmp/bitzh-test-nonexistent.pid")
    worker.kernel_started = True  # 模拟内核曾正常运行
    worker.output.connect(lambda _t: None)
    worker.finished.connect(lambda _c: None)
    win.worker = worker

    handle_connection_finished(win, -1)
    assert win.reconnect_manager.retry_count == 1  # 已安排退避重连
    win.reconnect_manager.cancel()


def test_empty_credentials_rolls_back_fake_connected_state(qtbot):
    """空凭据触发连接的早退必须复位按钮勾选/文案/输入框，不留"假连接"态。

    可达路径：空凭据点托盘"VPN 连接"（托盘 action 不受主窗口内联校验禁用影响）。
    """
    win = _make_window(qtbot)
    win.username_input.clear()
    win.password_input.clear()
    # 真实路径：点托盘"VPN 连接"时 Qt 会先勾选 action 自身，再 triggered → 按钮
    win.tray_connect_action.setChecked(True)
    win.connect_button.setChecked(True)  # 模拟托盘触发
    assert win.connect_button.isChecked() is False
    assert win.connect_button.text() == "连接"
    assert win.username_input.isEnabled()
    assert win.password_input.isEnabled()
    assert win.status_panel.subtitle.text() == "请输入用户名和密码"
    # 早退复位在 QSignalBlocker 下进行，托盘勾选无法靠 toggled 联动，须显式复位
    assert win.tray_connect_action.isChecked() is False


def test_tun_conflict_aborts_before_spawn(qtbot, monkeypatch):
    """TUN 冲突早退：不创建 worker、不触发提权，按钮/输入框/托盘复位且仪表盘提示冲突网卡"""
    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr("utils.connection_utils.check_tun_conflict", lambda: "utun9")
    spawned = []
    monkeypatch.setattr(
        "utils.connection_utils.spawn_elevated_async",
        lambda *a, **k: spawned.append(True),
    )

    win.connect_button.setChecked(True)  # 模拟点"连接"

    assert spawned == []  # 早退绝不能触发真实提权（开发机会弹授权框）
    assert win.worker is None
    assert win.connect_button.isChecked() is False
    assert win.connect_button.text() == "连接"
    assert win.username_input.isEnabled()
    assert win.password_input.isEnabled()
    assert win.status_panel.status_text.text() == "未连接"
    assert win.status_panel.subtitle.text() == "与 utun9 的 TUN 冲突"
    assert win.tray_connect_action.isChecked() is False


def test_windows_tun_hard_guard(qtbot, monkeypatch):
    """Windows 硬守卫：即使编程绕过置灰开关，TUN 分支也直接早退、不提权"""
    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr("utils.connection_utils.system", lambda: "Windows")
    spawned = []
    monkeypatch.setattr(
        "utils.connection_utils.spawn_elevated_async",
        lambda *a, **k: spawned.append(True),
    )

    win.connect_button.setChecked(True)

    assert spawned == []
    assert win.worker is None
    assert win.connect_button.isChecked() is False
    assert win.status_panel.subtitle.text() == "本期暂不支持 Windows TUN"


def test_stale_spawn_done_kills_orphan_kernel(qtbot, monkeypatch):
    """快速重连 spawn 竞态：连接1 的授权回调迟到时 window.worker 已换成新 worker，
    内核1 刚被拉起即成孤儿（root + 全局路由），必须立即补杀；回调2 正常不误杀"""
    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr("utils.connection_utils.check_tun_conflict", lambda: None)
    callbacks = []
    monkeypatch.setattr(
        "utils.connection_utils.spawn_elevated_async",
        lambda launcher, on_done: callbacks.append(on_done),
    )
    killed = []
    monkeypatch.setattr(
        "utils.connection_utils.kill_elevated_async",
        lambda pid, on_done=None: killed.append(pid),
    )

    # 连接1：worker1 启动，spawn1 在途
    win.connect_button.setChecked(True)
    assert len(callbacks) == 1
    worker1 = win.worker
    assert worker1 is not None

    # 用户断开1（worker1 收尾、临时文件清掉）→ 立即重连2（worker2 + spawn2）
    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)
    win.connect_button.setChecked(True)
    assert len(callbacks) == 2
    worker2 = win.worker
    assert worker2 is not None and worker2 is not worker1

    # 模拟 launcher1 已被批准执行：pidfile1 被重新写入内核1 的 pid
    with open(worker1.pid_path, "w") as f:
        f.write("31415")

    # 回调1 迟到到达：worker 已换成 worker2 → 内核1 孤儿 → 补杀
    callbacks[0](True)
    assert killed == [31415]
    # 回调2 正常到达：worker 匹配且未 stop → 不误杀
    callbacks[1](True)
    assert killed == [31415]

    # 收尾：停掉 worker2，避免测试结束时 QThread 存活告警
    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


class _StubTimer:
    """记录 singleShot 调用但不真正调度，避免测试进程真的退出"""
    calls = []

    @staticmethod
    def singleShot(ms, fn):
        _StubTimer.calls.append((ms, fn))


def test_quit_app_reentrant_and_defers_quit(qtbot, monkeypatch):
    """退出流程可重入：重复调用 quit_app 不重复调度退出计时器"""
    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    _StubTimer.calls.clear()
    win = _make_window(qtbot)
    win.show()
    win.quit_app()
    assert win._quitting is True
    assert not win.isVisible()
    assert len(_StubTimer.calls) == 1
    assert _StubTimer.calls[0][0] == 1500
    win.quit_app()  # 第二次调用应是空操作
    assert len(_StubTimer.calls) == 1


def test_close_event_during_quit_accepted_without_touching_tray(qtbot, monkeypatch):
    """macOS teardown 补发的 closeEvent 在退出流程中必须安全放行（F1 回归）"""
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    win = _make_window(qtbot)
    win.quit_app()
    event = QCloseEvent()
    win.closeEvent(event)  # 不应抛异常（托盘可能已被 deleteLater）
    assert event.isAccepted()


def test_close_event_with_deleted_tray_no_crash(qtbot, monkeypatch):
    """托盘对象已销毁时 handle_close_event 不得抛异常（RuntimeError 守卫）"""
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QCloseEvent
    from utils.tray_utils import handle_close_event

    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    win = _make_window(qtbot)
    dead = QObject()
    dead.deleteLater()
    qtbot.wait(50)  # 让 DeferredDelete 生效，C++ 对象真正销毁
    event = QCloseEvent()
    handle_close_event(win, event, dead)  # 不抛异常，走 quit 路径
    assert win._quitting is True
