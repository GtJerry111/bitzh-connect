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
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
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

    return QApplication.platformName() == "cocoa"


def create(on_toggle, on_context_menu):
    """创建状态栏项；非 macOS、非 cocoa 平台或任何桥接失败返回 None（调用方回退托盘）。"""
    if system() != "Darwin" or not _native_available():
        return None
    try:
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

            def onClick_(self, sender):
                nsapp = objc.lookUpClass("NSApplication").sharedApplication()
                if nsapp.currentEvent().type() == _NSEVENT_TYPE_RIGHT_MOUSE_UP:
                    self._menu()
                else:
                    self._toggle()

            onClick_ = objc.selector(onClick_, signature=b"v@:@")

        target = _Target.alloc().initWithCallbacks_(on_toggle, on_context_menu)
        item = (
            objc.lookUpClass("NSStatusBar")
            .systemStatusBar()
            .statusItemWithLength_(-1.0)  # NSSquareStatusItemLength
        )
        btn = item.button()
        btn.setImage_(_load_template_nsimage())
        btn.setTarget_(target)
        btn.setAction_("onClick:")
        btn.sendActionOn_(_SEND_ACTION_MASK)
        return MacStatusItem(item, target)
    except Exception:
        return None
