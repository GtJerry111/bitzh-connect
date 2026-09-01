import subprocess
from platform import system

from PySide6.QtCore import QThread, Signal

if system() == "Windows":
    from subprocess import CREATE_NO_WINDOW


def get_proxy_settings(window):
    """Get proxy settings from window HTTP and SOCKS binds"""
    http_host, http_port = "127.0.0.1", None
    socks_host, socks_port = "127.0.0.1", None

    if hasattr(window, "http_bind") and window.http_bind:
        try:
            http_port = int(window.http_bind)
        except ValueError:
            pass

    if hasattr(window, "socks_bind") and window.socks_bind:
        try:
            socks_port = int(window.socks_bind)
        except ValueError:
            pass

    return http_host, http_port, socks_host, socks_port


class CommandWorker(QThread):
    output = Signal(str)
    finished = Signal(int)  # 携带进程退出码

    def __init__(self, command_args, proxy_enabled, window=None):
        super().__init__()
        self.command_args = command_args
        self.proxy_enabled = proxy_enabled
        self.window = window
        self.process = None
        # stop() 先于 run() 中 Popen 完成时被调用时记录的终止意图（防竞态丢终止）
        self._stop_requested = False
        self._proxy_handlers = {
            "Windows": set_windows_proxy,
            "Darwin": set_macos_proxy,
            "Linux": set_linux_proxy,
        }

    def run(self):
        exit_code = -1
        try:
            # Set proxy if enabled
            if self.proxy_enabled and self.window:
                proxy_handler = self._proxy_handlers.get(system())
                if proxy_handler:
                    proxy_handler(True, *get_proxy_settings(self.window))

            # Run process
            creation_flags = CREATE_NO_WINDOW if system() == "Windows" else 0
            self.process = subprocess.Popen(
                self.command_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="utf-8",
                creationflags=creation_flags,
            )

            # stop() 可能在 Popen 完成前被调用：补杀，避免留下无人看管的存活进程
            if self._stop_requested:
                self.process.terminate()

            for line in self.process.stdout:
                self.output.emit(line)
            self.process.wait()
            exit_code = self.process.returncode
        finally:
            # Disable proxy on completion
            if self.proxy_enabled:
                proxy_handler = self._proxy_handlers.get(system())
                if proxy_handler:
                    proxy_handler(False)
            self.finished.emit(exit_code)

    def stop(self):
        """非阻塞终止进程。进程退出与代理由 run() 的收尾逻辑在工作线程完成。"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
        elif self.process is None:
            # 与 run() 中 Popen 竞态：进程尚未 spawn，记录终止意图待 spawn 后补杀
            self._stop_requested = True


def set_windows_proxy(
    enable, http_host=None, http_port=None, socks_host=None, socks_port=None
):
    """Manage proxy settings for Windows using the Windows Registry."""
    if system() != "Windows":
        return

    import winreg as reg
    import ctypes

    with reg.OpenKey(
        reg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        0,
        reg.KEY_ALL_ACCESS,
    ) as internet_settings:
        reg.SetValueEx(
            internet_settings, "ProxyEnable", 0, reg.REG_DWORD, 1 if enable else 0
        )
        if enable and http_host and http_port:
            reg.SetValueEx(
                internet_settings,
                "ProxyServer",
                0,
                reg.REG_SZ,
                f"{http_host}:{http_port}",
            )

    # Refresh system proxy settings
    ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
    ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)


def set_macos_proxy(
    enable, http_host=None, http_port=None, socks_host=None, socks_port=None
):
    """Manage proxy settings for macOS using networksetup."""
    if system() != "Darwin":
        return

    services = (
        subprocess.check_output(["networksetup", "-listallnetworkservices"])
        .decode()
        .split("\n")[1:]
    )
    services = [s for s in services if s and not s.startswith("*")]

    for service in services:
        if enable and http_host and http_port:
            subprocess.run(
                ["networksetup", "-setwebproxy", service, http_host, str(http_port)]
            )
            subprocess.run(
                [
                    "networksetup",
                    "-setsecurewebproxy",
                    service,
                    http_host,
                    str(http_port),
                ]
            )
            if socks_host and socks_port:
                subprocess.run(
                    [
                        "networksetup",
                        "-setsocksfirewallproxy",
                        service,
                        socks_host,
                        str(socks_port),
                    ]
                )
        else:
            subprocess.run(["networksetup", "-setwebproxystate", service, "off"])
            subprocess.run(["networksetup", "-setsecurewebproxystate", service, "off"])
            subprocess.run(
                ["networksetup", "-setsocksfirewallproxystate", service, "off"]
            )


def set_linux_proxy(
    enable, http_host=None, http_port=None, socks_host=None, socks_port=None
):
    """Manage proxy settings for Linux using gsettings."""
    if system() != "Linux":
        return

    if enable and http_host and http_port:
        subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"])
        for protocol in ["http", "https"]:
            subprocess.run(
                [
                    "gsettings",
                    "set",
                    f"org.gnome.system.proxy.{protocol}",
                    "host",
                    http_host,
                ]
            )
            subprocess.run(
                [
                    "gsettings",
                    "set",
                    f"org.gnome.system.proxy.{protocol}",
                    "port",
                    str(http_port),
                ]
            )
        if socks_host and socks_port:
            subprocess.run(
                ["gsettings", "set", "org.gnome.system.proxy.socks", "host", socks_host]
            )
            subprocess.run(
                [
                    "gsettings",
                    "set",
                    "org.gnome.system.proxy.socks",
                    "port",
                    str(socks_port),
                ]
            )
    else:
        subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "none"])


def proxy_points_to_us(http_port):
    """检查当前系统代理是否指向我们的 HTTP 代理端口。"""
    try:
        if system() == "Windows":
            import winreg as reg

            with reg.OpenKey(
                reg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as s:
                enabled, _ = reg.QueryValueEx(s, "ProxyEnable")
                server, _ = reg.QueryValueEx(s, "ProxyServer")
                return bool(enabled) and str(server).endswith(f":{http_port}")
        elif system() == "Darwin":
            out = subprocess.check_output(
                ["networksetup", "-getwebproxy", "Wi-Fi"], text=True
            )
            return "Enabled: Yes" in out and f"Port: {http_port}" in out
        elif system() == "Linux":
            mode = subprocess.check_output(
                ["gsettings", "get", "org.gnome.system.proxy", "mode"], text=True
            )
            port = subprocess.check_output(
                ["gsettings", "get", "org.gnome.system.proxy.http", "port"], text=True
            )
            return "manual" in mode and str(http_port) in port
    except Exception:
        return False
    return False


def cleanup_residue_proxy(window):
    """启动时调用：若系统代理仍指向本应用的端口（上次被强杀残留），则关闭它。

    返回 True 表示执行了清理。
    """
    http_port = getattr(window, "http_bind", None) or "1081"
    if not proxy_points_to_us(http_port):
        return False
    handler = {
        "Windows": set_windows_proxy,
        "Darwin": set_macos_proxy,
        "Linux": set_linux_proxy,
    }.get(system())
    if handler:
        handler(False)
        return True
    return False
