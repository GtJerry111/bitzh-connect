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


def test_get_latest_version_skips_drafts_and_handles_prerelease(monkeypatch):
    """releases 列表取第一条非草稿（预发布也要命中——流水线默认 prerelease:true，
    /latest 接口查不到预发布是本修复的初衷）"""
    import services.update_service as us

    class FakeResp:
        def json(self):
            return [
                {"tag_name": "v9.9.9", "draft": True},       # 草稿跳过
                {"tag_name": "v1.3.0", "prerelease": True},  # 预发布要命中
                {"tag_name": "v1.2.0"},
            ]

    monkeypatch.setattr(us.requests, "get", lambda *a, **k: FakeResp())
    assert us.UpdateChecker("1.0.0").get_latest_version() == "1.3.0"


def test_get_latest_version_empty_releases(monkeypatch):
    """还没发过版（空列表）→ None，不抛异常"""
    import services.update_service as us

    class FakeResp:
        def json(self):
            return []

    monkeypatch.setattr(us.requests, "get", lambda *a, **k: FakeResp())
    assert us.UpdateChecker("1.0.0").get_latest_version() is None
