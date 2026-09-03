import os
import stat
import subprocess
import time

from utils.tun_utils import read_pid, request_stop, write_launcher, _pid_alive


def test_write_launcher_quotes_args(tmp_path):
    """包装脚本必须经真实 shell 执行，参数用 shlex.quote（含特殊字符的密码安全）"""
    launcher = write_launcher(
        "/path with space/zju-connect",
        ["-password", "p@ss!word with space", "-tun-mode"],
        str(tmp_path / "t.log"),
        str(tmp_path / "t.pid"),
        str(tmp_path / "t.stop"),
    )
    content = open(launcher).read()
    assert "'p@ss!word with space'" in content
    assert "nohup" not in content  # nohup 在无控制终端环境（osascript 提权）下必败
    assert "> " in content and "&" in content and "echo $kpid" in content
    # 守护循环：停止标记出现即杀内核；stdio 全重定向以脱离 osascript 独立存活
    assert "kill -0 $kpid" in content and "t.stop" in content
    assert os.stat(launcher).st_mode & stat.S_IXUSR


def test_launcher_watcher_kills_kernel_on_stop_flag(tmp_path):
    """端到端：守护循环收到停止标记即杀内核（用普通 sleep 模拟内核，无需提权）"""
    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    stop = tmp_path / "t.stop"
    launcher = write_launcher("/bin/sleep", ["30"], str(log), str(pidf), str(stop))
    subprocess.run(["/bin/sh", launcher], check=True, timeout=5)

    pid = None
    for _ in range(50):
        pid = read_pid(str(pidf))
        if pid is not None:
            break
        time.sleep(0.1)
    assert pid is not None and _pid_alive(pid)

    try:
        request_stop(str(stop))
        # 守护循环 0.3s 轮询，2s 内必须杀掉"内核"
        deadline = time.time() + 2
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.1)
        assert not _pid_alive(pid)
    finally:
        subprocess.run(["kill", str(pid)], capture_output=True)


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


def test_spawn_elevated_async_exception_reports_false(qtbot, monkeypatch):
    """提权命令二进制缺失等异常 → done(False)，不能静默卡住 UI + 泄漏任务"""
    import utils.tun_utils as tu

    def _boom(path):
        raise FileNotFoundError("osascript missing")

    monkeypatch.setattr(tu, "spawn_elevated", _boom)
    results = []
    tu.spawn_elevated_async("/tmp/fake-launcher.sh", lambda ok: results.append(ok))
    qtbot.waitUntil(lambda: results == [False], timeout=3000)


def test_linux_tun_conflict_detects_tun_default_route(monkeypatch):
    """Linux：默认路由 dev 为 tun*/utun*（Clash/OpenVPN）→ 冲突；物理网卡不误伤"""
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Linux")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "default via 192.168.1.1 dev tun0 proto static\n",
    )
    assert tu.check_tun_conflict() == "tun0"

    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "default via 192.168.1.1 dev eth0 proto dhcp metric 100\n",
    )
    assert tu.check_tun_conflict() is None

    # WireGuard 的 wg0 不误伤（不抢全局路由语义）
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "default via 10.0.0.1 dev wg0\n",
    )
    assert tu.check_tun_conflict() is None
