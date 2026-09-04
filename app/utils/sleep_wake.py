# app/utils/sleep_wake.py
"""macOS 休眠/唤醒监听（NSWorkspace 通知中心 → pyobjc 桥）。

为什么需要：TUN/代理内核在系统休眠期间不会被通知"网络已死"，唤醒后隧道常处于
假死状态；且休眠期间自动重连的退避计时器会延后到唤醒瞬间触发——在用户不在场时
弹授权框。策略：休眠时取消在途重连；唤醒时若处于"应连接"态则立即重连。

只在 macOS 启用（Linux 的 logind PrepareForSleep / Windows 的 WM_POWERBROADCAST
本期不做）。
"""
from platform import system


def install_sleep_wake_hooks(window) -> bool:
    """注册 NSWorkspace 休眠/唤醒通知，转发给 window._on_system_sleep/_wake。

    返回是否安装成功；非 macOS 或 pyobjc 不可用时安静跳过（功能缺失不致命）。
    """
    if system() != "Darwin":
        return False
    try:
        import objc
        from Foundation import NSObject

        class _Observer(NSObject):
            """通知转发器（target-action 经典模式，避免 block 桥接的不确定性）。"""

            def initWithWindow_(self, window):
                self = self.init()
                if self is None:
                    return None
                self._window = window  # 强引用主窗口（生命周期 = app 生命周期）
                return self

            def onSleep_(self, notification):
                self._window._on_system_sleep()

            onSleep_ = objc.selector(onSleep_, signature=b"v@:@")

            def onWake_(self, notification):
                self._window._on_system_wake()

            onWake_ = objc.selector(onWake_, signature=b"v@:@")

        center = objc.lookUpClass("NSWorkspace").sharedWorkspace().notificationCenter()
        observer = _Observer.alloc().initWithWindow_(window)
        center.addObserver_selector_name_object_(
            observer, "onSleep:", "NSWorkspaceWillSleepNotification", None
        )
        center.addObserver_selector_name_object_(
            observer, "onWake:", "NSWorkspaceDidWakeNotification", None
        )
        # 防 GC：observer 须挂在长生命周期对象上
        window._sleep_wake_observer = observer
        return True
    except Exception:
        return False
