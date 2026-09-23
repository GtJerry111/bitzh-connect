import os
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


def test_rsa_material_collapsed_to_single_note(qtbot):
    """RSA 公钥材料行不上屏：折叠为一行中文说明，且每次连接只提示一次"""
    win = _make_window(qtbot)
    from utils.connection_utils import handle_output

    win._rsa_noted = False  # 模拟 start_connection 的每连接重置
    handle_output(win, "2026/09/03 10:00:00 RSA key: AB12CD34...\n")
    handle_output(win, "2026/09/03 10:00:00 RSA exp: 65537\n")
    log = win.output_text.toPlainText()
    assert "AB12CD34" not in log and "RSA exp" not in log
    assert "RSA 公钥" in log
    # 第二次同连接不再重复提示
    handle_output(win, "2026/09/03 10:00:01 RSA key: FF00\n")
    assert win.output_text.toPlainText().count("RSA 公钥") == 1


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
    worker = TunWorker("/tmp/bitzh-test-nonexistent.log", "/tmp/bitzh-test-nonexistent.pid",
                       "/tmp/bitzh-test-nonexistent.stop")
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
    worker = TunWorker("/tmp/bitzh-test-nonexistent.log", "/tmp/bitzh-test-nonexistent.pid",
                       "/tmp/bitzh-test-nonexistent.stop")
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


def test_tun_coexist_binds_physical_interface_no_abort(qtbot, monkeypatch):
    """TUN 共存：他方 TUN 截走服务器路由时，底层绑定物理网卡并继续（不再早退）"""
    import utils.connection_utils as cu
    from utils import helper_installer

    # 本用例锁的是 osascript 回退路径：固定 helper 不可用，避免装了 helper 的机器
    # 走分支①去调真实 helper_client.start（假凭据拉起 root 内核）
    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: False)

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr("utils.connection_utils.capturing_tun_for", lambda ip: "utun9")
    monkeypatch.setattr("utils.connection_utils.physical_interface", lambda: "en0")
    monkeypatch.setattr(
        "utils.connection_utils.spawn_elevated_async", lambda *a, **k: None
    )
    seen = {}
    real = cu.build_command_args

    def spy(window, command, tun_bind_interface=None):
        seen["bind"] = tun_bind_interface
        return real(window, command, tun_bind_interface)

    monkeypatch.setattr("utils.connection_utils.build_command_args", spy)

    win.connect_button.setChecked(True)

    assert seen["bind"] == "en0"          # 绑定参数已传到参数构建
    assert win.worker is not None          # 未早退
    assert "共存模式" in win.output_text.toPlainText()

    win.connect_button.setChecked(False)   # 收尾，避免残留 worker
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


def test_tun_coexist_bound_flag_true_when_captured(qtbot, monkeypatch):
    """TUN 模式下探测到他方 TUN 并绑物理网卡：记录 _coexist_bound，
    看门狗据此关闭路由告警（捕获已被内核层绕过，不再重连）。"""
    import utils.connection_utils as cu
    from utils import helper_installer

    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: False)

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: "utun9")
    monkeypatch.setattr(cu, "physical_interface", lambda: "en0")
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: None)

    win.connect_button.setChecked(True)
    assert win._coexist_bound is True

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


def test_tun_coexist_bound_flag_false_when_not_captured(qtbot, monkeypatch):
    """无他方 TUN 占用：_coexist_bound 为 False，看门狗路由告警保持开启。"""
    import utils.connection_utils as cu
    from utils import helper_installer

    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: False)

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: None)

    win.connect_button.setChecked(True)
    assert win._coexist_bound is False

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


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


def test_stale_spawn_done_stops_orphan_kernel(qtbot, monkeypatch):
    """快速重连 spawn 竞态：连接1 的授权回调迟到时 window.worker 已换成新 worker，
    内核1 刚被拉起即成孤儿（root + 全局路由）——回调必须重写停止标记让守护循环
    补杀（worker1 收尾已把旧标记清掉）；回调2 正常到达不误写标记"""
    from utils import helper_installer

    # 本用例锁的是 osascript spawn 计数：固定 helper 不可用，避免装了 helper 的机器
    # 走分支①导致 spawn_elevated_async 不再被调用、回调计数断言失败
    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: False)

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr("utils.connection_utils.capturing_tun_for", lambda ip: None)
    callbacks = []
    monkeypatch.setattr(
        "utils.connection_utils.spawn_elevated_async",
        lambda launcher, on_done: callbacks.append(on_done),
    )

    # 连接1：worker1 启动，spawn1 在途
    win.connect_button.setChecked(True)
    assert len(callbacks) == 1
    worker1 = win.worker
    assert worker1 is not None

    # 用户断开1（worker1 收尾、临时文件清掉）→ 立即重连2（worker2 + spawn2）
    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)
    assert not os.path.exists(worker1.stop_path)  # 收尾已清理
    win.connect_button.setChecked(True)
    assert len(callbacks) == 2
    worker2 = win.worker
    assert worker2 is not None and worker2 is not worker1

    # 回调1 迟到到达：worker 已换成 worker2 → 重写停止标记，守护循环收标杀孤儿
    callbacks[0](True)
    assert os.path.exists(worker1.stop_path)
    # 回调2 正常到达：worker 匹配且未 stop → 不误写
    callbacks[1](True)
    assert not os.path.exists(worker2.stop_path)

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


def test_quit_app_waits_for_worker_thread(qtbot, monkeypatch):
    """teardown 前必须等 worker 线程退出——QThread 运行中析构必 qFatal（真实崩溃栈：
    QThreadWrapper::~QThreadWrapper 于解释器收尾期）"""
    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    _StubTimer.calls.clear()
    win = _make_window(qtbot)

    class FakeWorker:
        """stop() 后线程仍需一拍才退出（模拟内核收尾耗时）"""

        def __init__(self):
            self.waits = []
            self._running = True

        def stop(self):
            pass

        def isRunning(self):
            return self._running

        def wait(self, ms):
            self.waits.append(ms)
            self._running = False
            return True

        def terminate(self):
            raise AssertionError("正常退出路径不得强杀线程")

    win.worker = FakeWorker()
    win.quit_app()
    assert win.worker.waits == [3000]  # 等待过一次（3s 上限）


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


def test_tun_uses_helper_when_usable(qtbot, monkeypatch):
    """helper 可用时：走 socket 启动，不调用 osascript 提权。"""
    import utils.connection_utils as cu
    from utils import helper_client, helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: True)
    started = []
    monkeypatch.setattr(
        helper_client, "start",
        lambda args, log, pid, stop, socket_path=None: (
            started.append(args) or {"ok": True, "pid": 123}
        ),
    )
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert started, "helper.start 应被调用"
    assert spawned == [], "不得走 osascript 提权"
    assert win.worker is not None

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


def test_tun_prompts_install_when_installable(qtbot, monkeypatch):
    """可安装但未装：触发安装引导并按早退复位，不建 worker、不提权。"""
    import utils.connection_utils as cu
    from utils import helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    win._helper_install_declined = False

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: True)
    prompted = []
    monkeypatch.setattr(win, "prompt_helper_install", lambda on_done=None: prompted.append(True))
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert prompted == [True]
    assert spawned == []
    assert win.worker is None
    assert win.connect_button.isChecked() is False  # 已复位


def test_tun_falls_back_to_osascript_when_declined(qtbot, monkeypatch):
    """用户已拒绝安装：直接回退 osascript 授权路径。"""
    import utils.connection_utils as cu
    from utils import helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    win._helper_install_declined = True

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: True)
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert spawned == [True]
    assert win.worker is not None

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


def test_tun_already_running_stops_and_retries(qtbot, monkeypatch):
    """helper 报 already_running（真机发现的残留内核对）时先停再起，
    绝不能当成失败回退 osascript——那会弹系统授权框并多起一个内核。"""
    import utils.connection_utils as cu
    from utils import helper_client, helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: True)

    calls = {"start": 0, "stop": 0}

    def fake_start(args, log, pid, stop, socket_path=None):
        calls["start"] += 1
        if calls["start"] == 1:
            return {"ok": False, "error": "already_running"}
        return {"ok": True, "pid": 123}

    monkeypatch.setattr(helper_client, "start", fake_start)
    monkeypatch.setattr(
        helper_client, "stop",
        lambda socket_path=None: calls.update(stop=calls["stop"] + 1),
    )
    monkeypatch.setattr(
        helper_client, "status",
        lambda socket_path=None: {"ok": True, "running": False},
    )
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert calls["start"] == 2   # 第一次 already_running，停掉残留后重试成功
    assert calls["stop"] == 1    # 主动停了残留内核
    assert spawned == []         # 没有回退 osascript
    assert win.worker is not None

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


def test_disconnect_reason_and_interface_logged(qtbot, monkeypatch):
    """内核输出经 classify_disconnect/parse_tun_interface 记录，"连接结束"行带上原因/接口。"""
    import utils.connection_utils as cu
    from utils.connection_utils import handle_output, handle_connection_finished

    win = _make_window(qtbot)
    win._watchdog = None
    win._disconnect_reason = None
    win._tun_interface = None
    logs = []
    monkeypatch.setattr(cu.diagnostics, "append", lambda line: logs.append(line))

    handle_output(win, "2026/09/22 14:32:17 Interface Name: utun11, index 32\n")
    handle_output(win, "2026/09/22 14:34:00 SHUTDOWN (cmd 0x08)\n")
    assert win._tun_interface == "utun11"
    assert win._disconnect_reason == "server_kick"

    win._manual_stop = False
    win._auth_failed = False
    handle_connection_finished(win, -1)
    joined = "\n".join(logs)
    assert "原因=server_kick" in joined
    assert "接口=utun11" in joined
    # handle_connection_finished 以 manual=False 收尾会安排退避重连计时器；
    # 取消之，避免计时器在后续用例的事件循环里到点（同文件既有用例做法）。
    win.reconnect_manager.cancel()


def test_manual_stop_takes_priority_over_network_reason(qtbot, monkeypatch):
    """手动断开优先记为 manual：_disconnect_reason 会被本次连接任一 network
    特征行（i/o timeout 等）命中并粘住，绝不能覆盖用户手动断开这一事实。"""
    import utils.connection_utils as cu
    from utils.connection_utils import handle_output, handle_connection_finished

    win = _make_window(qtbot)
    win._watchdog = None
    win._disconnect_reason = None
    win._tun_interface = None
    logs = []
    monkeypatch.setattr(cu.diagnostics, "append", lambda line: logs.append(line))

    handle_output(win, "2026/09/23 10:00:00 dial tcp: i/o timeout\n")
    assert win._disconnect_reason == "network"  # 诊断原因已被粘住

    win._manual_stop = True
    win._auth_failed = False
    handle_connection_finished(win, -1)
    joined = "\n".join(logs)
    assert "原因=manual" in joined
    assert "原因=network" not in joined
    # manual=True 收尾本不安排退避重连；仍取消一次计时器，
    # 防御性清理残留回调，避免影响后续用例的事件循环。
    win.reconnect_manager.cancel()


def test_keepalive_only_refreshes_watchdog(qtbot):
    """只有 keepalive 行才刷新看门狗活跃度（普通输出不算心跳）。"""
    from utils.connection_utils import handle_output

    win = _make_window(qtbot)
    noted = []
    win._watchdog = type(
        "W", (), {
            "note_activity": lambda self: noted.append(1),
            "start": lambda self: None,
            "stop": lambda self: None,
        },
    )()

    handle_output(win, "2026/09/22 14:32:18 an ordinary output line\n")
    assert noted == []
    handle_output(win, "2026/09/22 14:33:17 KeepAlive using UDP: OK\n")
    assert noted == [1]
