import os
import sys
from platform import system
import gc
from PySide6.QtCore import QSignalBlocker
from .set_proxy import CommandWorker
from .log_parser import parse_client_ip, is_auth_failure, is_server_kick
from .tun_utils import (
    check_tun_conflict,
    write_launcher,
    spawn_elevated_async,
    kill_elevated_async,
    read_pid,
)
from .tun_worker import TunWorker


def _reset_connect_ui(window, status_detail: str):
    """早退路径统一复位：仪表盘断开态 + 按钮/输入框/托盘回滚（屏蔽信号防回环）。

    编程式 setChecked(False) 会触发 toggled → stop_connection() → reconnect_manager.cancel()，
    必须用 QSignalBlocker；被屏蔽的 toggled 附带效果（按钮文案、输入框禁用态、
    托盘勾选联动）需手动恢复。
    """
    window.status_panel.set_disconnected(hero="未连接", detail=status_detail)
    if hasattr(window, "connect_button"):
        blocker = QSignalBlocker(window.connect_button)
        window.connect_button.setChecked(False)
        window.connect_button.setText("连接")
        window.username_input.setEnabled(True)
        window.password_input.setEnabled(True)
        del blocker
        # 按钮 toggled 被屏蔽，托盘"VPN 连接"勾选态不会自动联动，需手动复位
        if hasattr(window, "tray_connect_action"):
            window.tray_connect_action.setChecked(False)


def handle_output(window, text):
    """处理内核输出：上屏 + 解析状态"""
    window.output_text.append(text)

    ip = parse_client_ip(text)
    if ip:
        window.virtual_ip = ip
        window.reconnect_manager.on_connection_established()
        window.status_panel.set_connected(ip)
        # TUN 模式：连接成功即启动网卡速率监控（仪表盘上行/下行）
        if getattr(window, "tun_mode", False) and hasattr(window, "start_rate_monitor"):
            window.start_rate_monitor(ip)

    if is_auth_failure(text):
        window._auth_failed = True

    if is_server_kick(text):
        window.output_text.append("[BITZH Connect] 检测到被服务器断开，将自动重连\n")


def handle_connection_finished(window, exit_code):
    """进程退出收尾（可能被自动重连重新拉起）"""
    if window.worker:
        window.worker.output.disconnect()
        window.worker.finished.disconnect()
        window.worker.deleteLater()
        window.worker = None
        gc.collect()

    manual = getattr(window, "_manual_stop", True)
    auth_failed = getattr(window, "_auth_failed", False)

    # TUN 模式速率监控随连接终止一并停止
    if hasattr(window, "stop_rate_monitor"):
        window.stop_rate_monitor()

    if auth_failed:
        window.status_panel.set_disconnected(hero="认证失败", detail="请检查用户名和密码")
    else:
        window.status_panel.set_disconnected()

    # 编程式复位按钮必须屏蔽信号（grilling 确认的 plan 漏洞修复）：
    # 直接 setChecked(False) 会触发 toggled → stop_connection() → reconnect_manager.cancel()，
    # 把重试计数清零——退避将永远停在第一档、retries_exhausted 永不触发。
    # 被屏蔽的 toggled 附带效果（按钮文案、输入框禁用态）需手动恢复。
    if hasattr(window, "connect_button"):
        blocker = QSignalBlocker(window.connect_button)
        window.connect_button.setChecked(False)
        window.connect_button.setText("连接")
        window.username_input.setEnabled(True)
        window.password_input.setEnabled(True)
        del blocker
        # 按钮 toggled 被屏蔽，托盘"VPN 连接"勾选态不会自动联动，需手动复位
        if hasattr(window, "tray_connect_action"):
            window.tray_connect_action.setChecked(False)

    window.reconnect_manager.on_process_exited(manual=manual, auth_failed=auth_failed)


def build_command_args(window, command):
    """根据窗口配置构建 zju-connect 命令行参数。

    注意：严禁对参数做 shell 引号处理——subprocess 传 list 不经 shell，
    任何引号都会被字面传给内核（上游 shlex.quote 的 bug）。
    """
    command_args = [
        command,
        "-server", window.server_address,
        "-port", str(window.port),
        "-username", window.username_input.text(),
        "-password", window.password_input.text(),
    ]

    # 远端 DNS：auto 或指定地址（参数新名为 -remote-dns-server）
    if window.auto_dns:
        command_args.extend(["-remote-dns-server", "auto"])
    else:
        command_args.extend(["-remote-dns-server", window.dns_server])

    if window.http_bind:
        command_args.extend(["-http-bind", "127.0.0.1:" + window.http_bind])

    if window.socks_bind:
        command_args.extend(["-socks-bind", "127.0.0.1:" + window.socks_bind])

    if not window.keep_alive:
        command_args.append("-disable-keep-alive")

    if window.debug_dump:
        command_args.append("-debug-dump")

    if window.disable_multi_line:
        command_args.append("-disable-multi-line")

    if window.cert_file:
        command_args.extend(["-cert-file", window.cert_file])
        if window.cert_password:
            command_args.extend(["-cert-password", window.cert_password])

    if getattr(window, "tun_mode", False):
        command_args.append("-tun-mode")
        command_args.append("-add-route")

    command_args.append("-disable-zju-config")
    command_args.append("-skip-domain-resource")

    return command_args


def mask_command_args(command_args):
    """生成脱敏后的命令行副本，用于日志展示。"""
    debug_command = command_args.copy()
    for flag in ("-username", "-password", "-cert-password"):
        if flag in debug_command:
            debug_command[debug_command.index(flag) + 1] = "********"
    return debug_command


def start_connection(window):
    """启动 VPN 连接"""
    # 防御性校验：与主窗口内联校验双保险，凭据为空不拉起进程
    if not (window.username_input.text() and window.password_input.text()):
        # 早退前复位"假连接"态：toggled(True) 已发出，按钮勾选/文案/输入框禁用态都被切换
        _reset_connect_ui(window, "请输入用户名和密码")
        return

    if window.worker and window.worker.isRunning():
        window.status_panel.set_connecting()
        return

    # 手动发起连接：取消可能在途的退避重连计时器（stray timer），
    # 防止它在本次连接期间到点、用旧凭据再拉起一次连接
    window.reconnect_manager.on_connect_attempt()

    window._manual_stop = False
    window._auth_failed = False

    is_nuitka = "__compiled__" in globals()

    if is_nuitka:
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        base_path = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    if system() == "Windows":
        command = os.path.join(base_path, "app", "core", "zju-connect.exe")
    else:
        command = os.path.join(base_path, "app", "core", "zju-connect")
        if os.path.exists(command):
            os.chmod(command, 0o755)

    command_args = build_command_args(window, command)
    window.output_text.append(f"Running command: {' '.join(mask_command_args(command_args))}\n")

    if getattr(window, "tun_mode", False):
        conflict = check_tun_conflict()
        if conflict:
            window.output_text.append(
                f"[BITZH Connect] 检测到默认路由已在虚拟网卡 {conflict}（如 Clash TUN），请先关闭再连\n"
            )
            _reset_connect_ui(window, f"与 {conflict} 的 TUN 冲突")
            return
        # 注意：os 已在模块顶部导入，函数内重复 import 会把 os 变成本地变量，
        # 导致函数前段 os.path 用法 UnboundLocalError——这里只补 tempfile
        import tempfile
        log_fd, log_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".log")
        os.close(log_fd)
        pid_fd, pid_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".pid")
        os.close(pid_fd)
        launcher = write_launcher(command, command_args[1:], log_path, pid_path)
        # 授权框可能停留数十秒：提权异步执行，worker 先行启动
        # （pidfile 120s 等待窗口本就为覆盖授权时长而设）
        window.worker = TunWorker(log_path, pid_path)
        window.worker.output.connect(lambda text: handle_output(window, text))
        window.worker.finished.connect(lambda code: handle_connection_finished(window, code))
        window.worker.start()
        window.status_panel.set_connecting()

        def _on_spawn_done(ok: bool):
            if ok:
                # 授权期间用户已先行断开：内核刚被拉起即成孤儿（root + 全局路由），立即补杀
                worker = window.worker
                if worker is None or getattr(worker, "_stop_requested", False):
                    pid = read_pid(pid_path)
                    if pid is not None:
                        kill_elevated_async(pid)
                return
            # 用户取消授权：连接从未建立，不走"进程退出"收尾路径
            # （避免 handle_connection_finished 用默认文案覆盖"已取消授权"、误触自动重连）
            window.output_text.append("[BITZH Connect] 授权取消，未启动 TUN 连接\n")
            window._manual_stop = True
            worker = window.worker
            if worker is not None:
                try:
                    worker.output.disconnect()
                    worker.finished.disconnect()
                except RuntimeError:
                    pass
                worker.finished.connect(worker.deleteLater)  # 线程退出后自毁
                worker.stop()  # pidfile 尚为空，不会触发 kill，仅停掉等待循环
                window.worker = None
            _reset_connect_ui(window, "已取消授权")

        # task 挂 window 防 GC（update_service._workers 同款教训）
        window._tun_spawn_task = spawn_elevated_async(launcher, _on_spawn_done)
        return

    window.worker = CommandWorker(
        command_args=command_args, proxy_enabled=window.proxy, window=window
    )
    window.worker.output.connect(lambda text: handle_output(window, text))
    window.worker.finished.connect(lambda code: handle_connection_finished(window, code))
    window.worker.start()

    window.status_panel.set_connecting()


def stop_connection(window, manual=True):
    """断开连接。非阻塞：只发 terminate，收尾在 finished 回调里做。"""
    window._manual_stop = manual
    window.reconnect_manager.cancel()
    if window.worker:
        window.worker.stop()
        if not window.worker.isRunning():
            handle_connection_finished(window, -1)
    else:
        window.status_panel.set_disconnected()
