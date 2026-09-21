"""行内原生 NSMenu 弹出（连接模式选择）：macOS 26+ 系统自动套液态玻璃。

一次性菜单：构建 → 指定屏幕坐标模态弹出 → 返回选中下标；取消返回 None。
非 cocoa 平台/桥接失败抛 RuntimeError（调用方退化为直接切换）。
target 类惰性缓存（与 macos_status_item 同款纪律：pyobjc 禁止同类二次定义）。
"""
from platform import system

_TARGET_CLASS = None


def _target_class():
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        import objc
        from Foundation import NSObject

        class _MenuTarget(NSObject):
            def init(self):
                self = super().init()
                self.selected = []
                return self

            def onPick_(self, sender):
                self.selected.append(sender.tag())

            onPick_ = objc.selector(onPick_, signature=b"v@:@")

        _TARGET_CLASS = _MenuTarget
    return _TARGET_CLASS


def popup_menu(items, checked_index: int, global_pos):
    """items: 标题列表；checked_index: 当前勾选下标；global_pos: Qt 全局坐标。

    返回选中下标；用户取消返回 None；非 cocoa/桥接失败抛 RuntimeError。
    """
    from PySide6.QtWidgets import QApplication

    if (
        system() != "Darwin"
        or QApplication.instance() is None
        or QApplication.platformName() != "cocoa"
    ):
        raise RuntimeError("原生菜单不可用（非 cocoa 平台）")
    import objc
    from AppKit import NSMenu, NSMenuItem

    target = _target_class().alloc().init()
    menu = NSMenu.alloc().init()
    for idx, title in enumerate(items):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, b"onPick:", b""
        )
        item.setTarget_(target)
        item.setTag_(idx)
        item.setState_(1 if idx == checked_index else 0)
        menu.addItem_(item)
    # Qt 全局坐标（y 向下）→ Cocoa 屏幕坐标（y 向上）
    primary_h = (
        objc.lookUpClass("NSScreen").screens().firstObject().frame().size.height
    )
    menu.popUpMenuPositioningItem_atLocation_inView_(
        None, (global_pos.x(), primary_h - global_pos.y()), None
    )
    return target.selected[0] if target.selected else None
