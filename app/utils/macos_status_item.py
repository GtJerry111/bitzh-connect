# app/utils/macos_status_item.py
"""macOS 原生状态栏项（NSStatusItem）：左键展开/收起面板，右键弹原生 NSMenu。

为什么不用 QSystemTrayIcon：macOS 上给它设了 contextMenu 后，单击图标只会
弹菜单，收不到左键 activated 信号——"点击图标直接展开面板"做不到；
且 geometry() 在图标被刘海挤出时不可靠。pyobjc 直连 NSStatusItem 可精确
区分左右键，并经 button.window 拿到图标精确屏幕坐标。

右键菜单用**原生 NSMenu**（而非 Qt QMenu）：macOS 26+ 会由系统自动给原生
菜单套用液态玻璃质感，Qt 自绘菜单拿不到。菜单项由 menu_spec 声明式描述，
勾选态在弹出前从回调现取（原生菜单不像 Qt 那样自动联动）。

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

    def set_speed(self, up_text: str, down_text: str):
        """显示两行速率（上=上行、下=下行）。失败静默（不影响主流程）。"""
        try:
            self._item.button().setImage_(_speed_nsimage(up_text, down_text))
        except Exception:
            pass

    def restore_icon(self):
        """恢复为默认菜单栏图标。"""
        try:
            self._item.button().setImage_(_load_template_nsimage())
        except Exception:
            pass

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


def _speed_nsimage(up_text: str, down_text: str):
    """把两行速率文字渲染成模板 NSImage（上=上行、下=下行；无箭头）。

    模板图随菜单栏深浅色自动反色（黑↔白），无需按主题手动取色。
    """
    import objc
    from Foundation import NSData
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    fm = QFontMetrics(font)
    w = max(fm.horizontalAdvance(up_text), fm.horizontalAdvance(down_text)) + 2
    line_h = fm.height()
    h = line_h * 2
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32)  # @2x 保 Retina 清晰
    img.setDevicePixelRatio(2)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setFont(font)
    painter.setPen(QColor(0, 0, 0))
    painter.drawText(QRect(0, 0, w, line_h), Qt.AlignRight | Qt.AlignVCenter, up_text)
    painter.drawText(QRect(0, line_h, w, line_h), Qt.AlignRight | Qt.AlignVCenter, down_text)
    painter.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    nsdata = NSData.dataWithBytes_length_(bytes(ba), len(ba))
    nsi = objc.lookUpClass("NSImage").alloc().initWithData_(nsdata)
    nsi.setTemplate_(True)
    return nsi


def _menu_icon_nsimage():
    return _load_template_nsimage()


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
    把 class 定义在 create() 内，本进程第二次 create()（重建状态栏项）会抛错并被
    except 吞成 None，状态栏项静默降级为托盘图标。
    惰性创建同时保证非 cocoa 平台不 import Foundation（守卫生效）。
    """
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        import objc
        from Foundation import NSObject

        class _Target(NSObject):
            def initWithCallbacks_(self, toggle, menu_spec):
                self = self.init()
                if self is None:
                    return None
                self._toggle = toggle
                self._menu_spec = menu_spec  # 声明式菜单项列表
                self._menu = None
                self._item = None
                return self

            # Python 名只有一个下划线，pyobjc 会推导成单参 selector `initWithCallbacks:`，
            # 与两参签名冲突（pyobjc 12.1 定义类时抛 BadPrototypeError）。显式声明
            # 双参 selector `initWithCallbacks:menuSpec:`。
            initWithCallbacks_ = objc.selector(
                initWithCallbacks_,
                selector=b"initWithCallbacks:menuSpec:",
                signature=b"@@:@@",
            )

            def onClick_(self, sender):
                nsapp = objc.lookUpClass("NSApplication").sharedApplication()
                if nsapp.currentEvent().type() == _NSEVENT_TYPE_RIGHT_MOUSE_UP:
                    self._popup_menu()
                else:
                    self._toggle()

            onClick_ = objc.selector(onClick_, signature=b"v@:@")

            def onMenuItem_(self, sender):
                # 统一分发：靠 tag 回到 menu_spec 下标，避免为每项定义 selector
                entry = self._menu_spec[sender.tag()]
                action = entry.get("action")
                if action is not None:
                    action()

            onMenuItem_ = objc.selector(onMenuItem_, signature=b"v@:@")

            def _popup_menu(self):
                if self._menu is None:
                    return
                # 勾选态在弹出前现取（原生菜单不像 Qt 那样自动联动按钮状态）
                for entry in self._menu_spec:
                    is_checked = entry.get("is_checked")
                    menu_item = entry.get("_item")
                    if is_checked is not None and menu_item is not None:
                        try:
                            menu_item.setState_(1 if is_checked() else 0)
                        except Exception:
                            pass
                self._item.popUpStatusItemMenu_(self._menu)

        _TARGET_CLASS = _Target
    return _TARGET_CLASS


def _build_native_menu(target):
    """menu_spec → 原生 NSMenu（系统据此在 macOS 26+ 自动套用液态玻璃）。"""
    from AppKit import NSMenu, NSMenuItem

    menu = NSMenu.alloc().init()
    for idx, entry in enumerate(target._menu_spec):
        if entry.get("separator"):
            menu.addItem_(NSMenuItem.separatorItem())
            continue
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            entry["title"], b"onMenuItem:", b""
        )
        item.setTarget_(target)
        item.setTag_(idx)
        menu.addItem_(item)
        entry["_item"] = item  # 弹出前同步勾选态用
    return menu


def create(on_toggle, menu_spec):
    """创建状态栏项；非 macOS、非 cocoa 平台或任何桥接失败返回 None（调用方回退托盘）。

    menu_spec：右键菜单声明，元素为
    {"title": str, "action": callable, "is_checked": callable | None}
    或 {"separator": True}。
    """
    if system() != "Darwin" or not _native_available():
        return None
    try:
        import objc

        target = _target_class().alloc().initWithCallbacks_(on_toggle, menu_spec)
        item = (
            objc.lookUpClass("NSStatusBar")
            .systemStatusBar()
            .statusItemWithLength_(-1.0)  # NSVariableStatusItemLength（-1.0；勿改成 -2）
        )
        try:
            btn = item.button()
            btn.setImage_(_load_template_nsimage())
            btn.setTarget_(target)
            btn.setAction_("onClick:")
            btn.sendActionOn_(_SEND_ACTION_MASK)
            target._item = item
            target._menu = _build_native_menu(target)
        except Exception:
            # 素材/按钮/菜单桥接失败：撤掉已建的裸状态栏项，避免留下不可移除的空图标
            objc.lookUpClass("NSStatusBar").systemStatusBar().removeStatusItem_(item)
            return None
        return MacStatusItem(item, target)
    except Exception:
        return None
