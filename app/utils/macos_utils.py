import objc
from platform import system


def hide_dock_icon(hide=True):
    """Control the visibility of the app icon in the dock using macOS API"""
    if system() == "Darwin":
        NSApp = objc.lookUpClass("NSApplication").sharedApplication()
        NSApp.setActivationPolicy_(
            1 if hide else 0
        )  # 1 = NSApplicationActivationPolicyAccessory, 0 = NSApplicationActivationPolicyRegular


def install_activation_hook(window) -> bool:
    """Dock 图标点击/Cmd-Tab 激活应用时显示主窗口（托盘图标被菜单栏挤出时的兜底入口）。

    macOS 菜单栏拥挤（刘海屏/窄屏）时托盘图标会被系统裁掉，此时 Dock 是唯一入口；
    Qt 默认不会在 Dock 点击时重新显示已隐藏的窗口，需自己接
    NSApplicationDidBecomeActiveNotification。
    """
    if system() != "Darwin":
        return False
    try:
        from Foundation import NSObject

        class _ActivationObserver(NSObject):
            """应用激活通知转发（target-action，与 sleep_wake 同款桥接模式）。"""

            def initWithWindow_(self, window):
                self = self.init()
                if self is None:
                    return None
                self._window = window
                return self

            def onActive_(self, notification):
                self._window._on_app_activate()

            onActive_ = objc.selector(onActive_, signature=b"v@:@")

        center = objc.lookUpClass("NSNotificationCenter").defaultCenter()
        observer = _ActivationObserver.alloc().initWithWindow_(window)
        center.addObserver_selector_name_object_(
            observer, "onActive:", "NSApplicationDidBecomeActiveNotification", None
        )
        # 防 GC：挂到主窗口上（生命周期 = app 生命周期）
        window._activation_observer = observer
        return True
    except Exception:
        return False
