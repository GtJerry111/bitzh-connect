"""Qt ≤ 6.11.2 的 QSystemTrayIcon 在 macOS 27 上点击即崩的规避补丁。

根因（已对照 Qt 源码与二进制双重确认）：
- Qt 6.11.0 发布版 QCocoaSystemTrayIcon::emitActivated() 直接调用
  NSApp.currentEvent.clickCount，无事件类型守卫。
- macOS 27 起状态栏图标点击改由 gesture recognizer 驱动，点击期间
  currentEvent 是 SysDefined 事件（subtype=7）→ -[NSEvent clickCount]
  抛 NSInternalInconsistencyException → abort。
- 触发点两处：statusItemMenuBeganTracking:（带菜单时点图标，经
  NSMenuDidBeginTrackingNotification 观察者）与 statusItemClicked
  （无菜单时按钮 action 回调）。

上游 Qt 6.11 开发分支已修（qt_mac_isMouseEvent 守卫，注释明写
"NSControls are driven by gesture recognizers in macOS 27"），但截至
6.11.2 的所有发布版均未包含，升级依赖无法解决。

规避：把 QStatusItemDelegate 的两个激活回调 IMP 替换为 -[NSObject self]
（纯 getter，无副作用；v@:@ 调用方忽略返回值，调用约定兼容）。
代价：macOS 27 上 QSystemTrayIcon.activated 信号不再发出——本 App 仅用
DoubleClick 唤窗，而带菜单时点击本就弹菜单（macOS 平台行为），
DoubleClick 实际不可达，零损失；且与上游修复后的行为等价
（上游此时 emit activated(Unknown)，本 App 不消费该值）。

仅 macOS 27+（Darwin 27+）且真实 cocoa 平台生效；offscreen 测试环境、
低版本 macOS、未来 Qt 改名内部类（lookUpClass 失败）均安静跳过。
"""
import ctypes
from platform import system

_applied = False


def _darwin_major() -> int:
    import platform

    try:
        return int(platform.release().split(".")[0])
    except (ValueError, IndexError):
        return 0


def apply_tray_click_fix() -> bool:
    """替换 QStatusItemDelegate 的激活回调为无害实现。返回是否实际打上补丁。"""
    global _applied
    if _applied:
        return True
    if system() != "Darwin" or _darwin_major() < 27:
        return False
    from PySide6.QtWidgets import QApplication

    # offscreen（测试环境）未加载 libqcocoa，类不存在；也无崩溃路径
    if QApplication.instance() is None or QApplication.platformName() != "cocoa":
        return False
    try:
        libobjc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        libobjc.sel_registerName.restype = ctypes.c_void_p
        libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
        libobjc.objc_getClass.restype = ctypes.c_void_p
        libobjc.objc_getClass.argtypes = [ctypes.c_char_p]
        libobjc.class_getMethodImplementation.restype = ctypes.c_void_p
        libobjc.class_getMethodImplementation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        libobjc.class_replaceMethod.restype = ctypes.c_void_p
        libobjc.class_replaceMethod.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]

        cls = libobjc.objc_getClass(b"QStatusItemDelegate")
        nsobject = libobjc.objc_getClass(b"NSObject")
        if not cls or not nsobject:
            return False  # Qt 内部类改名/移除：跳过补丁（未来 Qt 可能已修复）
        noop_imp = libobjc.class_getMethodImplementation(
            nsobject, libobjc.sel_registerName(b"self")
        )
        for name in (b"statusItemMenuBeganTracking:", b"statusItemClicked"):
            libobjc.class_replaceMethod(
                cls, libobjc.sel_registerName(name), noop_imp, b"v@:@"
            )
        _applied = True
        return True
    except Exception:
        return False  # 补丁失败只是回到可崩状态，绝不能影响 App 启动
