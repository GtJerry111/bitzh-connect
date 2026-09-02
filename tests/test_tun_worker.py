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


def test_tun_worker_stop_kills_process(qtbot, tmp_path, monkeypatch):
    from utils import tun_utils
    from utils.tun_worker import TunWorker

    killed = []
    monkeypatch.setattr(tun_utils, "kill_elevated", lambda pid: killed.append(pid) or True)
    # TunWorker 内部 from 引用 tun_utils 的函数——若直接 import 了 kill_elevated，
    # 需 patch tun_worker 命名空间；以 TunWorker 实现中的引用方式为准
    import utils.tun_worker as tw
    monkeypatch.setattr(tw, "kill_elevated", lambda pid: killed.append(pid) or True)

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    log.write_text("")
    pidf.write_text("424242")
    worker = TunWorker(str(log), str(pidf))
    worker.stop()
    assert killed == [424242]
