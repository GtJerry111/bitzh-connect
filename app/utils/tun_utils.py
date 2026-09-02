# app/utils/tun_utils.py
"""TUN 模式支持：提权启动/停止内核、pid 管理、冲突检测。

提权方案（本期最简，后续可换 SMAppServices 特权助手）：
- macOS：osascript do shell script ... with administrator privileges（每次弹系统授权框）
- Linux：pkexec
- Windows：ShellExecute runas（UAC）+ .bat 包装（本期 best-effort，Windows 平台验证后置）

内核以 root 后台运行，输出重定向到日志文件；GUI 用 TunWorker 尾随解析。
注意：包装脚本经真实 shell 执行，参数必须 shlex.quote（这里 quoting 是对的——
与 B1 修复不矛盾：B1 是 subprocess list 不过 shell，这里过 shell）。
"""
import os
import shlex
import stat
import subprocess
import tempfile
from platform import system


def check_tun_conflict() -> str | None:
    """默认路由已在虚拟网卡上（如 Clash TUN）→ 返回该网卡名；否则 None。"""
    if system() == "Darwin":
        try:
            out = subprocess.check_output(["netstat", "-rn", "-f", "inet"], text=True)
            for line in out.splitlines():
                parts = line.split()
                if parts and parts[0] == "default" and parts[-1].startswith("utun"):
                    return parts[-1]
        except Exception:
            return None
    return None  # Windows/Linux 本期不做检测


def write_launcher(kernel_path: str, args: list, log_path: str, pid_path: str) -> str:
    """生成提权启动包装脚本，返回脚本路径。"""
    if system() == "Windows":
        quoted = " ".join(f'"{a}"' for a in [kernel_path, *args])
        content = f'@echo off\r\nstart /b "" {quoted} > "{log_path}" 2>&1\r\n'
        suffix = ".bat"
    else:
        quoted = " ".join(shlex.quote(a) for a in [kernel_path, *args])
        content = (
            "#!/bin/sh\n"
            f"nohup {quoted} > {shlex.quote(log_path)} 2>&1 &\n"
            f"echo $! > {shlex.quote(pid_path)}\n"
        )
        suffix = ".sh"
    fd, path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def spawn_elevated(launcher_path: str) -> bool:
    """提权执行包装脚本（授权框弹出期间不阻塞事件循环；用户取消返回 False）。"""
    if system() == "Darwin":
        r = subprocess.run(
            ["osascript", "-e",
             f'do shell script "/bin/sh {launcher_path}" with administrator privileges'],
            capture_output=True,
        )
        return r.returncode == 0
    if system() == "Linux":
        return subprocess.run(["pkexec", "/bin/sh", launcher_path]).returncode == 0
    if system() == "Windows":
        import ctypes

        return ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f'/c "{launcher_path}"', None, 0
        ) > 32
    return False


def read_pid(pid_path: str) -> int | None:
    try:
        with open(pid_path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """探测进程是否存活（无权限发信号说明是 root 进程，也视为存活）。

    先尝试收割僵死子进程：生产场景内核被 reparent 到 init、死亡即被回收，
    但测试里被监控进程是本进程的子进程，退出后未 wait 会残留为僵尸，
    kill(pid, 0) 对僵尸仍成功 → 永远判定存活。waitpid 只对子进程有效，
    非子进程抛 ChildProcessError，落入 kill(0) 探测路径。
    """
    try:
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def kill_elevated(pid: int) -> bool:
    """提权杀死内核进程（断开连接时可能再弹一次授权框）。"""
    if system() == "Darwin":
        r = subprocess.run(
            ["osascript", "-e",
             f'do shell script "kill {pid}" with administrator privileges'],
            capture_output=True,
        )
        return r.returncode == 0
    if system() == "Linux":
        return subprocess.run(["pkexec", "kill", str(pid)]).returncode == 0
    if system() == "Windows":
        return subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                              capture_output=True).returncode == 0
    return False
