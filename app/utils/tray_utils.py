from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QMainWindow
from PySide6.QtGui import QIcon, QAction
from platform import system
from common import resources


def create_tray_menu(window: QMainWindow, tray_icon):
    """Create and set up the system tray menu"""
    menu = QMenu()
    show_action = menu.addAction("打开面板")
    show_action.triggered.connect(window.show)
    show_action.triggered.connect(window.raise_)
    connect_action = QAction("VPN 连接", menu)
    connect_action.setCheckable(True)
    connect_action.triggered.connect(
        lambda checked: window.connect_button.setChecked(checked)
    )
    # 同步托盘勾选与按钮实时状态（读 isChecked 而非 toggled 参数）：
    # start_connection 凭据校验早退已在前面槽位复位按钮/托盘，用参数会重新勾选
    window.connect_button.toggled.connect(
        lambda checked: connect_action.setChecked(window.connect_button.isChecked())
    )
    # 挂到 window 上：断连收尾（按钮 toggled 被 QSignalBlocker 屏蔽）时手动同步勾选态
    window.tray_connect_action = connect_action
    menu.addAction(connect_action)
    quit_action = menu.addAction("退出")
    quit_action.triggered.connect(window.quit_app)

    tray_icon.setContextMenu(menu)
    tray_icon.activated.connect(lambda reason: tray_icon_activated(reason, window))


def tray_icon_activated(reason, window):
    """Handle tray icon activation"""
    if reason == QSystemTrayIcon.DoubleClick:
        window.show()
        window.activateWindow()


def handle_close_event(window, event, tray_icon):
    """Handle window close event"""
    if tray_icon.isVisible():
        window.hide()
        event.ignore()
    else:
        window.quit_app()


def quit_app(window, tray_icon):
    """Quit the application"""
    window.stop_connection()
    tray_icon.deleteLater()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(1500, QApplication.quit)


def init_tray_icon(window):
    """Initialize system tray icon and menu"""
    tray_icon = QSystemTrayIcon(window)

    # Set icon based on platform
    if system() == "Windows":
        icon_path = ":/icons/icon.ico"
    elif system() == "Darwin":
        icon_path = ":/icons/menu-icon.png"
        icon = QIcon(icon_path)
        icon.setIsMask(True)
        tray_icon.setIcon(icon)
        create_tray_menu(window, tray_icon)
        tray_icon.show()
        return tray_icon
    elif system() == "Linux":
        icon_path = ":/icons/icon.png"

    tray_icon.setIcon(QIcon(icon_path))
    create_tray_menu(window, tray_icon)
    tray_icon.show()
    return tray_icon
