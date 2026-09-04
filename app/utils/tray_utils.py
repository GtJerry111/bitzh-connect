from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QMainWindow
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QTimer
from shiboken6 import isValid
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
    # 退出流程中（macOS teardown 会补发 closeEvent）：直接放行，
    # 不触碰任何可能已销毁的对象（F1 崩溃修复）
    if getattr(window, "_quitting", False):
        event.accept()
        return
    try:
        # isValid 前置短路：C++ 对象已销毁时根本不触碰它；
        # RuntimeError 兜底 isValid 与 isVisible 之间的删除竞态
        tray_visible = isValid(tray_icon) and tray_icon.isVisible()
    except RuntimeError:
        tray_visible = False  # 托盘 C++ 对象已销毁（退出竞态）
    if tray_visible:
        window.hide()
        event.ignore()
    else:
        window.quit_app()


def quit_app(window, tray_icon):
    """Quit the application（可重入；保证 teardown 期不再有 Python override 抛异常）"""
    if getattr(window, "_quitting", False):
        return
    window._quitting = True
    window.stop_connection()
    window.hide()
    # 关键：worker 线程必须死在 QApplication 销毁之前——QThread 析构时线程仍在跑
    # 会 qFatal（真实崩溃栈：QThreadWrapper::~QThreadWrapper 于解释器收尾期）。
    # 内核 SIGTERM 后的收尾（清路由/还原 resolver）可能超过原 1.5s 固定延迟，
    # 改为显式等待；阻塞发生在 hide 之后，用户无感。
    worker = getattr(window, "worker", None)
    if worker is not None and worker.isRunning():
        worker.wait(3000)
        if worker.isRunning():
            # 兜底：极端挂死时强杀线程（内核进程已终止，读循环不会自行返回；
            # 不杀则 teardown 必崩——两害相权取强杀）
            worker.terminate()
            worker.wait(500)
    if isValid(tray_icon):
        tray_icon.deleteLater()
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
