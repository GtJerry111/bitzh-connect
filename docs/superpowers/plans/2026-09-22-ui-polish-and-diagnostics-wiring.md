# UI 打磨与断开诊断接线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接线已实现但未使用的断开诊断解析函数；打磨若干 UI（特权服务双态入口、"稍后"警示、深色图标/值对比度、蓝色高亮统一为校徽绿）。

**Architecture:** 纯前端/接线改动，不新增子系统。接线走 `handle_output`→`window._disconnect_reason/_tun_interface`→`handle_connection_finished` 诊断行；UI 改动集中在 `advanced_panel` / `helper_setup_dialog` / `menu_bar_panel` / `chevron` / `theme`。

**Tech Stack:** Python 3.11 / PySide6 / pytest（offscreen）。

**Spec:** 本轮 grilling 结论（见 commit 讨论）。无独立 spec 文件。

---

## 背景（给零上下文的工程师）

- `app/utils/log_parser.py` 里 `classify_disconnect()`/`parse_tun_interface()`/`is_keepalive()` 已实现且测试通过，但**全仓零调用**（死代码），导致"连接结束"诊断行没有"断开原因"。
- TUN 特权服务：helper 安装/卸载能力已实现，但设置面板只在"已安装"时显示一个全宽灰色"卸载"按钮；未安装时没有任何安装入口（首次连接点"稍后"后就再也装不了）。
- 深色下菜单栏面板的行图标/箭头/"TUN"值用 `secondary_text`（中灰），在磨砂底上发灰。
- 高级设置里 tab 选中、复选框勾选是 macOS 原生**蓝色**（系统强调色），未统一为校徽绿。
- 测试命令：`.venv/bin/python -m pytest <path> -q`。

## File Structure

- `app/utils/connection_utils.py` — 接线三个解析函数；诊断行加"原因/接口"
- `app/views/advanced_panel.py` — 特权服务双态行入口
- `app/views/helper_setup_dialog.py` — "稍后"二次确认
- `app/views/menu_bar_panel.py` — 行图标/值改 ink
- `app/views/chevron.py` — Chevron 支持自定义颜色
- `app/common/theme.py` — 全局高亮调色板改校徽绿
- `tests/test_connection_flow.py`、`tests/test_advanced_panel.py`、`tests/test_helper_setup_dialog.py`、`tests/test_menu_bar_panel.py`、`tests/test_theme.py`

---

## Task 1: 断开原因 / TUN 接口 / keepalive 心跳接线

**Files:**
- Modify: `app/utils/connection_utils.py`
- Test: `tests/test_connection_flow.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_connection_flow.py` 末尾追加：

```python
def test_disconnect_reason_and_interface_logged(qtbot, monkeypatch):
    """内核输出经 classify_disconnect/parse_tun_interface 记录，"连接结束"行带上原因/接口。"""
    import utils.connection_utils as cu
    from utils.connection_utils import handle_output, handle_connection_finished

    win = _make_window(qtbot)
    win._watchdog = None
    win._disconnect_reason = None
    win._tun_interface = None
    logs = []
    monkeypatch.setattr(cu.diagnostics, "append", lambda line: logs.append(line))

    handle_output(win, "2026/09/22 14:32:17 Interface Name: utun11, index 32\n")
    handle_output(win, "2026/09/22 14:34:00 SHUTDOWN (cmd 0x08)\n")
    assert win._tun_interface == "utun11"
    assert win._disconnect_reason == "server_kick"

    win._manual_stop = False
    win._auth_failed = False
    handle_connection_finished(win, -1)
    joined = "\n".join(logs)
    assert "原因=server_kick" in joined
    assert "接口=utun11" in joined


def test_keepalive_only_refreshes_watchdog(qtbot):
    """只有 keepalive 行才刷新看门狗活跃度（普通输出不算心跳）。"""
    from utils.connection_utils import handle_output

    win = _make_window(qtbot)
    noted = []
    win._watchdog = type(
        "W", (), {
            "note_activity": lambda self: noted.append(1),
            "start": lambda self: None,
            "stop": lambda self: None,
        },
    )()

    handle_output(win, "2026/09/22 14:32:18 an ordinary output line\n")
    assert noted == []
    handle_output(win, "2026/09/22 14:33:17 KeepAlive using UDP: OK\n")
    assert noted == [1]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_connection_flow.py -q -k "disconnect_reason or keepalive_only"`
Expected: FAIL（`handle_output` 目前不记录 reason/interface，也不按 keepalive 门控）。

- [ ] **Step 3: 实现接线**

3a. 顶部导入行改为：

```python
from .log_parser import (
    parse_client_ip,
    is_auth_failure,
    is_server_kick,
    is_rsa_material,
    classify_disconnect,
    is_keepalive,
    parse_tun_interface,
)
```

3b. `handle_output` 开头（`watchdog = getattr(...)` 之前）插入解析与打点，并改 keepalive 门控：

```python
def handle_output(window, text):
    """处理内核输出：上屏 + 解析状态"""
    # 断开原因 / TUN 接口：记录本次连接最后一条可分类结果，供收尾诊断使用
    reason = classify_disconnect(text)
    if reason is not None:
        window._disconnect_reason = reason
    iface = parse_tun_interface(text)
    if iface is not None:
        window._tun_interface = iface
    watchdog = getattr(window, "_watchdog", None)
    if watchdog is not None and is_keepalive(text):
        watchdog.note_activity()
    diagnostics.append(text)
```

3c. `start_connection` 中重置每连接状态。在 `window._rsa_noted = False` 之后加：

```python
    window._disconnect_reason = None
    window._tun_interface = None
```

3d. `handle_connection_finished` 的收尾诊断行改为：

```python
    route = capturing_tun_for(getattr(window, "server_address", "")) or "物理网卡"
    reason = getattr(window, "_disconnect_reason", None)
    if reason is None:
        reason = "manual" if manual else ("auth" if auth_failed else "unknown")
    iface = getattr(window, "_tun_interface", None) or "-"
    diagnostics.append(
        f"连接结束 exit={exit_code} manual={manual} auth_failed={auth_failed} "
        f"原因={reason} 接口={iface} 服务器路由出口={route}"
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_connection_flow.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/utils/connection_utils.py tests/test_connection_flow.py
git commit -m "feat(diagnostics): 接线断开原因/TUN 接口/keepalive 心跳"
```

---

## Task 2: 特权服务双态行入口

**Files:**
- Modify: `app/views/advanced_panel.py`
- Test: `tests/test_advanced_panel.py`

- [ ] **Step 1: 写失败测试**

把 `tests/test_advanced_panel.py` 里现有用例 `test_uninstall_helper_button_runs_uninstall` 替换为（属性名由 `uninstall_helper_button` 改为 `helper_button`）：

```python
def test_helper_row_uninstall_runs(qtbot, monkeypatch):
    from views import advanced_panel as mod
    from views.advanced_panel import AdvancedSettingsDialog

    monkeypatch.setattr(mod, "system", lambda: "Darwin")
    monkeypatch.setattr(mod.helper_installer, "is_installed", lambda: True)
    monkeypatch.setattr(mod.helper_installer, "can_install", lambda: True)
    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "uninstall_async", lambda on_done: calls.append(on_done)
    )
    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.helper_button.text() == "卸载特权服务"
    dlg.helper_button.click()
    assert calls  # 触发卸载
    assert not dlg.helper_button.isEnabled()  # 卸载中禁用防重复


def test_helper_row_install_state(qtbot, monkeypatch):
    from views import advanced_panel as mod
    from views.advanced_panel import AdvancedSettingsDialog

    monkeypatch.setattr(mod, "system", lambda: "Darwin")
    monkeypatch.setattr(mod.helper_installer, "is_installed", lambda: False)
    monkeypatch.setattr(mod.helper_installer, "can_install", lambda: True)
    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.helper_button.text() == "安装特权服务"
    assert dlg.helper_button.isEnabled()


def test_helper_row_install_opens_dialog(qtbot, monkeypatch):
    from views import advanced_panel as mod
    from views import helper_setup_dialog as hsd
    from views.advanced_panel import AdvancedSettingsDialog

    monkeypatch.setattr(mod, "system", lambda: "Darwin")
    state = {"installed": False}
    monkeypatch.setattr(mod.helper_installer, "is_installed", lambda: state["installed"])
    monkeypatch.setattr(mod.helper_installer, "can_install", lambda: True)

    opened = []

    class _FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            opened.append(True)
            state["installed"] = True  # 模拟安装成功
            return 1

    monkeypatch.setattr(hsd, "HelperSetupDialog", _FakeDialog)
    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.helper_button.text() == "安装特权服务"
    dlg.helper_button.click()
    assert opened == [True]
    assert dlg.helper_button.text() == "卸载特权服务"  # 装完刷新为卸载
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q -k helper`
Expected: FAIL（`helper_button` 不存在 / 双态未实现）。

- [ ] **Step 3: 实现双态行**

3a. 把 `setup_ui` 里现有块（`if system() == "Darwin" and helper_installer.is_installed(): ... else: ...`，约 347-357 行）整体替换为：

```python
        # ---- 特权服务（macOS）：双态行入口——未装可装、已装可卸 ----
        if system() == "Darwin" and helper_installer.is_supported():
            network_layout.addWidget(self._group_header("特权服务"))
            priv_row = QWidget()
            priv_layout = QHBoxLayout(priv_row)
            priv_layout.setContentsMargins(0, 0, 0, 0)
            priv_layout.addWidget(QLabel("TUN 特权服务"))
            priv_layout.addStretch()
            self.helper_button = QPushButton()
            self.helper_button.setMinimumWidth(96)
            self.helper_button.setStyleSheet(self._secondary_button_style())
            self.helper_button.clicked.connect(self._on_helper_button)
            priv_layout.addWidget(self.helper_button)
            network_layout.addWidget(priv_row)
            self._helper_hint = self._description("")
            network_layout.addWidget(self._helper_hint)
            self._refresh_helper_row()
        else:
            self.helper_button = QPushButton()
            self.helper_button.setVisible(False)
            self._helper_hint = self._description("")
            self._helper_hint.setVisible(False)
```

3b. 新增方法（放在 `_uninstall_helper` 附近，替换掉旧的 `_uninstall_helper`）：

```python
    def _secondary_button_style(self) -> str:
        """次级描边按钮样式（与安装对话框"取消"同款几何）。"""
        return f"""
            QPushButton {{
                background-color: {theme.card_background()};
                color: {theme.semantic_color("ink")};
                border: 1px solid {theme.semantic_color("separator")};
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12pt;
            }}
            QPushButton:hover {{
                background-color: {theme.with_alpha("accent", 0.08)};
            }}
            QPushButton:disabled {{
                color: {theme.semantic_color("secondary_text")};
            }}
        """

    def _refresh_helper_row(self):
        """按安装状态刷新按钮文案/可用性/说明。"""
        if not hasattr(self, "helper_button") or not helper_installer.is_supported():
            return
        if helper_installer.is_installed():
            self.helper_button.setText("卸载特权服务")
            self.helper_button.setEnabled(True)
            self._helper_hint.setText("移除 TUN 特权服务；卸载应用前建议先点此清理")
        else:
            self.helper_button.setText("安装特权服务")
            can = helper_installer.can_install()
            self.helper_button.setEnabled(can)
            self._helper_hint.setText(
                "安装后 TUN 连接免输管理员密码（一次授权、长期有效）"
                if can
                else "当前环境无法安装特权服务（需使用打包后的应用）"
            )

    def _on_helper_button(self):
        if helper_installer.is_installed():
            self._uninstall_helper()
        else:
            self._install_helper()

    def _install_helper(self):
        from views import helper_setup_dialog

        dialog = helper_setup_dialog.HelperSetupDialog(self)
        dialog.exec()
        self._refresh_helper_row()

    def _uninstall_helper(self):
        """卸载 TUN 特权服务（一次授权），完成后刷新为"安装"态。"""
        self.helper_button.setEnabled(False)

        def _done(ok: bool):
            self.helper_button.setEnabled(True)
            self._refresh_helper_row()

        helper_installer.uninstall_async(_done)
```

> 注：`QWidget`/`QLabel`/`QHBoxLayout`/`QPushButton` 均已在文件顶部导入。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q`
Expected: 全部 PASS（含更新后的三个 helper 用例）。

- [ ] **Step 5: 提交**

```bash
git add app/views/advanced_panel.py tests/test_advanced_panel.py
git commit -m "feat(settings): 特权服务改为安装/卸载双态行入口"
```

---

## Task 3: 「稍后」二次确认（告知 = 每次授权）

**Files:**
- Modify: `app/views/helper_setup_dialog.py`
- Test: `tests/test_helper_setup_dialog.py`

- [ ] **Step 1: 写失败测试**

把 `tests/test_helper_setup_dialog.py` 里 `test_cancel_rejects_without_running_installer` 改为（新增确认 seam），并追加两个用例：

```python
def test_cancel_rejects_without_running_installer(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async", lambda on_done: calls.append(on_done)
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    monkeypatch.setattr(dlg, "_confirm_later", lambda: True)  # 用户确认"仍要稍后"
    dlg.cancel_button.click()
    assert not calls  # "稍后"不触发安装
    assert dlg.result() == dlg.DialogCode.Rejected


def test_cancel_returning_to_install_keeps_dialog(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    monkeypatch.setattr(dlg, "_confirm_later", lambda: False)  # 用户点"返回安装"
    dlg.cancel_button.click()
    assert dlg.result() != dlg.DialogCode.Rejected  # 未关闭


def test_later_warning_mentions_osascript(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    text = dlg.later_warning_text()
    assert "每次" in text and ("授权" in text or "密码" in text)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_setup_dialog.py -q -k "cancel or later"`
Expected: FAIL（`_confirm_later`/`later_warning_text` 不存在）。

- [ ] **Step 3: 实现**

3a. 常量（放在 `_OPERATIONS` 之后）：

```python
_LATER_WARNING = (
    "选择“稍后”将回退为每次连接时授权（osascript），"
    "每次连接 TUN 都需要输入管理员密码。\n"
    "你稍后可在「设置 → 网络 → 特权服务」里安装。"
)
```

3b. `cancel_button.clicked` 由 `self.reject` 改为 `self._on_later`：

```python
        self.cancel_button.clicked.connect(self._on_later)
```

3c. 新增方法（放在 `status_text` 之后）：

```python
    def later_warning_text(self) -> str:
        return _LATER_WARNING

    def _on_later(self):
        if self._confirm_later():
            self.reject()

    def _confirm_later(self) -> bool:
        """点"稍后"时的二次确认；返回 True = 确认稍后（回退每次授权）。"""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("将改用每次授权模式")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(_LATER_WARNING)
        back = box.addButton("返回安装", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("仍要稍后", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(back)
        box.exec()
        return box.clickedButton() is later
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_setup_dialog.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/views/helper_setup_dialog.py tests/test_helper_setup_dialog.py
git commit -m "feat(helper): 点“稍后”二次确认，告知回退为每次授权"
```

---

## Task 4: 深色模式行图标/值/箭头改 `ink`

**Files:**
- Modify: `app/views/menu_bar_panel.py`
- Modify: `app/views/chevron.py`
- Test: `tests/test_menu_bar_panel.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_menu_bar_panel.py` 末尾追加：

```python
def test_row_value_uses_ink(panel):
    from common import theme

    assert theme.semantic_color("ink") in panel._mode_row.value.styleSheet()


def test_row_icon_uses_ink(panel):
    assert panel._mode_row_icon.color_name == "ink"


def test_nav_chevron_uses_ink(panel):
    assert panel._nav_chevron._color_name == "ink"
```

> 若 `panel` fixture 未暴露 `_mode_row_icon`，见 Step 3 的命名调整。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_panel.py -q -k "ink"`
Expected: FAIL。

- [ ] **Step 3: 实现**

3a. `chevron.py`：`Chevron` 支持自定义颜色名（默认保持 `secondary_text`，不影响高级设置里的用法）：

```python
    def __init__(self, parent=None, color_name: str = "secondary_text"):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._angle = 0.0
        self._color_name = color_name
```

并把 `paintEvent` 中的颜色改为 `theme.semantic_color(self._color_name)`。

3b. `menu_bar_panel.py`：
- `_Icon.__init__` 增加 `color_name: str = "ink"` 参数并存 `self.color_name = color_name`；`paintEvent` 用 `theme.semantic_color(self.color_name)` 取代 `secondary_text`。
- `_Row.__init__` 保存图标引用：`self._icon = _Icon(icon_kind); row.addWidget(self._icon)`（供测试/后续用）。
- `_Row.refresh_theme` 的 `self.value.setStyleSheet(...)` 颜色由 `secondary_text` 改为 `ink`。
- `_mode_row` 的图标暴露为 `self._mode_row_icon`（即 `self._mode_row._icon`），便于测试。
- `_nav_chevron = Chevron(color_name="ink")`。

> 具体：在 `MenuBarPanel` 构建 `_mode_row` 处，存 `self._mode_row_icon = self._mode_row._icon`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_panel.py tests/test_advanced_panel.py tests/test_main_window.py -q`
Expected: 全部 PASS（Chevron 默认色未变，高级设置折叠头不受影响）。

- [ ] **Step 5: 提交**

```bash
git add app/views/menu_bar_panel.py app/views/chevron.py tests/test_menu_bar_panel.py
git commit -m "style(panel): 行图标/值/箭头深色下改用 ink 提对比"
```

---

## Task 5: 蓝色高亮统一为校徽绿（全局调色板）

**Files:**
- Modify: `app/common/theme.py`
- Test: `tests/test_theme.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_theme.py` 末尾追加：

```python
def test_highlight_palette_follows_accent(qtbot):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from common import theme

    theme.set_appearance("light")
    got = QApplication.instance().palette().color(QPalette.ColorRole.Highlight).name().lower()
    assert got == theme.semantic_color("accent").lower()

    theme.set_appearance("dark")
    got = QApplication.instance().palette().color(QPalette.ColorRole.Highlight).name().lower()
    assert got == theme.semantic_color("accent").lower()

    theme.set_appearance("system")  # 复位，避免影响其它用例
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_theme.py -q -k highlight`
Expected: FAIL（当前 palette Highlight 是系统蓝）。

- [ ] **Step 3: 实现**

3a. 在 `theme.py` 增加函数（放在 `semantic_color` 之后）：

```python
def apply_highlight_palette():
    """把控件高亮色（复选框/tab/文本选择等）统一为校徽绿 accent。"""
    try:
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(semantic_color("accent")))
        pal.setColor(
            QPalette.ColorRole.HighlightedText, QColor(semantic_color("accent_text"))
        )
        app.setPalette(pal)
    except Exception as e:  # 平台差异下不致命：退回系统高亮
        print(f"[theme] 应用高亮调色板失败: {e}", file=sys.stderr)
```

3b. 在 `_run_refresh()` 开头调用它（覆盖启动、切外观、系统深浅色变化）：

```python
def _run_refresh():
    apply_highlight_palette()
    alive = []
    ...
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_theme.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 真机确认（关键，A 方案可能对原生复选框无效）**

打包或源码启动后，打开高级设置：确认
- 选中 tab 是否变绿；
- 勾选的复选框是否变绿。
若仍有蓝色残留（macOS 原生样式忽略 palette），**记录现象并升级到方案 B**（QSS 显式覆盖 `QTabBar::tab:selected` + `QCheckBox::indicator:checked` 用绿勾资源），另开任务——本任务先按 A 交付。

- [ ] **Step 6: 提交**

```bash
git add app/common/theme.py tests/test_theme.py
git commit -m "style(theme): 全局高亮色统一为校徽绿（palette Highlight）"
```

---

## Task 6: 全量回归 + 真机验证 + 发布（v1.3.5）

**Files:** 无代码改动（发布流程）

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 2: 真机验证（打包版）**

1. 按 release.yml 的 macOS 命令打包（`--standalone` app + `PYTHONPATH=app nuitka --onefile` helper，helper 放入 `Contents/MacOS/`），装入 `/Applications`。
2. 验证 Task 2：设置 → 网络 → 特权服务，未装时显示「安装特权服务」，点击弹安装引导，装好显示「卸载特权服务」。
3. 验证 Task 3：删除 helper（卸载）后再触发首次连接安装引导，点「稍后」应弹确认框，文案含"每次连接都需要输入管理员密码"。
4. 验证 Task 4：深色模式下菜单栏面板的图标/箭头/"TUN" 显示为白色/高对比。
5. 验证 Task 5：高级设置里 tab 选中与复选框是否为绿色（若仍蓝 → 记入 backlog 走方案 B）。
6. 验证 Task 1：连接后断开（被服务器踢或拔网），查看 `~/Library/Logs/BITZH Connect/bitzh-connect.log` 的"连接结束"行是否含 `原因=` 与 `接口=`。

- [ ] **Step 3: 发布 v1.3.5（用户操作）**

合并到 `main` 后打 tag 并推送（CI 会自动把 `.app-version` 写为 1.3.5 并提交回 main）：

```bash
git checkout main
git merge --ff-only feat/ui-polish-and-diagnostics-wiring
git tag v1.3.5
git push origin main --tags
```

Expected: GitHub Actions 触发 build；`update-version` job 把 `.app-version` 更新为 `1.3.5`；发布页面出现 v1.3.5 的 DMG。之后本地 `git pull` 拿到版本 bump。

---

## 完成标准

- "连接结束"诊断行含 `原因=`（server_kick/auth/network/manual/unknown）与 `接口=`。
- 设置里特权服务为安装/卸载双态；未装可一键安装。
- 点「稍后」有明确二次确认，告知将改为每次授权。
- 深色面板行图标/值/箭头为 `ink`（高对比）。
- 全局高亮尝试统一为校徽绿（A 方案）；若原生控件仍蓝，记录并转 B。
- v1.3.5 tag 推进后 `.app-version` 与 GitHub Release 对齐。
