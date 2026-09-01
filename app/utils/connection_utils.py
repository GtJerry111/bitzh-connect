import os
import sys
from platform import system
import gc
from .set_proxy import CommandWorker


def handle_output(window, text):
    """Handle output text from the worker"""
    window.output_text.append(text)


def handle_connection_finished(window):
    """Handle connection finished event with proper cleanup"""
    if window.worker:
        window.worker.output.disconnect()
        window.worker.finished.disconnect()
        window.worker.deleteLater()
        window.worker = None
        gc.collect()

    window.status_label.setText("状态: 未连接")
    if hasattr(window, "connect_button"):
        window.connect_button.setChecked(False)


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
    """Start VPN connection"""
    if window.worker and window.worker.isRunning():
        window.status_label.setText("状态: 正在运行")
        return

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
    window.worker.finished.connect(lambda: handle_connection_finished(window))
    window.worker.start()

    window.status_label.setText("状态: 正在运行")


def stop_connection(window):
    """Stop VPN connection with proper cleanup"""
    if window.worker:
        window.worker.stop()
        window.worker.wait()
        window.worker.output.disconnect()
        window.worker.finished.disconnect()
        window.worker.deleteLater()
        window.worker = None
        gc.collect()

    window.status_label.setText("状态: 未连接")
