# app/utils/macos_status_item.py
"""macOS 原生状态栏项（NSStatusItem）：左键展开/收起面板，右键弹 Qt 菜单。

为什么不用 QSystemTrayIcon：macOS 上给它设了 contextMenu 后，单击图标只会
弹菜单，收不到左键 activated 信号——"点击图标直接展开面板"做不到；
且 geometry() 在图标被刘海挤出时不可靠。pyobjc 直连 NSStatusItem 可精确
区分左右键，并经 button.window 拿到图标精确屏幕坐标。

桥接模式与 utils/sleep_wake.py 一致（NSObject target-action，防 GC 挂自身）。
仅 macOS 真实 cocoa 平台可用；非 cocoa（offscreen 测试）或任何一步失败
create() 返回 None，调用方回退 QSystemTrayIcon。
"""
from platform import system

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

# NSEventTypeRightMouseUp（pyobjc 实测：LeftMouseUp=2、RightMouseDown=3、RightMouseUp=4）
_NSEVENT_TYPE_RIGHT_MOUSE_UP = 4
# NSEventMaskFromType(t) = 1 << t：LeftMouseUp=2、RightMouseUp=4 → 4|16
_SEND_ACTION_MASK = (1 << 2) | (1 << 4)


class MacStatusItem:
    """NSStatusItem 封装。on_toggle: 左键回调；on_context_menu: 右键回调。"""

    def __init__(self, item, target):
        self._item = item      # NSStatusItem（retain）
        self._target = target  # NSObject target（防 GC）

    def icon_global_rect(self):
        """图标的 Qt 全局屏幕坐标（Cocoa y 轴向上 → Qt y 轴向下）；失效返回 None。"""
        try:
            btn = self._item.button()
            if btn is None or btn.window() is None:
                return None
            rect_w = btn.convertRect_toView_(btn.bounds(), None)
            rect_s = btn.window().convertRectToScreen_(rect_w)
            import objc

            primary_h = (
                objc.lookUpClass("NSScreen").screens().firstObject().frame().size.height
            )
            qt_y = primary_h - rect_s.origin.y - rect_s.size.height
            return QRect(
                int(rect_s.origin.x), int(qt_y),
                int(rect_s.size.width), int(rect_s.size.height),
            )
        except Exception:
            return None  # 图标被挤出菜单栏等场景：调用方退化定位

    def teardown(self):
        """从状态栏移除图标（退出/切回浮动模式时调用；可重入）。"""
        item, self._item = self._item, None
        if item is None:
            return
        import objc

        objc.lookUpClass("NSStatusBar").systemStatusBar().removeStatusItem_(item)


def _load_template_nsimage():
    """从 Qt 资源系统读托盘图标并转 NSImage 模板（随系统深浅色自动着色）。

    走 QImage→PNG buffer→NSData 桥：qrc 资源对 pyobjc 不可见，且打包后
    无文件系统路径依赖。图标素材与 QSystemTrayIcon 路径一致（menu-icon.png）。
    """
    import objc
    from Foundation import NSData
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    img = QImage(":/icons/menu-icon.png")
    if img.isNull():
        # qrc 未注册等异常：显式失败，避免走到 nil NSImage 靠 AttributeError 兜底
        raise RuntimeError("菜单栏图标素材加载失败（qrc 未注册？）")
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    if not img.save(buf, "PNG"):
        raise RuntimeError("菜单栏图标 PNG 编码失败")
    nsdata = NSData.dataWithBytes_length_(bytes(ba), len(ba))
    nsimage = objc.lookUpClass("NSImage").alloc().initWithData_(nsdata)
    nsimage.setTemplate_(True)
    nsimage.setSize_((18.0, 18.0))  # 44px 素材直接进菜单栏会过大；Task 1 spike 实测 18pt 合适
    return nsimage


def _native_available() -> bool:
    """仅真实 cocoa 平台可安全桥接 NSStatusItem。

    offscreen（测试环境，conftest 强制）下 NSStatusBar 仍能创建真实状态栏项，
    会在开发机真实菜单栏留下图标且无 teardown；必须守卫掉。
    """
    from PySide6.QtWidgets import QApplication

    # 无 QApplication 实例时 platformName() 返回 Qt 编译期默认平台（macOS 为 "cocoa"），
    # 而非 QT_QPA_PLATFORM 指定的 offscreen——此时若放行会在裸进程冒烟中触碰原生 AppKit。
    if QApplication.instance() is None:
        return False
    return QApplication.platformName() == "cocoa"


_TARGET_CLASS = None


def _target_class():
    """惰性缓存 ObjC target 类（全进程只定义一次）。

    pyobjc 不允许同名 ObjC 类二次定义（实测 pyobjc 12.1：
    `objc.error: _Target is overriding existing Objective-C class`）。若像初版那样
    把 class 定义在 create() 内，本进程第二次 create()（Task 8 reinit_tray 运行时
    切换形态）会抛错并被 except 吞成 None，状态栏项静默降级为托盘图标。
    惰性创建同时保证非 cocoa 平台不 import Foundation（守卫生效）。
    """
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        import objc
        from Foundation import NSObject

        class _Target(NSObject):
            def initWithCallbacks_(self, toggle, menu):
                self = self.init()
                if self is None:
                    return None
                self._toggle = toggle
                self._menu = menu
                return self

            # Python 名只有一个下划线，pyobjc 会推导成单参 selector `initWithCallbacks:`，
            # 与两参签名冲突（pyobjc 12.1 定义类时抛 BadPrototypeError）。显式声明
            # 双参 selector `initWithCallbacks:menu:`，保留 brief 的调用形式。
            initWithCallbacks_ = objc.selector(
                initWithCallbacks_,
                selector=b"initWithCallbacks:menu:",
                signature=b"@@:@@",
            )

            def onClick_(self, sender):
                nsapp = objc.lookUpClass("NSApplication").sharedApplication()
                if nsapp.currentEvent().type() == _NSEVENT_TYPE_RIGHT_MOUSE_UP:
                    self._menu()
                else:
                    self._toggle()

            onClick_ = objc.selector(onClick_, signature=b"v@:@")

        _TARGET_CLASS = _Target
    return _TARGET_CLASS


def create(on_toggle, on_context_menu):
    """创建状态栏项；非 macOS、非 cocoa 平台或任何桥接失败返回 None（调用方回退托盘）。"""
    if system() != "Darwin" or not _native_available():
        return None
    try:
        import objc

        target = _target_class().alloc().initWithCallbacks_(on_toggle, on_context_menu)
        item = (
            objc.lookUpClass("NSStatusBar")
            .systemStatusBar()
            .statusItemWithLength_(-1.0)  # NSSquareStatusItemLength
        )
        try:
            btn = item.button()
            btn.setImage_(_load_template_nsimage())
            btn.setTarget_(target)
            btn.setAction_("onClick:")
            btn.sendActionOn_(_SEND_ACTION_MASK)
        except Exception:
            # 素材/按钮桥接失败：撤掉已建的裸状态栏项，避免留下不可移除的空图标
            objc.lookUpClass("NSStatusBar").systemStatusBar().removeStatusItem_(item)
            return None
        return MacStatusItem(item, target)
    except Exception:
        return None
