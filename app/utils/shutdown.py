# app/utils/shutdown.py
"""退出信号处理：把 SIGINT/SIGTERM/SIGHUP 转成一次优雅退出（走 window.quit_app）。

Qt 的 C++ 事件循环不会即时执行 Python 信号处理器——处理器只置标志，由 QTimer
轮询在事件循环里触发回调（200ms 延迟换实现简单，退出路径不敏感）。

SIGHUP 为 Unix-only，故信号常量统一用 getattr 取，缺失平台（Windows）安静跳过，
避免模块 import 期即 AttributeError。
"""
import signal

from PySide6.QtCore import QTimer

_SIGNALS = tuple(
    s for s in (
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGHUP", None),
    ) if s is not None
)


def install_exit_signal_handlers(on_signal, parent=None) -> QTimer:
    """安装退出信号处理器，返回需保活的 QTimer（挂 parent 上随其生命周期）。

    on_signal 在事件循环里触发（可重入性由调用方 quit_app 自身保证）。
    非主线程/平台不支持的信号安装失败时安静跳过。
    """
    state = {"fired": False}

    def _handler(_signum, _frame):
        state["fired"] = True

    for sig in _SIGNALS:
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass

    timer = QTimer(parent)
    timer.setInterval(200)

    def _poll():
        if state["fired"]:
            timer.stop()
            on_signal()

    timer.timeout.connect(_poll)
    timer.start()
    return timer
