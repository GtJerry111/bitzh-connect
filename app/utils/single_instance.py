# app/utils/single_instance.py
"""单实例锁：避免同时运行两个 app 实例。

启动自愈清扫会扫 TMPDIR 下的 TUN 残留；若两个实例并存，后启动者会误杀前一实例
正在用的内核。QLockFile 自带陈旧锁检测（持有进程已死则自动接管），崩溃后可重启。
"""
import os
import tempfile

from PySide6.QtCore import QLockFile

# 锁文件名带 uid：Linux 的 /tmp 是全用户共享，不带 uid 会让用户 B 被用户 A 残留的锁
# 挡在门外（且 sticky /tmp 下 B 删不掉 A 的文件）。Windows 无 os.getuid，用 'win' 占位。
_LOCK_NAME = f"bitzh-connect-{getattr(os, 'getuid', lambda: 'win')()}.lock"


def acquire_single_instance_lock():
    """尝试获取单实例锁；成功返回 QLockFile（调用方须保活），已被占用返回 None。"""
    path = os.path.join(tempfile.gettempdir(), _LOCK_NAME)
    lock = QLockFile(path)
    if lock.tryLock(100):
        return lock
    # Qt 只暴露 error()（QLockFile.LockError），无 errorString()；用枚举名作原因描述
    print(f"[BITZH Connect] 已有实例在运行（{lock.error().name}），退出", flush=True)
    return None
