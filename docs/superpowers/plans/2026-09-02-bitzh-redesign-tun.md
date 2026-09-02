# BITZH Connect 重设计（方案 B）+ 修复包 + TUN 模式 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 2026-09-02 设计文档（`docs/superpowers/specs/2026-09-02-bitzh-redesign-design.md`）：修复退出崩溃/Dock 名/文案截断，主窗口重设计为方案 B（极简大状态居中 + 凭据区收起/资源区展开动画），新增校内资源入口、外观三态开关、TUN 全局路由模式。

**Architecture:** 沿用现有 PySide6 架构。StatusPanel 重写为 hero 布局并新增 `areas_changed(cred_visible, res_visible)` 信号驱动主窗口"一收一放"动画；资源区为独立组件；TUN 模式用提权包装脚本启动内核（输出落日志文件），新增 TunWorker（tail 日志）与 RateMonitor（psutil 读 utun 网卡）；外观三态走 `QStyleHints.setColorScheme`（Qt 6.8+）。

**Tech Stack:** Python 3.11 + PySide6 6.11 + uv；新增 psutil（TUN 速率统计）；pytest + pytest-qt（offscreen）。

**已锁定决策（grilling + 可视化确认，见设计文档）：** 方案 B；资源区连接成功才展开且与凭据区"一收一放"（250ms OutCubic 可打断）；外观三态在高级设置-通用；TUN 提权用 osascript（macOS，每次连接/断开可能弹授权框，已接受的折衷）/pkexec（Linux）/runas+UAC（Windows）；TUN 下跳过系统代理；资源仅两个硬编码。

**执行约束：**
- 在新分支 `redesign-tun` 上执行，全部完成后合回 main
- 每个 Task 一个 commit，commit message 按计划原文
- 代码注释中文；不 push、不打 tag
- 不得启动阻塞式 GUI（验证用 offscreen）
- macOS 提权路径代码只写不跑（osascript 会弹授权框，留到手动验证）

---

### Task 1: 修复包 — 退出 segfault（F1）+ Dock 名（F2）

**Files:**
- Modify: `app/utils/tray_utils.py`
- Modify: `app/main.py`
- Modify: `tests/test_connection_flow.py`

**背景（F1 崩溃链）：** quit_app 里 `tray_icon.deleteLater()` 后，macOS 在应用 teardown 时给窗口补发 closeEvent → `handle_close_event` 访问已删除的托盘 C++ 对象 → Python override 抛 RuntimeError → shiboken 在解释器收尾期打印异常时 SIGSEGV（崩溃栈 `sbk_o_closeEvent → storePythonOverrideErrorOrPrint → PepException_GetArgs`）。修法：quit 可重入 + `_quitting` 标志 + RuntimeError 守卫。

- [ ] **Step 1: 从 main 拉分支**

```bash
git checkout -b redesign-tun
```

- [ ] **Step 2: 写失败测试**

`tests/test_connection_flow.py` 顶部 import 区不动，文件末尾追加：

```python
class _StubTimer:
    """记录 singleShot 调用但不真正调度，避免测试进程真的退出"""
    calls = []

    @staticmethod
    def singleShot(ms, fn):
        _StubTimer.calls.append((ms, fn))


def test_quit_app_reentrant_and_defers_quit(qtbot, monkeypatch):
    """退出流程可重入：重复调用 quit_app 不重复调度退出计时器"""
    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    _StubTimer.calls.clear()
    win = _make_window(qtbot)
    win.show()
    win.quit_app()
    assert win._quitting is True
    assert not win.isVisible()
    assert len(_StubTimer.calls) == 1
    assert _StubTimer.calls[0][0] == 1500
    win.quit_app()  # 第二次调用应是空操作
    assert len(_StubTimer.calls) == 1


def test_close_event_during_quit_accepted_without_touching_tray(qtbot, monkeypatch):
    """macOS teardown 补发的 closeEvent 在退出流程中必须安全放行（F1 回归）"""
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    win = _make_window(qtbot)
    win.quit_app()
    event = QCloseEvent()
    win.closeEvent(event)  # 不应抛异常（托盘可能已被 deleteLater）
    assert event.isAccepted()


def test_close_event_with_deleted_tray_no_crash(qtbot, monkeypatch):
    """托盘对象已销毁时 handle_close_event 不得抛异常（RuntimeError 守卫）"""
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QCloseEvent
    from utils.tray_utils import handle_close_event

    monkeypatch.setattr("utils.tray_utils.QTimer", _StubTimer)
    win = _make_window(qtbot)
    dead = QObject()
    dead.deleteLater()
    qtbot.wait(50)  # 让 DeferredDelete 生效，C++ 对象真正销毁
    event = QCloseEvent()
    handle_close_event(win, event, dead)  # 不抛异常，走 quit 路径
    assert win._quitting is True
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_connection_flow.py -v
```

预期：3 个新用例 FAIL（`_quitting` 属性不存在 / 第二次 quit 仍调度）。

- [ ] **Step 4: 实现修复**

`app/utils/tray_utils.py`：
- 顶部 import 加 `from shiboken6 import isValid`、`from PySide6.QtCore import QTimer`
- `handle_close_event` 改为：

```python
def handle_close_event(window, event, tray_icon):
    """Handle window close event"""
    # 退出流程中（macOS teardown 会补发 closeEvent）：直接放行，
    # 不触碰任何可能已销毁的对象（F1 崩溃修复）
    if getattr(window, "_quitting", False):
        event.accept()
        return
    try:
        tray_visible = tray_icon.isVisible()
    except RuntimeError:
        tray_visible = False  # 托盘 C++ 对象已销毁（退出竞态）
    if tray_visible:
        window.hide()
        event.ignore()
    else:
        window.quit_app()
```

- `quit_app` 改为：

```python
def quit_app(window, tray_icon):
    """Quit the application（可重入；保证 teardown 期不再有 Python override 抛异常）"""
    if getattr(window, "_quitting", False):
        return
    window._quitting = True
    window.stop_connection()
    window.hide()
    if isValid(tray_icon):
        tray_icon.deleteLater()
    QTimer.singleShot(1500, QApplication.quit)
```

（删除原来 quit_app 里的局部 import QTimer。）

`app/main.py`：

```python
from common.constants import APP_NAME
...
if __name__ == "__main__":
    app = QApplication()
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    if system() == "Darwin":
        # 未打包运行时 Dock/菜单栏默认显示进程名（python3.x），尽量纠正；
        # 打包成 .app 后由 bundle 保证，此处只是尽力而为
        try:
            from Foundation import NSProcessInfo

            NSProcessInfo.processInfo().setProcessName_(APP_NAME)
        except Exception:
            pass
    window = MainWindow()
    ...
```

（`from common.constants import APP_NAME` 加在文件顶部既有 import 区。）

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

```bash
uv run pytest tests/ -v
```

预期：全 PASS（65 个）。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "fix: quit crash on macOS teardown (reentrant quit_app, guarded closeEvent); set app display name for dock/menubar"
```

---

### Task 2: StatusPanel 重写为方案 B hero 布局

**Files:**
- Modify: `app/views/status_panel.py`（整文件重写）
- Modify: `app/common/theme.py`（加 hero_font）
- Modify: `tests/test_status_panel.py`（整文件重写）
- Modify: `app/utils/connection_utils.py`（两处 set_disconnected 调用换签名）

**背景：** 方案 B：hero（圆点/spinner + 26pt 状态词 + 12pt 副标题）+ 无边框统计行。hero 只放短词，原因进副标题（修 F3 截断）。新增 `areas_changed(bool, bool)` 信号（Task 4 主窗口消费）。新增 `set_rates(up, down)`（Task 6 TUN 用）。

- [ ] **Step 1: theme.py 加 hero_font**

`app/common/theme.py` 末尾追加：

```python
def hero_font() -> QFont:
    """方案 B 状态大词：26pt Bold，负字距。"""
    f = QFont()
    f.setPointSize(26)
    f.setWeight(QFont.Bold)
    f.setLetterSpacing(QFont.PercentageSpacing, 97)
    return f
```

- [ ] **Step 2: 写失败测试（整文件重写 tests/test_status_panel.py）**

```python
import pytest


@pytest.fixture(autouse=True)
def _instant(monkeypatch):
    """颜色动画退化为即时切换，便于断言样式。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)


@pytest.fixture
def panel(qtbot):
    from views.status_panel import StatusPanel

    p = StatusPanel(server_text="112.91.150.228")
    qtbot.addWidget(p)
    p.show()  # Qt 语义：顶层未 show 时子控件 isVisible() 恒 False
    return p


def test_initial_state(panel):
    assert panel.status_text.text() == "未连接"
    assert panel.subtitle.text() == "112.91.150.228"
    assert panel.ip_text == "—"
    assert panel.duration_text == "00:00:00"
    assert not panel.spinner.isVisible()
    assert panel.status_dot.isVisible()


def test_connecting_shows_spinner_hides_dot(panel, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    monkeypatch.setattr("views.busy_spinner.reduce_motion", lambda: False)
    panel.set_connecting()
    assert "连接中" in panel.status_text.text()
    assert panel.spinner.isVisible()
    assert not panel.status_dot.isVisible()


def test_connected_state_and_areas_signal(panel):
    fired = []
    panel.areas_changed.connect(lambda c, r: fired.append((c, r)))
    panel.set_connecting()
    fired.clear()
    panel.set_connected("10.0.43.17")
    assert panel.status_text.text() == "已连接"
    assert panel.subtitle.text() == "10.0.43.17 · 112.91.150.228"
    assert panel.ip_text == "10.0.43.17"
    assert panel._duration_timer.isActive()
    assert not panel.spinner.isVisible()
    assert panel.status_dot.isVisible()
    assert fired == [(False, True)]  # 凭据收起、资源展开


def test_auth_failure_hero_and_detail(panel):
    """F3 回归：认证失败 hero 只放短词，原因进副标题（不再截断）"""
    panel.set_disconnected(hero="认证失败", detail="请检查用户名和密码")
    assert panel.status_text.text() == "认证失败"
    assert panel.subtitle.text() == "请检查用户名和密码"


def test_reconnecting_countdown_in_subtitle(panel, qtbot):
    fired = []
    panel.areas_changed.connect(lambda c, r: fired.append((c, r)))
    panel.set_reconnecting(1, 3)
    assert panel.status_text.text() == "连接中断"
    assert "3" in panel.subtitle.text()
    assert "第 1 次" in panel.subtitle.text()
    qtbot.wait(1300)
    assert "2" in panel.subtitle.text()
    assert fired == [(False, False)]  # 重连等待：凭据不收起、资源收起


def test_paused_message_and_areas(panel):
    fired = []
    panel.areas_changed.connect(lambda c, r: fired.append((c, r)))
    panel.set_reconnect_paused()
    assert panel.status_text.text() == "自动重连已暂停"
    assert "手动连接" in panel.subtitle.text()
    assert fired == [(True, False)]  # 暂停后用户要操作：凭据展开


def test_disconnected_resets(panel):
    panel.set_connected("10.0.43.17")
    panel.set_disconnected()
    assert panel.status_text.text() == "未连接"
    assert panel.subtitle.text() == "112.91.150.228"
    assert panel.ip_text == "—"
    assert not panel._duration_timer.isActive()


def test_set_rates(panel):
    panel.set_rates("1.2 MB/s", "3.4 MB/s")
    assert panel.up_text == "1.2 MB/s"
    assert panel.down_text == "3.4 MB/s"
    panel.set_disconnected()
    assert panel.up_text == "—"
    assert panel.down_text == "—"
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_status_panel.py -v
```

预期：FAIL（subtitle/areas_changed/set_rates 不存在）。

- [ ] **Step 4: 整文件重写 app/views/status_panel.py**

```python
# app/views/status_panel.py
"""状态仪表盘（方案 B：极简大状态居中）。

hero：圆点/旋转弧 + 26pt 状态词 + 12pt 副标题（状态词保持短，原因进副标题，
     彻底解决长文案截断问题——原 F3）。
统计行：时长/上行/下行无边框纯文字（tnum 防每秒抖动）。
代理模式拿不到速率计数，恒显示 "—"；TUN 模式由 RateMonitor 驱动 set_rates。
区域联动：areas_changed(credentials_visible, resources_visible) 由主窗口消费，
驱动"凭据区收起 / 资源区展开"的一收一放动画。
"""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from common import theme
from utils.motion_utils import animate_label_color, reduce_motion
from views.busy_spinner import BusySpinner


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class StatusPanel(QWidget):
    # (凭据区是否可见, 资源区是否可见)
    areas_changed = Signal(bool, bool)

    def __init__(self, server_text: str = "", parent=None):
        super().__init__(parent)
        self._server_text = server_text
        self._connected_since: datetime | None = None
        self._countdown_remaining = 0
        self._retry_attempt = 0

        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(0, 12, 0, 0)

        # ---- hero：圆点/旋转弧（同位互斥）+ 状态词 + 副标题 ----
        self.spinner = BusySpinner(self, diameter=18)
        self.status_dot = QLabel("●")
        self.status_dot.setAlignment(Qt.AlignCenter)
        dot_row = QHBoxLayout()
        dot_row.setAlignment(Qt.AlignCenter)
        dot_row.addWidget(self.spinner)
        dot_row.addWidget(self.status_dot)
        layout.addLayout(dot_row)

        self.status_text = QLabel("未连接")
        self.status_text.setFont(theme.hero_font())
        self.status_text.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_text)

        self.subtitle = QLabel(server_text)
        self.subtitle.setFont(theme.card_title_font())
        self.subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.subtitle)

        # ---- 统计行：无边框纯文字三列 ----
        stats = QHBoxLayout()
        stats.setSpacing(0)
        stats.setContentsMargins(0, 10, 0, 4)
        self._stat_labels = []
        self.duration_value = self._add_stat(stats, "00:00:00", "时长")
        self.up_value = self._add_stat(stats, "—", "↑ 上行")
        self.down_value = self._add_stat(stats, "—", "↓ 下行")
        layout.addLayout(stats)

        self.setLayout(layout)

        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._tick)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)

        self.refresh_theme()

    def _add_stat(self, row, initial, caption):
        row.addStretch()
        col = QVBoxLayout()
        col.setSpacing(2)
        value = QLabel(initial)
        value.setFont(theme.card_value_font())
        value.setAlignment(Qt.AlignCenter)
        label = QLabel(caption)
        label.setFont(theme.card_title_font())
        label.setAlignment(Qt.AlignCenter)
        col.addWidget(value)
        col.addWidget(label)
        row.addLayout(col)
        row.addStretch()
        self._stat_labels.append(label)
        return value

    # ---- 便捷只读属性（测试与外部断言用） ----

    @property
    def ip_text(self) -> str:
        return self.subtitle.text().split(" · ")[0] if " · " in self.subtitle.text() else "—"

    @property
    def duration_text(self) -> str:
        return self.duration_value.text()

    @property
    def up_text(self) -> str:
        return self.up_value.text()

    @property
    def down_text(self) -> str:
        return self.down_value.text()

    def refresh_theme(self):
        """深浅色/外观切换时刷新依赖主题色的样式。"""
        secondary = theme.semantic_color("secondary_text")
        self.subtitle.setStyleSheet(f"color: {secondary};")
        for label in self._stat_labels:
            label.setStyleSheet(f"color: {secondary};")

    def _set_hero(self, text: str, color_name: str, subtitle: str):
        self.status_text.setText(text)
        self.subtitle.setText(subtitle)
        animate_label_color(self.status_dot, theme.semantic_color(color_name))

    def _tick(self):
        if self._connected_since:
            self.duration_value.setText(
                _fmt_duration(int((datetime.now() - self._connected_since).total_seconds()))
            )

    def _countdown_tick(self):
        self._countdown_remaining = max(0, self._countdown_remaining - 1)
        self.subtitle.setText(f"{self._countdown_remaining}s 后第 {self._retry_attempt} 次重连…")
        if self._countdown_remaining == 0:
            self._countdown_timer.stop()

    def set_server_text(self, text: str):
        """高级设置改了服务器地址后同步副标题（未连接/连接中显示）。"""
        self._server_text = text
        if self.status_text.text() in ("未连接", "连接中…"):
            self.subtitle.setText(text)

    # ---- 对外状态接口 ----

    def set_connecting(self):
        self._countdown_timer.stop()
        self.spinner.start()  # 减少动态效果时为空操作（保持隐藏）
        self.status_dot.setVisible(not self.spinner.isVisible())
        self._set_hero("连接中…", "working", self._server_text)
        self.areas_changed.emit(True, False)

    def set_connected(self, virtual_ip: str):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._connected_since = datetime.now()
        self._set_hero("已连接", "connected", f"{virtual_ip} · {self._server_text}")
        self._duration_timer.start()
        self.areas_changed.emit(False, True)

    def set_reconnecting(self, attempt: int, delay: float):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._retry_attempt = attempt
        self._countdown_remaining = int(delay)
        self._set_hero("连接中断", "working", f"{self._countdown_remaining}s 后第 {attempt} 次重连…")
        self._countdown_timer.start()
        self.areas_changed.emit(False, False)

    def set_reconnect_paused(self):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._set_hero("自动重连已暂停", "error", "连续失败 3 次，请手动连接")
        self.areas_changed.emit(True, False)

    def set_disconnected(self, hero: str = "未连接", detail: str = ""):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._connected_since = None
        self._duration_timer.stop()
        is_error = hero != "未连接"
        self._set_hero(hero, "error" if is_error else "idle", detail or self._server_text)
        self.duration_value.setText("00:00:00")
        self.up_value.setText("—")
        self.down_value.setText("—")
        self.areas_changed.emit(True, False)

    def set_rates(self, up_text: str, down_text: str):
        """TUN 模式速率喂数（代理模式不调用，保持 "—"）。"""
        self.up_value.setText(up_text)
        self.down_value.setText(down_text)
```

- [ ] **Step 5: connection_utils.py 两处调用换签名 + menu_utils 对齐 + 既有测试对齐**

`app/utils/connection_utils.py` 中：
- `window.status_panel.set_disconnected("认证失败，请检查用户名和密码")` → `window.status_panel.set_disconnected(hero="认证失败", detail="请检查用户名和密码")`
- `window.status_panel.set_disconnected("请输入用户名和密码")` → `window.status_panel.set_disconnected(hero="未连接", detail="请输入用户名和密码")`

`app/views/menu_utils.py` 中 `window.status_panel.server_label.setText(window.server_address)` → `window.status_panel.set_server_text(window.server_address)`（server_label 已随重写删除，必须同步改，否则打开高级设置保存就崩）。

`tests/test_connection_flow.py` 的 `test_empty_credentials_rolls_back_fake_connected_state`：断言从 `"请输入用户名和密码" in win.status_panel.status_text.text()` 改为 `win.status_panel.subtitle.text() == "请输入用户名和密码"`（新接口下原因进副标题）。

- [ ] **Step 6: 跑测试 + 全量回归**

```bash
uv run pytest tests/ -v
```

预期：全 PASS。注意 test_main_window.py / test_connection_flow.py 里对旧面板的引用若失败，按新接口对齐（`set_disconnected` 签名变化；`ip_value` 等旧卡片属性已删，改用 `subtitle`/`ip_text`）。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: rewrite status panel as direction-B hero layout with areas_changed signal and rate API"
```

---

### Task 3: 资源区组件 ResourceSection

**Files:**
- Modify: `app/common/constants.py`
- Create: `app/views/resource_section.py`
- Create: `tests/test_resource_section.py`

- [ ] **Step 1: constants.py 加资源定义**

`app/common/constants.py` 末尾追加：

```python
# 校内资源入口（用户明确只需要这两个，不做自定义管理）
RESOURCES = [
    ("📖 电子图书馆", "http://elib.bitzh.edu.cn:8080/interlibSSO/main/main.jsp"),
    ("🏛 统一门户", "https://s.bitzh.edu.cn"),
]
```

- [ ] **Step 2: 写失败测试**

`tests/test_resource_section.py`：

```python
def test_two_resource_buttons_with_urls(qtbot):
    from common.constants import RESOURCES
    from views.resource_section import ResourceSection

    section = ResourceSection()
    qtbot.addWidget(section)
    assert len(section._buttons) == 2
    assert section._buttons[0].text() == RESOURCES[0][0]
    assert section._buttons[0].property("resource_url") == RESOURCES[0][1]


def test_click_opens_url(qtbot, monkeypatch):
    from views import resource_section
    from views.resource_section import ResourceSection

    opened = []
    monkeypatch.setattr(
        resource_section.QDesktopServices, "openUrl", lambda url: opened.append(url)
    )
    section = ResourceSection()
    qtbot.addWidget(section)
    section._buttons[1].click()
    assert len(opened) == 1
    assert "s.bitzh.edu.cn" in opened[0].toString()


def test_pill_style_uses_accent(qtbot):
    from common import theme
    from views.resource_section import ResourceSection

    section = ResourceSection()
    qtbot.addWidget(section)
    assert theme.semantic_color("accent").lower() in section._buttons[0].styleSheet().lower()
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_resource_section.py -v
```

- [ ] **Step 4: 实现 app/views/resource_section.py**

```python
# app/views/resource_section.py
"""校内资源入口（方案 B 胶囊按钮）。连接成功后展开，点击用默认浏览器打开。

资源仅两个（电子图书馆、统一门户），用户明确不需要自定义管理（YAGNI）。
"""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from common import theme
from common.constants import RESOURCES


class ResourceSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignCenter)
        self._buttons = []
        for name, url in RESOURCES:
            btn = QPushButton(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("resource_url", url)
            btn.clicked.connect(
                lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u))
            )
            row.addWidget(btn)
            self._buttons.append(btn)
        self.setLayout(row)
        self.refresh_theme()

    def refresh_theme(self):
        """胶囊样式：BIT 绿描边，按下填充（随深浅色刷新）。"""
        for btn in self._buttons:
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {theme.semantic_color("accent")};
                    border: 1px solid {theme.semantic_color("accent")};
                    border-radius: 13px;
                    padding: 5px 14px;
                    background: transparent;
                }}
                QPushButton:pressed {{
                    background-color: {theme.semantic_color("accent")};
                    color: {theme.semantic_color("accent_text")};
                }}
            """)
```

- [ ] **Step 5: 跑测试确认通过 + Commit**

```bash
uv run pytest tests/ -v && git add -A && git commit -m "feat: add resource section with BITZH library/portal pill buttons"
```

---

### Task 4: 主窗口方案 B 布局 + 一收一放动画

**Files:**
- Modify: `app/views/main_window.py`（setup_ui 重写 + 区域动画）
- Modify: `tests/test_main_window.py`（对齐 + 新增区域联动用例）

**布局顺序（自上而下）：** StatusPanel → ResourceSection（初始隐藏）→ cred_area（凭据容器）→ 按钮行 → 折叠日志。

- [ ] **Step 1: main_window.py 改造**

`setup_ui` 中凭据区改为容器、接入资源区和动画（其余既有逻辑保留）：

```python
    def setup_ui(self):
        from common import theme
        from utils.credential_utils import load_credentials
        from utils.motion_utils import animated_height_toggle
        from views.resource_section import ResourceSection
        from views.status_panel import StatusPanel

        self.setMinimumSize(360, 520)
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # 状态仪表盘（hero 布局）
        self.status_panel = StatusPanel(server_text=self.server_address)
        layout.addWidget(self.status_panel)

        # 资源区（初始隐藏，连接成功展开）
        self.resource_area = ResourceSection()
        self.resource_area.setVisible(False)
        layout.addWidget(self.resource_area)

        # 凭据区（容器化，连接成功收起）
        self.cred_area = QWidget()
        cred_layout = QVBoxLayout(self.cred_area)
        cred_layout.setSpacing(8)
        cred_layout.setContentsMargins(0, 0, 0, 0)

        saved_username, saved_password = load_credentials()

        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("用户名"))
        self.username_input = QLineEdit()
        self.username_input.setText(saved_username)
        self.username_input.setPlaceholderText("学号/工号")
        user_row.addWidget(self.username_input)
        cred_layout.addLayout(user_row)

        pass_row = QHBoxLayout()
        pass_row.addWidget(QLabel("密码"))
        self.password_input = QLineEdit()
        self.password_input.setText(saved_password)
        self.password_input.setEchoMode(QLineEdit.Password)
        pass_row.addWidget(self.password_input)
        cred_layout.addLayout(pass_row)

        opt_row = QHBoxLayout()
        self.remember_cb = QCheckBox("记住密码")
        self.remember_cb.setChecked(self.remember)
        self.remember_cb.stateChanged.connect(self.save_credentials)
        opt_row.addWidget(self.remember_cb)
        self.show_password_cb = QCheckBox("显示密码")
        self.show_password_cb.stateChanged.connect(
            lambda checked: toggle_password_visibility(self.password_input, checked)
        )
        opt_row.addWidget(self.show_password_cb)
        opt_row.addStretch()
        cred_layout.addLayout(opt_row)

        layout.addWidget(self.cred_area)

        # 连接按钮（BIT 绿 accent）+ 小号退出按钮（同前，代码不变）
        ...（保留 Task 8 版本的按钮行、eventFilter、内联校验、折叠日志全部代码）...

        # 一收一放：仪表盘状态驱动凭据区/资源区显隐动画
        self._cred_visible = True
        self._res_visible = False
        self.status_panel.areas_changed.connect(self._apply_area_visibility)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        theme.on_scheme_changed(self._apply_button_style)
        theme.on_scheme_changed(self.status_panel.refresh_theme)
        theme.on_scheme_changed(self.resource_area.refresh_theme)

    def _apply_area_visibility(self, cred_visible: bool, res_visible: bool):
        """凭据区/资源区一收一放（250ms，可打断，幂等）。"""
        if cred_visible == self._cred_visible and res_visible == self._res_visible:
            return
        self._cred_visible = cred_visible
        self._res_visible = res_visible
        self._animated_height_toggle(
            self.cred_area, cred_visible, max_height=140, on_frame=self.adjustSize
        )
        self._animated_height_toggle(
            self.resource_area, res_visible, max_height=40, on_frame=self.adjustSize
        )
```

注意：
- `self._animated_height_toggle = animated_height_toggle` 这行赋值保留（在原有位置）
- 输入框禁用逻辑（toggled 读 isChecked 的两个 lambda）**保留**——连接中凭据区仍可见（连接成功才收起）
- `status_panel.set_server_text` 在 Task 9 的 menu_utils 高级设置保存路径已经接线（上一轮的 server_label 同步需改名为 `set_server_text`——检查 `app/views/menu_utils.py` 里 `status_panel.server_label.setText(...)` 改为 `status_panel.set_server_text(...)`）

- [ ] **Step 2: 对齐与新增测试**

`tests/test_main_window.py`：
- 保留既有用例；新增：

```python
def test_area_animation_on_connect_disconnect(window, monkeypatch):
    """连接成功：凭据收起+资源展开；断开：还原（一收一放）"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    assert window.cred_area.isVisible() or not window.cred_area.isVisible()  # 初始无论
    window.status_panel.set_connected("10.0.43.17")
    assert not window.cred_area.isVisible()
    assert window.resource_area.isVisible()
    window.status_panel.set_disconnected()
    assert window.cred_area.isVisible()
    assert not window.resource_area.isVisible()


def test_area_visibility_idempotent(window, monkeypatch):
    """重复状态信号不重复触发动画（幂等守卫）"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    window.status_panel.set_connected("10.0.43.17")
    window.status_panel.set_disconnected()
    assert window._cred_visible is True and window._res_visible is False
    # 再次 set_disconnected 不应改变状态（也不会动画重跳）
    window.status_panel.set_disconnected()
    assert window.cred_area.isVisible()
```

注意：`window` fixture 里 MainWindow() 构造后若资源区初始 setVisible(False)，offscreen 下 `isVisible()` 依赖父链 show——fixture 已有 `w.show()`，初始断言改为 `_cred_visible/_res_visible` 标志位判断更稳（布局显隐以标志为准）。

- [ ] **Step 3: 全量回归 + Commit**

```bash
uv run pytest tests/ -v && git add -A && git commit -m "feat: direction-B main window layout with collapse/expand area animation and resource section"
```

---

### Task 5: 外观三态开关

**Files:**
- Modify: `app/common/theme.py`
- Modify: `app/utils/config_utils.py`
- Modify: `app/views/advanced_panel.py`
- Modify: `app/views/menu_utils.py`
- Modify: `app/views/main_window.py`（启动时应用）
- Create: `tests/test_appearance.py`

- [ ] **Step 1: theme.py 加外观管理**

`app/common/theme.py` 顶部 import 加 `from platform import system`，文件改写/追加：

```python
_REFRESH_CALLBACKS = []
_scheme_signal_connected = False


def on_scheme_changed(callback):
    """深浅色切换（含 app 内外观切换）时回调。同一回调只注册一次。"""
    global _scheme_signal_connected
    _REFRESH_CALLBACKS.append(callback)
    if not _scheme_signal_connected:
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: _run_refresh()
        )
        _scheme_signal_connected = True


def _run_refresh():
    for cb in list(_REFRESH_CALLBACKS):
        cb()


def set_appearance(mode: str):
    """外观三态：system / light / dark。

    Qt 6.8+ setColorScheme 显式覆盖（Unknown = 跟随系统），
    随后手动触发一次刷新（setColorScheme 不一定发 colorSchemeChanged）。
    macOS 窗口标题栏用 NSAppearance 跟随。
    """
    scheme = {
        "system": Qt.ColorScheme.Unknown,
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
    }[mode]
    QGuiApplication.styleHints().setColorScheme(scheme)
    if system() == "Darwin":
        try:
            import objc

            nsapp = objc.lookUpClass("NSApplication").sharedApplication()
            if mode == "system":
                nsapp.setAppearance_(None)
            else:
                name = "NSAppearanceNameDarkAqua" if mode == "dark" else "NSAppearanceNameAqua"
                nsapp.setAppearance_(objc.lookUpClass("NSAppearance").appearanceNamed_(name))
        except Exception:
            pass
    _run_refresh()
```

（删除旧的 `on_scheme_changed` 定义。）

- [ ] **Step 2: config_utils 加 appearance 键**

`default_config` 加 `"appearance": "system"`；`load_settings` 末尾加 `self.appearance = config["appearance"]`。

- [ ] **Step 3: 写失败测试**

`tests/test_appearance.py`：

```python
import pytest


@pytest.fixture(autouse=True)
def _reset_appearance():
    yield
    from common import theme

    theme.set_appearance("system")


def test_set_appearance_dark_light(qapp):
    from common import theme

    theme.set_appearance("dark")
    assert theme.is_dark() is True
    theme.set_appearance("light")
    assert theme.is_dark() is False


def test_set_appearance_triggers_refresh(qapp):
    from common import theme

    calls = []
    theme.on_scheme_changed(lambda: calls.append(1))
    theme.set_appearance("dark")
    assert len(calls) >= 1


def test_appearance_config_default():
    from utils.config_utils import load_config

    assert load_config()["appearance"] == "system"
```

- [ ] **Step 4: 跑测试确认失败 → 实现已通过（Step 1-2 已写）→ 确认通过**

```bash
uv run pytest tests/test_appearance.py -v
```

预期：3 个用例 PASS（TDD 此处测试先行、实现已随 Step 1-2 给出——实现者按顺序先只写测试跑出 FAIL，再落实现）。若 `setColorScheme(Unknown)` 在某些平台不恢复系统跟随，测试 1 的 fixture 复位会暴露（后续用例颜色断言错）——此时改用「仅非 system 时 setColorScheme + is_dark() 加显式 override 变量」的备选实现。

- [ ] **Step 5: advanced_panel 通用 tab 加外观下拉 + 接线**

`app/views/advanced_panel.py` 通用 tab（"断线自动重连"开关附近）加：

```python
        appearance_layout = QHBoxLayout()
        appearance_layout.addWidget(QLabel("外观"))
        self.appearance_combo = QComboBox()
        self.appearance_combo.addItems(["跟随系统", "浅色", "深色"])
        appearance_layout.addWidget(self.appearance_combo)
        general_layout.addLayout(appearance_layout)
```

（顶部 PySide6.QtWidgets import 加 QComboBox。）

`get_settings` 返回 dict 加 `"appearance": ["system", "light", "dark"][self.appearance_combo.currentIndex()]`；`set_settings` 签名加 `appearance="system"` 并 `self.appearance_combo.setCurrentIndex(["system", "light", "dark"].index(appearance))`。

`app/views/menu_utils.py` 的 `show_advanced_settings`：`dialog.set_settings(...)` 调用加 `window.appearance`（注意 set_settings 是位置参数，appearance 追加在 cert_password 之后）；`if dialog.exec():` 后加：

```python
        window.appearance = settings["appearance"]
        from common import theme

        theme.set_appearance(settings["appearance"])
```

（advanced_panel.py 的 accept() 里 settings 落盘路径已覆盖新键，无需改。）

`app/views/main_window.py` `__init__` 中 `self.load_settings()` 之后加：

```python
        from common import theme

        theme.set_appearance(self.appearance)
```

- [ ] **Step 6: 全量回归 + Commit**

```bash
uv run pytest tests/ -v && git add -A && git commit -m "feat: appearance override (system/light/dark) via setColorScheme with NSAppearance fallback"
```

---

### Task 6: TUN 模式

**Files:**
- Modify: `pyproject.toml`（+psutil）
- Modify: `app/utils/config_utils.py`（+tun_mode）
- Modify: `app/views/advanced_panel.py`（网络 tab +开关）
- Modify: `app/views/menu_utils.py`（接线）
- Create: `app/utils/tun_utils.py`
- Create: `app/utils/tun_worker.py`
- Create: `app/services/rate_monitor.py`
- Modify: `app/utils/connection_utils.py`（tun 分支）
- Modify: `app/views/main_window.py`（rate monitor 生命周期）
- Create: `tests/test_tun_utils.py`、`tests/test_tun_worker.py`、`tests/test_rate_monitor.py`
- Modify: `.github/workflows/release.yml`（Windows 捆 wintun.dll）

- [ ] **Step 1: pyproject 加依赖**

`dependencies` 加 `"psutil>=6.0"`，`uv sync`。

- [ ] **Step 2: config + 面板开关**

`config_utils.py` default_config 加 `"tun_mode": False`；`load_settings` 加 `self.tun_mode = config["tun_mode"]`。

`advanced_panel.py` 网络 tab 末尾（证书密码行之后）加：

```python
        self.tun_mode_switch = QCheckBox("TUN 模式（全局路由）")
        self.tun_mode_switch.setToolTip(
            "所有流量（含 SSH 等裸 TCP）都走 VPN；需要管理员授权；与 Clash TUN 模式互斥"
        )
        network_layout.addWidget(self.tun_mode_switch)
```

`get_settings` 加 `"tun_mode": self.tun_mode_switch.isChecked()`；`set_settings` 签名加 `tun_mode=False` 并 `self.tun_mode_switch.setChecked(tun_mode)`。

`menu_utils.py` `show_advanced_settings`：set_settings 调用加 `window.tun_mode`（追加在 appearance 之后）；exec 后加 `window.tun_mode = settings["tun_mode"]`。

- [ ] **Step 3: 写失败测试**

`tests/test_tun_utils.py`：

```python
import os
import stat

from utils.tun_utils import read_pid, write_launcher, _pid_alive


def test_write_launcher_quotes_args(tmp_path):
    """包装脚本必须经真实 shell 执行，参数用 shlex.quote（含特殊字符的密码安全）"""
    launcher = write_launcher(
        "/path with space/zju-connect",
        ["-password", "p@ss!word with space", "-tun-mode"],
        str(tmp_path / "t.log"),
        str(tmp_path / "t.pid"),
    )
    content = open(launcher).read()
    assert "'p@ss!word with space'" in content
    assert "nohup" in content and "echo $!" in content
    assert os.stat(launcher).st_mode & stat.S_IXUSR


def test_read_pid(tmp_path):
    p = tmp_path / "x.pid"
    assert read_pid(str(p)) is None
    p.write_text("12345\n")
    assert read_pid(str(p)) == 12345
    p.write_text("garbage")
    assert read_pid(str(p)) is None


def test_pid_alive():
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(99999999) is False
```

`tests/test_tun_worker.py`：

```python
import subprocess
import sys
import time


def test_tun_worker_tails_log_and_detects_exit(qtbot, tmp_path):
    """TunWorker 尾随日志文件、按 pidfile 监控进程存活（用真实子进程验证）"""
    from utils.tun_worker import TunWorker

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time; print('line1', flush=True); time.sleep(0.3); print('Client IP: 10.0.43.17', flush=True)"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    pidf.write_text(str(proc.pid))

    worker = TunWorker(str(log), str(pidf))
    lines, done = [], []
    worker.output.connect(lambda t: lines.append(t))
    worker.finished.connect(lambda c: done.append(c))
    worker.start()
    qtbot.waitUntil(lambda: len(done) == 1, timeout=5000)
    text = "".join(lines)
    assert "line1" in text and "Client IP: 10.0.43.17" in text


def test_tun_worker_stop_kills_process(qtbot, tmp_path, monkeypatch):
    from utils import tun_utils
    from utils.tun_worker import TunWorker

    killed = []
    monkeypatch.setattr(tun_utils, "kill_elevated", lambda pid: killed.append(pid) or True)
    # TunWorker 内部 from 引用 tun_utils 的函数——若直接 import 了 kill_elevated，
    # 需 patch tun_worker 命名空间；以 TunWorker 实现中的引用方式为准
    import utils.tun_worker as tw
    monkeypatch.setattr(tw, "kill_elevated", lambda pid: killed.append(pid) or True)

    log = tmp_path / "t.log"
    pidf = tmp_path / "t.pid"
    log.write_text("")
    pidf.write_text("424242")
    worker = TunWorker(str(log), str(pidf))
    worker.stop()
    assert killed == [424242]
```

`tests/test_rate_monitor.py`：

```python
from services.rate_monitor import _fmt_rate, find_tun_interface


def test_fmt_rate():
    assert _fmt_rate(512) == "512 B/s"
    assert _fmt_rate(2048) == "2.0 KB/s"
    assert _fmt_rate(3 * 1024 * 1024) == "3.0 MB/s"


def test_find_tun_interface(monkeypatch):
    import services.rate_monitor as rm

    class A:
        def __init__(self, address):
            self.address = address

    monkeypatch.setattr(
        rm.psutil, "net_if_addrs",
        lambda: {"en0": [A("192.168.1.2")], "utun4": [A("10.0.43.17")]},
    )
    assert find_tun_interface("10.0.43.17") == "utun4"
    assert find_tun_interface("9.9.9.9") is None
```

- [ ] **Step 4: 跑测试确认失败 → 实现三个新模块**

`app/utils/tun_utils.py`：

```python
# app/utils/tun_utils.py
"""TUN 模式支持：提权启动/停止内核、pid 管理、冲突检测。

提权方案（本期最简，后续可换 SMAppServices 特权助手）：
- macOS：osascript do shell script ... with administrator privileges（每次弹系统授权框）
- Linux：pkexec
- Windows：ShellExecute runas（UAC）+ .bat 包装（本期 best-effort，Windows 平台验证后置）

内核以 root 后台运行，输出重定向到日志文件；GUI 用 TunWorker 尾随解析。
注意：包装脚本经真实 shell 执行，参数必须 shlex.quote（这里 quoting 是对的——
与 B1 修复不矛盾：B1 是 subprocess list 不过 shell，这里过 shell）。
"""
import os
import shlex
import stat
import subprocess
import tempfile
from platform import system


def check_tun_conflict() -> str | None:
    """默认路由已在虚拟网卡上（如 Clash TUN）→ 返回该网卡名；否则 None。"""
    if system() == "Darwin":
        try:
            out = subprocess.check_output(["netstat", "-rn", "-f", "inet"], text=True)
            for line in out.splitlines():
                parts = line.split()
                if parts and parts[0] == "default" and parts[-1].startswith("utun"):
                    return parts[-1]
        except Exception:
            return None
    return None  # Windows/Linux 本期不做检测


def write_launcher(kernel_path: str, args: list, log_path: str, pid_path: str) -> str:
    """生成提权启动包装脚本，返回脚本路径。"""
    if system() == "Windows":
        quoted = " ".join(f'"{a}"' for a in [kernel_path, *args])
        content = f'@echo off\r\nstart /b "" {quoted} > "{log_path}" 2>&1\r\n'
        suffix = ".bat"
    else:
        quoted = " ".join(shlex.quote(a) for a in [kernel_path, *args])
        content = (
            "#!/bin/sh\n"
            f"nohup {quoted} > {shlex.quote(log_path)} 2>&1 &\n"
            f"echo $! > {shlex.quote(pid_path)}\n"
        )
        suffix = ".sh"
    fd, path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def spawn_elevated(launcher_path: str) -> bool:
    """提权执行包装脚本（授权框弹出期间不阻塞事件循环；用户取消返回 False）。"""
    if system() == "Darwin":
        r = subprocess.run(
            ["osascript", "-e",
             f'do shell script "/bin/sh {launcher_path}" with administrator privileges'],
            capture_output=True,
        )
        return r.returncode == 0
    if system() == "Linux":
        return subprocess.run(["pkexec", "/bin/sh", launcher_path]).returncode == 0
    if system() == "Windows":
        import ctypes

        return ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f'/c "{launcher_path}"', None, 0
        ) > 32
    return False


def read_pid(pid_path: str) -> int | None:
    try:
        with open(pid_path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """探测进程是否存活（无权限发信号说明是 root 进程，也视为存活）。"""
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def kill_elevated(pid: int) -> bool:
    """提权杀死内核进程（断开连接时可能再弹一次授权框）。"""
    if system() == "Darwin":
        r = subprocess.run(
            ["osascript", "-e",
             f'do shell script "kill {pid}" with administrator privileges'],
            capture_output=True,
        )
        return r.returncode == 0
    if system() == "Linux":
        return subprocess.run(["pkexec", "kill", str(pid)]).returncode == 0
    if system() == "Windows":
        return subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                              capture_output=True).returncode == 0
    return False
```

`app/utils/tun_worker.py`：

```python
# app/utils/tun_worker.py
"""TUN 模式 worker：内核以 root 后台运行，本 worker 尾随日志文件并监视 pid 存活。

与 CommandWorker 保持同一输出契约（output(str) / finished(int)），
handle_output / handle_connection_finished 无需区分模式。
"""
import time

from PySide6.QtCore import QThread, Signal

from utils.tun_utils import _pid_alive, kill_elevated, read_pid


class TunWorker(QThread):
    output = Signal(str)
    finished = Signal(int)

    # pidfile 出现前最长等待（覆盖用户输入授权密码的时间）
    PID_WAIT_TIMEOUT_S = 120

    def __init__(self, log_path: str, pid_path: str, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._pid_path = pid_path
        self._stop_requested = False

    def run(self):
        pid = None
        deadline = time.time() + self.PID_WAIT_TIMEOUT_S
        while pid is None and time.time() < deadline and not self._stop_requested:
            pid = read_pid(self._pid_path)
            if pid is None:
                self.msleep(200)

        position = 0
        while not self._stop_requested:
            try:
                with open(self._log_path, "r", errors="replace") as f:
                    f.seek(position)
                    chunk = f.read()
                    position = f.tell()
                if chunk:
                    for line in chunk.splitlines(keepends=True):
                        self.output.emit(line)
            except FileNotFoundError:
                pass
            if pid is None or not _pid_alive(pid):
                break
            self.msleep(300)
        self.finished.emit(-1)

    def stop(self):
        """非阻塞停止：置标志 + 提权 kill；收尾在 run() 循环退出后由 finished 完成。"""
        self._stop_requested = True
        pid = read_pid(self._pid_path)
        if pid is not None:
            kill_elevated(pid)
```

`app/services/rate_monitor.py`：

```python
# app/services/rate_monitor.py
"""TUN 模式速率监控：psutil 每秒读虚拟网卡计数差值，喂给仪表盘。"""
import psutil
from PySide6.QtCore import QObject, QTimer


def find_tun_interface(virtual_ip: str) -> str | None:
    """按虚拟 IP 定位 tun 网卡名（如 utun4）。"""
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.address == virtual_ip:
                return name
    return None


def _fmt_rate(bytes_per_sec: float) -> str:
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f} B/s"
    if bytes_per_sec < 1024**2:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    return f"{bytes_per_sec / 1024**2:.1f} MB/s"


class RateMonitor(QObject):
    def __init__(self, interface: str, on_rates, parent=None):
        super().__init__(parent)
        self._interface = interface
        self._on_rates = on_rates
        self._last = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._last = self._read()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _read(self):
        counters = psutil.net_io_counters(pernic=True).get(self._interface)
        return (counters.bytes_sent, counters.bytes_recv) if counters else None

    def _tick(self):
        current = self._read()
        if current is None:
            self.stop()
            return
        if self._last is not None:
            up = current[0] - self._last[0]
            down = current[1] - self._last[1]
            self._on_rates(_fmt_rate(max(up, 0)), _fmt_rate(max(down, 0)))
        self._last = current
```

- [ ] **Step 5: 跑测试确认通过**

```bash
uv run pytest tests/test_tun_utils.py tests/test_tun_worker.py tests/test_rate_monitor.py -v
```

- [ ] **Step 6: connection_utils.py 接 TUN 分支**

- `build_command_args`：`command_args.append("-disable-zju-config")` 之前加：

```python
    if getattr(window, "tun_mode", False):
        command_args.append("-tun-mode")
        command_args.append("-add-route")
```

- `start_connection`：在 `command_args = build_command_args(window, command)` 之后、创建 worker 处改为：

```python
    if getattr(window, "tun_mode", False):
        conflict = check_tun_conflict()
        if conflict:
            window.output_text.append(
                f"[BITZH Connect] 检测到默认路由已在虚拟网卡 {conflict}（如 Clash TUN），请先关闭再连\n"
            )
            window.status_panel.set_disconnected(hero="未连接", detail=f"与 {conflict} 的 TUN 冲突")
            # 按钮复位（早退同空凭据路径的处理）
            blocker = QSignalBlocker(window.connect_button)
            window.connect_button.setChecked(False)
            window.connect_button.setText("连接")
            window.username_input.setEnabled(True)
            window.password_input.setEnabled(True)
            if hasattr(window, "tray_connect_action"):
                window.tray_connect_action.setChecked(False)
            del blocker
            return
        import os
        import tempfile
        log_fd, log_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".log")
        os.close(log_fd)
        pid_fd, pid_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".pid")
        os.close(pid_fd)
        launcher = write_launcher(command, command_args[1:], log_path, pid_path)
        window._tun_pid_path = pid_path
        if not spawn_elevated(launcher):
            window.output_text.append("[BITZH Connect] 授权取消，未启动 TUN 连接\n")
            window.status_panel.set_disconnected(hero="未连接", detail="已取消授权")
            blocker = QSignalBlocker(window.connect_button)
            window.connect_button.setChecked(False)
            window.connect_button.setText("连接")
            window.username_input.setEnabled(True)
            window.password_input.setEnabled(True)
            if hasattr(window, "tray_connect_action"):
                window.tray_connect_action.setChecked(False)
            del blocker
            return
        window.worker = TunWorker(log_path, pid_path)
        window.worker.output.connect(lambda text: handle_output(window, text))
        window.worker.finished.connect(lambda code: handle_connection_finished(window, code))
        window.worker.start()
        window.status_panel.set_connecting()
        return
```

（import 区加 `from .tun_utils import check_tun_conflict, write_launcher, spawn_elevated`、`from .tun_worker import TunWorker`。）

- `handle_output`：在 `window.status_panel.set_connected(ip)` 之后加：

```python
        if getattr(window, "tun_mode", False) and hasattr(window, "start_rate_monitor"):
            window.start_rate_monitor(ip)
```

- `handle_connection_finished`：在状态复位前加：

```python
    if hasattr(window, "stop_rate_monitor"):
        window.stop_rate_monitor()
```

- [ ] **Step 7: main_window.py 加 rate monitor 生命周期**

```python
    def start_rate_monitor(self, virtual_ip: str):
        """TUN 连接成功后启动速率监控（tun 网卡创建可能滞后，最多等 5s）。"""
        self.stop_rate_monitor()
        from services.rate_monitor import RateMonitor, find_tun_interface

        def _try_start(attempts=0):
            interface = find_tun_interface(virtual_ip)
            if interface:
                self._rate_monitor = RateMonitor(interface, self.status_panel.set_rates, self)
                self._rate_monitor.start()
            elif attempts < 10:
                QTimer.singleShot(500, lambda: _try_start(attempts + 1))

        self._rate_monitor = None
        _try_start()

    def stop_rate_monitor(self):
        if getattr(self, "_rate_monitor", None):
            self._rate_monitor.stop()
            self._rate_monitor = None
```

（`__init__` 加 `self._rate_monitor = None`。）

- [ ] **Step 8: CI 捆 wintun.dll（Windows）**

`.github/workflows/release.yml` 的 Windows 构建段（下载 zju-connect 之后）加：

```yaml
        if [ "${{ runner.os }}" == "Windows" ]; then
          curl -L "https://www.wintun.net/builds/wintun-0.14.1.zip" -o wintun.zip
          powershell -command "Expand-Archive -Path wintun.zip -DestinationPath wintun"
          cp wintun/wintun/bin/amd64/wintun.dll app/core/
          rm -rf wintun wintun.zip
        fi
```

（放在 bash 步骤里还是分开按现有 yml 结构对齐；arm64 Windows 需取 `wintun/bin/arm64/wintun.dll`，按 matrix.arch 分支处理。）

- [ ] **Step 9: 全量回归 + Commit**

```bash
uv run pytest tests/ -v && git add -A && git commit -m "feat: TUN mode (privileged kernel launch, log-tail worker, rate monitor, conflict detection)"
```

预期：全 PASS。TUN 实际连接留到 Task 8 手动验证。

---

### Task 7: README / Clash 规则补全

**Files:**
- Modify: `README.md`、`README.zh-CN.md`
- Modify: `scripts/clash-utils.js`

- [ ] **Step 1: Clash 规则补 zhbit.com**

`scripts/clash-utils.js` 中 bitzh.edu.cn 规则旁加 `DOMAIN-SUFFIX,zhbit.com` 同向规则（走"校园网"代理组）。

- [ ] **Step 2: README 双语更新**

- Clash 配置示例 rules 加 `- "DOMAIN-SUFFIX,zhbit.com,校园网"`（英文版同位）
- 新增「TUN 模式」小节：高级设置开启、需管理员授权（macOS 每次连接/断开可能弹授权框）、与 Clash TUN 互斥、TUN 下速率显示真实数据
- 新增「资源入口」一句：连接成功后仪表盘出现电子图书馆/统一门户快捷入口
- 代理模式 SSH 提示：附 `~/.ssh/config` 的 ProxyCommand 示例（`nc -X 5 -x 127.0.0.1:1080 %h %p`）

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "docs: TUN mode guide, resource shortcuts, zhbit.com clash rules, SSH proxy hint"
```

---

### Task 8: 真实环境验证清单（手动，不可 mock）

逐项验证（每项发现问题单独 commit 修复）：

- [ ] **1. 退出不崩（F1）**：连接中点退出 / 托盘退出 / 连按两次退出 → 均不出现"python3 quit unexpectedly"
- [ ] **2. Dock 名（F2）**：`uv run app/main.py` 运行期间菜单栏（左上角苹果图标旁）显示 BITZH Connect；Dock 悬停标签若仍是 python3.11 属已知限制（打包后正确），记录即可
- [ ] **3. 文案不截断（F3）**：错密码连接 → hero 显示"认证失败"，副标题完整显示"请检查用户名和密码"
- [ ] **4. 一收一放动画**：连接成功瞬间凭据区收起+资源胶囊展开（250ms 平滑）；断开还原；动画中途反复点连接/断开无跳变
- [ ] **5. 资源入口**：连接成功 → 点"电子图书馆"→ 浏览器打开 elib.bitzh.edu.cn:8080 页面可访问；点"统一门户"同理
- [ ] **6. 外观三态**：高级设置 → 通用 → 外观：浅色/深色/跟随系统 切换即时生效（窗口标题栏 + 内容都跟随），重启 app 保持
- [ ] **7. TUN 连接**：高级设置开 TUN → 连接 → 弹授权框输密码 → 已连接后：① `ssh czr@10.8.18.32` 直接通（不带 ProxyCommand）② 浏览器内外网都正常 ③ 仪表盘上行/下行显示真实速率 ④ 浏览器访问校内资源正常
- [ ] **8. TUN 断开**：点断开 → 可能再弹一次授权框（kill）→ 断开后 `ping 10.8.18.32` 应失败（路由已撤）、外网正常
- [ ] **9. TUN 冲突检测**：先开 Clash TUN 模式 → 再开本 app TUN 连接 → 应提示冲突且不启动
- [ ] **10. 代理模式回归**：关掉 TUN → 常规连接、断开、自动重连（断 WiFi）、kill -9 残留清理、启动自动连接、托盘同步——上一轮 Task 11 清单全过一遍

---

## 后续阶段（本期不做）

- SMAppServices 特权助手（macOS 免每次授权框）
- Windows/Linux TUN 实机验证与打磨
- 资源自定义管理
