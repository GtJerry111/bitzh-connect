import os
import sys
from platform import system
import gc
from PySide6.QtCore import QSignalBlocker
from .set_proxy import CommandWorker
from .log_parser import parse_client_ip, is_auth_failure, is_server_kick


def handle_output(window, text):
    """处理内核输出：上屏 + 解析状态"""
    window.output_text.append(text)

    ip = parse_client_ip(text)
    if ip:
        window.virtual_ip = ip
        window.reconnect_manager.on_connection_established()
        window.status_panel.set_connected(ip)

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

    if auth_failed:
        window.status_panel.set_disconnected("认证失败，请检查用户名和密码")
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
        # 早退前复位"假连接"态：toggled(True) 已发出，按钮勾选/文案/输入框禁用态
        # 都被切换，需手动恢复（屏蔽信号避免回环触发 stop_connection）
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
        window.status_panel.set_disconnected("请输入用户名和密码")
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
