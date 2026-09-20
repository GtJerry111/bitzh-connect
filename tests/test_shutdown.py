"""退出信号处理：SIGINT/SIGTERM/SIGHUP → 置标志，QTimer 轮询触发优雅退出。"""
import signal


def test_install_exit_signal_handlers_triggers_on_signal(qtbot):
    from utils.shutdown import install_exit_signal_handlers

    fired = []
    saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    timer = install_exit_signal_handlers(lambda: fired.append(True))
    try:
        signal.raise_signal(signal.SIGINT)
        qtbot.waitUntil(lambda: fired == [True], timeout=2000)
    finally:
        timer.stop()
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def test_install_exit_signal_handlers_survives_unsupported_signal(monkeypatch, qtbot):
    import utils.shutdown as sd

    def boom(sig, handler):
        raise ValueError("not main thread")

    monkeypatch.setattr(sd.signal, "signal", boom)
    timer = sd.install_exit_signal_handlers(lambda: None)
    timer.stop()  # 安装全失败也不崩、仍返回可用 timer
