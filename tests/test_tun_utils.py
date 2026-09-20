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


def test_parse_route_get_interface():
    import utils.tun_utils as tu

    text = (
        "   route to: 112.91.150.228\n"
        "destination: 112.91.150.228\n"
        "       mask: 255.255.255.255\n"
        "  interface: utun5\n"
    )
    assert tu._parse_route_get_interface(text) == "utun5"
    assert tu._parse_route_get_interface("no interface line") is None


def test_parse_scutil_nwi():
    import utils.tun_utils as tu

    text = (
        "Network information\n\n"
        "IPv4 network interface information\n"
        "     en0 : flags      : 0x7 (IPv4,IPv6,DNS)\n"
        "Network interfaces: en0\n"
    )
    assert tu._parse_scutil_nwi(text) == "en0"
    assert tu._parse_scutil_nwi("nothing here") is None


def test_parse_ip_route_dev():
    import utils.tun_utils as tu

    assert (
        tu._parse_ip_route_dev("1.1.1.1 via 10.0.0.1 dev en0 src 10.0.0.2")
        == "en0"
    )
    assert tu._parse_ip_route_dev("no dev token") is None


def test_capturing_tun_for_darwin_hits_tun(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "   route to: 112.91.150.228\n  interface: utun5\n",
    )
    assert tu.capturing_tun_for("112.91.150.228") == "utun5"


def test_capturing_tun_for_physical_is_none(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "   route to: 1.1.1.1\n  interface: en0\n",
    )
    assert tu.capturing_tun_for("1.1.1.1") is None


def test_capturing_tun_for_linux(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Linux")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "112.91.150.228 via 10.0.0.1 dev tun0 src 10.0.0.2\n",
    )
    assert tu.capturing_tun_for("112.91.150.228") == "tun0"


def test_capturing_tun_for_error_is_none(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")

    def boom(*a, **k):
        raise FileNotFoundError("route")

    monkeypatch.setattr(tu.subprocess, "check_output", boom)
    assert tu.capturing_tun_for("112.91.150.228") is None


def test_physical_interface_darwin(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "IPv4 network interface information\nNetwork interfaces: en0\n",
    )
    assert tu.physical_interface() == "en0"


def test_physical_interface_excludes_tun_and_falls_back(monkeypatch):
    """nwi 只报 tun（异常）→ 回退默认路由出口；且 utun 出口不被采纳"""
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")

    def fake(cmd, *a, **k):
        if cmd[0] == "scutil":
            return "Network interfaces: utun5\n"
        return "   route to: default\n  interface: en0\n"

    monkeypatch.setattr(tu.subprocess, "check_output", fake)
    assert tu.physical_interface() == "en0"


def test_sweep_orphan_tun_stops_live_kernel(monkeypatch, tmp_path):
    import os

    import utils.tun_utils as tu

    monkeypatch.setattr(tu.tempfile, "gettempdir", lambda: str(tmp_path))
    pid_file = tmp_path / "bitzh-tun-abcd1234.pid"
    pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(tu, "_pid_alive", lambda pid: True)

    stopped = tu.sweep_orphan_tun()

    assert stopped == 1
    assert (tmp_path / "bitzh-tun-abcd1234.pid.stop").exists()


def test_sweep_orphan_tun_removes_dead(monkeypatch, tmp_path):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu.tempfile, "gettempdir", lambda: str(tmp_path))
    pid_file = tmp_path / "bitzh-tun-deadbeef.pid"
    pid_file.write_text("99999999")
    stop_file = tmp_path / "bitzh-tun-deadbeef.pid.stop"
    stop_file.write_text("")
    monkeypatch.setattr(tu, "_pid_alive", lambda pid: False)

    stopped = tu.sweep_orphan_tun()

    assert stopped == 0
    assert not pid_file.exists()
    assert not stop_file.exists()


def test_sweep_orphan_tun_removes_launcher_and_log(monkeypatch, tmp_path):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu.tempfile, "gettempdir", lambda: str(tmp_path))
    sh = tmp_path / "bitzh-tun-launcher.sh"
    log = tmp_path / "bitzh-tun-session.log"
    sh.write_text("#!/bin/sh\n")
    log.write_text("log\n")
    monkeypatch.setattr(tu, "_pid_alive", lambda pid: False)

    tu.sweep_orphan_tun()

    assert not sh.exists()
    assert not log.exists()
