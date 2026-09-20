"""退出信号处理：SIGINT/SIGTERM/SIGHUP → 置标志，QTimer 轮询触发优雅退出。"""
import signal

import pytest

_PLATFORM_SIGNALS = [
    s for s in (
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGHUP", None),
    ) if s is not None
]


def test_signals_constant_has_no_missing():
    """SIGHUP 等 Unix-only 常量在缺失平台不得让模块 import 崩（Windows）。"""
    import utils.shutdown as sd

    assert sd._SIGNALS  # 至少有 SIGINT/SIGTERM
    assert all(s is not None for s in sd._SIGNALS)


@pytest.mark.parametrize("sig", _PLATFORM_SIGNALS)
def test_install_exit_signal_handlers_triggers_on_signal(qtbot, sig):
    from utils.shutdown import install_exit_signal_handlers

    fired = []
    saved = {s: signal.getsignal(s) for s in _PLATFORM_SIGNALS}
    timer = install_exit_signal_handlers(lambda: fired.append(True))
    try:
        signal.raise_signal(sig)
        qtbot.waitUntil(lambda: fired == [True], timeout=2000)
        assert timer.isActive() is False  # 触发后停表
    finally:
        timer.stop()
        for s, handler in saved.items():
            signal.signal(s, handler)


def test_install_exit_signal_handlers_survives_unsupported_signal(monkeypatch, qtbot):
    import utils.shutdown as sd

    def boom(sig, handler):
        raise ValueError("not main thread")

    monkeypatch.setattr(sd.signal, "signal", boom)
    timer = sd.install_exit_signal_handlers(lambda: None)
    timer.stop()  # 安装全失败也不崩、仍返回可用 timer


def test_install_exit_signal_handlers_survives_oserror(monkeypatch, qtbot):
    import utils.shutdown as sd

    def boom(sig, handler):
        raise OSError("unsupported")

    monkeypatch.setattr(sd.signal, "signal", boom)
    timer = sd.install_exit_signal_handlers(lambda: None)
    timer.stop()
