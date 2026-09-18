# Liquid Glass 菜单栏面板 + 主窗口重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 取消「浮动窗口 ↔ 菜单栏面板」二选一形态；macOS 主窗口回归唯一完整 UI（卡片化 + 液态玻璃），NSStatusItem 常驻，左键弹出全新独立设计的液态玻璃快捷面板，右键保持原生三项菜单。

**Architecture:** 新视图 `MenuBarPanel`（独立 QWidget，不复用 MainWindow），只读镜像 MainWindow/StatusPanel 状态（`state_changed` 信号 + 1s 轮询），toggle 直通 `connect_button.setChecked`。材质层复用现有 `install_glass`/`install_vibrancy` 桥接（圆角参数化），模式行弹原生 NSMenu。主窗口元素零删减、卡片化分组后装玻璃。

**Tech Stack:** PySide6 6.11+ / pyobjc（NSGlassEffectView、NSStatusItem、NSMenu）/ pytest + pytest-qt（offscreen）。

**Spec:** `docs/superpowers/specs/2026-09-18-liquid-glass-menubar-design.md`

**通用纪律：**
- 测试一律 `uv run pytest tests/<file> -q`（conftest 已强制 offscreen + 隔离 QSettings）
- 所有 pyobjc/AppKit import 保持函数内局部导入 + cocoa 平台守卫（offscreen 下触碰会 SIGSEGV）
- 动效遵守 `utils/motion_utils` 纪律：reduce-motion 即时、可打断、不用 DeleteWhenStopped 于 QVariantAnimation

---

### Task 1: ToggleSwitch 自绘开关

面板专用 macOS 风格开关（主窗口不引入）。

**Files:**
- Create: `app/views/toggle_switch.py`
- Test: `tests/test_toggle_switch.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_toggle_switch.py
from PySide6.QtCore import QSize

from views.toggle_switch import ToggleSwitch


def test_toggle_size_and_checkable(qtbot):
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    assert sw.isCheckable()
    assert sw.size() == QSize(38, 23)
    assert not sw.isChecked()


def test_toggle_click_toggles(qtbot):
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    sw.click()
    assert sw.isChecked()
    sw.click()
    assert not sw.isChecked()


def test_knob_snaps_under_reduce_motion(qtbot, monkeypatch):
    monkeypatch.setattr("views.toggle_switch.reduce_motion", lambda: True)
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    sw.setChecked(True)
    assert sw._knob == 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_toggle_switch.py -q`
Expected: FAIL（ModuleNotFoundError: views.toggle_switch）

- [ ] **Step 3: 实现**

```python
# app/views/toggle_switch.py
"""macOS 风格开关（菜单栏快捷面板专用）。

38×23 轨道 + 白色圆形 knob（带 1px 下沉阴影），150ms OutCubic 滑动，可打断；
on=accent 绿 / off=track 灰；disabled 整体 40% 透明（honest 置灰）。
"""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton
from shiboken6 import isValid

from common import theme
from utils.motion_utils import reduce_motion


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 23)
        self._knob = 0.0  # 0=左(off) 1=右(on)，动画驱动
        self.toggled.connect(self._animate_knob)

    def _animate_knob(self, checked: bool):
        target = 1.0 if checked else 0.0
        if reduce_motion():
            self._knob = target
            self.update()
            return
        old = getattr(self, "_knob_anim", None)
        if old is not None:
            self._knob_anim = None
            if isValid(old):
                old.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(150)
        anim.setStartValue(self._knob)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._on_knob_frame)
        self._knob_anim = anim
        anim.start()

    def _on_knob_frame(self, v):
        self._knob = float(v)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        w, h = self.width(), self.height()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.semantic_color("accent" if self.isChecked() else "track")))
        painter.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        d = h - 4
        x = 2 + self._knob * (w - d - 4)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(QRectF(x, 3, d, d))  # 1px 下沉假阴影
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, 2, d, d))
        painter.end()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_toggle_switch.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/views/toggle_switch.py tests/test_toggle_switch.py
git commit -m "feat: 自绘 macOS 风格 ToggleSwitch（38×23，knob 滑动动画，reduce-motion 即时）"
```

---

### Task 2: StatusPanel 状态信号

面板镜像的唯一新增信号通道：`_set_hero` 是所有状态文案变化的单一漏斗。

**Files:**
- Modify: `app/views/status_panel.py`
- Test: `tests/test_status_panel.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_status_panel.py 追加
def test_state_changed_emitted_on_hero_transitions(qtbot):
    from views.status_panel import StatusPanel

    panel = StatusPanel(server_text="112.91.150.228:443")
    qtbot.addWidget(panel)
    calls = []
    panel.state_changed.connect(lambda: calls.append(1))
    panel.set_connecting()
    panel.set_connected("10.0.43.17")
    panel.set_disconnected()
    assert len(calls) == 3


def test_dot_state_property(qtbot):
    from views.status_panel import StatusPanel

    panel = StatusPanel(server_text="s")
    qtbot.addWidget(panel)
    assert panel.dot_state == "idle"
    panel.set_connected("10.0.43.17")
    assert panel.dot_state == "connected"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_status_panel.py -q`
Expected: FAIL（AttributeError: state_changed / dot_state）

- [ ] **Step 3: 实现**

`app/views/status_panel.py` 信号声明处（`areas_changed` 旁）：

```python
class StatusPanel(QWidget):
    # (凭据区是否可见, 资源区是否可见)
    areas_changed = Signal(bool, bool)
    # hero/副标题变化（_set_hero 单一漏斗发出，菜单栏面板镜像用）
    state_changed = Signal()
```

`_set_hero` 方法体末尾追加 `self.state_changed.emit()`；类内加只读属性：

```python
    @property
    def dot_state(self) -> str:
        """当前语义状态色名（idle/working/connected/error）。"""
        return self._dot_state
```

- [ ] **Step 4: 跑测试确认通过（含回归）**

Run: `uv run pytest tests/test_status_panel.py -q`
Expected: 全部 passed（新 2 条 + 既有用例）

- [ ] **Step 5: Commit**

```bash
git add app/views/status_panel.py tests/test_status_panel.py
git commit -m "feat: StatusPanel 新增 state_changed 信号与 dot_state 只读属性（面板镜像通道）"
```

---

### Task 3: MenuBarPanel 骨架与状态镜像

面板结构（布局 A：连接卡 + 裸行 + 工具条）与数据镜像。玻璃/定位/动画在 Task 4，导航展开在 Task 6，模式菜单在 Task 5——本任务行点击先留占位（mode 行直接切换、nav 行内联展开空调用）。

**Files:**
- Create: `app/views/menu_bar_panel.py`
- Modify: `app/common/theme.py`（加 `card_qss`）
- Modify: `app/views/main_window.py`（加 `open_main_window` / `set_connection_mode` / `toggle_panel` 委托占位）
- Test: `tests/test_menu_bar_panel.py`

- [ ] **Step 1: theme.card_qss 助手（TDD 先行）**

`tests/test_theme.py` 追加：

```python
def test_card_qss_glass_vs_solid():
    from common import theme

    glass = theme.card_qss(glass=True)
    assert "rgba(" in glass and "border-radius: 14px" in glass
    solid = theme.card_qss(glass=False)
    assert "rgba(" not in solid.split("border")[0]  # 实色底（card_background 十六进制）
```

`app/common/theme.py` 追加：

```python
def card_qss(glass: bool) -> str:
    """卡片 QSS 片段：玻璃形态半透（液态玻璃二级材质），否则实色提亮。

    玻璃版带 0.5px 半透描边模拟 inset 高光；实色版无边框（与现状卡片观感一致）。
    """
    if glass:
        if is_dark():
            return ("background: rgba(64,64,68,128); "
                    "border: 1px solid rgba(255,255,255,36); border-radius: 14px;")
        return ("background: rgba(255,255,255,140); "
                "border: 1px solid rgba(255,255,255,110); border-radius: 14px;")
    return f"background: {card_background()}; border: none; border-radius: 14px;"
```

Run: `uv run pytest tests/test_theme.py -q` → passed

- [ ] **Step 2: MainWindow 公开入口（面板依赖）**

`app/views/main_window.py`：

```python
    def open_main_window(self, focus_credentials: bool = False):
        """打开主窗口（托盘菜单/面板 pill/Dock 激活的统一入口）。"""
        self.show()
        self.raise_()
        self.activateWindow()
        if focus_credentials:
            self.username_input.setFocus()

    def set_connection_mode(self, tun: bool):
        """代理/TUN 切换统一入口（分段控件与菜单栏面板共用；幂等）。"""
        tun = bool(tun)
        if tun == self.tun_mode:
            return
        self.tun_mode = tun
        config = load_config()
        config["tun_mode"] = tun
        save_config(config)
        # 分段控件编程同步（setCurrentIndex 不发信号，不回环）
        self.mode_switch.setCurrentIndex(1 if tun else 0)
        if self.connect_button.isChecked():
            self.output_text.append("[BITZH Connect] 正在切换连接模式，重新连接…\n")
            self._bounce_connection()

    def toggle_panel(self):
        """状态栏图标左键：快捷面板展开 ↔ 收起（懒创建）。"""
        if self._menu_bar_panel is None:
            from views.menu_bar_panel import MenuBarPanel

            self._menu_bar_panel = MenuBarPanel(self)
        self._menu_bar_panel.toggle()
```

`_on_mode_changed` 改为薄转发（信号仍由分段控件发）：

```python
    def _on_mode_changed(self, index: int):
        self.set_connection_mode(index == 1)
```

`__init__` 里加 `self._menu_bar_panel = None`（与 `_panel_mode = False` 相邻；旧面板代码 Task 7 才拆，本任务保留不动）。

- [ ] **Step 3: 写面板失败测试**

```python
# tests/test_menu_bar_panel.py
"""菜单栏快捷面板（offscreen：玻璃/状态栏项桥接自动回退，结构行为全可测）。"""
import pytest


@pytest.fixture
def main(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def panel(main, qtbot):
    from views.menu_bar_panel import MenuBarPanel

    p = MenuBarPanel(main)
    qtbot.addWidget(p)
    return p


def test_panel_structure(panel):
    assert panel.width() == 300
    assert panel._toggle is not None
    assert panel._status.text() == "未连接"


def test_mirror_connected(panel, main, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    main.status_panel.set_connected("10.0.43.17")
    assert panel._status.text() == "已连接"
    assert panel._subtitle.text() == "内网 IP 10.0.43.17"
    assert not panel._stats_area.isHidden()


def test_mirror_disconnected_hides_stats(panel, main, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    main.status_panel.set_connected("10.0.43.17")
    main.status_panel.set_disconnected()
    assert panel._status.text() == "未连接"
    assert panel._stats_area.isHidden()


def test_toggle_drives_connect_button(panel, main, monkeypatch):
    called = []
    monkeypatch.setattr(main, "start_connection", lambda: called.append(1))
    main.username_input.setText("u")
    main.password_input.setText("p")
    panel._toggle.click()
    assert main.connect_button.isChecked()
    assert called


def test_no_credentials_hint_and_open_main(panel, main, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    opened = []
    monkeypatch.setattr(
        main, "open_main_window",
        lambda focus_credentials=False: opened.append(focus_credentials),
    )
    panel._toggle.click()  # 凭据为空 → start_connection 早退复位
    assert not panel._toggle.isChecked()  # 弹回
    assert panel._hint_active
    assert panel._subtitle.text() == "请先在主窗口填写凭据"
    assert opened == [True]
```

- [ ] **Step 4: 跑测试确认失败**

Run: `uv run pytest tests/test_menu_bar_panel.py -q`
Expected: FAIL（ModuleNotFoundError: views.menu_bar_panel）

- [ ] **Step 5: 实现 MenuBarPanel**

```python
# app/views/menu_bar_panel.py
"""菜单栏快捷面板（macOS 专属，液态玻璃范式，布局 A：连接卡 + 裸行 + 工具条）。

定位：主窗口是唯一完整 UI；面板是状态栏图标左键唤出的快捷操作面。
状态镜像：只读 MainWindow/StatusPanel（state_changed 信号即时 + 1s 轮询时长/速率），
不复制状态机；toggle 拨动 = main.connect_button.setChecked（校验早退会复位按钮，
面板经 toggled 镜像弹回）。
外壳（flags/玻璃/定位/动画）见 Task 4——本文件结构与方法全集在此。
"""
from platform import system

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QRectF, Qt, QTimer, QUrl, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from common import theme
from common.constants import NAV_GROUPS
from utils.motion_utils import ANIMATION_DURATION_MS, animated_height_toggle, reduce_motion
from views.chevron import Chevron
from views.status_panel import StatusDot
from views.toggle_switch import ToggleSwitch

_PANEL_WIDTH = 300


def _draw_icon(painter: QPainter, kind: str):
    """24px 网格单色线条图标（swap/grid/gear/power/window/chevron_right）。

    颜色由调用方设 pen。行内图标用 secondary_text（退后），工具按钮用 ink。
    """
    if kind == "swap":
        painter.drawLine(QPointF(6, 8), QPointF(18, 8))
        painter.drawLine(QPointF(14, 4), QPointF(18, 8))
        painter.drawLine(QPointF(18, 8), QPointF(14, 12))
        painter.drawLine(QPointF(6, 16), QPointF(18, 16))
        painter.drawLine(QPointF(10, 12), QPointF(6, 16))
        painter.drawLine(QPointF(6, 16), QPointF(10, 20))
    elif kind == "grid":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.6, 1.6)
    elif kind == "gear":
        painter.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        for i in range(8):
            painter.save()
            painter.translate(12, 12)
            painter.rotate(i * 45)
            painter.drawLine(QPointF(0, -5.6), QPointF(0, -8.2))
            painter.restore()
    elif kind == "power":
        painter.drawLine(QPointF(12, 4), QPointF(12, 11))
        painter.drawArc(QRectF(5.5, 6.5, 13, 13), 130 * 16, 280 * 16)
    elif kind == "window":
        painter.drawRoundedRect(QRectF(4, 5, 16, 14), 2.5, 2.5)
        painter.drawLine(QPointF(4, 9.5), QPointF(20, 9.5))
    elif kind == "chevron_right":
        painter.drawLine(QPointF(9, 5), QPointF(16, 12))
        painter.drawLine(QPointF(16, 12), QPointF(9, 19))


def icon_pixmap(kind: str, size: int = 15, color: str | None = None) -> QPixmap:
    """把线条图标渲染成 QPixmap（@2x 保 Retina 清晰），供 QPushButton setIcon。"""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color or theme.semantic_color("ink")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.scale(size / 24.0, size / 24.0)
    _draw_icon(painter, kind)
    painter.end()
    return pm


class _Icon(QWidget):
    """行内线条图标（_draw_icon 的 widget 形态）。"""

    def __init__(self, kind: str, size: int = 15, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.semantic_color("secondary_text")))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.scale(self.width() / 24.0, self.width() / 24.0)
        _draw_icon(painter, self._kind)
        painter.end()


class _Row(QWidget):
    """菜单行：图标 + 标签 + 右侧值/指示，整行可点（hover 圆角亮底）。"""

    clicked = Signal()

    def __init__(self, icon_kind: str, title: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(33)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(8)
        row.addWidget(_Icon(icon_kind))
        self.title = QLabel(title)
        self.title.setFont(theme.subtitle_font())
        row.addWidget(self.title)
        row.addStretch()
        self.value = QLabel("")
        row.addWidget(self.value)
        self._trailing_slot = QHBoxLayout()
        row.addLayout(self._trailing_slot)
        self.refresh_theme()

    def set_trailing(self, widget):
        self._trailing_slot.addWidget(widget)

    def mousePressEvent(self, event):
        self.clicked.emit()

    def refresh_theme(self):
        self.setStyleSheet(f"""
            _Row {{ border-radius: 8px; }}
            _Row:hover {{ background: {theme.with_alpha("accent", 0.08)}; }}
        """)
        self.value.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")


class MenuBarPanel(QWidget):
    """快捷面板：连接卡 + 模式/导航裸行 + 底部工具条。"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self._nav_expanded = False
        self._hint_active = False
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(_PANEL_WIDTH)
        self._build_ui()
        self._apply_styles()
        theme.on_scheme_changed(self._apply_styles)
        # 状态镜像：state_changed 即时；1s 轮询补时长/速率（仅可见时）
        main_window.status_panel.state_changed.connect(self._sync_from_main)
        main_window.connect_button.toggled.connect(self._sync_toggle)
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._sync_metrics)
        self._sync_from_main()
        self._sync_metrics()

    # ---- 结构 ----

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # 连接卡
        self.conn_card = QWidget()
        self.conn_card.setObjectName("PanelCard")
        self.conn_card.setAttribute(Qt.WA_StyledBackground, True)
        card = QVBoxLayout(self.conn_card)
        card.setContentsMargins(12, 10, 12, 10)
        card.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        self._dot = StatusDot(self.conn_card)
        head.addWidget(self._dot)
        self._status = QLabel("未连接")
        font = self._status.font()
        font.setPointSize(14.5)
        font.setWeight(QFont.DemiBold)
        self._status.setFont(font)
        head.addWidget(self._status)
        head.addStretch()
        self._toggle = ToggleSwitch(self.conn_card)
        self._toggle.toggled.connect(self._on_toggle)
        head.addWidget(self._toggle)
        card.addLayout(head)
        self._subtitle = QLabel("")
        self._subtitle.setContentsMargins(18, 0, 0, 0)  # 与状态词左对齐（dot 20px 槽位）
        self._subtitle.setFont(theme.card_title_font())
        card.addWidget(self._subtitle)
        # 速率三列（卡内、细分隔线之下；仅已连接态展开）
        self._stats_area = QWidget()
        stats_box = QVBoxLayout(self._stats_area)
        stats_box.setContentsMargins(0, 0, 0, 0)
        stats_box.setSpacing(6)
        from PySide6.QtWidgets import QFrame

        hairline = QFrame()
        hairline.setFrameShape(QFrame.HLine)
        hairline.setStyleSheet(f"color: {theme.with_alpha('separator', 0.6)};")
        stats_box.addWidget(hairline)
        row = QHBoxLayout()
        row.setSpacing(0)
        self._duration = self._add_stat(row, "时长")
        self._up = self._add_stat(row, "↑ 上行")
        self._down = self._add_stat(row, "↓ 下行")
        stats_box.addLayout(row)
        self._stats_area.setVisible(False)
        card.addWidget(self._stats_area)
        root.addWidget(self.conn_card)

        # 裸行区（行间 0.5px hairline）
        self._rows = QWidget()
        rows = QVBoxLayout(self._rows)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self._mode_row = _Row("swap", "连接模式")
        self._mode_row.set_trailing(_Icon("chevron_right", 10))
        self._mode_row.clicked.connect(self._on_mode_row)
        rows.addWidget(self._mode_row)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {theme.with_alpha('separator', 0.4)};")
        rows.addWidget(sep)
        self._nav_row = _Row("grid", "校内导航")
        self._nav_chevron = Chevron()
        self._nav_chevron.set_angle(90.0)  # 收起态朝下（展开器语义）
        self._nav_row.set_trailing(self._nav_chevron)
        self._nav_row.clicked.connect(self._toggle_nav)
        rows.addWidget(self._nav_row)
        # 导航展开区（Task 6 填 chips；本任务为空容器）
        self._nav_area = QWidget()
        self._nav_area.setVisible(False)
        rows.addWidget(self._nav_area)
        root.addWidget(self._rows)

        # 底部工具条
        bar = QHBoxLayout()
        bar.setSpacing(7)
        self._open_btn = QPushButton(" 打开主窗口")
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.clicked.connect(lambda: self._main.open_main_window())
        bar.addWidget(self._open_btn)
        bar.addStretch()
        self._settings_btn = self._round_button("gear", "设置")
        self._settings_btn.clicked.connect(self._open_settings)
        self._quit_btn = self._round_button("power", "退出")
        self._quit_btn.clicked.connect(self._main.quit_app)
        bar.addWidget(self._settings_btn)
        bar.addWidget(self._quit_btn)
        root.addLayout(bar)

    def _add_stat(self, row, caption: str):
        col = QVBoxLayout()
        col.setSpacing(1)
        value = QLabel("—")
        value.setFont(theme.card_value_font())
        value.setAlignment(Qt.AlignCenter)
        label = QLabel(caption)
        label.setFont(theme.card_title_font())
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        col.addWidget(value)
        col.addWidget(label)
        row.addStretch()
        row.addLayout(col)
        row.addStretch()
        return value

    def _round_button(self, icon_kind: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setIcon(QIcon(icon_pixmap(icon_kind, 13)))
        btn.setProperty("chip", True)  # QSS 选择器用
        return btn

    # ---- 样式 ----

    def _apply_styles(self):
        self.conn_card.setStyleSheet(
            f"QWidget#PanelCard {{ {theme.card_qss(glass=True)} }}"
        )
        chip_bg = "rgba(255,255,255,107)" if not theme.is_dark() else "rgba(64,64,68,128)"
        chip_bd = "rgba(255,255,255,140)" if not theme.is_dark() else "rgba(255,255,255,36)"
        self._open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {chip_bg}; border: 1px solid {chip_bd};
                border-radius: 14px; padding: 5px 12px; font-size: 12px;
                color: {theme.semantic_color("ink")};
            }}
            QPushButton:pressed {{ padding-top: 6px; }}
        """)
        for btn in (self._settings_btn, self._quit_btn):
            btn.setStyleSheet(f"""
                QPushButton[chip="true"] {{
                    background: {chip_bg}; border: 1px solid {chip_bd};
                    border-radius: 14px;
                }}
                QPushButton[chip="true"]:pressed {{ background: {chip_bd}; }}
            """)
        self._mode_row.refresh_theme()
        self._nav_row.refresh_theme()
        if not self._hint_active:
            self._subtitle.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text')};"
            )
        # 图标颜色随主题（ink 经 icon_pixmap 烘焙，需重建）
        self._open_btn.setIcon(QIcon(icon_pixmap("window", 12)))
        self._settings_btn.setIcon(QIcon(icon_pixmap("gear", 13)))
        self._quit_btn.setIcon(QIcon(icon_pixmap("power", 13)))

    # ---- 状态镜像 ----

    def _sync_from_main(self):
        sp = self._main.status_panel
        state = sp.dot_state
        self._status.setText(sp.status_text.text())
        if not self._hint_active:
            self._subtitle.setText(sp.subtitle.text())
        color = theme.semantic_color("ink" if state == "idle" else state)
        self._status.setStyleSheet(f"color: {color};")
        self._dot.setColor(theme.semantic_color(state))
        self._set_stats_visible(state == "connected")
        self._sync_toggle(self._main.connect_button.isChecked())
        self._sync_mode_label()

    def _sync_toggle(self, checked: bool):
        # 同态 setChecked 不发信号，不回环；异态经 toggled 走 knob 动画
        self._toggle.setChecked(checked)

    def _sync_metrics(self):
        sp = self._main.status_panel
        for label, text in (
            (self._duration, sp.duration_text),
            (self._up, sp.up_text),
            (self._down, sp.down_text),
        ):
            label.setText(text)
            placeholder = text == "—"
            label.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text' if placeholder else 'ink')};"
            )
        self._sync_mode_label()

    def _sync_mode_label(self):
        self._mode_row.value.setText("TUN" if self._main.tun_mode else "代理")

    def _set_stats_visible(self, visible: bool):
        if visible == getattr(self, "_stats_visible", False):
            return
        self._stats_visible = visible
        animated_height_toggle(
            self._stats_area, visible, max_height=64, fade=True,
            on_frame=self.adjustSize,
        )

    # ---- 交互 ----

    def _on_toggle(self, checked: bool):
        btn = self._main.connect_button
        btn.setChecked(checked)
        if checked and not btn.isChecked():
            # 同步早退复位（start_connection 校验失败）：凭据缺失 → 提示 + 引导主窗口
            if not (self._main.username_input.text() and self._main.password_input.text()):
                self._show_credential_hint()
                self._main.open_main_window(focus_credentials=True)

    def _show_credential_hint(self):
        self._hint_active = True
        self._subtitle.setText("请先在主窗口填写凭据")
        self._subtitle.setStyleSheet(f"color: {theme.semantic_color('error')};")
        QTimer.singleShot(3000, self._clear_credential_hint)

    def _clear_credential_hint(self):
        self._hint_active = False
        self._subtitle.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')};"
        )
        self._sync_from_main()

    def _on_mode_row(self):
        """原生 NSMenu 弹出；模块未实装（Task 5 前）或桥接失败 → 兜底直接切换。

        popup_menu 用局部导入：Task 5 才创建该模块，顶层导入会让 Task 3 无法运行。
        """
        items = ["代理", "TUN 全局路由"]
        checked = 1 if self._main.tun_mode else 0
        try:
            from utils.macos_menu_popup import popup_menu

            choice = popup_menu(items, checked, self._mode_row.mapToGlobal(
                self._mode_row.rect().bottomRight()))
        except Exception:
            # 原生菜单不可用：退化为点击直接切换
            self._main.set_connection_mode(not self._main.tun_mode)
            return
        if choice is not None and choice != checked:
            self._main.set_connection_mode(choice == 1)
        self._sync_mode_label()

    def _toggle_nav(self):
        """校内导航内联展开（chips 网格 Task 6 填充；本任务展开空容器）。"""
        self._nav_expanded = not self._nav_expanded
        angle = 270.0 if self._nav_expanded else 90.0
        if reduce_motion():
            self._nav_chevron.set_angle(angle)
        else:
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setStartValue(self._nav_chevron._angle)
            anim.setEndValue(angle)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._nav_chevron.set_angle)
            anim.start()
        animated_height_toggle(
            self._nav_area, self._nav_expanded,
            max_height=max(self._nav_area.sizeHint().height(), 1),
            fade=True, on_frame=self.adjustSize,
        )

    def _open_settings(self):
        from views.menu_utils import show_advanced_settings

        show_advanced_settings(self._main)

    # ---- 显隐（Task 4 填动画/定位；先给最小可用） ----

    def toggle(self):
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_panel()

    def show_panel(self, animated: bool = True):
        self._sync_from_main()
        self._sync_metrics()
        self.show()
        self._poll.start()

    def hide_panel(self):
        self._poll.stop()
        self.hide()
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_menu_bar_panel.py tests/test_theme.py -q`
Expected: 全部 passed

注：`test_mirror_connected` 依赖 `reduce_motion` patch——`animated_height_toggle` 在 `utils.motion_utils` 命名空间内解析 `reduce_motion`，patch 该模块即全局生效。

- [ ] **Step 7: Commit**

```bash
git add app/views/menu_bar_panel.py app/common/theme.py app/views/main_window.py tests/test_menu_bar_panel.py tests/test_theme.py
git commit -m "feat: 菜单栏快捷面板骨架——连接卡/裸行/工具条 + 状态镜像 + 无凭据引导"
```

---

### Task 4: 面板外壳——玻璃 22px、定位、动画、Esc/失焦、激活

**Files:**
- Modify: `app/utils/macos_glass.py`（corner_radius 参数化）
- Modify: `app/utils/macos_vibrancy.py`（corner_radius 参数化）
- Modify: `app/utils/macos_panel_shape.py`（圆角 10→22）
- Modify: `app/views/menu_bar_panel.py`（外壳与动画）
- Test: `tests/test_menu_bar_panel.py`

- [ ] **Step 1: 玻璃/毛玻璃圆角参数化**

`app/utils/macos_glass.py`：`install_glass(window)` → `install_glass(window, corner_radius: float = 10.0)`，函数体 `glass.setCornerRadius_(_CORNER_RADIUS)` 改 `glass.setCornerRadius_(corner_radius)`；模块常量 `_CORNER_RADIUS` 删除（docstring 同步改）。

`app/utils/macos_vibrancy.py` 同款：`install_vibrancy(window, corner_radius: float = 10.0)`，`effect.layer().setCornerRadius_(corner_radius)`。

`app/utils/macos_panel_shape.py`：`_CORNER_RADIUS = 10.0` → `22.0`（docstring 同步）。

- [ ] **Step 2: 写失败测试（外壳行为）**

`tests/test_menu_bar_panel.py` 追加：

```python
def test_panel_window_flags(panel):
    from PySide6.QtCore import Qt

    flags = panel.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.Tool
    assert flags & Qt.WindowStaysOnTopHint
    assert panel.testAttribute(Qt.WA_TranslucentBackground)


def test_esc_hides_panel(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    assert panel.isVisible()
    panel._esc.activated.emit()
    assert not panel.isVisible()


def test_hide_on_deactivate(panel, qtbot, monkeypatch):
    from PySide6.QtCore import QEvent

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    panel.event(QEvent(QEvent.WindowDeactivate))
    assert not panel.isVisible()


def test_show_panel_anchors_on_screen(panel, qtbot, monkeypatch):
    """无状态栏项（offscreen）退化到屏幕右上角可见区域内。"""
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    geo = QApplication.primaryScreen().availableGeometry()
    assert geo.contains(panel.geometry().topLeft())
    panel.hide_panel()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_menu_bar_panel.py -q -k "flags or esc or deactivate or anchors"`
Expected: FAIL（`_esc` 不存在等 AttributeError）

- [ ] **Step 4: 实现外壳与动画**

`app/views/menu_bar_panel.py`：`__init__` 尾部追加：

```python
        # Esc 收起（面板无标题栏/关闭按钮，Esc 是显式收起的键盘路径）
        from PySide6.QtGui import QKeySequence, QShortcut

        self._esc = QShortcut(QKeySequence("Esc"), self)
        self._esc.setContext(Qt.WindowShortcut)
        self._esc.activated.connect(self.hide_panel)
        self.winId()  # 真实化 NSWindow，供玻璃垫层安装
        from utils.macos_glass import install_glass

        if not install_glass(self, corner_radius=22.0):
            from utils.macos_vibrancy import install_vibrancy

            install_vibrancy(self, corner_radius=22.0)
        # 窗口 frame 同半径圆角：否则系统按矩形窗口算阴影，四角露出方形阴影残角
        from utils.macos_panel_shape import round_panel_window

        round_panel_window(self)
```

`show_panel` / `hide_panel` 替换为完整动画版（沿用旧 MainWindow 面板「慢开快收」参数）：

```python
    # 展开 220ms 下滑 8px+淡入；收起 160ms 淡出（grilling 定稿"慢开快收"）
    _SHOW_MS = 220
    _HIDE_MS = 160
    _SLIDE_PX = 8

    def show_panel(self, animated: bool = True):
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        from PySide6.QtWidgets import QApplication
        from utils.panel_geometry import panel_geometry

        self._anim_gen = getattr(self, "_anim_gen", 0) + 1
        self._stop_hide_anim()
        self._sync_from_main()
        self._sync_metrics()
        self.adjustSize()
        item = getattr(self._main, "_mac_status_item", None)
        icon_rect = item.icon_global_rect() if item is not None else None
        screen = None
        if icon_rect is not None:
            screen = QApplication.screenAt(icon_rect.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        geo = panel_geometry(icon_rect, screen.availableGeometry(), self.size())
        self.move(geo.topLeft())
        animated = animated and not reduce_motion()
        if not animated:
            self.setWindowOpacity(1.0)
            self.show()
            self._poll.start()
            self._activate()
            return
        self.setWindowOpacity(0.0)
        target = self.pos()
        self.move(target.x(), target.y() - self._SLIDE_PX)
        self.show()
        anim_pos = QPropertyAnimation(self, b"pos", self)
        anim_pos.setDuration(self._SHOW_MS)
        anim_pos.setStartValue(self.pos())
        anim_pos.setEndValue(target)
        anim_pos.setEasingCurve(QEasingCurve.OutCubic)
        anim_opacity = QPropertyAnimation(self, b"windowOpacity", self)
        anim_opacity.setDuration(self._SHOW_MS)
        anim_opacity.setStartValue(0.0)
        anim_opacity.setEndValue(1.0)
        anim_opacity.setEasingCurve(QEasingCurve.OutCubic)
        self._show_anims = (anim_pos, anim_opacity)  # 防 GC
        anim_pos.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        anim_opacity.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._poll.start()
        self._activate()

    def hide_panel(self):
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation

        self._anim_gen = getattr(self, "_anim_gen", 0) + 1
        gen = self._anim_gen
        self._stop_hide_anim()
        self._stop_show_anims()
        if reduce_motion() or not self.isVisible():
            self.hide()
            self.setWindowOpacity(1.0)
            self._poll.stop()
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(self._HIDE_MS)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            if getattr(self, "_anim_gen", 0) != gen:
                return  # 期间又 show/hide 过：陈旧回调不得决定终态
            self.hide()
            self.setWindowOpacity(1.0)
            self._poll.stop()

        anim.finished.connect(_finish)
        self._hide_anim = anim
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_show_anims(self):
        anims = getattr(self, "_show_anims", None)
        self._show_anims = None
        for anim in anims or ():
            try:
                if isValid(anim):
                    anim.stop()
            except RuntimeError:
                pass

    def _stop_hide_anim(self):
        anim = getattr(self, "_hide_anim", None)
        self._hide_anim = None
        if anim is not None:
            try:
                if isValid(anim):
                    anim.stop()
            except RuntimeError:
                pass

    def _activate(self):
        """Accessory 策略下抢键盘焦点（Esc/点击控件依赖）。"""
        from PySide6.QtWidgets import QApplication

        self.raise_()
        self.activateWindow()
        if system() == "Darwin" and QApplication.platformName() == "cocoa":
            try:
                import ctypes

                import objc

                nsapp = objc.lookUpClass("NSApplication").sharedApplication()
                nsapp.activateIgnoringOtherApps_(True)
                view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
                view.window().makeKeyAndOrderFront_(None)
            except Exception:
                pass

    def event(self, e):
        """失焦自动收起（IME 候选窗不触发本事件，中文输入不误关）。"""
        if e.type() == QEvent.WindowDeactivate and self.isVisible():
            self.hide_panel()
        return super().event(e)
```

（Task 3 里 `show_panel`/`hide_panel` 的最小实现整体替换；`toggle()` 不变。）

- [ ] **Step 5: 跑测试确认通过（含全量回归）**

Run: `uv run pytest tests/test_menu_bar_panel.py tests/test_toggle_switch.py -q`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add app/utils/macos_glass.py app/utils/macos_vibrancy.py app/utils/macos_panel_shape.py app/views/menu_bar_panel.py tests/test_menu_bar_panel.py
git commit -m "feat: 快捷面板外壳——22px 玻璃圆角、慢开快收动画、Esc/失焦收起、定位激活"
```

---

### Task 5: 原生 NSMenu 模式弹出

**Files:**
- Create: `app/utils/macos_menu_popup.py`
- Test: `tests/test_macos_menu_popup.py`、`tests/test_menu_bar_panel.py`（兜底路径）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_macos_menu_popup.py
import pytest
from PySide6.QtCore import QPoint


def test_popup_menu_raises_off_cocoa(qtbot):
    from utils.macos_menu_popup import popup_menu

    with pytest.raises(RuntimeError):
        popup_menu(["代理", "TUN 全局路由"], 1, QPoint(100, 100))
```

`tests/test_menu_bar_panel.py` 追加：

```python
def test_mode_row_fallback_toggles_mode(panel, main, monkeypatch):
    """原生菜单不可用（offscreen 抛 RuntimeError）→ 点击直接切换模式。"""
    old = main.tun_mode
    panel._on_mode_row()
    assert main.tun_mode == (not old)
    panel._on_mode_row()
    assert main.tun_mode == old
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_macos_menu_popup.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

```python
# app/utils/macos_menu_popup.py
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_macos_menu_popup.py tests/test_menu_bar_panel.py -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add app/utils/macos_menu_popup.py tests/test_macos_menu_popup.py tests/test_menu_bar_panel.py
git commit -m "feat: 连接模式行原生 NSMenu 弹出（✓ 当前项，桥接失败退化直接切换）"
```

---

### Task 6: 校内导航内联展开

**Files:**
- Modify: `app/views/menu_bar_panel.py`
- Test: `tests/test_menu_bar_panel.py`

- [ ] **Step 1: 写失败测试**

```python
def test_nav_expand_toggle(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    panel.show_panel(animated=False)
    assert panel._nav_area.isHidden()
    panel._nav_row.clicked.emit()
    assert not panel._nav_area.isHidden()
    assert panel._nav_chevron._angle == 270.0
    panel._nav_row.clicked.emit()
    assert panel._nav_area.isHidden()


def test_nav_chip_opens_url(panel, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    opened = []
    monkeypatch.setattr(
        "views.menu_bar_panel.QDesktopServices.openUrl",
        lambda url: opened.append(url),
    )
    panel._nav_row.clicked.emit()
    first_chip = panel._nav_area.findChildren(QPushButton)[0]
    first_chip.click()
    assert opened and str(opened[0].url()).startswith("http")
```

（文件顶部加 `from PySide6.QtWidgets import QPushButton`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_menu_bar_panel.py -q -k nav`
Expected: FAIL（空容器没有 chips / AttributeError）

- [ ] **Step 3: 实现 chips 网格**

`menu_bar_panel.py` `_build_ui` 中 `self._nav_area = QWidget()` 处替换为：

```python
        # 导航展开区：分组小标题 + 双列 chip（单字圆标 + 短名，App 纯排版语言）
        self._nav_area = QWidget()
        nav = QVBoxLayout(self._nav_area)
        nav.setContentsMargins(6, 0, 6, 4)
        nav.setSpacing(4)
        self._nav_badges = []
        for gi, (group_name, items) in enumerate(NAV_GROUPS):
            label = QLabel(group_name)
            label.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text')};"
                "font-size: 10px; padding-left: 4px;"
            )
            if gi:
                label.setContentsMargins(0, 6, 0, 0)
            nav.addWidget(label)
            for i in range(0, len(items), 2):
                chip_row = QHBoxLayout()
                chip_row.setSpacing(4)
                for glyph, name, url, tip in items[i : i + 2]:
                    chip_row.addWidget(self._make_chip(glyph, name, url, tip), 1)
                nav.addLayout(chip_row)
        self._nav_area.setVisible(False)
        rows.addWidget(self._nav_area)
```

新增方法：

```python
    def _make_chip(self, glyph: str, name: str, url: str, tip: str) -> QPushButton:
        chip = QPushButton()
        chip.setCursor(Qt.PointingHandCursor)
        chip.setFixedHeight(26)
        chip.setToolTip(tip)
        chip.setAttribute(Qt.WA_AlwaysShowToolTips)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)
        badge = QLabel(glyph)
        badge.setFixedSize(18, 18)
        badge.setAlignment(Qt.AlignCenter)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        bf = badge.font()
        bf.setPointSize(8.5)
        badge.setFont(bf)
        self._nav_badges.append(badge)
        lay.addWidget(badge)
        text = QLabel(name)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        tf = text.font()
        tf.setPointSize(11.5)
        text.setFont(tf)
        lay.addWidget(text, 1)
        chip.setProperty("navchip", True)
        chip.clicked.connect(
            lambda _c=False, u=url: QDesktopServices.openUrl(QUrl(u))
        )
        return chip

    def _refresh_nav_chips(self):
        for chip in self._nav_area.findChildren(QPushButton):
            chip.setStyleSheet(f"""
                QPushButton[navchip="true"] {{
                    border: none; border-radius: 6px;
                    background: transparent; text-align: left;
                }}
                QPushButton[navchip="true"]:hover {{
                    background: {theme.with_alpha("accent", 0.10)};
                }}
            """)
        for badge in self._nav_badges:
            badge.setStyleSheet(f"""
                QLabel {{
                    background: {theme.with_alpha("accent", 0.10)};
                    color: {theme.semantic_color("accent")};
                    border-radius: 9px;
                }}
            """)
```

`_apply_styles` 尾部调用 `self._refresh_nav_chips()`。文件头部 import 加 `from PySide6.QtCore import QUrl`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_menu_bar_panel.py -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add app/views/menu_bar_panel.py tests/test_menu_bar_panel.py
git commit -m "feat: 面板校内导航内联展开——分组双列 chip + chevron 旋转 + 高度动画"
```

---

### Task 7: 架构切换——NSStatusItem 常驻 + menu_bar_mode 全面移除

主窗口回归唯一完整 UI；托盘不再按形态路由。此任务为原子切换：中途状态不可用，一次完成。

**Files:**
- Modify: `app/utils/tray_utils.py`、`app/utils/config_utils.py`、`app/views/advanced_panel.py`、`app/views/menu_utils.py`、`app/main.py`、`app/views/main_window.py`
- Delete: `tests/test_menu_bar_mode.py`
- Test: `tests/test_menu_bar_panel.py`（新增集成用例）、`tests/test_main_window.py`（open_panel→open_main_window）

- [ ] **Step 1: 写失败测试**

`tests/test_menu_bar_panel.py` 追加：

```python
def test_toggle_panel_lazy_creates(main, qtbot, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    assert main._menu_bar_panel is None
    main.toggle_panel()
    assert main._menu_bar_panel is not None
    assert main._menu_bar_panel.isVisible()
    main.toggle_panel()
    assert not main._menu_bar_panel.isVisible()


def test_close_hides_to_status_item(main, qtbot):
    """macOS NSStatusItem 存在 = 后台驻留：关窗隐藏而非退出。"""
    main._mac_status_item = object()  # 哨兵：非 None 即驻留
    from PySide6.QtGui import QCloseEvent

    event = QCloseEvent()
    main.closeEvent(event)
    assert not event.isAccepted()


def test_menu_bar_mode_config_removed(qtbot):
    from utils.config_utils import load_config

    assert "menu_bar_mode" not in load_config()
```

`tests/test_main_window.py` 第 184 行 `monkeypatch.setattr(window, "open_panel", ...)` → `open_main_window`。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_menu_bar_panel.py::test_menu_bar_mode_config_removed -q`
Expected: FAIL（AssertionError）

- [ ] **Step 3: config 层移除**

`app/utils/config_utils.py`：删 `default_config` 中的 `"menu_bar_mode": False` 条目（含注释行）；`load_settings` 删 `self.menu_bar_mode = config["menu_bar_mode"]` 与非 Darwin 强制 False 块。

- [ ] **Step 4: MainWindow 拆除旧面板形态**

`app/views/main_window.py` 删除：
- `__init__` 中 `self._panel_mode = False` / `self._esc_shortcut = None` / `if self.menu_bar_mode: self._apply_panel_chrome(True)`；加 `self._menu_bar_panel = None`
- 方法：`_apply_panel_chrome`、`_install_backdrop`、`set_menu_bar_mode`、`show_panel`、`hide_panel`、`_stop_panel_anims`、`_stop_panel_hide_anim`、`_anchor_panel`、`open_panel`（已被 open_main_window 取代）、`event()` 覆盖（WindowDeactivate 收起）
- `_on_content_resize` 简化为 `self.adjustSize()`
- `_on_app_activate` 内 `self.open_panel()` → `self.open_main_window()`
- `closeEvent` 面板特例段替换为：

```python
    def closeEvent(self, event):
        if getattr(self, "_quitting", False):
            event.accept()
            return
        # macOS：NSStatusItem 常驻 = 后台驻留，关窗即隐藏（进程由状态栏项驻留）
        if getattr(self, "_mac_status_item", None) is not None:
            self.hide()
            event.ignore()
            return
        handle_close_event(self, event, self.tray_icon)
```

- 顶部面板动画常量（`_PANEL_SHOW_DURATION_MS` 等三行）删除
- `_activate_panel` 删除（逻辑已在 MenuBarPanel._activate）

- [ ] **Step 5: 托盘路由**

`app/utils/tray_utils.py` `init_tray_icon`：`if system() == "Darwin" and getattr(window, "menu_bar_mode", False):` → `if system() == "Darwin":`；menu_spec「打开面板」→「打开主窗口」、`window.open_panel` → `window.open_main_window`。`build_tray_menu` 中「打开面板」→「打开主窗口」、`window.open_panel` → `window.open_main_window`。删除 `reinit_tray` 函数（不再被调用）。

`quit_app` 中追加面板清理（`window.hide()` 之前）：

```python
    panel = getattr(window, "_menu_bar_panel", None)
    if panel is not None:
        panel.hide()
```

- [ ] **Step 6: 设置对话框与 menu_utils 清理**

`app/views/advanced_panel.py` 删除：
- `self._hide_dock_before_panel = None`（`__init__`）
- `menu_bar_mode_switch` 创建/说明/`toggled` 连接块（「菜单栏面板模式」整段）
- `_on_panel_mode_toggled` 方法
- `get_settings` 的 Darwin 分支简化为：

```python
        if system() == "Darwin":
            settings["hide_dock_icon"] = self.hide_dock_icon_switch.isChecked()
```

- `set_settings` 删 `menu_bar_mode=False` 参数；Darwin 块简化为：

```python
        if system() == "Darwin":
            self.hide_dock_icon_switch.setChecked(hide_dock_icon)
```

- `accept()` 的 Darwin 块简化为：

```python
        if system() == "Darwin" and self.parent() is not None:
            self.parent().hide_dock_icon = settings["hide_dock_icon"]
            hide_dock_icon(settings["hide_dock_icon"])
```

`app/views/menu_utils.py` `show_advanced_settings`：`set_settings(...)` 调用删 `menu_bar_mode=window.menu_bar_mode`；保存后处理删 `new_menu_bar_mode` 三行（`settings.get(...)`/`set_menu_bar_mode` 调用）；末尾 `hide_dock_icon(True if window.menu_bar_mode else window.hide_dock_icon)` → `hide_dock_icon(window.hide_dock_icon)`。

`app/main.py`：`if not window.silent_mode and not window.menu_bar_mode:` → `if not window.silent_mode:`；`hide_dock_icon(True if window.menu_bar_mode else window.hide_dock_icon)` → `hide_dock_icon(window.hide_dock_icon)`。

- [ ] **Step 7: 删除旧测试文件，全量回归**

```bash
git rm tests/test_menu_bar_mode.py
uv run pytest tests/ -q
```

Expected: 全部 passed（重点：`test_menu_bar_panel.py`、`test_main_window.py`、`test_advanced_panel.py`、`test_misc_fixes.py`）

注意：`tests/test_misc_fixes.py:20` 有自带 `open_panel` stub 的独立假窗口类，与本次改名无关，保持不动。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: 取消形态二选一——NSStatusItem 常驻，menu_bar_mode 全面移除"
```

---

### Task 8: 主窗口卡片化 + 断开按钮样式

元素零删减重排为卡片：状态卡 / 凭据卡 / 导航卡；模式分段与连接按钮裸置。

**Files:**
- Modify: `app/views/main_window.py`、`app/views/status_panel.py`（顶部 margin 24→8）
- Test: `tests/test_main_window.py`

- [ ] **Step 1: 写失败测试**

`tests/test_main_window.py` 追加：

```python
def test_main_window_cards_exist(window):
    cards = window.centralWidget().findChildren(QWidget, "Card")
    assert len(cards) == 3  # 状态卡 / 凭据卡 / 导航卡


def test_disconnect_button_outlined_when_connected(window):
    window.connect_button.setChecked(True)  # 凭据为空会早退复位，只看样式切换函数
    window._apply_connect_button_style(True)
    assert "border: 2px solid" in window.connect_button.styleSheet()
    window._apply_connect_button_style(False)
    assert "border: 2px solid transparent" in window.connect_button.styleSheet()
```

（文件头确认已有 `from PySide6.QtWidgets import QWidget`；没有则加。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_main_window.py -q -k "cards or outlined"`
Expected: FAIL

- [ ] **Step 3: 实现**

`app/views/main_window.py`：

新增卡片包装与玻璃态判断：

```python
    def _wrap_card(self, widget) -> QWidget:
        """卡片容器：objectName=Card，QSS 由 _apply_theme_styles 统一发放。"""
        card = QWidget()
        card.setObjectName("Card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(0)
        lay.addWidget(widget)
        return card

    def _glass_active(self) -> bool:
        """主窗口是否装着玻璃/毛玻璃垫层（决定卡片半透还是实色）。"""
        return (
            getattr(self, "_glass_view", None) is not None
            or getattr(self, "_vibrancy_view", None) is not None
        )
```

`setup_ui` 中：
- `layout.addWidget(self.status_panel)` → `layout.addWidget(self._wrap_card(self.status_panel))`
- `layout.addWidget(self.nav_area)` → `self.nav_card = self._wrap_card(self.nav_area); self.nav_card.setVisible(False); layout.addWidget(self.nav_card)`（原 `self.nav_area.setVisible(False)` 删除——显隐改由卡片承担）
- `layout.addWidget(self.cred_area)` → `self.cred_card = self._wrap_card(self.cred_area); layout.addWidget(self.cred_card)`

`_apply_area_visibility` 动画对象从 `cred_area`/`nav_area` 改为 `cred_card`/`nav_card`（max_height 各 +24 卡片 padding：cred 164，nav `sizeHint+24`），`self.cred_area`/`self.nav_area` 其余引用不动。

`_apply_theme_styles` 尾部追加：

```python
        # 卡片样式（玻璃半透 / 实色，随材质与深浅色重放）
        self.centralWidget().setStyleSheet(
            f"QWidget#Card {{ {theme.card_qss(glass=self._glass_active())} }}"
        )
        self._apply_connect_button_style(self.connect_button.isChecked())
```

`_apply_theme_styles` 中连接按钮样式段抽出为：

```python
    def _apply_connect_button_style(self, connected: bool):
        """连接（绿实心）/ 断开（白底绿描边）双态样式。"""
        from common import theme

        if not connected:
            self.connect_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme.semantic_color("accent")};
                    color: {theme.semantic_color("accent_text")};
                    border: 2px solid transparent;
                    border-radius: 6px;
                    font-size: 13pt;
                    font-weight: 600;
                }}
                QPushButton:hover:enabled {{
                    background-color: {theme.semantic_color("accent_hover")};
                }}
                QPushButton:pressed {{
                    background-color: {theme.semantic_color("accent_pressed")};
                    padding-top: 1px;
                }}
                QPushButton:focus {{
                    border: 2px solid {theme.with_alpha("accent", 0.5)};
                }}
                QPushButton:disabled {{
                    background-color: {theme.semantic_color("accent_disabled")};
                    color: {theme.semantic_color("accent_text")};
                }}
            """)
        else:
            self.connect_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {theme.semantic_color("accent")};
                    border: 2px solid {theme.semantic_color("accent")};
                    border-radius: 6px;
                    font-size: 13pt;
                    font-weight: 600;
                }}
                QPushButton:hover:enabled {{
                    background-color: {theme.with_alpha("accent", 0.08)};
                }}
                QPushButton:pressed {{
                    background-color: {theme.with_alpha("accent", 0.16)};
                    padding-top: 1px;
                }}
            """)
```

（原 `_apply_theme_styles` 中连接按钮 QSS 段删除，改为调用 `self._apply_connect_button_style(False)`；`connect_button.toggled` 增连 `lambda checked: self._apply_connect_button_style(self.connect_button.isChecked())`。）

`app/views/status_panel.py`：`layout.setContentsMargins(0, 24, 0, 0)` → `(0, 8, 0, 0)`（卡片已提供外边距）；`refresh_theme` 中「深色卡片分层方案已撤回」注释更新为：卡片由主窗口卡片容器承担（玻璃半透），本组件保持透明。

- [ ] **Step 4: 跑测试确认通过（含全量回归）**

Run: `uv run pytest tests/ -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add app/views/main_window.py app/views/status_panel.py tests/test_main_window.py
git commit -m "feat: 主窗口卡片化重排（状态/凭据/导航三卡）+ 断开按钮白底绿描边"
```

---

### Task 9: 主窗口液态玻璃

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_main_window.py`

- [ ] **Step 1: 写失败测试**

```python
def test_glass_not_installed_offscreen(window):
    """offscreen 守卫：不装玻璃、不设透明底（桥接保护）。"""
    from PySide6.QtCore import Qt

    assert getattr(window, "_glass_view", None) is None
    assert getattr(window, "_vibrancy_view", None) is None
    assert not window.testAttribute(Qt.WA_TranslucentBackground)
```

- [ ] **Step 2: 跑测试确认当前即过（守卫验证）+ 真机分支审查**

Run: `uv run pytest tests/test_main_window.py -q -k glass`
Expected: PASS（现状即满足——此测试锁定守卫行为，防 Task 实现把透明底误开到 offscreen）

- [ ] **Step 3: 实现**

`app/views/main_window.py` `__init__`：在 `setup_ui()` 之后、托盘初始化之前的位置（原 `if self.menu_bar_mode:` 块附近）插入：

```python
        # 主窗口液态玻璃（macOS 26+；旧系统回退毛玻璃；垫层装上才开透明底，
        # 否则保持不透明——offscreen/桥接失败不留透明窗）
        if system() == "Darwin":
            self.winId()  # 真实化 NSWindow（不 show）
            from utils.macos_glass import install_glass

            if not install_glass(self, corner_radius=12.0):
                from utils.macos_vibrancy import install_vibrancy

                install_vibrancy(self, corner_radius=12.0)
            if self._glass_active():
                self.setAttribute(Qt.WA_TranslucentBackground, True)
            theme.on_scheme_changed(self._update_backdrop)
            self._apply_theme_styles()  # 玻璃态就位后重放卡片 QSS（半透 vs 实色）
```

`_update_backdrop` 方法保留（Task 7 未拆），继续承担玻璃/毛玻璃深浅色跟随。

注意：`theme.on_scheme_changed(self._update_backdrop)` 依赖绑定方法去重（theme 按身份过滤重复注册），与 Task 7 后残留注册不冲突。

- [ ] **Step 4: 全量回归**

Run: `uv run pytest tests/ -q`
Expected: 全部 passed

- [ ] **Step 5: 真机验证（macOS）**

```bash
uv run python app/main.py
```

清单：主窗口玻璃透出桌面壁纸（26+）/ 毛玻璃（≤15）；卡片半透层级清晰；深浅色三态切换玻璃与卡片同步；水印在玻璃上可见；Windows/Linux 虚拟机或同事机确认白卡纯色底。

- [ ] **Step 6: Commit**

```bash
git add app/views/main_window.py tests/test_main_window.py
git commit -m "feat: 主窗口液态玻璃（macOS 26+，旧系统毛玻璃回退，卡片半透二级材质）"
```

---

### Task 10: 收尾——README、全量测试、真机验证

**Files:**
- Modify: `README.md`、`README.en.md`

- [ ] **Step 1: README 特性行更新**

`README.md`：删「macOS 双形态：浮动小窗口 / 菜单栏面板（点击状态栏图标展开；macOS 26+ 液态玻璃质感，旧系统毛玻璃），随时切换」，替换为：

```markdown
- macOS 原生体验：主窗口液态玻璃（macOS 26+，旧系统毛玻璃）；菜单栏常驻图标，左键展开液态玻璃快捷面板（连接开关/速率/模式/校内导航），右键快捷菜单
```

`README.en.md` 对应英文行同步替换（对照现有双语条目翻译）。

- [ ] **Step 2: 全量测试**

Run: `uv run pytest tests/ -q`
Expected: 全部 passed

- [ ] **Step 3: 真机完整验证清单**

```bash
uv run python app/main.py
```

- 左键状态栏图标 → 面板滑出（220ms 下滑+淡入），再次左键/点外/Esc 收起
- 面板 toggle 连接/断开与主窗口按钮双向同步；无凭据时弹回 + 红字提示 + 主窗口聚焦
- 模式行弹原生菜单（液态玻璃，✓ 当前项）；已连接切换 → bounce 重连
- 校内导航内联展开/收起，chip 点击开浏览器
- 底部：打开主窗口 pill、设置 ⚙、退出 ⏻
- 右键菜单三项：打开主窗口 / VPN 连接（勾选态跟随）/ 退出
- 关主窗口 → 后台驻留；面板仍可操作；退出后状态栏图标消失
- 深浅色切换、reduce-motion（系统设置 → 辅助功能 → 显示 → 减少动态效果）

- [ ] **Step 4: Commit**

```bash
git add README.md README.en.md
git commit -m "docs: README 特性行更新——液态玻璃主窗口 + 菜单栏快捷面板"
```

---

## Self-Review 记录

**Spec 覆盖核对：**
- §2 架构变化（形态移除/托盘常驻/closeEvent/Dock）→ Task 7 ✓
- §3.1-3.2 面板结构与视觉 → Task 3/4 ✓（toggle 规格 Task 1，卡片 QSS Task 3）
- §3.3 状态与交互（镜像/无凭据/模式菜单/导航展开/动效/定位）→ Task 3/4/5/6 ✓
- §4.1 主窗口卡片化 + 断开按钮 → Task 8 ✓
- §4.2 主窗口玻璃 + §5 平台矩阵回退 → Task 9 ✓（Windows/Linux 零改动自然成立）
- §6 技术要点（圆角参数化/状态同步/offscreen 守卫/测试）→ 各 Task ✓
- 右键菜单文案「打开面板」→「打开主窗口」→ Task 7 Step 5 ✓

**类型/命名一致性：** `open_main_window`（Task 3 定义，Task 5/7 消费）、`set_connection_mode`（Task 3 定义，Task 3/5 消费）、`card_qss(glass=)`（Task 3 定义，Task 8 消费）、`_menu_bar_panel`（Task 3 定义，Task 7 消费）、`popup_menu`（Task 5 定义，Task 3 占位调用同名）✓
