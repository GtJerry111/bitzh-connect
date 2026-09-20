import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from platform import system
from common.constants import APP_NAME

if system() == "Darwin":
    from utils.macos_utils import hide_dock_icon
from common import resources
from utils.shutdown import install_exit_signal_handlers
from utils.single_instance import acquire_single_instance_lock
from utils.tun_utils import sweep_orphan_tun
from views.main_window import MainWindow

# Run the application
if __name__ == "__main__":
    # 应用名设置须在 QApplication 构造之前：macOS 在 NSApplication 初始化时
    # 快照菜单栏/Dock 显示名，构造后再设可能不生效
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    if system() == "Darwin":
        # 未打包运行时 Dock/菜单栏默认显示进程名（python3.x），尽量纠正；
        # 打包成 .app 后由 bundle 保证，此处只是尽力而为
        try:
            from Foundation import NSProcessInfo

            NSProcessInfo.processInfo().setProcessName_(APP_NAME)
        except Exception as e:
            # 失败仅表现为 Dock 名不纠正，不影响功能
            print(f"setProcessName failed: {e}")
    app = QApplication()
    # 单实例：第二次启动直接退出——否则启动清扫会误伤另一实例正在用的 TUN 内核
    _instance_lock = acquire_single_instance_lock()
    if _instance_lock is None:
        sys.exit(0)
    # 启动自愈：清掉上次异常退出残留的 TUN 内核/临时文件（含内嵌密码的 launcher）
    sweep_orphan_tun()
    window = MainWindow()
    # 关闭终端/Ctrl-C/kill 时走一次优雅退出（写停止标记、收掉 root 内核）
    _exit_timer = install_exit_signal_handlers(window.quit_app, parent=window)

    if system() == "Windows":
        font = app.font()
        font.setFamily("Microsoft YaHei UI")
        app.setFont(font)

    if system() == "Windows":
        app.setWindowIcon(QIcon(":/icons/icon.ico"))
    elif system() == "Darwin":
        app.setWindowIcon(QIcon(":/icons/icon.icns"))
    elif system() == "Linux":
        app.setWindowIcon(QIcon(":/icons/icon.png"))

    if not window.silent_mode:
        window.show()

    if system() == "Darwin":
        hide_dock_icon(window.hide_dock_icon)

    app.exec()
