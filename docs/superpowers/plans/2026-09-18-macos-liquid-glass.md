# macOS 液态玻璃（Liquid Glass）面板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** macOS 26+ 的菜单栏面板从 NSVisualEffectView 毛玻璃升级为 NSGlassEffectView 液态玻璃（原生折射+边缘高光），并打磨面板动效与按压反馈；macOS 15 及以下、非 macOS 平台零改动。

**Architecture:** 新增 `macos_glass.py` pyobjc 薄壳（与 `macos_vibrancy.py` 同构：垫层置于 contentView 父视图、contentView 之下），`glass_available()` 用 `lookUpClass("NSGlassEffectView")` 特性检测自动路由：可用→玻璃，不可用→现有毛玻璃（现状保留）。动效：面板展开 220ms 下滑 8px + 淡入、收起 160ms 淡出（"慢开快收"）；连接按钮与模式切换引入按压下沉反馈。Spike 先行真机验证，再进主代码。

**Tech Stack:** PySide6 6.11+ / pyobjc (AppKit NSGlassEffectView) / pytest + pytest-qt（offscreen）

**已与用户对齐的决策（grilling 定稿）：**
- 范围：**只做菜单栏面板形态**；浮动窗口不动（带标题栏的常规窗口玻璃化会割裂，二期再说）
- 版本路由：特性检测自动路由，**不加新设置项**；macOS ≤ 15 保留现有毛玻璃
- 深浅色：跟随 **App 内主题设置**（复用 `theme.on_scheme_changed` + `setAppearance_`，与 vibrancy 一致）
- tintColor：**无色**（纯净玻璃，Apple 原生观感；品牌识别靠水印 + 连接按钮绿）
- 可读性：信任 `regular` 档自带的背景分离度，**不加 scrim**；spike 真机验证（花壁纸/纯深/纯浅）
- 动效 A：展开下滑 12px→8px、250ms→220ms；收起 160ms（比展开快，收起要利落）
- 动效 B：按压下沉反馈只给**连接按钮 + 模式切换**（克制，不一律全加）
- HIG 约束：玻璃只用于浮层、圆角连续（10px 与现状一致）、文字对比度真机验证
- Spike 验收 8 条清单（见 Task 1），真机肉验通过才进主代码

**关键先例（本项目已踩过的坑，直接复用结论）：**
- z-order：Qt 顶层窗口 contentView **就是** QNSView，垫层必须加到其**父视图**（NSThemeFrame）并用 `NSWindowBelow` 置于 contentView 之下；加成 subview 会盖住全部 Qt 内容（`a4e6f1d` 真机实测）
- 平台守卫：offscreen 下 `winId()` 返回 1，桥接会 SIGSEGV；无 QApplication 实例时 `platformName()` 恒返回 cocoa——守卫必须查实例存在 + cocoa
- pyobjc 薄壳不配真机单测（offscreen 无法实例化原生视图），真机清单兜底——与 vibrancy 同立场

---

## 文件结构

| 文件 | 责任 | 新建/修改 |
|---|---|---|
| `scripts/glass_spike.py` | Task 1 真机验证脚本（regular/clear 对比、深浅色、水印、可读性） | 新建 |
| `app/utils/macos_glass.py` | NSGlassEffectView 桥接：检测/安装/移除/深浅色跟随 | 新建 |
| `app/views/main_window.py` | `_apply_panel_chrome` 按可用性路由玻璃/毛玻璃；动效 A；连接按钮按压 | 修改 |
| `app/views/mode_switch.py` | 模式切换按压下沉（自绘控件 paintEvent 整体下移 1px） | 修改 |
| `tests/test_menu_bar_mode.py` | 玻璃路由测试 + 动效 A 参数测试 | 修改 |
| `tests/test_mode_switch.py` | 按压状态机测试 | 新建 |
| `tests/test_main_window.py` | 连接按钮按压 QSS 断言 | 修改 |
| `README.md` / `README.en.md` | 特性行更新 | 修改 |

---

## Task 1: Spike —— 真机验证 NSGlassEffectView 垫层效果

先做风险验证，**不改主代码库**。产出可运行脚本 + 用户真机验收结论（特别是 regular vs clear 选档）。

**Files:**
- Create: `scripts/glass_spike.py`

- [ ] **Step 1: 编写 spike 脚本**

```python
"""液态玻璃 Spike：验证 NSGlassEffectView 垫层在 Qt 面板窗口中的真实效果。

用法（项目根目录）：
    .venv/bin/python scripts/glass_spike.py [--style regular|clear] [--appearance system|light|dark]

真机验收清单（逐条确认后在 plan 回填结论）：
1. 玻璃垫层正常渲染：折射/边缘高光肉眼可见，且不盖住 Qt 控件（z-order 正确）
2. regular vs clear 两档各跑一次对比，选定默认档（记录选择：______）
3. 深浅色切换（点窗口内"切换深浅色"按钮，模拟 App 内强制切换）玻璃质感正确跟随
4. 校训水印（右侧竖排）叠在玻璃上：可读、不脏
5. 把窗口拖到花壁纸 / 纯深色 / 纯浅色背景上：次要灰字（"副标题样本"）可读
6. 反复点"收起/展开"按钮：透明度动画播放时玻璃不闪不破
7. 窗口失焦（点击桌面）时玻璃不变灰死（玻璃无 state 概念，预期恒活跃——确认实际表现）
8. 关闭脚本后无残留进程/崩溃
"""
import argparse
import sys

import objc
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

sys.path.insert(0, "app")
import common.resources  # noqa: F401 注册 qrc（水印素材）

_NS_WINDOW_BELOW = -1
_AUTORESIZE = 2 | 16  # WidthSizable | HeightSizable
_STYLE = {"regular": 0, "clear": 1}  # NSGlassEffectStyleRegular / Clear


def install_glass(window, style: int) -> bool:
    """垫 NSGlassEffectView 到 contentView 父视图、contentView 之下（z-order 关键）。"""
    try:
        import ctypes

        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(window.winId())))
        content = view.window().contentView()
        host = content.superview()
        if host is None:
            print("FAIL: contentView 无父视图")
            return False
        glass_cls = objc.lookUpClass("NSGlassEffectView")
        glass = glass_cls.alloc().initWithFrame_(content.frame())
        glass.setAutoresizingMask_(_AUTORESIZE)
        glass.setCornerRadius_(10.0)
        glass.setStyle_(style)
        host.addSubview_positioned_relativeTo_(glass, _NS_WINDOW_BELOW, content)
        window._glass = glass  # 防 GC
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def set_glass_appearance(window, dark: bool):
    glass = getattr(window, "_glass", None)
    if glass is None:
        return
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
    glass.setAppearance_(objc.lookUpClass("NSAppearance").appearanceNamed_(name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["regular", "clear"], default="regular")
    parser.add_argument("--appearance", choices=["system", "light", "dark"],
                        default="system")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    try:
        objc.lookUpClass("NSGlassEffectView")
    except Exception:
        print("本机无 NSGlassEffectView（macOS < 26）——spike 不适用")
        return 1

    win = QWidget(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
    win.setAttribute(Qt.WA_TranslucentBackground, True)
    win.setFixedWidth(360)
    layout = QVBoxLayout(win)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)

    title = QLabel("液态玻璃 Spike")
    title.setStyleSheet("font-size: 20pt; font-weight: 600; color: #1D1D1F;")
    layout.addWidget(title)
    sub = QLabel("副标题样本：次要灰字可读性验证")
    sub.setStyleSheet("font-size: 13pt; color: #606066;")
    layout.addWidget(sub)
    layout.addWidget(QLineEdit(placeholderText="输入框样本（含中文输入法测试）"))
    btn = QPushButton("连接")
    btn.setMinimumHeight(38)
    btn.setStyleSheet(
        "QPushButton { background: #005C31; color: white; border-radius: 6px;"
        " font-size: 13pt; font-weight: 600; }"
        "QPushButton:pressed { background: #004A26; padding-top: 1px; }"
    )
    layout.addWidget(btn)

    state = {"dark": False}
    toggle = QPushButton("切换深浅色（验证玻璃跟随）")
    def _toggle():
        state["dark"] = not state["dark"]
        set_glass_appearance(win, state["dark"])
    toggle.clicked.connect(_toggle)
    layout.addWidget(toggle)

    hide_btn = QPushButton("收起/展开（验证动画中玻璃表现）")
    def _hide_show():
        if win.isVisible():
            win.setWindowOpacity(0.0)
            win.hide()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(600, lambda: (win.setWindowOpacity(1.0), win.show()))
    hide_btn.clicked.connect(_hide_show)
    layout.addWidget(hide_btn)

    # 水印（右下小图，验证玻璃上的叠加效果）
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import Qt as _Qt
    wm = QLabel()
    pix = QPixmap(":/brand/motto.png")
    if not pix.isNull():
        wm.setPixmap(pix.scaledToHeight(120, _Qt.SmoothTransformation))
        wm.setStyleSheet("background: transparent;")
        wm.setAlignment(_Qt.AlignRight)
    layout.addWidget(wm)

    win.show()
    win.raise_()
    win.activateWindow()
    ok = install_glass(win, _STYLE[args.style])
    print(f"glass installed: {ok}, style={args.style}")
    if args.appearance != "system":
        set_glass_appearance(win, args.appearance == "dark")
    objc.lookUpClass("NSApplication").sharedApplication() \
        .activateIgnoringOtherApps_(True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

注意 spike 里的窗口只是 Tool 无边框，内容颜色写死浅色样本——深浅色切换只验证**玻璃质感**跟随（setAppearance_），文字颜色不变属预期（主代码里文字由 theme 体系管）。

- [ ] **Step 2: 用户真机运行并按清单验收**

Run: `.venv/bin/python scripts/glass_spike.py --style regular`
Run: `.venv/bin/python scripts/glass_spike.py --style clear`
Expected: 清单 8 条逐条确认；**记录 regular/clear 选定结果**。

- [ ] **Step 3: 回填结论到本 plan**

在 Task 1 末尾回填：选定 style、验收异常项（若有）及其处置。

- [ ] **Step 4: Commit**

```bash
git add scripts/glass_spike.py docs/superpowers/plans/2026-09-18-macos-liquid-glass.md
git commit -m "test: 液态玻璃 spike——NSGlassEffectView 垫层真机验证（regular/clear 对比）"
```

---

## Task 2: `macos_glass.py` —— 玻璃桥接模块

**Files:**
- Create: `app/utils/macos_glass.py`
- Test: `tests/test_menu_bar_mode.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 tests/test_menu_bar_mode.py）**

```python
# ---- 液态玻璃（utils/macos_glass.py） ----


def test_glass_available_false_offscreen(qtbot):
    """offscreen 测试环境（非 cocoa）玻璃不可用。"""
    from utils.macos_glass import glass_available

    assert glass_available() is False


def test_glass_available_false_non_darwin(monkeypatch, qtbot):
    from utils import macos_glass

    monkeypatch.setattr(macos_glass, "system", lambda: "Windows")
    assert macos_glass.glass_available() is False


def test_glass_available_false_without_qapp(monkeypatch):
    """无 QApplication 实例时 platformName 恒返回 cocoa（编译期默认），必须挡掉。"""
    from utils import macos_glass

    class _FakeQApp:
        @staticmethod
        def instance():
            return None

        @staticmethod
        def platformName():
            return "cocoa"

    # 整体替换模块级 QApplication 引用：Shiboken 类的静态方法不适合逐方法打补丁
    monkeypatch.setattr(macos_glass, "QApplication", _FakeQApp)
    assert macos_glass.glass_available() is False


def test_install_glass_offscreen_returns_false(qtbot):
    from PySide6.QtWidgets import QWidget
    from utils.macos_glass import install_glass

    w = QWidget()
    qtbot.addWidget(w)
    assert install_glass(w) is False
    assert getattr(w, "_glass_view", None) is None


def test_remove_glass_noop_when_not_installed(qtbot):
    from PySide6.QtWidgets import QWidget
    from utils.macos_glass import remove_glass

    w = QWidget()
    qtbot.addWidget(w)
    remove_glass(w)  # 未安装：安静返回，不抛异常


def test_update_glass_appearance_noop_when_not_installed(qtbot):
    from PySide6.QtWidgets import QWidget
    from utils.macos_glass import update_glass_appearance

    w = QWidget()
    qtbot.addWidget(w)
    update_glass_appearance(w)  # 未安装：安静返回，不抛异常
```

注意 `test_glass_available_false_without_qapp` 直接打 `macos_glass.QApplication`——要求模块在**模块级** import QApplication（与 `macos_status_item._native_available` 的实例守卫同理）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -k "glass" -v`
Expected: FAIL —— `ModuleNotFoundError: utils.macos_glass`。

- [ ] **Step 3: 实现**

```python
# app/utils/macos_glass.py
"""NSGlassEffectView 液态玻璃背景（macOS 26+ 菜单栏面板形态专属）。

与 macos_vibrancy.py 同构：垫层置于 contentView 父视图（NSThemeFrame）、
contentView 之下——z-order 是关键，加成 contentView 的 subview 会盖住全部
Qt 内容（vibrancy 真机实测结论，直接复用）。

版本路由由 glass_available() 特性检测承担：类存在即 macOS 26+；
macOS 15 及以下 lookUpClass 抛错 → 调用方回退 vibrancy（现状不动）。

与 vibrancy 的差异：玻璃无 material/state 概念（恒活跃，折射由系统管理），
圆角走 cornerRadius 属性（不需 wantsLayer + layer mask）。
深浅色跟随 App 主题设置（set_appearance 三态），与 vibrancy 行为一致。

平台守卫必需：offscreen（测试环境）下 winId() 返回 1，桥接会 SIGSEGV。
"""
from platform import system

from PySide6.QtWidgets import QApplication

from utils.macos_vibrancy import _nsview_of

_NS_WINDOW_BELOW = -1    # NSWindowOrderingMode
_AUTORESIZE = 2 | 16     # WidthSizable | HeightSizable
_CORNER_RADIUS = 10.0    # 与面板 QSS 圆角一致（HIG：圆角连续）
_GLASS_STYLE = 0         # NSGlassEffectStyleRegular（spike 选定；clear=1）


def _cocoa() -> bool:
    """真实 cocoa 平台且 QApplication 已实例化（无实例时 platformName 谎报 cocoa）。"""
    if QApplication.instance() is None:
        return False
    return system() == "Darwin" and QApplication.platformName() == "cocoa"


def glass_available() -> bool:
    """NSGlassEffectView 是否可用（macOS 26+ 且真实 cocoa 平台）。"""
    if not _cocoa():
        return False
    try:
        import objc

        objc.lookUpClass("NSGlassEffectView")
        return True
    except Exception:
        return False


def install_glass(window) -> bool:
    """为窗口安装液态玻璃背景（幂等）。返回是否成功；失败由调用方回退 vibrancy。"""
    if not glass_available():
        return False
    if getattr(window, "_glass_view", None) is not None:
        return True  # 已安装：避免重复 addSubview 叠层
    try:
        import objc

        view = _nsview_of(window)
        content = view.window().contentView()  # 即 QNSView，Qt 内容画在它自己的图层
        host = content.superview()
        if host is None:
            return False  # 无法垫在内容之下时宁可不安（绝不盖内容）
        glass_cls = objc.lookUpClass("NSGlassEffectView")
        # frame 与 content 完全重合；autoresize 跟随窗口尺寸
        glass = glass_cls.alloc().initWithFrame_(content.frame())
        glass.setAutoresizingMask_(_AUTORESIZE)
        glass.setCornerRadius_(_CORNER_RADIUS)
        glass.setStyle_(_GLASS_STYLE)
        # 关键：置于 host 中、contentView 之下（不能加到 contentView 里）
        host.addSubview_positioned_relativeTo_(glass, _NS_WINDOW_BELOW, content)
        window._glass_view = glass  # 防 GC + 供移除/更新时查找
        update_glass_appearance(window)
        return True
    except Exception:
        return False


def remove_glass(window) -> None:
    """移除玻璃（切回浮动模式时调用；未安装时安静返回）。"""
    glass = getattr(window, "_glass_view", None)
    if glass is None:
        return
    window._glass_view = None
    try:
        glass.removeFromSuperview()
    except Exception:
        pass


def update_glass_appearance(window) -> None:
    """深浅色跟随 App 主题（theme.is_dark 已含 system/light/dark 三态解析）。"""
    glass = getattr(window, "_glass_view", None)
    if glass is None or system() != "Darwin":
        return
    try:
        import objc

        from common import theme

        name = "NSAppearanceNameDarkAqua" if theme.is_dark() else "NSAppearanceNameAqua"
        glass.setAppearance_(
            objc.lookUpClass("NSAppearance").appearanceNamed_(name)
        )
    except Exception:
        pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -k "glass" -v`
Expected: 6 passed。

- [ ] **Step 5: 语法与导入冒烟（真机 cocoa 路径）**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'app'); from PySide6.QtWidgets import QApplication; app = QApplication(); from utils.macos_glass import glass_available; print('glass_available:', glass_available())"`
Expected: macOS 26+ 输出 `glass_available: True`；低版本输出 `False`。

- [ ] **Step 6: Commit**

```bash
git add app/utils/macos_glass.py tests/test_menu_bar_mode.py
git commit -m "feat: NSGlassEffectView 液态玻璃桥接模块（特性检测/安装/移除/深浅色跟随，失败回退 vibrancy）"
```

---

## Task 3: 面板外壳按可用性路由玻璃/毛玻璃

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_menu_bar_mode.py`（追加）

- [ ] **Step 1: 写失败测试（追加）**

```python
@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_chrome_prefers_glass_when_available(window, monkeypatch):
    """玻璃可用时安装玻璃、不装毛玻璃。"""
    calls = []
    monkeypatch.setattr("utils.macos_glass.glass_available", lambda: True)
    monkeypatch.setattr(
        "utils.macos_glass.install_glass", lambda w: calls.append("glass") or True
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.install_vibrancy",
        lambda w: calls.append("vibrancy") or True,
    )
    window.set_menu_bar_mode(True)
    assert calls == ["glass"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_panel_chrome_falls_back_to_vibrancy(window, monkeypatch):
    """玻璃不可用（macOS ≤ 15）时回退现有毛玻璃路径。"""
    calls = []
    monkeypatch.setattr("utils.macos_glass.glass_available", lambda: False)
    monkeypatch.setattr(
        "utils.macos_glass.install_glass", lambda w: calls.append("glass") or True
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.install_vibrancy",
        lambda w: calls.append("vibrancy") or True,
    )
    window.set_menu_bar_mode(True)
    assert calls == ["vibrancy"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_exit_panel_mode_removes_both_backdrops(window, monkeypatch):
    """切回浮动模式：玻璃与毛玻璃都拆除（幂等安静，防御同会话残留）。"""
    removed = []
    monkeypatch.setattr(
        "utils.macos_glass.remove_glass", lambda w: removed.append("glass")
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.remove_vibrancy", lambda w: removed.append("vibrancy")
    )
    window.set_menu_bar_mode(True)
    window.set_menu_bar_mode(False)
    assert removed == ["glass", "vibrancy"]


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_backdrop_update_dispatches_both(window, monkeypatch):
    """深浅色切换回调同时分发玻璃与毛玻璃更新（未安装一侧安静返回）。"""
    updated = []
    monkeypatch.setattr(
        "utils.macos_glass.update_glass_appearance", lambda w: updated.append("g")
    )
    monkeypatch.setattr(
        "utils.macos_vibrancy.update_vibrancy_appearance",
        lambda w: updated.append("v"),
    )
    window._update_backdrop()
    assert updated == ["g", "v"]
```

注意：monkeypatch 打在 `utils.macos_glass` / `utils.macos_vibrancy` **模块属性**上——`_apply_panel_chrome` 内的函数内 import 每次取的都是模块当前属性，可拦截。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -k "backdrop or prefers_glass or falls_back" -v`
Expected: FAIL —— `AttributeError: _update_backdrop` / calls 断言不符（现状无条件 vibrancy）。

- [ ] **Step 3: 实现**

`app/views/main_window.py` 的 `_apply_panel_chrome(True)` 分支，把：

```python
            from utils.macos_vibrancy import install_vibrancy
            from common import theme

            self.winId()  # 真实化 NSWindow（winId 即创建），不 show——启动路径窗口须保持隐藏
            install_vibrancy(self)
            theme.on_scheme_changed(self._update_vibrancy)  # 绑定方法可去重，避免每次切换累积 lambda
```

改为：

```python
            from common import theme

            self.winId()  # 真实化 NSWindow（winId 即创建），不 show——启动路径窗口须保持隐藏
            self._install_backdrop()
            theme.on_scheme_changed(self._update_backdrop)  # 绑定方法可去重，避免每次切换累积 lambda
```

`_apply_panel_chrome(False)` 分支，把：

```python
            from utils.macos_vibrancy import remove_vibrancy

            remove_vibrancy(self)
```

改为：

```python
            from utils.macos_glass import remove_glass
            from utils.macos_vibrancy import remove_vibrancy

            remove_glass(self)
            remove_vibrancy(self)  # 同会话只会装过一种，另一侧安静返回（防御性双拆）
```

`_update_vibrancy` 方法替换为两个方法（`_update_vibrancy` 删除，无其他引用）：

```python
    def _install_backdrop(self):
        """面板背景垫层：macOS 26+ 液态玻璃，旧系统回退毛玻璃（现状）。"""
        from utils.macos_glass import glass_available, install_glass

        if glass_available():
            if install_glass(self):
                return
            # 玻璃类存在但安装失败（桥接异常）：回退毛玻璃，不留透明底窗口
        from utils.macos_vibrancy import install_vibrancy

        install_vibrancy(self)

    def _update_backdrop(self):
        """深浅色切换：同步玻璃/毛玻璃外观（绑定方法注册，theme 按身份去重）。"""
        from utils.macos_glass import update_glass_appearance
        from utils.macos_vibrancy import update_vibrancy_appearance

        update_glass_appearance(self)
        update_vibrancy_appearance(self)  # 未安装的一侧安静返回
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 全部 passed（现有面板测试不受影响：offscreen 下 `glass_available()` 为 False，走 vibrancy 路径且被守卫挡掉，行为与现状一致）。

- [ ] **Step 5: Commit**

```bash
git add app/views/main_window.py tests/test_menu_bar_mode.py
git commit -m "feat: 面板背景按系统能力路由——macOS 26+ 液态玻璃，旧系统回退毛玻璃"
```

---

## Task 4: 动效 A —— 面板展开/收起曲线打磨

**Files:**
- Modify: `app/views/main_window.py`（`show_panel` / `hide_panel`）
- Test: `tests/test_menu_bar_mode.py`（追加）

- [ ] **Step 1: 写失败测试（追加）**

```python
@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_show_panel_animation_params(window, monkeypatch):
    """展开动效定稿：下滑 8px + 淡入，220ms OutCubic（"慢开快收"的开）。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    window.set_menu_bar_mode(True)
    window.show_panel()
    anim_pos, anim_opacity = window._panel_anims
    assert anim_pos.duration() == 220
    # 下滑 8px：起点在终点上方 8px
    assert anim_pos.startValue().y() == anim_pos.endValue().y() - 8
    assert anim_pos.startValue().x() == anim_pos.endValue().x()
    assert anim_opacity.duration() == 220
    assert anim_opacity.startValue() == 0.0
    assert anim_opacity.endValue() == 1.0


@pytest.mark.skipif(system() != "Darwin", reason="菜单栏面板仅 macOS")
def test_hide_panel_animation_params(window, monkeypatch):
    """收起动效定稿：160ms 淡出（比展开快，收起要利落）。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    window.set_menu_bar_mode(True)
    window.show_panel(animated=False)
    window.hide_panel()
    anim = window._panel_hide_anim
    assert anim is not None
    assert anim.duration() == 160
    assert anim.endValue() == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_mode.py -k "animation_params" -v`
Expected: FAIL —— duration 250 / 下滑 12px 与断言不符。

- [ ] **Step 3: 实现**

`app/views/main_window.py` 顶部（`_WATERMARK_OPACITY` 附近）加面板动效常量：

```python
# 面板展开/收起动效（grilling 定稿"慢开快收"）：展开 220ms 下滑 8px+淡入；收起 160ms 淡出
_PANEL_SHOW_DURATION_MS = 220
_PANEL_HIDE_DURATION_MS = 160
_PANEL_SLIDE_PX = 8
```

`show_panel` 中：

- `self.move(target.x(), target.y() - 12)` → `self.move(target.x(), target.y() - _PANEL_SLIDE_PX)`
- 两个动画的 `setDuration(ANIMATION_DURATION_MS)` → `setDuration(_PANEL_SHOW_DURATION_MS)`

`hide_panel` 中：

- `anim_opacity.setDuration(ANIMATION_DURATION_MS)` → `setDuration(_PANEL_HIDE_DURATION_MS)`

若 `ANIMATION_DURATION_MS` 在这两个方法里不再有引用，从函数内 import 列表移除（`reduce_motion` 仍在用）。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 全部 passed。重点确认现有动画测试不破：`test_show_panel_positions_under_icon`（reduce-motion 直出，与参数无关）、`test_show_panel_cancels_pending_hide`（断言 `_panel_hide_anim` 存在性，与时长无关）。

- [ ] **Step 5: Commit**

```bash
git add app/views/main_window.py tests/test_menu_bar_mode.py
git commit -m "feat: 面板动效打磨——展开 220ms 下滑 8px，收起 160ms（慢开快收）"
```

---

## Task 5: 动效 B1 —— 连接按钮按压下沉

**Files:**
- Modify: `app/views/main_window.py`（`_apply_theme_styles` 的连接按钮 QSS）
- Test: `tests/test_main_window.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 tests/test_main_window.py）**

```python
def test_connect_button_pressed_sink_qss(qtbot):
    """按压液态反馈：pressed 态内容下沉 1px（padding-top），背景加深已有。"""
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    qss = w.connect_button.styleSheet()
    assert ":pressed" in qss
    assert "padding-top: 1px" in qss
    w.reconnect_manager.cancel()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -k "pressed_sink" -v`
Expected: FAIL —— QSS 中无 `padding-top: 1px`。

- [ ] **Step 3: 实现**

`_apply_theme_styles` 的连接按钮 QSS `QPushButton:pressed` 块改为：

```python
            QPushButton:pressed {{
                background-color: {theme.semantic_color("accent_pressed")};
                padding-top: 1px;  /* 按压下沉 1px（内容偏移；按钮外框/布局不动） */
            }}
```

设计说明（写进代码注释）：QSS 无 transition，按压/弹回即时生效——与 Apple 按钮按压行为一致（按压即暗即沉，无延迟动画）。“下沉”用 padding 而非 margin/position：布局管理的 widget 直接 move 会被布局覆盖，margin 会推挤邻近行（底部工具行抖动），padding-top 只让内容在固定按钮框内下移，零副作用。

- [ ] **Step 4: 跑测试确认通过 + 真机目验**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: 全部 passed。真机 `python app/main.py` 点连接按钮：按下时文字轻微下沉 + 背景加深。

- [ ] **Step 5: Commit**

```bash
git add app/views/main_window.py tests/test_main_window.py
git commit -m "feat: 连接按钮按压下沉 1px（液态触感，QSS pressed 态）"
```

---

## Task 6: 动效 B2 —— 模式切换按压下沉

**Files:**
- Modify: `app/views/mode_switch.py`
- Test: `tests/test_mode_switch.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mode_switch.py
"""SegmentedModeSwitch 按压下沉反馈（自绘控件，paintEvent 整体下移 1px）。"""
from views.mode_switch import SegmentedModeSwitch


def test_press_sets_pressed_state(qtbot):
    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    assert w._pressed is False
    qtbot.mousePress(w, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton)
    assert w._pressed is True


def test_release_clears_pressed_state(qtbot):
    from PySide6.QtCore import Qt

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    qtbot.mousePress(w, Qt.LeftButton)
    qtbot.mouseRelease(w, Qt.LeftButton)
    assert w._pressed is False


def test_leave_clears_pressed_state(qtbot):
    """按住拖出控件：按压态必须恢复（否则控件卡在下沉态）。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt, QPointF

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    qtbot.mousePress(w, Qt.LeftButton)
    assert w._pressed is True
    leave = QEvent(QEvent.Leave)
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(w, leave)
    assert w._pressed is False


def test_press_does_not_break_segment_switch(qtbot):
    """按压反馈不得影响原有点击切换逻辑（mousePress 即切换 + 发信号）。"""
    from PySide6.QtCore import QPoint, Qt

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    received = []
    w.currentChanged.connect(received.append)
    # 点击右半段（TUN 模式）：段切换 + 信号发射与按压状态互不干扰
    qtbot.mousePress(w, Qt.LeftButton, pos=QPoint(w.width() - 5, w.height() // 2))
    assert w.currentIndex() == 1
    assert received == [1]
    assert w._pressed is True  # 按压态独立置位
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_mode_switch.py -v`
Expected: FAIL —— `AttributeError: 'SegmentedModeSwitch' object has no attribute '_pressed'`。

- [ ] **Step 3: 实现**

`app/views/mode_switch.py`：

① `__init__` 加状态位（`self._segments` 之后）：

```python
        self._pressed = False  # 按压下沉反馈（paintEvent 整体下移 1px）
```

② 事件处理（`mousePressEvent` 改为置位 + 原逻辑；新增 release/leave）：

```python
    def mousePressEvent(self, event):
        self._pressed = True
        self.update()
        seg_w = self.width() / len(self._segments)
        self._set_current(int(event.position().x() // seg_w))

    def mouseReleaseEvent(self, event):
        if self._pressed:
            self._pressed = False
            self.update()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        # 按住拖出控件：恢复按压态，否则控件卡在下沉态
        if self._pressed:
            self._pressed = False
            self.update()
        super().leaveEvent(event)
```

③ `paintEvent` 开头（`painter.setRenderHint` 之后）加：

```python
        if self._pressed:
            painter.translate(0, 1)  # 按压下沉 1px（轨道+药丸+文字整体，含假阴影同步）
```

- [ ] **Step 4: 跑测试确认通过 + 真机目验**

Run: `.venv/bin/python -m pytest tests/test_mode_switch.py -v`
Expected: 4 passed。真机按住模式切换：整个控件下沉 1px，松开/拖出恢复，切换逻辑不变。

- [ ] **Step 5: Commit**

```bash
git add app/views/mode_switch.py tests/test_mode_switch.py
git commit -m "feat: 模式切换按压下沉 1px（自绘控件整体偏移，拖出恢复）"
```

---

## Task 7: 全量回归 + 真机验收 + README

**Files:**
- Modify: `README.md` / `README.en.md`

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed。

- [ ] **Step 2: 真机验收清单（用户执行）**

Run: `.venv/bin/python app/main.py`，设置 → 通用 → 勾选"菜单栏面板模式"：

- [ ] 面板为液态玻璃：折射/边缘高光肉眼可见（与毛玻璃对比：背景内容有"弯曲"而非仅模糊）
- [ ] 玻璃不盖住任何控件（z-order 正确），圆角 10px 与面板一致
- [ ] 深浅色切换（系统切换 + App 内设置强制浅色/深色）玻璃质感正确跟随
- [ ] 校训水印叠在玻璃上可读、不脏；花壁纸/纯深/纯浅背景下次要灰字可读
- [ ] 展开 220ms/收起 160ms 动效手感：慢开快收，玻璃在动画中不闪不破
- [ ] 连接按钮按压：文字下沉 1px + 背景加深；模式切换按压：整体下沉 1px，拖出恢复
- [ ] 切回浮动模式：玻璃完整拆除，窗口恢复不透明 + 标题栏，无视觉残留
- [ ] 失焦收起 / Esc 收起 / 再点图标展开 / 中文输入法候选窗不误关（面板回归项）
- [ ] 退出：状态栏图标移除，无残留进程

- [ ] **Step 3: README 特性行更新**

`README.md` 特性列表中菜单栏面板一行改为：

```markdown
- macOS 双形态：浮动小窗口 / 菜单栏面板（点击状态栏图标展开；macOS 26+ 液态玻璃质感，旧系统毛玻璃），随时切换
```

`README.en.md` 对应行改为：

```markdown
- Dual macOS modes: floating window / menu bar panel (click status icon to expand; Liquid Glass on macOS 26+, vibrancy on older systems), switchable anytime
```

- [ ] **Step 4: Commit**

```bash
git add README.md README.en.md
git commit -m "docs: README 特性行更新——菜单栏面板 macOS 26+ 液态玻璃"
```

---

## Self-Review 记录

**决策覆盖核对（grilling 定稿 → 任务）：**
- 只做面板形态 → Task 2/3 接入点仅 `_apply_panel_chrome`（面板路径），浮动窗口无改动 ✅
- 版本自动路由、无新设置项 → `glass_available()` 特性检测 + Task 3 回退分支 ✅
- 深浅色跟随 App 设置 → `update_glass_appearance` 走 `theme.is_dark()`（含三态解析）+ `_update_backdrop` 注册 `theme.on_scheme_changed` ✅
- tintColor 无色 → 不调用 `setTintColor_`（Task 2 实现中无此行）✅
- 不加 scrim、regular 档信任 → `_GLASS_STYLE = 0`；可读性验证在 Task 1 清单第 5 条 + Task 7 清单 ✅
- 动效 A（220ms/8px/160ms）→ Task 4；动效 B（连接按钮 + 模式切换）→ Task 5/6 ✅
- Spike 8 条验收清单 → Task 1 docstring ✅

**类型/命名一致性：** `_glass_view` 属性名在 install/remove/update 三处一致 ✅；`glass_available` / `install_glass` / `remove_glass` / `update_glass_appearance` 与 Task 3 调用点一致 ✅；`_install_backdrop` / `_update_backdrop` 命名与现有 `_update_vibrancy` 风格一致 ✅；测试 monkeypatch 目标均为模块属性（`utils.macos_glass.X`），与实现中的函数内 import 兼容 ✅。

**已知取舍（真机兜底）：**
- NSGlassEffectView 垫层的实际渲染（折射管线与 vibrancy 不同）由 Task 1 spike 验证，失败则不合并 Task 2+，零成本回头
- `_GLASS_STYLE` 常量值以 Task 1 spike 的 regular/clear 对比结论为准（计划默认 regular；若选 clear 改一行常量 + 注释）
- QSS `padding-top` 按压下沉为纯视觉技巧；若真机感觉太弱，备选 `position: relative; top: 1px`（Qt QSS 相对定位，真机两案对比后定）
- 玻璃在窗口失焦时的表现（无 state API，预期恒活跃）列入 Task 1 清单第 7 条
