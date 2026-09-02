import os
import stat

from utils.tun_utils import read_pid, write_launcher, _pid_alive


def test_write_launcher_quotes_args(tmp_path):
    """包装脚本必须经真实 shell 执行，参数用 shlex.quote（含特殊字符的密码安全）"""
    launcher = write_launcher(
        "/path with space/zju-connect",
        ["-password", "p@ss!word with space", "-tun-mode"],
        str(tmp_path / "t.log"),
        str(tmp_path / "t.pid"),
    )
    content = open(launcher).read()
    assert "'p@ss!word with space'" in content
    assert "nohup" in content and "echo $!" in content
    assert os.stat(launcher).st_mode & stat.S_IXUSR


def test_read_pid(tmp_path):
    p = tmp_path / "x.pid"
    assert read_pid(str(p)) is None
    p.write_text("12345\n")
    assert read_pid(str(p)) == 12345
    p.write_text("garbage")
    assert read_pid(str(p)) is None


def test_pid_alive():
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(99999999) is False


def test_spawn_elevated_async_reports_result(qtbot, monkeypatch):
    """异步提权：同步版放到线程池执行，结果经信号回传（不触碰真实授权命令）"""
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "spawn_elevated", lambda path: True)
    results = []
    task = tu.spawn_elevated_async("/tmp/fake-launcher.sh", lambda ok: results.append(ok))
    qtbot.waitUntil(lambda: results == [True], timeout=3000)
    assert task is not None
