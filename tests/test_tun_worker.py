import subprocess
import sys
import time


def test_tun_worker_tails_log_and_detects_exit(qtbot, tmp_path):
    """TunWorker 尾随日志文件、按 pidfile 监控进程存活（用真实子进程验证）"""
    from utils.tun_worker import TunWorker

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time; print('line1', flush=True); time.sleep(0.3); print('Client IP: 10.0.43.17', flush=True)"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    pidf.write_text(str(proc.pid))

    worker = TunWorker(str(log), str(pidf))
    lines, done = [], []
    worker.output.connect(lambda t: lines.append(t))
    worker.finished.connect(lambda c: done.append(c))
    worker.start()
    qtbot.waitUntil(lambda: len(done) == 1, timeout=5000)
    text = "".join(lines)
    assert "line1" in text and "Client IP: 10.0.43.17" in text


def test_tun_worker_drains_tail_after_process_exit(qtbot, tmp_path):
    """进程快速退出：死亡瞬间写入的尾部日志也必须完整上屏（drain 兜底）"""
    from utils.tun_worker import TunWorker

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "print('head-line', flush=True); print('tail-line', flush=True)"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    pidf.write_text(str(proc.pid))

    worker = TunWorker(str(log), str(pidf))
    lines, done = [], []
    worker.output.connect(lambda t: lines.append(t))
    worker.finished.connect(lambda c: done.append(c))
    worker.start()
    qtbot.waitUntil(lambda: len(done) == 1, timeout=5000)
    text = "".join(lines)
    assert "head-line" in text and "tail-line" in text


def test_tun_worker_stop_kills_process(qtbot, tmp_path, monkeypatch):
    import utils.tun_worker as tw

    killed = []
    monkeypatch.setattr(
        tw, "kill_elevated_async", lambda pid, on_done=None: killed.append(pid)
    )

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    log.write_text("")
    pidf.write_text("424242")
    worker = tw.TunWorker(str(log), str(pidf))
    worker.stop()
    assert killed == [424242]


def test_tun_worker_kill_failure_emits_warning(qtbot, tmp_path, monkeypatch):
    """kill 失败（如用户取消二次授权）必须经 output 留痕，不能静默吞掉"""
    import utils.tun_worker as tw

    monkeypatch.setattr(
        tw, "kill_elevated_async", lambda pid, on_done=None: on_done(False)
    )

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    log.write_text("")
    pidf.write_text("424242")
    worker = tw.TunWorker(str(log), str(pidf))
    lines = []
    worker.output.connect(lambda t: lines.append(t))
    worker.stop()
    assert any("未能停止 TUN 内核进程" in t for t in lines)
