"""B7：更新检查竞态——worker 须延迟到事件循环下一轮 start，且服务持有引用防 GC。"""


def test_check_for_updates_defers_start(qtbot):
    """调用方在 check_for_updates 返回后才连信号；同步 start 会丢信号。"""
    from services.update_service import UpdateService

    service = UpdateService()
    started = []
    service.thread_pool.start = lambda worker: started.append(worker)

    service.check_for_updates("1.0.0")
    assert started == []  # 同步阶段不得 start
    qtbot.waitUntil(lambda: started != [], timeout=1000)


def test_worker_held_until_update_available(qtbot, monkeypatch):
    """worker 须被服务持有，信号发出后清理引用（防 QRunnable 自动删除后信号丢失）。"""
    from services.update_service import UpdateService

    monkeypatch.setattr(
        "services.update_service.UpdateChecker.get_latest_version",
        lambda self: "99.0.0",
    )
    service = UpdateService()
    signals = service.check_for_updates("1.0.0")

    got = []
    signals.update_available.connect(lambda v: got.append(v))
    qtbot.waitUntil(lambda: got == ["99.0.0"], timeout=5000)
    qtbot.waitUntil(lambda: service._workers == [], timeout=1000)
