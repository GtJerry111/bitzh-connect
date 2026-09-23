from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QMainWindow
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QTimer
from shiboken6 import isValid
from platform import system
from common import resources


def _detach_qt_tray_sync(window):
    """撤销旧的 QAction 勾选同步槽并清空引用（重建 Qt 菜单 / 切原生菜单前调用）。

    否则陈旧 lambda 仍挂在长寿的 connect_button.toggled 上，命中已销毁 QAction
    会 RuntimeError（见 Task 6 ⑤）。原生 NSMenu 不建 QAction，故置 None。
    """
    old_sync = getattr(window, "_tray_connect_sync", None)
    if old_sync is not None:
        try:
            window.connect_button.toggled.disconnect(old_sync)
        except (RuntimeError, TypeError):
            pass
        window._tray_connect_sync = None
    window.tray_connect_action = None


def build_tray_menu(window: QMainWindow) -> QMenu:
    """构建 Qt 托盘菜单（打开主窗口 / VPN 连接 / 退出；QSystemTrayIcon 用）。"""
    # 重建时先撤销旧同步槽（否则陈旧 lambda 命中已销毁 QAction，见 Task 6 ⑤）
    _detach_qt_tray_sync(window)
    menu = QMenu()
    show_action = menu.addAction("打开主窗口")
    show_action.triggered.connect(window.open_main_window)
    connect_action = QAction("VPN 连接", menu)
    connect_action.setCheckable(True)
    connect_action.triggered.connect(
        lambda checked: window.connect_button.setChecked(checked)
    )
    # 同步托盘勾选与按钮实时状态（读 isChecked 而非 toggled 参数）：
    # start_connection 凭据校验早退已在前面槽位复位按钮/托盘，用参数会重新勾选
    sync = lambda checked: connect_action.setChecked(window.connect_button.isChecked())
    window.connect_button.toggled.connect(sync)
    window._tray_connect_sync = sync
    # 挂到 window 上：断连收尾（按钮 toggled 被 QSignalBlocker 屏蔽）时手动同步勾选态
    window.tray_connect_action = connect_action
    menu.addAction(connect_action)
    quit_action = menu.addAction("退出")
    quit_action.triggered.connect(window.quit_app)
    return menu


def create_tray_menu(window: QMainWindow, tray_icon):
    """QSystemTrayIcon 路径：挂 context menu + 双击唤出（Win/Linux）。"""
    tray_icon.setContextMenu(build_tray_menu(window))
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
        # None 前置短路：原生状态栏项路径 tray_icon 为 None（托盘职责在
        # _mac_status_item）；isValid 前置短路已销毁的 C++ 对象；
        # RuntimeError 兜底 isValid 与 isVisible 之间的删除竞态
        tray_visible = (
            tray_icon is not None and isValid(tray_icon) and tray_icon.isVisible()
        )
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
    mac_item = getattr(window, "_mac_status_item", None)
    if mac_item is not None:
        mac_item.teardown()
        window._mac_status_item = None
    panel = getattr(window, "_menu_bar_panel", None)
    if panel is not None:
        panel.hide()
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
    # None 守卫：原生状态栏项路径 tray_icon 为 None
    # （shiboken6.isValid(None) 实为 True，只靠 isValid 会 AttributeError）
    if tray_icon is not None and isValid(tray_icon):
        tray_icon.deleteLater()
    QTimer.singleShot(1500, QApplication.quit)


def init_tray_icon(window):
    """初始化托盘/状态栏项。macOS 恒尝试原生 NSStatusItem（左键展开快捷面板、
    右键菜单）；桥接失败静默回退 QSystemTrayIcon。返回托盘对象
    （原生状态栏项创建成功时为 None，托盘职责由 window._mac_status_item 承担）。"""
    if system() == "Darwin":
        # QSystemTrayIcon 在 macOS 27 + Qt ≤ 6.11.2 上点击即崩（Qt 内部
        # emitActivated 对 SysDefined 事件发 clickCount）；建托盘前打补丁
        from utils.macos_tray_fix import apply_tray_click_fix

        apply_tray_click_fix()
    if system() == "Darwin":
        from utils.macos_status_item import create

        # 原生 NSMenu：macOS 26+ 由系统自动给右键菜单套液态玻璃（Qt QMenu 拿不到）
        menu_spec = [
            {"title": "打开主窗口", "action": window.open_main_window},
            {
                "title": "VPN 连接",
                "action": window.connect_button.toggle,
                "is_checked": window.connect_button.isChecked,
            },
            {
                "title": "在菜单栏显示速度",
                "action": lambda: window.set_menu_bar_speed(
                    not getattr(window, "menu_bar_speed", False)
                ),
                "is_checked": lambda: bool(getattr(window, "menu_bar_speed", False)),
            },
            {"separator": True},
            {"title": "退出", "action": window.quit_app},
        ]
        _detach_qt_tray_sync(window)  # 原生菜单不建 QAction：清掉旧同步防陈旧 lambda
        item = create(on_toggle=window.toggle_panel, menu_spec=menu_spec)
        if item is not None:
            window._mac_status_item = item
            return None
        # 桥接不可用（非 cocoa/无 pyobjc）：回退 QSystemTrayIcon

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
