# app/utils/single_instance.py
"""单实例锁：避免同时运行两个 app 实例。

启动自愈清扫会扫 TMPDIR 下的 TUN 残留；若两个实例并存，后启动者会误杀前一实例
正在用的内核。QLockFile 自带陈旧锁检测（持有进程已死则自动接管），崩溃后可重启。
"""
import os
import tempfile

from PySide6.QtCore import QLockFile

_LOCK_NAME = "bitzh-connect.lock"


def acquire_single_instance_lock():
    """尝试获取单实例锁；成功返回 QLockFile（调用方须保活），已被占用返回 None。"""
    path = os.path.join(tempfile.gettempdir(), _LOCK_NAME)
    lock = QLockFile(path)
    if lock.tryLock(100):
        return lock
    return None
