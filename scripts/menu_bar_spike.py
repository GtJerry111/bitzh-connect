"""菜单栏面板形态 Spike：验证三个技术风险点（一次性脚本，验证后保留作诊断）。

用法（项目根目录）：.venv/bin/python scripts/menu_bar_spike.py

手动验证清单：
1. 状态栏出现模板图标，左键点击 → 面板展开/收起交替
2. 右键点击 → 终端打印 "right-click"
3. 面板展开后 QLineEdit 可输入英文；切换到中文输入法，候选窗弹出时面板不误关
4. 点击面板外任意处 → 面板自动关闭（Qt.Popup 自带行为）
5. 面板水平居中于状态栏图标、顶部贴菜单栏下缘（坐标转换正确）
"""
import sys

import objc
from Foundation import NSObject, NSData
from PySide6.QtCore import QRect, QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

NSApplicationActivationPolicyAccessory = 1
# pyobjc 实测枚举：LeftMouseUp=2、RightMouseDown=3、RightMouseUp=4
NSEventTypeRightMouseUp = 4
# NSEventMaskFromType: mask = 1 << type（LeftMouseUp=2 → 4, RightMouseUp=4 → 16）
EVENT_MASK = (1 << 2) | (1 << 4)


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
    """22x22 黑色方块模板图标（spike 不需要真图标）。"""
    img = QImage(22, 22, QImage.Format_ARGB32)
    img.fill(Qt.black)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    nsdata = NSData.dataWithBytes_length_(bytes(ba), len(ba))
    nsimage = objc.lookUpClass("NSImage").alloc().initWithData_(nsdata)
    nsimage.setTemplate_(True)
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
    objc.lookUpClass("NSApplication").sharedApplication().activateIgnoringOtherApps_(True)


app = QApplication(sys.argv)
objc.lookUpClass("NSApplication").sharedApplication().setActivationPolicy_(
    NSApplicationActivationPolicyAccessory
)

_panel = QWidget(None, Qt.FramelessWindowHint | Qt.Popup)
_panel.setFixedWidth(360)
_panel.setMinimumHeight(200)
layout = QVBoxLayout(_panel)
layout.addWidget(QLineEdit(placeholderText="输入测试（含中文输入法）"))

target = _Target.alloc().init()
bar = objc.lookUpClass("NSStatusBar").systemStatusBar()
_item = bar.statusItemWithLength_(-1.0)  # NSSquareStatusItemLength
_item.button().setImage_(_make_icon())
_item.button().setTarget_(target)
_item.button().setAction_("onClick:")
_item.button().sendActionOn_(EVENT_MASK)

sys.exit(app.exec())
