# app/utils/tun_utils.py
"""TUN 模式支持：提权启动内核、停止标记、pid 管理、共存探测。

提权方案（本期最简，后续可换 SMAppServices 特权助手）：
- macOS：osascript do shell script ... with administrator privileges（仅连接时弹一次授权框）
- Linux：pkexec
- Windows：本期不可用（.bat + UAC 链路未验证，高级设置里开关已置灰，后置处理）

内核以 root 后台运行，输出重定向到日志文件；GUI 用 TunWorker 尾随解析。
断连零弹窗：包装脚本自带 root 守护循环（轮询停止标记文件，出现即杀内核），
GUI 断开时只需 request_stop 写标记文件——普通文件写，无需任何权限。
注意：包装脚本经真实 shell 执行，参数必须 shlex.quote（这里 quoting 是对的——
与 B1 修复不矛盾：B1 是 subprocess list 不过 shell，这里过 shell）。

同步版 spawn_elevated 会阻塞等待用户授权（可达数十秒），
GUI 路径一律走 *_async 版本（QThreadPool 执行，结果信号回主线程）。
"""
import glob
import os
import shlex
import stat
import subprocess
import tempfile
from platform import system

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


def _parse_route_get_interface(text: str) -> str | None:
    """从 `route -n get <ip>` 输出里取 interface（macOS）。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("interface:"):
            return stripped.split(":", 1)[1].strip() or None
    return None


def _parse_scutil_nwi(text: str) -> str | None:
    """从 `scutil --nwi` 输出取主网卡（"Network interfaces: en0, en1"）。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Network interfaces:"):
            names = stripped.split(":", 1)[1].replace(",", " ").split()
            return names[0] if names else None
    return None


# `ip route` 行的特殊目的关键字（非地址开头的情形）
_ROUTE_DEST_KEYWORDS = frozenset({
    "default", "local", "broadcast", "multicast",
    "unreachable", "prohibit", "blackhole", "throw", "nat",
})


def _parse_ip_route_dev(text: str) -> str | None:
    """从 `ip route` 输出取 `dev <iface>`（Linux）。

    `ip route` 行以目的地址开头（IP/CIDR、IPv6 或 default/local 等关键字）；
    先校验这点，避免恰好含 "dev" 单词的普通文本（如 "no dev token"）被误当
    路由输出解析。
    """
    parts = text.split()
    if not parts:
        return None
    dest = parts[0]
    if dest not in _ROUTE_DEST_KEYWORDS and ":" not in dest and not dest[0].isdigit():
        return None
    if "dev" in parts:
        idx = parts.index("dev")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _is_tun_name(name: str) -> bool:
    return name.startswith(("utun", "tun"))


def capturing_tun_for(server_ip: str) -> str | None:
    """返回会把去 server_ip 的流量截进 TUN 的网卡名；无则 None。

    比"默认路由是否在 utun"更准：FlClash/mihomo 不抢默认路由，而是用一串
    明细路由（如 64.0.0.0/2）把服务器 IP 拐进自己的 utun。
    命令失败/解析失败安静返回 None（探测失败不该阻断连接）。
    """
    try:
        if system() == "Darwin":
            out = subprocess.check_output(
                ["route", "-n", "get", server_ip],
                text=True, stderr=subprocess.DEVNULL,
            )
            dev = _parse_route_get_interface(out)
        elif system() == "Linux":
            out = subprocess.check_output(
                ["ip", "route", "get", server_ip],
                text=True, stderr=subprocess.DEVNULL,
            )
            dev = _parse_ip_route_dev(out)
        else:
            return None
        return dev if dev and _is_tun_name(dev) else None
    except Exception:
        return None


def physical_interface() -> str | None:
    """主物理网卡名；macOS 用 scutil --nwi，失败回退默认路由出口；排除 TUN。"""
    try:
        if system() == "Darwin":
            out = subprocess.check_output(
                ["scutil", "--nwi"], text=True, stderr=subprocess.DEVNULL
            )
            name = _parse_scutil_nwi(out)
            if name and not _is_tun_name(name):
                return name
            out = subprocess.check_output(
                ["route", "-n", "get", "default"],
                text=True, stderr=subprocess.DEVNULL,
            )
            name = _parse_route_get_interface(out)
        elif system() == "Linux":
            out = subprocess.check_output(
                ["ip", "route", "show", "default"],
                text=True, stderr=subprocess.DEVNULL,
            )
            name = _parse_ip_route_dev(out)
        else:
            return None
        return name if name and not _is_tun_name(name) else None
    except Exception:
        return None


def write_launcher(
    kernel_path: str, args: list, log_path: str, pid_path: str, stop_path: str
) -> str:
    """生成提权启动包装脚本，返回脚本路径。

    POSIX 版脚本三段：后台拉起内核 → 写 pidfile → 挂 root 守护循环。
    守护循环每 0.3s 查一次停止标记文件：出现即杀内核；内核自己退出（如被
    服务器踢）循环自然结束。断开侧因此只需 touch 标记文件，全程零权限。
    """
    if system() == "Windows":
        # Windows TUN 本期硬守卫不可达：.bat 不含守护循环，启用时需补对等机制
        quoted = " ".join(f'"{a}"' for a in [kernel_path, *args])
        content = f'@echo off\r\nstart /b "" {quoted} > "{log_path}" 2>&1\r\n'
        suffix = ".bat"
    else:
        # 不用 nohup：osascript 提权执行时没有控制终端，macOS 的 nohup 会报
        # "can't detach from console" 直接失败（已实测踩中）。sh 退出时不会给
        # 后台任务发 SIGHUP，后台+重定向已足够。
        quoted = " ".join(shlex.quote(a) for a in [kernel_path, *args])
        stop_quoted = shlex.quote(stop_path)
        content = (
            "#!/bin/sh\n"
            f"{quoted} > {shlex.quote(log_path)} 2>&1 &\n"
            "kpid=$!\n"
            f"echo $kpid > {shlex.quote(pid_path)}\n"
            # 守护循环：stdio 全部重定向后脱离 osascript 独立存活（不拖住
            # do shell script 的返回）；停止标记出现即杀内核并退出
            f"( while kill -0 $kpid 2>/dev/null; do\n"
            f"    if [ -f {stop_quoted} ]; then kill $kpid 2>/dev/null; break; fi\n"
            f"    sleep 0.3\n"
            f"  done ) < /dev/null > /dev/null 2>&1 &\n"
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
    # waitpid/WNOHANG 仅 Unix 存在；Windows 走下方 kill(0) 探测分支。
    # 注意 Windows 的 os.kill(pid, 0) 实现是 TerminateProcess——会真杀进程；
    # 本期 Windows TUN 已置灰 + 硬守卫不可达，未来启用需换 OpenProcess 探测
    if system() != "Windows":
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


def request_stop(stop_path: str) -> None:
    """创建停止标记文件，通知包装脚本里的 root 守护循环杀内核。

    普通文件写，零权限、不弹授权框——这是断连/退出路径不再提权的关键。
    标记可能被 worker 收尾提前清理，需要确保"内核必死"时（如孤儿补杀）
    调用方应重写一次；重复创建幂等。
    """
    try:
        with open(stop_path, "w"):
            pass
    except OSError:
        pass


def sweep_orphan_tun() -> int:
    """清理异常退出残留的 TUN 内核与临时文件（启动时自愈）。

    正常断开时 app 会写停止标记、root 守护脚本收掉内核并清理临时文件；app 被强杀
    （关终端 / Ctrl-C / 崩溃）时内核与临时文件会残留。启动时：
    - pid 仍存活 → 写 .stop，交给仍在等待的 root 守护脚本收掉；
    - pid 已死 → 删掉残留的 pid/stop；
    - 删掉残留的 launcher 脚本与日志（脚本内嵌命令行含密码，必须清）。
    返回本次要求停止的内核数量。失败安静忽略（启动不应被清理问题阻断）。
    """
    stopped = 0
    tmp = tempfile.gettempdir()
    for pid_file in glob.glob(os.path.join(tmp, "bitzh-tun-*.pid")):
        pid = read_pid(pid_file)
        if pid is not None and _pid_alive(pid):
            request_stop(pid_file + ".stop")
            stopped += 1
        else:
            for suffix in ("", ".stop"):
                try:
                    os.remove(pid_file + suffix)
                except OSError:
                    pass
    for pattern in ("bitzh-tun-*.sh", "bitzh-tun-*.log"):
        for path in glob.glob(os.path.join(tmp, pattern)):
            try:
                os.remove(path)
            except OSError:
                pass
    return stopped


# ---- 异步提权（GUI 路径专用）----


class _ElevatedSignals(QObject):
    """提权任务完成信号（结果投递回主线程）。"""

    done = Signal(bool)


class _ElevatedTask(QRunnable):
    """线程池里跑同步提权命令：授权框停留期间不冻结 GUI 事件循环。"""

    def __init__(self, fn, arg):
        super().__init__()
        self._fn = fn
        self._arg = arg
        self.signals = _ElevatedSignals()

    def run(self):
        try:
            ok = bool(self._fn(self._arg))
        except Exception:
            # osascript/pkexec 缺失等异常按失败上报（update_service.UpdateChecker 同款
            # try/except 先例）：不能让 done 永不 emit——spawn 路径 UI 会卡"连接中"
            # 120s 且 _pending_tasks 泄漏；kill 路径警告永不发
            ok = False
        self.signals.done.emit(ok)


# 持有在途任务引用直到 done 投递完成：QRunnable autoDelete 后
# queued 信号尚未投递会丢（update_service._workers 同款教训）
_pending_tasks = []


def _run_elevated(fn, arg, on_done) -> _ElevatedTask:
    task = _ElevatedTask(fn, arg)
    _pending_tasks.append(task)

    def _cleanup(ok):
        try:
            if on_done:
                on_done(ok)
        finally:
            _pending_tasks.remove(task)

    # 实测 PySide6 把普通闭包槽投递回主线程执行，on_done 里可直接操作 GUI
    task.signals.done.connect(_cleanup)
    QThreadPool.globalInstance().start(task)
    return task


def spawn_elevated_async(launcher_path: str, on_done) -> _ElevatedTask:
    """异步提权执行包装脚本；完成后在 GUI 线程回调 on_done(ok: bool)。

    返回任务对象——调用方应挂到长生命周期对象（如 window）上防 GC。
    """
    return _run_elevated(spawn_elevated, launcher_path, on_done)
