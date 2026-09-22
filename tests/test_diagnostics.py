import os

from utils import diagnostics


def test_log_path_under_app_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: str(tmp_path))
    assert diagnostics.log_path().endswith("bitzh-connect.log")
    assert str(tmp_path) in diagnostics.log_path()


def test_append_creates_file_and_timestamps(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: str(tmp_path))
    diagnostics.append("hello world")
    content = open(diagnostics.log_path(), encoding="utf-8").read()
    assert "hello world" in content
    # 行首应是时间戳
    assert content.split(" ", 1)[0].count("-") == 2


def test_append_rotates_when_too_large(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(diagnostics, "_MAX_BYTES", 50)
    diagnostics.append("x" * 100)
    diagnostics.append("second")
    assert os.path.exists(diagnostics.log_path() + ".1")
    # 新文件里只有第二行
    current = open(diagnostics.log_path(), encoding="utf-8").read()
    assert "second" in current and "x" * 100 not in current


def test_append_never_raises_on_bad_dir(monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: "/proc/definitely/not/writable")
    diagnostics.append("boom")  # 不抛异常
