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


def test_signals_constant_has_core_signals():
    """SIGHUP 等 Unix-only 常量在缺失平台不得让模块 import 崩（Windows）。"""
    import signal as _signal

    import utils.shutdown as sd

    assert _signal.SIGINT in sd._SIGNALS
    assert _signal.SIGTERM in sd._SIGNALS
    assert all(s is not None for s in sd._SIGNALS)


@pytest.mark.parametrize("sig", _PLATFORM_SIGNALS)
def test_install_exit_signal_handlers_triggers_on_signal(qtbot, sig):
    from utils.shutdown import install_exit_signal_handlers

    fired = []
    saved = {s: signal.getsignal(s) for s in _PLATFORM_SIGNALS}
    timer = install_exit_signal_handlers(lambda: fired.append(True))
    try:
        assert signal.getsignal(sig) is not signal.SIG_DFL  # 确认 handler 已装上，避免误杀 pytest
        signal.raise_signal(sig)
        qtbot.waitUntil(lambda: fired == [True], timeout=2000)
        assert timer.isActive() is False  # 触发后停表
    finally:
        timer.stop()
        for s, handler in saved.items():
            signal.signal(s, handler)


def test_on_signal_exception_keeps_handler_alive(qtbot):
    """on_signal 抛异常不得让信号处理永久失效：后续信号仍可再触发。"""
    from utils.shutdown import install_exit_signal_handlers

    sig = signal.SIGTERM
    calls = []
    saved = {s: signal.getsignal(s) for s in _PLATFORM_SIGNALS}

    def on_signal():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("boom")

    timer = install_exit_signal_handlers(on_signal)
    try:
        signal.raise_signal(sig)
        qtbot.waitUntil(lambda: len(calls) >= 1, timeout=2000)
        assert timer.isActive() is True  # 异常后轮询不得停表
        signal.raise_signal(sig)
        qtbot.waitUntil(lambda: len(calls) >= 2, timeout=2000)
        qtbot.waitUntil(lambda: timer.isActive() is False, timeout=2000)  # 成功后停表
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
