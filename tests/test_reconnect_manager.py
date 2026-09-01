import pytest
from pytestqt.qtbot import QtBot  # noqa: F401  (确保 pytest-qt 可用)

from services.reconnect_manager import ReconnectManager


@pytest.fixture
def manager(qapp):
    calls = []
    m = ReconnectManager(
        reconnect_action=lambda: calls.append("reconnect"),
        max_retries=3,
        backoff=[0.05, 0.1, 0.15],  # 测试用短退避（秒）
        stability_window=0.2,
    )
    yield m, calls
    m.cancel()


def test_manual_stop_does_not_reconnect(manager, qtbot):
    m, calls = manager
    m.on_process_exited(manual=True, auth_failed=False)
    qtbot.wait(300)
    assert calls == []
    assert m.retry_count == 0


def test_auth_failure_does_not_reconnect(manager, qtbot):
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=True)
    qtbot.wait(300)
    assert calls == []


def test_crash_triggers_reconnect_after_backoff(manager, qtbot):
    m, calls = manager
    scheduled = []
    m.retry_scheduled.connect(lambda attempt, delay: scheduled.append((attempt, delay)))
    m.on_process_exited(manual=False, auth_failed=False)
    assert scheduled == [(1, 0.05)]
    qtbot.waitUntil(lambda: calls == ["reconnect"], timeout=2000)


def test_exhaustion_after_max_retries(manager, qtbot):
    m, calls = manager
    exhausted = []
    m.retries_exhausted.connect(lambda: exhausted.append(True))
    for _ in range(3):
        m.on_process_exited(manual=False, auth_failed=False)
        qtbot.waitUntil(lambda: len(calls) > len(exhausted) or True, timeout=10)  # 让事件循环转一下
        qtbot.wait(250)  # 等退避计时器触发
    # 已触发 3 次重连，第 4 次掉线应暂停
    assert calls == ["reconnect"] * 3
    m.on_process_exited(manual=False, auth_failed=False)
    qtbot.wait(300)
    assert exhausted == [True]
    assert calls == ["reconnect"] * 3


def test_stable_connection_resets_counter(manager, qtbot):
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=False)
    qtbot.waitUntil(lambda: calls == ["reconnect"], timeout=2000)
    assert m.retry_count == 1
    # 连接建立并稳定存活超过 stability_window → 计数重置
    m.on_connection_established()
    qtbot.wait(400)
    assert m.retry_count == 0


def test_unstable_connection_keeps_counter(manager, qtbot):
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=False)
    qtbot.waitUntil(lambda: calls == ["reconnect"], timeout=2000)
    m.on_connection_established()
    m.on_process_exited(manual=False, auth_failed=False)  # 60s(测试为0.2s)内又掉 → 不重置
    assert m.retry_count == 2


def test_on_connect_attempt_cancels_pending_retry(manager, qtbot):
    """手动发起连接必须取消在途的退避重连计时器（stray timer）。

    只停计时器：retry_count 保留（不清计数），防止旧退避计时器在手动连接
    期间到点、用旧凭据再连一次把 UI 从"认证失败"翻回"连接中"。
    """
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=False)
    assert m.retry_count == 1
    m.on_connect_attempt()
    qtbot.wait(300)  # 越过第一档退避（0.05s）
    assert calls == []
    assert m.retry_count == 1
