# 设置页分组卡片重排 + 菜单栏速度 + 发版版本号修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ①设置三页改"分组卡片"风（4A）并统一绿色；②菜单栏状态项可选显示实时速率（图标 + 两行：上行/下行，无箭头，仅连接时显示，右键菜单勾选、默认关）；③修复发布流水线的版本号 bug（产物内版本号与 release 不一致）。

**Architecture:** 设置页新增 `_card_group()` 把每组包成圆角卡片；菜单栏速度复用现有 `RateMonitor/ProxyRateMonitor` 的 `on_rates(up_text, down_text)` 通道，把两行文字渲染成模板 `NSImage` 设到 `NSStatusItem` 按钮（模板图随菜单栏深浅色自动反色）；开关经右键原生菜单项持久化到配置。发版 bug 在 `release.yml` 里按 tag 名覆盖 `.app-version`。

**Tech Stack:** Python 3.11 / PySide6 / pyobjc / pytest；macOS `NSStatusItem`。

**Spec:** 本轮 grilling 结论（4A / 1B / 2A / 上=上行 下=下行 / 无箭头 / 默认关 / 帮助页绿色）。

---

## 背景（给零上下文的工程师）

- 设置对话框：`app/views/advanced_panel.py` 的 `AdvancedSettingsDialog`，三个 tab（通用/网络/帮助），现有 `_group_header(text)`（标题+全宽线）与 `SettingRow`（左标签+右开关，行间细线）。
- 速率：`app/services/rate_monitor.py` 的 `RateMonitor`/`ProxyRateMonitor`，回调 `on_rates(up_text, down_text)`（**先上后下**）与 `on_sample(up_bps, down_bps)`；`_fmt_rate` 产生 "B/s/KB/s/MB/s"。`MainWindow.start_rate_monitor()` 目前把 `on_rates` 接到 `status_panel.set_rates`。
- 状态栏项：`app/utils/macos_status_item.py` 的 `MacStatusItem` 封装 `NSStatusItem`；右键菜单是声明式 `menu_spec`（`tray_utils.init_tray_icon` 里构建）。
- 版本显示：`get_version()` 读 QRC 里的 `.app-version`（打包时 `pyside6-rcc` 嵌入）。发版 bug：`release.yml` 的 `build` 任务 checkout 未指定 ref，tag 推送时检出的是 tag 提交（`.app-version` 仍是旧的），而 `update-version` 之后才把新版本写回 main。
- 测试命令：`.venv/bin/python -m pytest <path> -q`。

## File Structure

- `.github/workflows/release.yml` — 按 tag 覆盖 `.app-version`
- `app/views/advanced_panel.py` — 三页改分组卡片；帮助页绿色统一
- `app/utils/config_utils.py` — 新增 `menu_bar_speed`
- `app/utils/macos_status_item.py` — 状态项显示两行速率/恢复图标
- `app/views/main_window.py` — 速率喂给状态项、连接/断开门控、开关应用
- `app/utils/tray_utils.py` — 右键菜单加"在菜单栏显示速度"可勾选项
- `tests/test_advanced_panel.py`、`tests/test_config_utils.py`、`tests/test_menu_bar_speed.py`、`tests/test_menu_bar_panel.py`

---

## Task 1: 发版版本号修复（release.yml）

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: 在 build 任务、各平台编译之前，按 tag 覆盖 `.app-version`**

在 `build:` 任务里、"Install Dependencies"步骤之后（任何 `pyside6-rcc` 之前）插入：

```yaml
      # 修复：build checkout 未指定 ref，tag 构建时检出的是 tag 提交（.app-version 还是旧值）。
      # 这里直接按 tag 名覆盖，确保产物内嵌版本 === 发布版本。
      - name: Set version from tag
        if: startsWith(github.ref, 'refs/tags/v')
        shell: bash
        run: echo "${GITHUB_REF_NAME#v}" > .app-version
```

- [ ] **Step 2: 校验**

Run:
```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('yaml ok')"
grep -n "Set version from tag" .github/workflows/release.yml
```
Expected: `yaml ok`，且 grep 命中该步骤。

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/release.yml
git commit -m "fix(ci): 按 tag 覆盖 .app-version，修复产物版本号落后"
```

> 真机验证放在 Task 5（发 v1.3.6 后确认 app 内版本号 == 发布版本）。

---

## Task 2: 设置页"分组卡片"重排（4A）+ 帮助页绿色统一

**Files:**
- Modify: `app/views/advanced_panel.py`
- Test: `tests/test_advanced_panel.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_advanced_panel.py` 末尾追加：

```python
def test_groups_are_cards(qtbot):
    """设置页分组已改为卡片：每张卡片是带 SettingsCard 样式表的容器。"""
    from views.advanced_panel import AdvancedSettingsDialog

    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    cards = [
        w for w in dlg.findChildren(QWidget)
        if w.objectName() == "SettingsCard"
    ]
    assert len(cards) >= 4  # 通用 2 + 网络 3 + 帮助 2 中至少 4 张


def test_help_links_and_update_button_are_accent(qtbot):
    """帮助页链接与"检查更新"按钮统一为校徽绿。"""
    from common import theme
    from views.advanced_panel import AdvancedSettingsDialog

    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    accent = theme.semantic_color("accent").lower()
    assert accent in dlg.update_btn.styleSheet().lower()
    assert accent in dlg._help_links_label.text().lower()  # 链接色内联 accent
```

（需在文件顶部/用例内 `from PySide6.QtWidgets import QWidget`。）

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q -k "cards or help_links"`
Expected: FAIL（无 `SettingsCard`、无 `_help_links_label`、按钮非绿）。

- [ ] **Step 3: 新增卡片助手**

在 `AdvancedSettingsDialog` 内新增（放在 `_group_header` 附近）：

```python
    def _card_group(self, layout, title):
        """分组卡片：小号标题 + 圆角卡片容器；返回卡片内容的 QVBoxLayout。"""
        label = QLabel(title)
        font = label.font()
        font.setPointSize(12)
        font.setWeight(font.Weight.DemiBold)
        label.setFont(font)
        label.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; margin: 10px 4px 4px 4px;"
        )
        layout.addWidget(label)

        card = QWidget()
        card.setObjectName("SettingsCard")
        card.setStyleSheet(
            f"#SettingsCard {{ background: {theme.card_background()};"
            f" border-radius: 10px; }}"
        )
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 2, 0, 2)
        inner.setSpacing(0)
        layout.addWidget(card)
        return inner
```

- [ ] **Step 4: 按表把三页分组改成卡片**

把每个 `layout.addWidget(self._group_header("X"))` 替换为 `inner = self._card_group(layout, "X")`，其后该组的所有行/控件 `addWidget/addLayout` 的目标从 `layout` 改为 `inner`：

| Tab | 原分组标题 | 卡片内容（迁移目标） |
|---|---|---|
| 通用 | 启动 | startup/silent_mode/connect_startup 三个 SettingRow |
| 通用 | 外观与更新 | check_update/auto_reconnect 行 + appearance_row + hide_dock 行 |
| 网络 | 连接 | connect_form（服务端/端口）+ auto_dns 行 + dns_row |
| 网络 | 代理 | proxy_form（SOCKS5/HTTP）+ proxy_switch 行 |
| 网络 | （无，新增）系统 | 特权服务 SettingRow（原位于高级之上） |
| 网络 | 高级 | 高级 DisclosureHeader 改为卡片内的折叠行；卡片内容 = keep_alive/debug/auto_multi/tun 行 + tun_note + log_viewer + 日志按钮行 |
| 帮助 | 关于 | about 标签（链接改绿）+ 一行"检查更新"（左标签 + 右侧绿实心按钮 `update_btn`，复用 `_primary_button_style()`） |
| 帮助 | 校园网支持 | 两行（方案 A）：①「校园网校内管理」左主标题 + 副行"需连接校园网（或本 VPN）后访问"，右侧绿链接"打开 ↗"；②「校园网络中心电话」左主标题 + 副行"(0756) 3835303"，右侧次要按钮"复制"（点击复制电话到剪贴板） |

要点：
- `SettingRow` 的行间细线靠 `_has_following_row()`（下一项也是 SettingRow 才画）——放进卡片后自动只在行间画，卡片首/尾无孤线。
- `_group_header` 若不再被任何地方使用则删除；`_description` 保留。
- 高级折叠：把 `DisclosureHeader("高级")` 放进一张卡片作为标题行，`self.advanced_area` 作为卡片内内容，整体用 `_card_group` 包裹（或给 `advanced_area` 也套 `#SettingsCard` 容器）。

- [ ] **Step 5: 帮助页按方案 A 重排 + 绿色统一**

- **关于卡**：`about` 标签里 GitHub 仓库 / HITSZ / ZJU 三处 `<a>` 加 `style='color:{theme.semantic_color("accent")}; text-decoration: none;'`，并把该 QLabel 存为 `self._help_links_label`（供测试）。其后在同卡片内加一行"检查更新"：左 `QLabel("检查更新")` + 右侧 `self.update_btn`（套用 `_primary_button_style()`）。
- **校园网支持卡**：两行结构——
  ```python
        # 行1：校内管理（左信息 + 右绿链接）
        manage_row = QWidget(); mr = QHBoxLayout(manage_row)
        mr.setContentsMargins(14, 10, 14, 10); mr.setSpacing(12)
        mleft = QVBoxLayout(); mleft.setSpacing(1)
        mleft.addWidget(QLabel("校园网校内管理"))
        mleft.addWidget(self._description("需连接校园网（或本 VPN）后访问"))
        mr.addLayout(mleft, 1)
        campus_link = QLabel(
            f"<a href='http://10.7.0.103:9066/' style='color: {theme.semantic_color('accent')};"
            f" text-decoration: none;'>打开 ↗</a>"
        )
        campus_link.setOpenExternalLinks(True)
        campus_link.setCursor(Qt.PointingHandCursor)
        mr.addWidget(campus_link, 0, Qt.AlignVCenter)
        support_inner.addWidget(manage_row)

        # 行2：电话（左信息 + 右"复制"按钮）
        phone_row = QWidget(); pr = QHBoxLayout(phone_row)
        pr.setContentsMargins(14, 10, 14, 10); pr.setSpacing(12)
        pleft = QVBoxLayout(); pleft.setSpacing(1)
        pleft.addWidget(QLabel("校园网络中心电话"))
        pleft.addWidget(self._description("(0756) 3835303"))
        pr.addLayout(pleft, 1)
        self.copy_phone_btn = QPushButton("复制")
        self.copy_phone_btn.setStyleSheet(self._secondary_button_style())
        self.copy_phone_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText("(0756) 3835303")
        )
        pr.addWidget(self.copy_phone_btn, 0, Qt.AlignVCenter)
        support_inner.addWidget(phone_row)
  ```
  （`support_inner` 为「校园网支持」卡片的 `_card_group(...)` 返回的内层布局；行间细线由卡片内相邻行分隔，两行之间可加一条 1px `separator` 分隔。）
- `_secondary_button_style()` 若 Task 6(旧) 删除过，请按 `helper_setup_dialog` 的"取消"按钮同款次级样式重新提供（`card_background` 底 / `ink` 字 / 1px `separator` 描边 / radius 6 / padding 5px 12px）。

- [ ] **Step 5b: 更新对应测试**

`test_help_links_and_update_button_are_accent` 保留；追加：

```python
def test_copy_phone_button(qtbot):
    from PySide6.QtWidgets import QApplication
    from views.advanced_panel import AdvancedSettingsDialog

    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    dlg.copy_phone_btn.click()
    assert "3835303" in QApplication.clipboard().text()
```

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q`
Expected: 全部 PASS（`get_settings/set_settings` 行为不变）。

- [ ] **Step 7: 提交**

```bash
git add app/views/advanced_panel.py tests/test_advanced_panel.py
git commit -m "feat(settings): 三页改分组卡片风 + 帮助页绿色统一"
```

---

## Task 3: 配置键 menu_bar_speed

**Files:**
- Modify: `app/utils/config_utils.py`
- Test: `tests/test_config_utils.py`（若不存在则创建）

- [ ] **Step 1: 写失败测试**

创建/追加 `tests/test_config_utils.py`：

```python
def test_menu_bar_speed_default_off(qtbot):
    from utils.config_utils import load_config

    assert load_config()["menu_bar_speed"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_config_utils.py -q`
Expected: FAIL（KeyError / 缺键）。

- [ ] **Step 3: 加默认键**

在 `load_config()` 的 `default_config` 里、`"nav_expanded": False,` 之后加：

```python
        # 菜单栏状态项显示实时速率（右键菜单可开关；默认关）
        "menu_bar_speed": False,
```

- [ ] **Step 4: 运行确认通过并提交**

Run: `.venv/bin/python -m pytest tests/test_config_utils.py -q`
Expected: PASS。

```bash
git add app/utils/config_utils.py tests/test_config_utils.py
git commit -m "feat(config): 新增 menu_bar_speed"
```

---

## Task 4: 菜单栏速度显示（1B/2A）

**Files:**
- Modify: `app/utils/macos_status_item.py`
- Modify: `app/views/main_window.py`
- Modify: `app/utils/tray_utils.py`
- Test: `tests/test_menu_bar_speed.py`

- [ ] **Step 1: 写失败测试（纯逻辑门控 + 状态项接口）**

创建 `tests/test_menu_bar_speed.py`：

```python
def test_format_and_gate(qtbot):
    """确保：断开/未启用时不显示速率；启用且连接时显示两行（上=上行 下=下行）。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.menu_bar_speed = True

    calls = []
    win._mac_status_item = type(
        "S", (), {
            "set_speed": lambda self, up, down: calls.append(("speed", up, down)),
            "restore_icon": lambda self: calls.append(("icon",)),
        },
    )()

    # 未连接（无虚拟 IP）→ 不显示
    win.virtual_ip = None
    win._update_menu_bar_speed("1.0 KB/s", "2.0 KB/s")
    assert calls == []

    # 已连接 → 显示（上行在前）
    win.virtual_ip = "10.0.43.5"
    win._update_menu_bar_speed("1.0 KB/s", "2.0 KB/s")
    assert calls == [("speed", "1.0 KB/s", "2.0 KB/s")]

    # 关闭开关 → 恢复图标
    win.menu_bar_speed = False
    win._update_menu_bar_speed("1.0 KB/s", "2.0 KB/s")
    assert calls[-1] == ("icon",)

    win.reconnect_manager.cancel()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_speed.py -q`
Expected: FAIL（`_update_menu_bar_speed` 不存在）。

- [ ] **Step 3: 状态栏项支持两行速率图**

在 `app/utils/macos_status_item.py` 增加：

```python
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
```

在 `MacStatusItem` 增加方法：

```python
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
```

- [ ] **Step 4: MainWindow 接线（喂数 + 门控 + 开关）**

4a. `load_settings(self)` 里读取配置（`app/utils/config_utils.py` 的 `load_settings` 加 `self.menu_bar_speed = config["menu_bar_speed"]`）。

4b. 在 `MainWindow` 增加：

```python
    def _update_menu_bar_speed(self, up_text: str, down_text: str):
        """按开关与连接态更新菜单栏速率：开且已连接→两行速率；否则恢复图标。"""
        item = getattr(self, "_mac_status_item", None)
        if item is None:
            return
        if getattr(self, "menu_bar_speed", False) and getattr(self, "virtual_ip", None):
            item.set_speed(up_text, down_text)
        else:
            item.restore_icon()

    def set_menu_bar_speed(self, enabled: bool):
        """右键菜单勾选切换：写配置并即时应用。"""
        self.menu_bar_speed = bool(enabled)
        config = load_config()
        config["menu_bar_speed"] = self.menu_bar_speed
        save_config(config)
        if not self.menu_bar_speed:
            item = getattr(self, "_mac_status_item", None)
            if item is not None:
                item.restore_icon()
        elif getattr(self, "virtual_ip", None):
            item = getattr(self, "_mac_status_item", None)
            if item is not None and getattr(self, "_last_rates", None):
                up, down = self._last_rates
                item.set_speed(up, down)
```

4c. `start_rate_monitor`：把 `on_rates` 从 `self.status_panel.set_rates` 改为一个包装方法，既喂状态面板又喂菜单栏：

```python
        def _on_rates(up_text, down_text):
            self.status_panel.set_rates(up_text, down_text)
            self._last_rates = (up_text, down_text)
            self._update_menu_bar_speed(up_text, down_text)

        on_rates = _on_rates
        on_sample = self.status_panel.append_rate_sample
```

（`self._last_rates = None` 在 `__init__` 初始化。）

4d. 断线收尾：`handle_connection_finished` 已调用 `stop_rate_monitor`；在 `MainWindow.stop_rate_monitor` 里加：

```python
        self._last_rates = None
        item = getattr(self, "_mac_status_item", None)
        if item is not None:
            item.restore_icon()
```

- [ ] **Step 5: 右键菜单加可勾选项**

`app/utils/tray_utils.py` 的 `init_tray_icon` 里，macOS 的 `menu_spec` 在 `VPN 连接` 与分隔符之间（或之后）插入：

```python
            {
                "title": "在菜单栏显示速度",
                "action": lambda: window.set_menu_bar_speed(not window.menu_bar_speed),
                "is_checked": lambda: bool(getattr(window, "menu_bar_speed", False)),
            },
```

> 该入口仅 macOS 原生菜单路径有；Windows/Linux 的 Qt 菜单不加快捷项（菜单栏速度是 macOS 概念）。

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_menu_bar_speed.py tests/test_config_utils.py tests/test_main_window.py -q`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/utils/macos_status_item.py app/views/main_window.py app/utils/tray_utils.py app/utils/config_utils.py tests/test_menu_bar_speed.py
git commit -m "feat(menubar): 状态项可选显示两行速率（开源默认关，右键菜单开关）"
```

---

## Task 5: 全量回归 + 真机验证 + 发 v1.3.6

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 2: 真机验证（打包版）**

1. 设置三页确为分组卡片、间距合适、无多余线条；帮助页链接与「检查更新」为绿。
2. 右键状态栏图标 → 勾选「在菜单栏显示速度」→ 连接后状态项显示两行（上=上行、下=下行、无箭头）；断开后恢复图标；取消勾选立即恢复图标。
3. 重启 app，"显示速度"开关状态被记住。
4. 发 v1.3.6 后，帮助页版本号应显示 **1.3.6**（验证 Task 1 修复）。

- [ ] **Step 3: 合并 + 发版（用户执行）**

```bash
git checkout main && git merge --ff-only <feature-branch>
git push origin main
git tag v1.3.6 && git push origin v1.3.6
```
Expected: CI 全绿；release v1.3.6 产物内版本号 = 1.3.6。

---

## 完成标准

- 发版产物内嵌版本号与 tag/Release 一致（`.app-version` 按 tag 覆盖）。
- 设置三页为分组卡片风，帮助页链接/按钮绿色。
- 菜单栏状态项可在右键菜单勾选显示实时速率（图标+两行，上行在上、下行在下、无箭头），仅连接时显示，默认关、持久化。
- 全量测试通过、真机验证通过、v1.3.6 发布。
