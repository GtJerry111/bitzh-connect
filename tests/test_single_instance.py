"""单实例锁（QLockFile）：同进程二次获取失败、释放后可再获取。"""


def test_single_instance_lock_second_acquire_fails(tmp_path, monkeypatch):
    import utils.single_instance as si

    monkeypatch.setattr(si.tempfile, "gettempdir", lambda: str(tmp_path))
    first = si.acquire_single_instance_lock()
    assert first is not None
    try:
        assert si.acquire_single_instance_lock() is None
    finally:
        first.unlock()
    third = si.acquire_single_instance_lock()
    assert third is not None
    third.unlock()
