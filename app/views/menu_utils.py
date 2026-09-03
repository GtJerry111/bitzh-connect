import webbrowser

from PySide6.QtWidgets import QMessageBox
from .advanced_panel import AdvancedSettingsDialog
from platform import system
from services.update_service import UpdateService
from common.constants import RELEASES_URL

if system() == "Darwin":
    from utils.macos_utils import hide_dock_icon

update_service = UpdateService()


# 注：窗口菜单栏已移除——设置入口在主窗口右下角"设置"按钮（⌘, 快捷键保留），
# 帮助功能（关于/复制日志/检查更新）收进高级设置对话框的"帮助" tab


def check_for_updates(parent, current_version, startup=False):
    """
    Check for updates and show dialog.

    Args:
        parent: Parent widget for dialogs
        current_version: Current version string
        startup: Whether this check is happening at startup
    """
    signals = update_service.check_for_updates(current_version)

    def on_update_available(latest_version):
        if not startup:
            reply = QMessageBox.question(
                parent, "检查更新", f"发现新版本 {latest_version}，是否前往下载？"
            )
            if reply == QMessageBox.Yes:
                webbrowser.open(RELEASES_URL)
        else:
            parent.output_text.append(f"New version {latest_version} is available.\n")

    def on_up_to_date():
        if not startup:
            QMessageBox.information(parent, "检查更新", "当前已是最新版本")
        else:
            parent.output_text.append("App is up to date.\n")

    def on_error(error_msg):
        if not startup:
            QMessageBox.critical(parent, "检查更新", "检查更新失败，请检查网络连接")
        else:
            parent.output_text.append(
                "Failed to check for updates. Please check your network connection.\n"
            )

    # Connect the signals
    signals.update_available.connect(on_update_available)
    signals.up_to_date.connect(on_up_to_date)
    signals.error.connect(on_error)


def show_advanced_settings(window):
    """Show advanced settings dialog with proper cleanup"""
    dialog = AdvancedSettingsDialog(window)
    dialog.set_settings(
        window.server_address,
        window.port,
        window.dns_server,
        window.proxy,
        window.connect_startup,
        window.silent_mode,
        window.check_update,
        window.hide_dock_icon,
        window.keep_alive,
        window.debug_dump,
        window.disable_multi_line,
        window.http_bind,
        window.socks_bind,
        window.auto_dns,
        window.cert_file,
        window.cert_password,
        window.auto_reconnect,
        window.appearance,
        window.tun_mode,
    )

    if dialog.exec():
        settings = dialog.get_settings()
        server_changed = settings["server"] != window.server_address
        window.server_address = settings["server"]
        window.port = settings["port"]
        window.dns_server = settings["dns"]
        window.auto_dns = settings["auto_dns"]
        window.proxy = settings["proxy"]
        window.connect_startup = settings["connect_startup"]
        window.silent_mode = settings["silent_mode"]
        window.check_update = settings["check_update"]
        window.hide_dock_icon = settings.get("hide_dock_icon", False)
        window.keep_alive = settings["keep_alive"]
        window.debug_dump = settings["debug_dump"]
        window.disable_multi_line = settings["disable_multi_line"]
        window.http_bind = settings["http_bind"]
        window.socks_bind = settings["socks_bind"]
        window.cert_file = settings["cert_file"]
        window.cert_password = settings["cert_password"]
        window.auto_reconnect = settings["auto_reconnect"]
        window.reconnect_manager.set_enabled(window.auto_reconnect)
        window.appearance = settings["appearance"]
        window.tun_mode = settings["tun_mode"]
        from common import theme

        theme.set_appearance(settings["appearance"])
        # 服务器变了 → 同步仪表盘副标题中的服务器小字
        if server_changed:
            window.status_panel.set_server_text(window.server_address)
        if system() == "Darwin":
            hide_dock_icon(window.hide_dock_icon)
