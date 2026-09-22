"""连接诊断日志持久化：连接起止、断开原因、路由快照、内核输出（带轮转）。

日志文件不落任意敏感数据之外的额外内容；内核原始输出本身不含密码
（zju-connect 不打印密码）。目标：断线后可事后定位原因。
"""
import os
import time
from platform import system

_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3


def _log_base_dir() -> str:
    if system() == "Darwin":
        base = os.path.expanduser("~/Library/Logs")
    elif system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.local/state")
    return os.path.join(base, "BITZH Connect")


def log_dir() -> str:
    return _log_base_dir()


def log_path() -> str:
    return os.path.join(_log_base_dir(), "bitzh-connect.log")


def _rotate(path: str):
    try:
        if not os.path.exists(path) or os.path.getsize(path) < _MAX_BYTES:
            return
    except OSError:
        return
    for index in range(_BACKUPS - 1, 0, -1):
        src = f"{path}.{index}"
        if os.path.exists(src):
            try:
                os.replace(src, f"{path}.{index + 1}")
            except OSError:
                pass
    try:
        os.replace(path, path + ".1")
    except OSError:
        pass


def append(line: str):
    """追加一行（自动加时间戳并轮转）；任何失败都静默忽略，不影响主流程。"""
    try:
        os.makedirs(_log_base_dir(), exist_ok=True)
        path = log_path()
        _rotate(path)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {str(line).rstrip()}\n")
    except Exception:
        # 包括 UnicodeEncodeError（内核输出以 surrogateescape 解码后含孤立代理
        # 字符）：日志失败绝不冒泡进连接主流程。
        pass
