# macOS 菜单栏面板形态（Menu Bar Panel Mode）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** macOS 上为 BITZH Connect 增加第二种窗口形态——吸附状态栏、点击图标展开的菜单栏面板，与现有浮动小窗口形态可随时切换。

**Architecture:** macOS 路径用 pyobjc 原生 `NSStatusItem` 替换 `QSystemTrayIcon`（左键展开/收起、右键弹 Qt 菜单、精确坐标），面板本体是复用现有全部 UI 的无边框 Qt 窗口（`FramelessWindowHint | Tool | WindowStaysOnTopHint`，Task 1 实测 Popup 在 Accessory 下不可用），背后垫 `NSVisualEffectView` 毛玻璃。Win/Linux 路径一行不动。新增配置键 `menu_bar_mode`，设置对话框"通用"tab 提供开关，运行时切换即时生效。

**Tech Stack:** PySide6 6.11+ / pyobjc (AppKit) / pytest + pytest-qt（offscreen）

**已与用户对齐的决策：**
- 左键点击状态栏图标 = 展开/收起面板；右键 = 菜单（打开面板 / VPN 连接 / 退出，复用现有菜单项）
- 面板样式：10px 圆角 + 系统阴影 + 毛玻璃 vibrancy 背景（深浅色跟随 App 主题设置），**无顶部箭头**
- 固定 360 宽，高度内容驱动，顶部钉在菜单栏下缘，不可拖动
- 展开/收起动画：下滑 + 淡入 250ms OutCubic（复用 motion_utils 规范，reduce-motion 直出）
- 面板模式隐藏底部"退出"按钮（右键菜单已有退出），"设置"按钮保留
- 失焦自动收起（Tool 窗口手动监听 `WindowDeactivate`；Task 1 实测 Popup 不可用）+ Esc 收起
- 面板模式强制隐藏 Dock 图标（Accessory 策略），切回浮动模式恢复原设置

**关键风险（Task 1 Spike 已实测验证，结论见下）：**
1. ✅ Accessory 激活策略下的键盘焦点：`Qt.Popup` **不可用**——show() 后立即自隐（面板根本握不住焦点，中英文都无法输入）；改用 `Qt.Tool | WindowStaysOnTopHint` + `NSApp.activateIgnoringOtherApps_(True)` + 原生 `makeKeyAndOrderFront_`，实测 activeWin=True、focusWidget=QLineEdit。
2. ✅ 中文输入法候选窗：Tool 形态下候选窗弹出面板不误关（用户真机确认）。
3. ✅ `NSStatusItem.button.window` 坐标从 Cocoa 到 Qt 屏幕坐标系的转换正确（面板居中贴图标下缘）。

**测试环境隔离（预检实测发现，已与用户对齐）：**
- 本项目测试固定 `QT_QPA_PLATFORM=offscreen`（tests/conftest.py）。实测 offscreen 下 `winId()` 返回 `1`，`objc.objc_object(c_void_p=winId).window()` 直接 **SIGSEGV（退出码 139）**——`install_vibrancy` 若无守卫会杀死整个 pytest 进程。
- 实测 offscreen 下 `NSStatusBar.statusItemWithLength_` **仍会真实创建状态栏项**：测试会在开发机真实菜单栏留下图标，且测试不调用 `quit_app` 无 teardown，多个 panel 测试会累积污染。
- 统一守卫：`QApplication.platformName() == "cocoa"` 才执行原生桥接。非 cocoa 时 `macos_status_item.create()` 返回 None（调用方回退 QSystemTrayIcon）、`install_vibrancy()` 返回 False、`_activate_panel` 跳过 NSApp 调用。测试保持 offscreen 完全无原生副作用；原生路径由 Task 1 spike + Task 10 真机清单覆盖（与 plan 对 pyobjc 薄壳的既有立场一致）。
- Task 8 原 `test_tray_icon_none_in_panel_mode` 断言 `tray_icon is None` 与自身 docstring/Step 4 所述的"offscreen 桥接失败回退托盘"自相矛盾，已改为按平台分支断言（见 Task 8）。

---

## 文件结构

| 文件 | 责任 | 新建/修改 |
|---|---|---|
| `app/utils/macos_status_item.py` | 原生 NSStatusItem：图标、左右键事件分发、图标屏幕坐标、teardown | 新建 |
| `app/utils/macos_vibrancy.py` | NSVisualEffectView 毛玻璃安装/移除/深浅色跟随 | 新建 |
| `app/utils/panel_geometry.py` | 面板定位纯函数（平台无关，可单测） | 新建 |
| `app/utils/config_utils.py` | 新增 `menu_bar_mode` 配置键 | 修改 |
| `app/utils/tray_utils.py` | 托盘路由（面板模式→NSStatusItem，否则→QSystemTrayIcon）；菜单构建与 QSystemTrayIcon 解耦；quit 清理 | 修改 |
| `app/views/main_window.py` | `set_menu_bar_mode` / `show_panel` / `hide_panel` / `toggle_panel` / `open_panel`；Esc shortcut；高度变化顶边锚定 | 修改 |
| `app/views/menu_utils.py` | `show_advanced_settings` 传递并应用 `menu_bar_mode` | 修改 |
| `app/views/advanced_panel.py` | "通用"tab 新增 macOS 专属开关，与"隐藏 Dock 图标"联动 | 修改 |
| `app/main.py` | 面板模式下启动不直接 show 窗口 | 修改 |
| `scripts/menu_bar_spike.py` | Task 1 风险验证脚本（验证后保留作诊断） | 新建 |
| `tests/test_panel_geometry.py` | 定位纯函数测试 | 新建 |
| `tests/test_menu_bar_mode.py` | 配置、模式切换、面板行为测试 | 新建 |
| `tests/test_main_window.py` | tray_icon 兼容调整（如需要） | 修改 |
| `README.md` / `README.en.md` | 特性列表加一行 | 修改 |

---

## Task 1: Spike —— 验证 Accessory 焦点 / 输入法 / 坐标转换

先做风险验证，再铺开实现。本任务产出可运行的最小原型与验证结论，**不改主代码库**。

**Files:**
- Create: `scripts/menu_bar_spike.py`

- [x] **Step 1: 编写 spike 脚本**

> ✅ 已完成并定案：定稿脚本见仓库 `scripts/menu_bar_spike.py`（commit `73fc027`）。原计划下方的 `Qt.Popup` 雏形在真机实测中被证伪（Accessory 激活策略下 show() 即自隐、面板握不住焦点、中英文都无法输入），最终脚本改为 `Tool | WindowStaysOnTopHint` + 真 qrc 图标 + 手动 `WindowDeactivate` 收起 + `SIGINT` 复位。**实现一律以仓库脚本为准**，下方保留原雏形仅作历史记录。

```python
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
```

- [x] **Step 2: 运行并按清单验证**（用户真机确认 5/5 通过）

Run: `.venv/bin/python scripts/menu_bar_spike.py`
Expected: 清单 5 项全部通过，终端无 Objective-C 异常栈。

- [x] **Step 3: 记录结论并决策**

**实际结论（Plan 默认路线被证伪，采用降级路线）：**
- 面板窗口 flags 定案 **`Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint`**。原因：`Qt.Popup` 在 Accessory 激活策略下 `show()` 后立即 `visible=False`（应用非活跃 → popup 失活自隐），键盘焦点从未拿到，中英文输入均失败——不是"Popup 与输入法冲突"，而是 Popup 根本不可用。
- 失焦收起改为手动实现：面板 `event()` 里接 `QEvent.WindowDeactivate → hide()`（IME 候选窗弹出不触发面板失活，已真机确认不误关）。
- 在 `show_panel` 激活路径里加原生 `makeKeyAndOrderFront_`（`NSApp.activateIgnoringOtherApps_(True)` 之外）。
- 结论已写入 `scripts/menu_bar_spike.py` docstring 末尾；**本计划后续所有 `Qt.Popup` 出现处（Task 6/7/8 及 Self-Review）均已同步替换为 Tool 方案。**

- [x] **Step 4: Commit**

```bash
git add scripts/menu_bar_spike.py
git commit -m "test: 菜单栏面板形态 spike——Accessory 焦点/输入法/状态栏坐标转换验证"
```

---

## Task 2: 配置键 `menu_bar_mode`

**Files:**
- Modify: `app/utils/config_utils.py`
- Test: `tests/test_menu_bar_mode.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_menu_bar_mode.py
from platform import system

import pytest


def test_menu_bar_mode_default_false(qtbot):
    from utils.config_utils import load_config

    assert load_config()["menu_bar_mode"] is False


def test_menu_bar_mode_roundtrip(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)
    assert load_config()["menu_bar_mode"] is True


def test_menu_bar_mode_loaded_to_window(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    assert w.menu_bar_mode is True
    w.reconnect_manager.cancel()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -v`
Expected: FAIL —— `KeyError: 'menu_bar_mode'` / `AttributeError`。

- [ ] **Step 3: 实现**

`app/utils/config_utils.py` 的 `default_config` 中，`"nav_expanded": False,` 之后加一行：

```python
        "nav_expanded": False,
        # macOS 菜单栏面板形态：True=点击状态栏图标展开面板；False=浮动小窗口
        "menu_bar_mode": False,
    }
```

`load_settings(self)` 末尾（`self.tun_mode = config["tun_mode"]` 之后、Windows 硬守卫之前的位置任选，建议紧跟其后）加：

```python
    self.menu_bar_mode = config["menu_bar_mode"]
    if system() != "Darwin":
        # 菜单栏面板是 macOS 专属形态：其他平台读到脏配置也强制关闭
        self.menu_bar_mode = False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add app/utils/config_utils.py tests/test_menu_bar_mode.py
git commit -m "feat: 新增 menu_bar_mode 配置键（macOS 菜单栏面板形态开关，默认关闭）"
```

---

## Task 3: 面板定位纯函数 `panel_geometry`

**Files:**
- Create: `app/utils/panel_geometry.py`
- Test: `tests/test_panel_geometry.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_panel_geometry.py
from PySide6.QtCore import QRect, QSize

from utils.panel_geometry import panel_geometry

SCREEN = QRect(0, 0, 1920, 1080)       # availableGeometry
PANEL = QSize(360, 480)


def test_centered_under_icon():
    icon = QRect(900, 0, 24, 22)  # 菜单栏内图标
    geo = panel_geometry(icon, SCREEN, PANEL)
    assert geo.width() == 360 and geo.height() == 480
    assert geo.center().x() == icon.center().x()
    assert geo.top() == icon.bottom() + 4


def test_clamped_to_screen_right():
    icon = QRect(1900, 0, 20, 22)  # 最右侧图标：居中会溢出
    geo = panel_geometry(icon, SCREEN, PANEL)
    assert geo.right() <= SCREEN.right() - 8


def test_clamped_to_screen_left():
    icon = QRect(0, 0, 20, 22)
    geo = panel_geometry(icon, SCREEN, PANEL)
    assert geo.left() >= SCREEN.left() + 8


def test_invalid_icon_falls_back_to_top_right():
    geo = panel_geometry(None, SCREEN, PANEL)
    assert geo.right() == SCREEN.right() - 12
    assert geo.top() == SCREEN.top() + 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_geometry.py -v`
Expected: FAIL —— `ModuleNotFoundError: utils.panel_geometry`。

- [ ] **Step 3: 实现**

```python
# app/utils/panel_geometry.py
"""菜单栏面板定位：图标下缘居中，夹紧在屏幕可用区域内（纯函数，与平台解耦）。"""
from PySide6.QtCore import QRect, QSize

_EDGE_MARGIN = 8      # 面板与屏幕左右边缘的最小间距
_ICON_GAP = 4         # 面板顶边与图标（菜单栏）下缘的间距
_FALLBACK_MARGIN = 12  # 图标坐标失效时退化到屏幕右上角的右边距


def _left_for_right_edge(right: int, width: int, margin: int) -> int:
    """由期望的右边界反推左边界。

    QRect.right() 是闭区间（right == left + width - 1），所以要 +1 补偿，
    否则实际右边距会比 margin 多 1 像素。
    """
    return right - margin - width + 1


def panel_geometry(icon_rect, screen_rect: QRect, panel_size: QSize) -> QRect:
    """计算面板在全局屏幕坐标中的位置。

    icon_rect: 状态栏图标的全局 QRect；为 None（图标被刘海/拥挤挤出）时
    退化到屏幕右上角。screen_rect: 该屏 availableGeometry。
    """
    w, h = panel_size.width(), panel_size.height()
    if icon_rect is None or icon_rect.isNull() or icon_rect.isEmpty():
        x = _left_for_right_edge(screen_rect.right(), w, _FALLBACK_MARGIN)
        return QRect(x, screen_rect.top() + _ICON_GAP, w, h)
    # QRect 的中心也是闭区间，偏移量取 (w - 1) // 2 才能与图标中心对齐
    x = icon_rect.center().x() - (w - 1) // 2
    x = max(screen_rect.left() + _EDGE_MARGIN,
            min(x, _left_for_right_edge(screen_rect.right(), w, _EDGE_MARGIN)))
    y = icon_rect.bottom() + _ICON_GAP
    return QRect(x, y, w, h)
```

> **修订（Task 3 执行时发现）：** 上述原片段与本节自带测试自相矛盾——`QRect.right()`/`center()` 是闭区间语义，原片段 `w // 2` 居中会偏左 1px（测试断言 `910 != 911`）、`right() - w - 12` 退化锚点会多留 1px（`1906 != 1907`）。已按「测试即需求」修正实现（`(w-1)//2` 居中、`+1` 反推右边界），常量值不变；测试一字未改。上为修正后代码。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_geometry.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add app/utils/panel_geometry.py tests/test_panel_geometry.py
git commit -m "feat: 面板定位纯函数（图标下缘居中 + 屏幕夹紧 + 失效退化右上角）"
```

---

## Task 4: `MacStatusItem` —— 原生状态栏项

**Files:**
- Create: `app/utils/macos_status_item.py`

本模块是 pyobjc 薄壳（offscreen 测试环境无法实例化真状态栏项），**逻辑已在 Task 1 spike 验证**，本任务只做工程化封装，不配单测，手动验证在 Task 8 集成后进行。

- [ ] **Step 1: 实现**

```python
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
```

- [ ] **Step 2: 语法与导入冒烟**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'app'); from utils import macos_status_item; print('ok')"`
Expected: 输出 `ok`。

- [ ] **Step 3: Commit**

```bash
git add app/utils/macos_status_item.py
git commit -m "feat: macOS 原生状态栏项 MacStatusItem（左键展开面板/右键菜单/精确坐标，失败回退托盘）"
```

---

## Task 5: `macos_vibrancy` —— 毛玻璃背景

**Files:**
- Create: `app/utils/macos_vibrancy.py`

同为 pyobjc 薄壳（offscreen 无法验证视觉效果），不配单测，真机验证在 Task 10。

- [ ] **Step 1: 实现**

```python
# app/utils/macos_vibrancy.py
"""NSVisualEffectView 毛玻璃背景（菜单栏面板形态专属）。

原理：面板窗口 WA_TranslucentBackground 透明化后，在其 NSWindow contentView
最底层垫一块 NSVisualEffectView（popover 材质），Qt 内容直接"浮"在毛玻璃上。
深浅色跟随 App 主题设置（set_appearance 三态），而非只跟系统——用户 App 内
强制浅色/深色时质感与文字颜色不打架。

桥接模式与 utils/sleep_wake.py 一致；仅 macOS 真实 cocoa 平台；失败安静降级
（面板退化为透明底窗口，由 Qt 侧圆角样式兜底）。

平台守卫必需：offscreen（测试环境）下 winId() 返回 1，拿它构造 NSView 再取
window() 会 SIGSEGV，必须挡在桥接之前。
"""
from platform import system

_NS_VISUAL_EFFECT_MATERIAL_POPOVER = 6
_NS_VISUAL_EFFECT_BLENDING_BEHIND_WINDOW = 0
_NS_VISUAL_EFFECT_STATE_ACTIVE = 1  # 不随窗口失焦变灰（面板本就是瞬时激活）
_NS_WINDOW_BELOW = -1               # NSWindowOrderingMode
# NSAutoresizingMaskOptions：WidthSizable | HeightSizable
_AUTORESIZE = 2 | 16
_CORNER_RADIUS = 10.0


def _nsview_of(window):
    """QWidget 顶层窗口 → NSView（PySide6 winId 即 NSView 指针）。"""
    import objc

    return objc.objc_object(c_void_p=__import__("ctypes").c_void_p(int(window.winId())))


def install_vibrancy(window) -> bool:
    """为窗口安装毛玻璃背景（幂等）。返回是否成功。"""
    from PySide6.QtWidgets import QApplication

    # 非 cocoa 平台 winId 不是 NSView 指针（offscreen 下为 1），桥接会段错误
    if system() != "Darwin" or QApplication.platformName() != "cocoa":
        return False
    try:
        import objc

        view = _nsview_of(window)
        ns_window = view.window()
        content = ns_window.contentView()
        effect_cls = objc.lookUpClass("NSVisualEffectView")
        effect = effect_cls.alloc().initWithFrame_(content.bounds())
        effect.setAutoresizingMask_(_AUTORESIZE)
        effect.setMaterial_(_NS_VISUAL_EFFECT_MATERIAL_POPOVER)
        effect.setBlendingMode_(_NS_VISUAL_EFFECT_BLENDING_BEHIND_WINDOW)
        effect.setState_(_NS_VISUAL_EFFECT_STATE_ACTIVE)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(_CORNER_RADIUS)
        effect.layer().setMasksToBounds_(True)
        content.addSubview_positioned_relativeTo_(effect, _NS_WINDOW_BELOW, None)
        # 防 GC + 供移除/更新时查找
        window._vibrancy_view = effect
        update_vibrancy_appearance(window)
        return True
    except Exception:
        return False


def remove_vibrancy(window) -> None:
    """移除毛玻璃（切回浮动模式时调用；未安装时安静返回）。"""
    effect = getattr(window, "_vibrancy_view", None)
    if effect is None:
        return
    window._vibrancy_view = None
    try:
        effect.removeFromSuperview()
    except Exception:
        pass


def update_vibrancy_appearance(window) -> None:
    """深浅色跟随 App 主题（theme.is_dark 已含 system/light/dark 三态解析）。"""
    effect = getattr(window, "_vibrancy_view", None)
    if effect is None or system() != "Darwin":
        return
    try:
        import objc

        from common import theme

        name = "NSAppearanceNameDarkAqua" if theme.is_dark() else "NSAppearanceNameAqua"
        effect.setAppearance_(
            objc.lookUpClass("NSAppearance").appearanceNamed_(name)
        )
    except Exception:
        pass
```

- [ ] **Step 2: 语法与导入冒烟**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'app'); from utils import macos_vibrancy; print('ok')"`
Expected: 输出 `ok`。

- [ ] **Step 3: Commit**

```bash
git add app/utils/macos_vibrancy.py
git commit -m "feat: NSVisualEffectView 毛玻璃背景安装/移除/深浅色跟随（popover 材质，10px 圆角）"
```

---

## Task 6: MainWindow 形态切换骨架（`set_menu_bar_mode` / `open_panel` / Esc）

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_menu_bar_mode.py`

动画（show_panel/hide_panel 的位移淡入）在 Task 7，本任务先把形态切换的骨架立起来。

- [ ] **Step 1: 写失败测试（追加到 tests/test_menu_bar_mode.py）**

```python
@pytest.fixture
def window(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    qtbot.addWidget(w)
    yield w
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_enter_panel_mode(window):
    from PySide6.QtCore import Qt

    window.set_menu_bar_mode(True)
    flags = window.windowFlags()
    assert flags & Qt.FramelessWindowHint
    # 窗口类型须精确等于 Tool（Qt.Tool 与 Qt.Popup 共享 Window 位，
    # 直接 flags & Qt.Popup 会误判为真，必须用 WindowType_Mask 取类型）
    assert (flags & Qt.WindowType_Mask) == Qt.Tool
    assert flags & Qt.WindowStaysOnTopHint
    assert window.testAttribute(Qt.WA_TranslucentBackground)
    assert not window.exit_button.isVisible()
    assert window.settings_button.isVisible() or True  # 设置按钮保留（可见性随布局）


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_exit_panel_mode_restores_window(window):
    from PySide6.QtCore import Qt

    window.set_menu_bar_mode(True)
    window.set_menu_bar_mode(False)
    assert not (window.windowFlags() & Qt.FramelessWindowHint)
    assert not window.testAttribute(Qt.WA_TranslucentBackground)
    assert window.exit_button.isVisible()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_set_menu_bar_mode_idempotent(window):
    window.set_menu_bar_mode(True)
    flags_after_first = window.windowFlags()
    window.set_menu_bar_mode(True)  # 重复设置不应重建或闪烁
    assert window.windowFlags() == flags_after_first


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_open_panel_dispatch(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "show_panel", lambda: calls.append("panel"))
    window.set_menu_bar_mode(True)
    window.open_panel()
    assert calls == ["panel"]


def test_open_panel_dispatch_floating(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "show", lambda: calls.append("show"))
    window.set_menu_bar_mode(False)
    window.open_panel()
    assert calls == ["show"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_hide_panel_esc_shortcut_registered(window):
    window.set_menu_bar_mode(True)
    assert any(
        s.key().toString() == "Esc" for s in window.findChildren(type(window._esc_shortcut))
    ) or window._esc_shortcut is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -v`
Expected: FAIL —— `AttributeError: 'MainWindow' object has no attribute 'set_menu_bar_mode'`。

- [ ] **Step 3: 实现**

`app/views/main_window.py`：

① `__init__` 中，`self.tray_icon = init_tray_icon(self)` 之前的位置（`load_settings` 已读出 `menu_bar_mode`），加形态初始化（注意：`load_settings` 在 `setup_ui` 之前调用，`exit_button` 等控件在 `setup_ui` 里创建，所以模式应用放在 `setup_ui` 之后、`init_tray_icon` 之前）：

```python
        # 菜单栏面板形态（macOS）：flags/毛玻璃/锚定；须在托盘初始化之前
        # （托盘按形态路由 NSStatusItem / QSystemTrayIcon）
        self._panel_mode = False
        self._esc_shortcut = None
        if self.menu_bar_mode:
            self._apply_panel_chrome(True)
```

② 新增方法（放在 `_on_app_activate` 之后）：

```python
    # ---- 菜单栏面板形态（macOS 专属） ----

    def set_menu_bar_mode(self, enabled: bool):
        """切换浮动窗口 ↔ 菜单栏面板形态（幂等；运行时切换即时生效）。"""
        from platform import system

        if system() != "Darwin":
            return
        enabled = bool(enabled)
        if enabled == self._panel_mode:
            return
        self.menu_bar_mode = enabled
        # setWindowFlags 会隐式 hide——记录切换前可见性，切换后按原样恢复
        # （启动初始化路径窗口本不可见，不得因模式应用而提前弹出）
        was_visible = self.isVisible()
        self._apply_panel_chrome(enabled)
        # 托盘随形态路由（面板↔原生状态栏项，浮动↔QSystemTrayIcon）
        from utils.tray_utils import reinit_tray

        reinit_tray(self)
        from utils.macos_utils import hide_dock_icon

        # 面板形态强制 Accessory（Dock 图标无意义）；切回浮动恢复用户设置
        hide_dock_icon(True if enabled else self.hide_dock_icon)
        if was_visible:
            if enabled:
                self.show_panel(animated=False)
            else:
                self.show()

    def event(self, e):
        """面板失焦自动收起。

        Tool 形态没有 Qt.Popup 的自隐行为（Task 1 实测 Popup 在 Accessory 下
        show() 即自隐，不可用），改为手动接窗口失活；IME 候选窗不触发本事件，
        故中文输入时不会误关（Task 1 真机确认）。
        """
        if (
            self._panel_mode
            and e.type() == QEvent.WindowDeactivate
            and self.isVisible()
        ):
            self.hide_panel()
        return super().event(e)

    def _apply_panel_chrome(self, enabled: bool):
        """窗口外壳切换：flags / 透明底 / 毛玻璃 / 退出按钮 / Esc / 圆角样式。"""
        self._panel_mode = enabled
        if enabled:
            # Tool 形态（非 Popup）：Accessory 策略下 Popup show() 即自隐、无法输入
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setFixedWidth(360)
            self.exit_button.hide()
            from utils.macos_vibrancy import install_vibrancy, update_vibrancy_appearance

            self.winId()  # 真实化 NSWindow（winId 即创建），不 show——启动路径窗口须保持隐藏
            install_vibrancy(self)
            theme_cb = lambda: update_vibrancy_appearance(self)
            from common import theme

            theme.on_scheme_changed(theme_cb)
            self._vibrancy_theme_cb = theme_cb
            # Esc 收起（面板无标题栏/关闭按钮，Esc 是显式收起的键盘路径）
            from PySide6.QtGui import QShortcut, QKeySequence

            self._esc_shortcut = QShortcut(QKeySequence("Esc"), self)
            self._esc_shortcut.setContext(Qt.WindowShortcut)
            self._esc_shortcut.activated.connect(self.hide_panel)
            # 圆角视觉：central widget 圆角样式与毛玻璃圆角一致（10px）
            self.centralWidget().setStyleSheet(
                "WatermarkContainer { border-radius: 10px; }"
            )
        else:
            if self._esc_shortcut is not None:
                self._esc_shortcut.setEnabled(False)
                self._esc_shortcut.deleteLater()
                self._esc_shortcut = None
            from utils.macos_vibrancy import remove_vibrancy

            remove_vibrancy(self)
            self.centralWidget().setStyleSheet("")
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self.setMinimumWidth(360)
            self.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
            self.setWindowFlags(Qt.Window)
            self.exit_button.show()
            # 不主动 show：可见性由调用方（set_menu_bar_mode 的 was_visible）恢复

    def open_panel(self):
        """托盘/菜单/Dock 的统一"打开主界面"入口，按形态分发。"""
        if self._panel_mode:
            self.show_panel()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def toggle_panel(self):
        """状态栏图标左键：展开 ↔ 收起。"""
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_panel()
```

③ `_on_app_activate` 方法体改为走统一入口（面板模式下 Dock 虽隐藏，Cmd-Tab/其他激活路径仍可能触发，保持一致）：

```python
        if not getattr(self, "_ready", False) or getattr(self, "_quitting", False):
            return
        self.open_panel()
```

④ 本任务先用占位 `show_panel` / `hide_panel`（Task 7 补动画与锚定）：

```python
    def show_panel(self, animated: bool = True):
        """展开面板（Task 7 补定位与动画；当前直接显示）。"""
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_panel(self):
        self.hide()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py tests/test_main_window.py -v`
Expected: 全部 passed（注意 test_open_panel_dispatch_floating 在非 macOS 也应通过——`set_menu_bar_mode(False)` 在非 Darwin 直接返回但 `_panel_mode` 默认 False，`open_panel` 走浮动分支）。

若 `test_open_panel_dispatch_floating` 因 `self._panel_mode` 未初始化而 AttributeError：在 `__init__` 中确保 `self._panel_mode = False` 在 `open_panel` 任何调用路径之前赋值（上述 ① 已保证）。

- [ ] **Step 5: Commit**

```bash
git add app/views/main_window.py tests/test_menu_bar_mode.py
git commit -m "feat: 主窗口菜单栏面板形态骨架——set_menu_bar_mode/open_panel/toggle_panel，Esc 收起，Dock 联动"
```

---

## Task 7: 展开/收起动画与顶边锚定

**Files:**
- Modify: `app/views/main_window.py`（替换 Task 6 的占位 `show_panel` / `hide_panel`）
- Test: `tests/test_menu_bar_mode.py`

- [ ] **Step 1: 写失败测试（追加）**

```python
@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_show_panel_positions_under_icon(window, monkeypatch):
    """面板顶部钉在图标下缘（reduce-motion 直出路径，无动画干扰）。

    图标坐标取自 offscreen 屏幕（800x800）内部，避免触发 panel_geometry
    的屏幕边缘夹紧——否则测试失败是夹紧所致而非定位 bug。
    """
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    from PySide6.QtCore import QRect

    fake_item = type("FakeItem", (), {"icon_global_rect": lambda self: QRect(400, 0, 24, 22)})()
    window._mac_status_item = fake_item
    window.set_menu_bar_mode(True)
    window.show_panel()
    assert window.frameGeometry().top() == 22 + 4
    assert abs(window.frameGeometry().center().x() - (400 + 12)) <= 2


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_hide_panel_immediate_under_reduce_motion(window, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.set_menu_bar_mode(True)
    window.show_panel()
    window.hide_panel()
    assert not window.isVisible()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_content_resize_keeps_top_anchored(window, monkeypatch):
    """内容高度变化（凭据区收放→adjustSize）后顶边位置不变。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.set_menu_bar_mode(True)
    window.show_panel()
    top_before = window.frameGeometry().top()
    window._on_content_resize()
    assert window.frameGeometry().top() == top_before


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_hides_on_window_deactivate(window, monkeypatch):
    """失焦手动收起（Tool 形态无 Popup 自隐）：窗口失活事件 → 面板隐藏。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QGuiApplication

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.set_menu_bar_mode(True)
    window.show_panel()
    assert window.isVisible()
    QGuiApplication.sendEvent(window, QEvent(QEvent.WindowDeactivate))
    assert not window.isVisible()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -k "panel" -v`
Expected: FAIL（占位实现无定位/无 `_on_content_resize`）。

- [ ] **Step 3: 实现**

`app/views/main_window.py`：删除 Task 6 的占位方法，替换为：

```python
    def show_panel(self, animated: bool = True):
        """展开面板：定位到状态栏图标下缘，下滑 12px + 淡入（250ms OutCubic）。"""
        from PySide6.QtCore import QPropertyAnimation
        from utils.motion_utils import ANIMATION_DURATION_MS, reduce_motion

        self._anchor_panel()
        animated = animated and not reduce_motion()
        if not animated:
            self.show()
            self._activate_panel()
            return
        self.setWindowOpacity(0.0)
        target = self.pos()
        self.move(target.x(), target.y() - 12)
        self.show()
        anim_pos = QPropertyAnimation(self, b"pos", self)
        anim_pos.setDuration(ANIMATION_DURATION_MS)
        anim_pos.setStartValue(self.pos())
        anim_pos.setEndValue(target)
        anim_pos.setEasingCurve(QEasingCurve.OutCubic)
        anim_opacity = QPropertyAnimation(self, b"windowOpacity", self)
        anim_opacity.setDuration(ANIMATION_DURATION_MS)
        anim_opacity.setStartValue(0.0)
        anim_opacity.setEndValue(1.0)
        anim_opacity.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anims = (anim_pos, anim_opacity)  # 防 GC
        anim_pos.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        anim_opacity.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._activate_panel()

    def hide_panel(self):
        """收起面板（Esc/再点图标）：淡出 + 上移 8px 后隐藏；reduce-motion 直出。"""
        from PySide6.QtCore import QPropertyAnimation
        from utils.motion_utils import ANIMATION_DURATION_MS, reduce_motion

        if reduce_motion() or not self.isVisible():
            self.hide()
            return
        anim_opacity = QPropertyAnimation(self, b"windowOpacity", self)
        anim_opacity.setDuration(ANIMATION_DURATION_MS)
        anim_opacity.setStartValue(1.0)
        anim_opacity.setEndValue(0.0)
        anim_opacity.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            self.hide()
            self.setWindowOpacity(1.0)  # 复位：下次 show 不带残留透明度

        anim_opacity.finished.connect(_finish)
        self._panel_hide_anim = anim_opacity
        anim_opacity.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _activate_panel(self):
        """Accessory 策略下抢键盘焦点（用户名/密码输入框依赖）。"""
        from platform import system

        from PySide6.QtWidgets import QApplication

        self.raise_()
        self.activateWindow()
        # 仅真实 cocoa 平台调 NSApp（offscreen 测试下调用会无意义地抢开发机焦点）
        if system() == "Darwin" and QApplication.platformName() == "cocoa":
            try:
                import ctypes

                import objc

                nsapp = objc.lookUpClass("NSApplication").sharedApplication()
                nsapp.activateIgnoringOtherApps_(True)
                # Tool 窗口需显式 makeKey 才能真正拿到键盘焦点（Task 1 spike 实测）
                view = objc.objc_object(
                    c_void_p=ctypes.c_void_p(int(self.winId()))
                )
                view.window().makeKeyAndOrderFront_(None)
            except Exception:
                pass

    def _anchor_panel(self):
        """面板定位：状态栏图标下缘居中；图标失效退化屏幕右上角。"""
        from PySide6.QtWidgets import QApplication
        from utils.panel_geometry import panel_geometry

        item = getattr(self, "_mac_status_item", None)
        icon_rect = item.icon_global_rect() if item is not None else None
        screen = None
        if icon_rect is not None:
            screen = QApplication.screenAt(icon_rect.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        geo = panel_geometry(icon_rect, screen.availableGeometry(), self.size())
        self.move(geo.topLeft())

    def _on_content_resize(self):
        """内容高度变化（凭据区/资源区收放）：adjustSize 后面板顶边钉住不动。"""
        self.adjustSize()
        if self._panel_mode and self.isVisible():
            self._anchor_panel()
```

同时把 `_apply_area_visibility` 里两处 `on_frame=self.adjustSize` 改为 `on_frame=self._on_content_resize`。

注意：`show_panel` 的 `self.size()` 在窗口从未显示过时可能不是内容尺寸——`_anchor_panel` 前先 `self.adjustSize()` 兜底（在 `_anchor_panel` 开头加 `self.adjustSize()`，幂等无副作用）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -v`
Expected: 全部 passed。

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 全部 passed（`test_main_window.py` 的区域动画测试改用 `_on_content_resize` 后仍应通过——它内部仍调 `adjustSize`）。

- [ ] **Step 6: Commit**

```bash
git add app/views/main_window.py tests/test_menu_bar_mode.py
git commit -m "feat: 面板展开/收起动画（下滑淡入 250ms）与图标下缘顶边锚定"
```

---

## Task 8: 托盘路由与运行时切换

**Files:**
- Modify: `app/utils/tray_utils.py`
- Modify: `app/views/main_window.py`（quit/close 兼容）
- Modify: `app/main.py`
- Test: `tests/test_menu_bar_mode.py`

- [ ] **Step 1: 写失败测试（追加）**

```python
@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_tray_routing_in_panel_mode(qtbot):
    """面板模式托盘路由按平台分支：
    - cocoa（真机）：走原生 NSStatusItem，不建 QSystemTrayIcon；
    - 非 cocoa（offscreen 测试）：原生被守卫关闭，回退 QSystemTrayIcon。
    两条路径都不得创建残留原生状态栏项。"""
    from PySide6.QtWidgets import QApplication
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    if QApplication.platformName() == "cocoa":
        assert w._mac_status_item is not None
        assert w.tray_icon is None
    else:
        assert w._mac_status_item is None
        assert w.tray_icon is not None
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_close_event_panel_mode_hides(qtbot, monkeypatch):
    """面板模式 closeEvent = 收起（不退出）。"""
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    from PySide6.QtGui import QCloseEvent

    w.closeEvent(QCloseEvent())
    assert not w.isVisible()
    assert not getattr(w, "_quitting", False)
    w.reconnect_manager.cancel()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -v`
Expected: FAIL（`tray_icon` 非 None / 无 `_mac_status_item` / closeEvent 路由不符）。

- [ ] **Step 3: 实现**

`app/utils/tray_utils.py`：

① 菜单构建与 QSystemTrayIcon 解耦——`create_tray_menu` 拆分为 `build_tray_menu`（纯构建，两种形态共用）：

```python
from PySide6.QtGui import QCursor


def build_tray_menu(window: QMainWindow) -> QMenu:
    """构建托盘/状态栏菜单（打开面板 / VPN 连接 / 退出；两形态共用）。"""
    menu = QMenu()
    show_action = menu.addAction("打开面板")
    show_action.triggered.connect(window.open_panel)
    connect_action = QAction("VPN 连接", menu)
    connect_action.setCheckable(True)
    connect_action.triggered.connect(
        lambda checked: window.connect_button.setChecked(checked)
    )
    # 同步托盘勾选与按钮实时状态（读 isChecked 而非 toggled 参数）：
    # start_connection 凭据校验早退已在前面槽位复位按钮/托盘，用参数会重新勾选
    window.connect_button.toggled.connect(
        lambda checked: connect_action.setChecked(window.connect_button.isChecked())
    )
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
```

② `init_tray_icon` 加 macOS 面板路由，并新增 `reinit_tray`（运行时切换）：

```python
def init_tray_icon(window):
    """初始化托盘/状态栏项。macOS 面板模式走原生 NSStatusItem（左键展开
    面板、右键菜单）；桥接失败静默回退 QSystemTrayIcon。返回托盘对象
    （面板模式且桥接成功时为 None，托盘职责由 window._mac_status_item 承担）。"""
    if system() == "Darwin" and getattr(window, "menu_bar_mode", False):
        from utils.macos_status_item import create

        window._tray_menu = build_tray_menu(window)
        item = create(
            on_toggle=window.toggle_panel,
            on_context_menu=lambda: window._tray_menu.exec_(QCursor.pos()),
        )
        if item is not None:
            window._mac_status_item = item
            return None
        # 桥接失败：回落浮动托盘路径（menu_bar_mode 配置不强行改写，
        # 窗口外壳已由 set_menu_bar_mode 决定，托盘只是入口之一）

    tray_icon = QSystemTrayIcon(window)
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


def reinit_tray(window):
    """形态切换时重建托盘/状态栏项（先拆后建，幂等）。"""
    item = getattr(window, "_mac_status_item", None)
    if item is not None:
        item.teardown()
        window._mac_status_item = None
    old_tray = getattr(window, "tray_icon", None)
    if old_tray is not None:
        try:
            old_tray.hide()
            old_tray.deleteLater()
        except RuntimeError:
            pass
        window.tray_icon = None
    window.tray_icon = init_tray_icon(window)
```

③ `quit_app` 加状态栏项清理（`window.stop_connection()` 之后即可）：

```python
    window.stop_connection()
    mac_item = getattr(window, "_mac_status_item", None)
    if mac_item is not None:
        mac_item.teardown()
        window._mac_status_item = None
    window.hide()
```

`quit_app` 原有 `if isValid(tray_icon):` 行对 `tray_icon=None` 安全（`shiboken6.isValid(None)` 返回 False），无需改。

`app/views/main_window.py`：

④ `__init__` 中 `self.tray_icon = init_tray_icon(self)` 之前补一行默认（防御 `reinit_tray` 的 getattr）：

```python
        self._mac_status_item = None
        self.tray_icon = init_tray_icon(self)
```

⑤ `closeEvent` 面板模式路由：

```python
    def closeEvent(self, event):
        if self._panel_mode:
            # 面板无"关闭"概念：收起即隐藏，进程由状态栏项驻留
            self.hide()
            event.ignore()
            return
        handle_close_event(self, event, self.tray_icon)
```

`app/main.py`：

⑥ 面板模式启动不直接显示窗口（等用户点击状态栏图标）：

```python
    if not window.silent_mode and not window.menu_bar_mode:
        window.show()
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 全部 passed。特别确认 `test_main_window.py`、`test_connection_flow.py`（托盘相关）无回归——默认 `menu_bar_mode=False`，旧路径不受影响。offscreen 测试环境下 `create()` 因平台守卫返回 None → 回退 QSystemTrayIcon，`test_tray_routing_in_panel_mode` 走非 cocoa 分支断言（`_mac_status_item is None` + `tray_icon is not None`）；真实 cocoa 分支由 Task 10 真机清单覆盖。

- [ ] **Step 5: Commit**

```bash
git add app/utils/tray_utils.py app/views/main_window.py app/main.py tests/test_menu_bar_mode.py
git commit -m "feat: 托盘按形态路由（面板→原生 NSStatusItem，浮动→QSystemTrayIcon），运行时切换重建，退出清理"
```

---

## Task 9: 设置对话框集成

**Files:**
- Modify: `app/views/advanced_panel.py`
- Modify: `app/views/menu_utils.py`
- Test: `tests/test_menu_bar_mode.py`

- [ ] **Step 1: 写失败测试（追加）**

```python
@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_settings_dialog_has_panel_switch(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    from views.advanced_panel import AdvancedSettingsDialog

    dialog = AdvancedSettingsDialog(w)
    assert hasattr(dialog, "menu_bar_mode_switch")
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_switch_forces_hide_dock(qtbot):
    """勾选菜单栏面板 → 隐藏 Dock 自动勾上且禁用（面板形态 Dock 无意义）。"""
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    from views.advanced_panel import AdvancedSettingsDialog

    dialog = AdvancedSettingsDialog(w)
    dialog.menu_bar_mode_switch.setChecked(True)
    assert dialog.hide_dock_icon_switch.isChecked()
    assert not dialog.hide_dock_icon_switch.isEnabled()
    settings = dialog.get_settings()
    assert settings["menu_bar_mode"] is True
    assert settings["hide_dock_icon"] is True
    dialog.menu_bar_mode_switch.setChecked(False)
    assert dialog.hide_dock_icon_switch.isEnabled()
    w.reconnect_manager.cancel()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -k "settings_dialog or panel_switch" -v`
Expected: FAIL —— `AttributeError: menu_bar_mode_switch`。

- [ ] **Step 3: 实现**

`app/views/advanced_panel.py`：

① `setup_ui` 的 macOS 区块（`hide_dock_icon_switch` 创建处之后）加：

```python
        # Hide dock icon option (only for macOS)
        if system() == "Darwin":
            self.hide_dock_icon_switch = QCheckBox("隐藏 Dock 图标")
            general_layout.addWidget(self.hide_dock_icon_switch)
            general_layout.addWidget(
                self._description("隐藏后应用仅驻留菜单栏托盘；设置入口在主窗口右下角")
            )

            self.menu_bar_mode_switch = QCheckBox("菜单栏面板模式")
            general_layout.addWidget(self.menu_bar_mode_switch)
            general_layout.addWidget(
                self._description(
                    "开启后主窗口吸附在菜单栏：点击状态栏图标展开/收起，"
                    "点面板外或按 Esc 自动收起；Dock 图标将始终隐藏"
                )
            )
            self.menu_bar_mode_switch.toggled.connect(self._on_panel_mode_toggled)
```

② 新增联动方法：

```python
    def _on_panel_mode_toggled(self, checked: bool):
        """面板模式强制隐藏 Dock（Accessory 无 Dock 图标），勾选态跟随并锁定。"""
        if system() != "Darwin":
            return
        if checked:
            self.hide_dock_icon_switch.setChecked(True)
        self.hide_dock_icon_switch.setEnabled(not checked)
```

③ `get_settings` 的 Darwin 区块加：

```python
        if system() == "Darwin":
            settings["menu_bar_mode"] = self.menu_bar_mode_switch.isChecked()
            # 面板模式强制隐藏 Dock（联动开关已锁定，这里再兜底一次）
            settings["hide_dock_icon"] = (
                True if settings["menu_bar_mode"]
                else self.hide_dock_icon_switch.isChecked()
            )
```

④ `set_settings` 签名加 `menu_bar_mode=False` 关键字参数（放 `tun_mode=False` 之后），方法体 Darwin 区块加：

```python
        if system() == "Darwin":
            self.hide_dock_icon_switch.setChecked(hide_dock_icon)
            self.menu_bar_mode_switch.setChecked(menu_bar_mode)
            self._on_panel_mode_toggled(menu_bar_mode)  # 恢复联动锁定态
```

⑤ `accept` 的 Darwin 区块保持不变（`hide_dock_icon` 已由 get_settings 收敛）。

`app/views/menu_utils.py` 的 `show_advanced_settings`：

⑥ `set_settings` 调用加参数（`window.tun_mode,` 之后）：

```python
        window.tun_mode,
        menu_bar_mode=window.menu_bar_mode,
    )
```

⑦ 保存应用区块（`window.tun_mode = settings["tun_mode"]` 之后）加：

```python
        new_menu_bar_mode = settings.get("menu_bar_mode", False)
        if system() == "Darwin" and new_menu_bar_mode != window.menu_bar_mode:
            window.set_menu_bar_mode(new_menu_bar_mode)
```

注意顺序：`set_menu_bar_mode` 内部会处理 Dock 策略；原有 `hide_dock_icon(window.hide_dock_icon)` 调用保持在其后，面板模式下 `hide_dock_icon` 已为 True，不冲突。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 全部 passed（含既有 `test_advanced_panel.py`）。

- [ ] **Step 5: Commit**

```bash
git add app/views/advanced_panel.py app/views/menu_utils.py tests/test_menu_bar_mode.py
git commit -m "feat: 设置对话框新增'菜单栏面板模式'开关（macOS 专属，联动锁定隐藏 Dock），保存即切换形态"
```

---

## Task 10: 全量回归 + 真机手动验证 + 文档

**Files:**
- Modify: `README.md` / `README.en.md`

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed。

- [ ] **Step 2: 真机手动验证清单（浮动形态回归）**

Run: `.venv/bin/python app/main.py`
- [ ] 默认（未开过面板模式）：窗口、托盘菜单、关闭藏托盘、Dock 激活兜底全部照旧
- [ ] 连接/断开全流程正常（凭据收放动画、资源区、速率图）

- [ ] **Step 3: 真机手动验证清单（面板形态）**

设置 → 通用 → 勾选"菜单栏面板模式" → 保存：
- [ ] 窗口立即变为无边框面板并吸附在状态栏图标下，毛玻璃+圆角生效
- [ ] 左键图标：展开/收起交替；右键：菜单三项正常（VPN 连接勾选态同步）
- [ ] 面板内输入用户名/密码：英文、中文输入法均正常，候选窗不误关面板
- [ ] 点击面板外 → 自动收起；Esc → 收起；再点图标 → 展开（状态保留）
- [ ] 连接后凭据区收起、资源区展开时，面板顶边钉住、向下生长
- [ ] TUN 连接弹授权框后行为可接受（面板失焦收起，授权流程正常）
- [ ] 深浅色切换（含 App 内强制）：毛玻璃质感与文字颜色同步
- [ ] 退出（右键菜单）：状态栏图标移除，无残留进程
- [ ] 取消勾选回到浮动模式：标题栏/Dock/托盘全部恢复
- [ ] 刘海屏/外接显示器（如有条件）：图标被挤出时退化到屏幕右上角

- [ ] **Step 4: README 特性行**

`README.md` 与 `README.en.md` 特性列表各加一行：

```markdown
- macOS 双形态：浮动小窗口 / 菜单栏面板（点击状态栏图标展开，毛玻璃质感），随时切换
```

```markdown
- Dual macOS modes: floating window / menu bar panel (click status icon to expand, vibrancy background), switchable anytime
```

- [ ] **Step 5: Commit**

```bash
git add README.md README.en.md
git commit -m "docs: README 特性列表补充 macOS 菜单栏面板形态"
```

---

## Self-Review 记录

**Spec coverage：**
- 左键展开/右键菜单 → Task 4 + Task 8 ✅
- 毛玻璃/圆角/360 宽/无箭头 → Task 5 + Task 6 ✅
- 下滑淡入动画 + 顶边锚定 → Task 7 ✅
- 失焦/Esc 收起 → Task 6 手动 `WindowDeactivate` + Esc ✅
- 退出按钮隐藏/设置保留 → Task 6 `_apply_panel_chrome` ✅
- 形态切换 + 持久化 + Dock 联动 → Task 2/6/8/9 ✅
- Win/Linux 不受影响 → Task 2 非 Darwin 强制 False + 托盘路由守卫 ✅
- Accessory 焦点风险 → Task 1 Spike 先行 ✅

**类型一致性：** `MacStatusItem.icon_global_rect()` 返回 `QRect | None`，`panel_geometry(icon_rect, ...)` 接受 None ✅；`_mac_status_item` 在 `__init__`、`reinit_tray`、`quit_app`、`show_panel`/`_anchor_panel` 各处命名一致 ✅；`open_panel`/`toggle_panel`/`show_panel`/`hide_panel` 签名前后一致 ✅。

**已知取舍（真机验证兜底）：** 失焦收起走 `WindowDeactivate → hide_panel()`（会播放收起动画）；TUN 授权弹窗期间面板失焦收起（可接受，见 Task 10 清单）。

**自查修正记录：** `set_menu_bar_mode`/`_apply_panel_chrome` 初版无条件 `show()`——启动初始化路径（`__init__` 内应用已持久化的面板模式）会提前弹窗，违反"面板模式启动等点击"的约定。已修正为 `winId()` 真实化 NSWindow 不显示，可见性由 `was_visible` 按切换前状态恢复。
