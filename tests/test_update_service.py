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


def test_worker_released_on_up_to_date(qtbot, monkeypatch):
    """已是最新版（up_to_date）也是终态，worker 须被清理，否则每次检查都泄漏。"""
    from services.update_service import UpdateService

    monkeypatch.setattr(
        "services.update_service.UpdateChecker.get_latest_version",
        lambda self: "1.0.0",
    )
    service = UpdateService()
    signals = service.check_for_updates("1.0.0")

    done = []
    signals.up_to_date.connect(lambda: done.append(True))
    qtbot.waitUntil(lambda: done == [True], timeout=5000)
    qtbot.waitUntil(lambda: service._workers == [], timeout=1000)


def test_worker_released_on_error(qtbot, monkeypatch):
    """检查失败（error）也是终态，worker 须被清理，否则每次检查都泄漏。"""
    from services.update_service import UpdateService

    monkeypatch.setattr(
        "services.update_service.UpdateChecker.get_latest_version",
        lambda self: None,
    )
    service = UpdateService()
    signals = service.check_for_updates("1.0.0")

    errors = []
    signals.error.connect(lambda msg: errors.append(msg))
    qtbot.waitUntil(lambda: errors != [], timeout=5000)
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


def test_mirror_urls_auto_and_custom():
    from services.update_service import api_urls, apply_mirror, download_urls

    assert apply_mirror(
        "https://github.com/x/y.zip", "auto"
    ) == "https://gh-proxy.com/https://github.com/x/y.zip"
    assert apply_mirror(
        "https://github.com/x/y.zip", "https://m.example/{url}"
    ) == "https://m.example/https://github.com/x/y.zip"
    assert api_urls("github") == ["https://api.github.com/repos/GtJerry111/bitzh-connect/releases"]
    assert len(api_urls("auto")) == 2
    assert download_urls("https://github.com/a.zip", "auto") == [
        "https://github.com/a.zip",
        "https://gh-proxy.com/https://github.com/a.zip",
    ]


def test_release_info_from_api():
    from services.update_service import ReleaseInfo

    info = ReleaseInfo.from_api(
        {
            "tag_name": "v1.5.0",
            "body": "notes",
            "html_url": "https://example/rel",
            "assets": [{"name": "a.zip"}],
        }
    )
    assert info.version == "1.5.0"
    assert info.tag == "v1.5.0"
    assert info.assets == ({"name": "a.zip"},)


def test_checker_falls_back_to_mirror(monkeypatch):
    import services.update_service as us

    calls = []

    class FakeResp:
        status_code = 200

        def json(self):
            return [{"tag_name": "v1.5.0", "draft": False}]

    def fake_get(url, **kwargs):
        calls.append(url)
        if url == us.RELEASES_API_URL:
            raise us.RequestException("blocked")
        return FakeResp()

    monkeypatch.setattr(us.requests, "get", fake_get)
    checker = us.UpdateChecker("1.4.0", "auto")
    assert checker.get_latest_version() == "1.5.0"
    assert len(calls) == 2
    assert checker.last_release is not None


def test_downloader_writes_and_verifies(tmp_path, monkeypatch):
    import hashlib
    import services.update_service as us

    payload = b"hello-update"

    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": str(len(payload))}

        def iter_content(self, chunk_size):
            yield payload

    monkeypatch.setattr(us.requests, "get", lambda *a, **k: FakeResponse())
    signals = us.DownloadSignals()
    progress = []
    finished = []
    signals.progress.connect(lambda done, total: progress.append((done, total)))
    signals.finished.connect(lambda path: finished.append(path))
    asset = {
        "name": "update.zip",
        "browser_download_url": "https://example/update.zip",
    }
    checksum = hashlib.sha256(payload).hexdigest()
    worker = us.UpdateDownloader(asset, checksum, "auto", str(tmp_path))
    worker.signals = signals
    worker.run()
    assert finished and finished[0].endswith("update.zip")
    assert (tmp_path / "update.zip").read_bytes() == payload
    assert progress[-1] == (len(payload), len(payload))


def test_downloader_retries_mirror_on_bad_checksum(tmp_path, monkeypatch):
    import hashlib
    import services.update_service as us

    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def __init__(self, payload):
            self.payload = payload

        def iter_content(self, chunk_size):
            yield self.payload

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.startswith("https://example/"):
            return FakeResponse(b"bad")
        return FakeResponse(b"good")

    monkeypatch.setattr(us.requests, "get", fake_get)
    signals = us.DownloadSignals()
    finished, errors = [], []
    signals.finished.connect(finished.append)
    signals.error.connect(errors.append)
    asset = {
        "name": "update.zip",
        "browser_download_url": "https://example/update.zip",
    }
    worker = us.UpdateDownloader(
        asset, hashlib.sha256(b"good").hexdigest(), "auto", str(tmp_path)
    )
    worker.signals = signals
    worker.run()
    assert len(calls) == 2
    assert finished and not errors
    assert (tmp_path / "update.zip").read_bytes() == b"good"
