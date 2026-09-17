"""菜单栏面板形态 Spike：验证三个技术风险点（诊断脚本，保留备查）。

用法（项目根目录）：.venv/bin/python scripts/menu_bar_spike.py
退出：终端 Ctrl+C（已把 SIGINT 复位为默认行为，Cocoa runloop 不会吞掉它）

手动验证清单：
1. 状态栏出现 APP 图标（模板图，随深浅色着色），左键点击 → 面板展开/收起交替
2. 右键点击 → 终端打印 "right-click"
3. 面板展开后 QLineEdit 可输入英文；切换到中文输入法，候选窗弹出时面板不误关
4. 点击面板外任意处（含其他 App）→ 面板自动收起（手动失焦收起）
5. 面板水平居中于状态栏图标、顶部贴菜单栏下缘（坐标转换正确）

== Task 1 结论（2026-09-17 实测）==
- 窗口标志定案：Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint。
  实测 Qt.Popup 在 Accessory 激活策略下 show() 后立即 visible=False（应用非活跃/
  popup 失活即自隐），面板根本握不住键盘焦点，QLineEdit 无法输入（中英文皆然）；
  故原计划的 Popup 自带走失焦收起不可用，必须走 Tool 方案 + 手动失焦收起。
- Qt.Tool 下实测：activeWin=True、focusWidget=QLineEdit、hasFocus()=True。
- NSApp.activateIgnoringOtherApps_(True) + 原生 makeKeyAndOrderFront_ 组合可用。
- NSEvent 右键枚举实测 RightMouseUp=4（非 3）；sendActionOn mask (1<<2)|(1<<4)。
- 状态栏图标须用真素材（:/icons/menu-icon.png）；纯色占位图被模板渲染成实心块。
"""
import os
import signal
import sys
import ctypes

import objc
from Foundation import NSObject, NSData
from PySide6.QtCore import QRect, QBuffer, QByteArray, QIODevice, QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from common import resources  # noqa: F401,E402  导入即注册 qrc 资源

NSApplicationActivationPolicyAccessory = 1
# pyobjc 实测枚举：LeftMouseUp=2、RightMouseDown=3、RightMouseUp=4
NSEventTypeRightMouseUp = 4
# NSEventMaskFromType: mask = 1 << type（LeftMouseUp=2 → 4, RightMouseUp=4 → 16）
EVENT_MASK = (1 << 2) | (1 << 4)


class SpikePanel(QWidget):
    """无边框工具窗面板：Tool 形态 + 手动失焦收起（替代失效的 Qt.Popup）。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint,
        )
        self.setFixedWidth(360)
        self.setMinimumHeight(200)
        layout = QVBoxLayout(self)
        layout.addWidget(QLineEdit(placeholderText="输入测试（含中文输入法）"))

    def event(self, e):
        # Qt.Popup 的失焦自隐在 Accessory 下不成立，自己接窗口失活事件
        if e.type() == QEvent.WindowDeactivate:
            self.hide()
        return super().event(e)


class _Target(NSObject):
    def onClick_(self, sender):
        event = objc.lookUpClass("NSApplication").sharedApplication().currentEvent()
        if event.type() == NSEventTypeRightMouseUp:
            print("right-click")
        else:
            toggle_panel()

    onClick_ = objc.selector(onClick_, signature=b"v@:@")


_panel = None


def _make_icon():
    """从 qrc 读真图标转 NSImage 模板（与 QSystemTrayIcon 路径同素材）。"""
    img = QImage(":/icons/menu-icon.png")
    if img.isNull():
        print("WARN: :/icons/menu-icon.png 加载失败，退出", flush=True)
        sys.exit(1)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    nsdata = NSData.dataWithBytes_length_(bytes(ba), len(ba))
    nsimage = objc.lookUpClass("NSImage").alloc().initWithData_(nsdata)
    nsimage.setTemplate_(True)
    nsimage.setSize_((18.0, 18.0))  # 定制尺寸，避免 44px 素材在菜单栏过大
    return nsimage


def _icon_global_rect(item):
    """NSStatusItem 图标的 Qt 全局屏幕坐标（Cocoa y 轴向上 → Qt y 轴向下）。"""
    btn = item.button()
    if btn is None or btn.window() is None:
        return None
    rect_w = btn.convertRect_toView_(btn.bounds(), None)
    rect_s = btn.window().convertRectToScreen_(rect_w)
    primary_h = (
        objc.lookUpClass("NSScreen").screens().firstObject().frame().size.height
    )
    qt_y = primary_h - rect_s.origin.y - rect_s.size.height
    return QRect(
        int(rect_s.origin.x), int(qt_y),
        int(rect_s.size.width), int(rect_s.size.height),
    )


def toggle_panel():
    global _panel
    if _panel.isVisible():
        _panel.hide()
        return
    screen = QApplication.screenAt(_panel.pos()) or QApplication.primaryScreen()
    rect = _icon_global_rect(_item)
    if rect is not None:
        avail = screen.availableGeometry()
        x = rect.center().x() - _panel.width() // 2
        x = max(avail.left() + 8, min(x, avail.right() - _panel.width() - 8))
        y = rect.bottom() + 4
        _panel.move(x, y)
    _panel.show()
    _panel.raise_()
    _panel.activateWindow()
    # Accessory 策略下抢键盘焦点（本 spike 的核心验证点）
    nsapp = objc.lookUpClass("NSApplication").sharedApplication()
    nsapp.activateIgnoringOtherApps_(True)
    try:
        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(_panel.winId())))
        view.window().makeKeyAndOrderFront_(None)
    except Exception as e:  # 诊断输出，不影响后续手动验证
        print(f"makeKeyAndOrderFront failed: {type(e).__name__}: {e}")


# Ctrl+C 直接终止：Cocoa runloop 不把 SIGINT 交回 Python，默认处理器会“无响应”
signal.signal(signal.SIGINT, signal.SIG_DFL)

app = QApplication(sys.argv)
objc.lookUpClass("NSApplication").sharedApplication().setActivationPolicy_(
    NSApplicationActivationPolicyAccessory
)

_panel = SpikePanel()

target = _Target.alloc().init()
bar = objc.lookUpClass("NSStatusBar").systemStatusBar()
_item = bar.statusItemWithLength_(-1.0)  # NSSquareStatusItemLength
_item.button().setImage_(_make_icon())
_item.button().setTarget_(target)
_item.button().setAction_("onClick:")
_item.button().sendActionOn_(EVENT_MASK)

sys.exit(app.exec())
