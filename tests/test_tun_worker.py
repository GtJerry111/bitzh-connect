import subprocess
import sys
import time


def test_tun_worker_tails_log_and_detects_exit(qtbot, tmp_path):
    """TunWorker 尾随日志文件、按 pidfile 监控进程存活（用真实子进程验证）"""
    from utils.tun_worker import TunWorker

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    stop = tmp_path / "t.stop"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time; print('line1', flush=True); time.sleep(0.3); print('Client IP: 10.0.43.17', flush=True)"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    pidf.write_text(str(proc.pid))

    worker = TunWorker(str(log), str(pidf), str(stop))
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
    stop = tmp_path / "t.stop"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "print('head-line', flush=True); print('tail-line', flush=True)"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    pidf.write_text(str(proc.pid))

    worker = TunWorker(str(log), str(pidf), str(stop))
    lines, done = [], []
    worker.output.connect(lambda t: lines.append(t))
    worker.finished.connect(lambda c: done.append(c))
    worker.start()
    qtbot.waitUntil(lambda: len(done) == 1, timeout=5000)
    text = "".join(lines)
    assert "head-line" in text and "tail-line" in text


def test_tun_worker_stop_writes_stop_flag(qtbot, tmp_path):
    """断开不再提权 kill（不弹授权框）：stop() 只写停止标记，由 root 守护循环杀内核"""
    import utils.tun_worker as tw

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    stop = tmp_path / "t.stop"
    log.write_text("")
    pidf.write_text("424242")
    worker = tw.TunWorker(str(log), str(pidf), str(stop))
    worker.stop()
    assert stop.exists()


def test_tun_worker_warns_if_kernel_survives_grace(qtbot, tmp_path, monkeypatch):
    """宽限期后内核仍存活（守护循环没杀掉）→ window 级 sink 留痕，不静默吞掉"""
    import utils.tun_worker as tw

    monkeypatch.setattr(tw.TunWorker, "KILL_GRACE_MS", 50)
    monkeypatch.setattr(tw, "_pid_alive", lambda pid: True)  # 假装内核顽固存活

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    stop = tmp_path / "t.stop"
    log.write_text("")
    pidf.write_text("424242")
    warnings = []
    worker = tw.TunWorker(
        str(log), str(pidf), str(stop), on_kill_failed=lambda: warnings.append(True)
    )
    worker.stop()
    qtbot.waitUntil(lambda: warnings == [True], timeout=2000)
