# 连接区控件"仿玻璃透出校训" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让主窗口的「模式分段控件」与「连接/断开主按钮」呈现玻璃质感——连接态下能**透出并模糊其后的校训水印**（浅色明显、深色随水印淡化）。

**Architecture:** 窗口背景只有"纯色 + 校训水印"两层，故**不需要真正的 backdrop 采样**：由 `WatermarkContainer` 在绘制时，把水印的**预模糊副本**裁剪绘制到"注册为玻璃"的控件矩形内（其余区域仍画清晰水印）；这些控件自身背景改为**半透明**，于是身后的模糊水印透出。确定生效、不依赖系统毛玻璃。

**Tech Stack:** PySide6 QPainter / QGraphicsBlurEffect / pytest（offscreen）。

**Spec:** 本轮 grilling 结论（范围=分段 + 主按钮两态；实现=仿玻璃；深色接受弱效果）。可视化：`bitzh-motto-glass2.html`。

---

## 背景（给零上下文的工程师）

- `WatermarkContainer`（`app/views/main_window.py`）的 `paintEvent` 在最底层画校训水印（右侧竖排、含量与深浅色基准 `_WATERMARK_OPACITY` 相乘）；子控件画在其上。水印显隐由 `set_motto_visible`（凭据区可见时隐藏、连接后淡入）。
- `SegmentedModeSwitch`（`app/views/mode_switch.py`）自绘：轨道 + 药丸 + 文案，颜色取 `theme.semantic_color(...)`（不透明）。
- 连接按钮 `MainWindow.connect_button`（`QPushButton`），样式在 `_apply_connect_button_style` 里用 QSS 双态设置（连接=绿实心、断开=绿描边）。
- `theme.with_alpha(name, alpha)` 返回 QSS 用的 `rgba(r,g,b,a)` 字符串；`theme.qcolor(name, alpha=None)` 返回 `QColor`。
- 校训素材：`:/brand/motto.png`（194×500）。测试命令：`.venv/bin/python -m pytest <path> -q`（offscreen）。

## File Structure

- `app/views/main_window.py` — `WatermarkContainer` 支持"玻璃控件"注册 + 模糊水印裁剪绘制；注册两个控件。
- `app/views/mode_switch.py` — 轨道/药丸改半透明玻璃 + 描边高光。
- `app/views/main_window.py` — 连接按钮双态改半透明玻璃 QSS。
- `tests/test_watermark_glass.py`（新建）、`tests/test_mode_switch.py`（追加）、`tests/test_main_window.py`（追加）

---

## Task 1: WatermarkContainer 支持玻璃控件（模糊水印裁剪）

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_watermark_glass.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_watermark_glass.py`：

```python
def test_glass_widgets_registered(qtbot):
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    container = win.centralWidget()
    assert win.mode_switch in container.glass_controls()
    assert win.connect_button in container.glass_controls()
    win.reconnect_manager.cancel()


def test_blur_cache_reused(qtbot):
    """同一张缩放水印只模糊一次（缓存命中）。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    container = win.centralWidget()
    scaled = container._watermark.scaledToHeight(120)
    b1 = container._blurred(scaled)
    b2 = container._blurred(scaled)
    assert b1 is b2  # 命中缓存返回同一对象
    win.reconnect_manager.cancel()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_watermark_glass.py -q`
Expected: FAIL（`glass_controls` / `_blurred` 不存在）。

- [ ] **Step 3: 实现**

在 `WatermarkContainer.__init__` 增加：

```python
        self._glass_controls = []   # 需要"磨砂透出校训"的控件
        self._blur_cache = None
        self._blur_key = None
```

新增方法：

```python
    def register_glass(self, widget):
        """登记一个需要磨砂玻璃效果的控件（其矩形内绘制模糊水印）。"""
        if widget is not None and widget not in self._glass_controls:
            self._glass_controls.append(widget)

    def glass_controls(self):
        return list(self._glass_controls)

    def _blurred(self, scaled):
        """返回 scaled 的模糊副本（按 cacheKey 缓存，避免每次重画都模糊）。"""
        key = scaled.cacheKey()
        if self._blur_key == key and self._blur_cache is not None:
            return self._blur_cache
        from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene
        from PySide6.QtCore import QRectF

        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(scaled)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(7)
        item.setGraphicsEffect(blur)
        scene.addItem(item)
        out = QPixmap(scaled.size())
        out.fill(Qt.transparent)
        painter = QPainter(out)
        scene.render(painter, QRectF(out.rect()), QRectF(scaled.rect()))
        painter.end()
        self._blur_key = key
        self._blur_cache = out
        return out
```

把 `paintEvent` 的水印绘制段改为（在原 `painter.drawPixmap(x, y, scaled)` 之后、`painter.end()` 之前插入玻璃区域绘制）：

```python
        painter.setOpacity(base * self._motto_level)
        painter.drawPixmap(x, y, scaled)
        # 玻璃控件区域：把该区域的水印换成"模糊版"——控件半透明背景即透出磨砂水印
        blurred = self._blurred(scaled)
        from PySide6.QtCore import QPoint, QRect

        for widget in self._glass_controls:
            if widget is None or not widget.isVisible():
                continue
            rect = QRect(widget.mapTo(self, QPoint(0, 0)), widget.size())
            painter.save()
            painter.setClipRect(rect)
            painter.drawPixmap(x, y, blurred)
            painter.restore()
        painter.end()
```

在 `setup_ui` 末尾（`container` 创建并 `setCentralWidget` 之后）注册：

```python
        container.register_glass(self.mode_switch)
        container.register_glass(self.connect_button)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_watermark_glass.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/views/main_window.py tests/test_watermark_glass.py
git commit -m "feat(ui): WatermarkContainer 支持玻璃控件（模糊水印裁剪）"
```

---

## Task 2: 分段控件改半透明玻璃

**Files:**
- Modify: `app/views/mode_switch.py`
- Test: `tests/test_mode_switch.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_mode_switch.py` 末尾追加：

```python
def test_track_and_pill_are_translucent(qtbot):
    """轨道与药丸为半透明（<255）玻璃，才能透出身后水印。"""
    from views.mode_switch import SegmentedModeSwitch

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    assert w._track_qcolor().alpha() < 255
    assert w._pill_qcolor().alpha() < 255
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_mode_switch.py -q -k translucent`
Expected: FAIL（无 `_track_qcolor`）。

- [ ] **Step 3: 实现**

在 `SegmentedModeSwitch` 增加颜色访问器，并让 `paintEvent` 使用它们：

```python
    def _track_qcolor(self):
        return theme.qcolor("track", 0.55)

    def _pill_qcolor(self):
        return theme.qcolor("pill", 0.72)
```

`paintEvent` 里：
- 轨道：`painter.setBrush(self._track_qcolor())`；并先画一圈细描边（玻璃边缘微光）：

```python
        # 玻璃描边（顶部微光）
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.qcolor("separator", 0.45), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
```
（需 `from PySide6.QtGui import QPen`；放在轨道之后、药丸之前。）
- 药丸：`painter.setBrush(self._pill_qcolor())`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_mode_switch.py -q`
Expected: 全部 PASS（既有交互用例不受影响）。

- [ ] **Step 5: 提交**

```bash
git add app/views/mode_switch.py tests/test_mode_switch.py
git commit -m "style(ui): 分段控件改半透明玻璃"
```

---

## Task 3: 连接/断开主按钮改半透明玻璃

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_main_window.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_main_window.py` 末尾追加：

```python
def test_connect_button_glass_is_translucent(window):
    """连接按钮双态背景为半透明（rgba）玻璃。"""
    window._apply_connect_button_style(False)
    assert "rgba(" in window.connect_button.styleSheet()
    window._apply_connect_button_style(True)
    assert "rgba(" in window.connect_button.styleSheet()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q -k glass_is_translucent`
Expected: FAIL（当前为不透明 hex）。

- [ ] **Step 3: 实现**

`_apply_connect_button_style` 两态样式改为半透明，并加顶部微光描边。

未连接（连接=绿玻璃，语义同实心绿但可透）：

```python
        if not connected:
            self.connect_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme.with_alpha("accent", 0.80)};
                    color: {theme.semantic_color("accent_text")};
                    border: none;
                    border-top: 1px solid {theme.with_alpha("accent_text", 0.30)};
                    border-radius: 6px;
                    font-size: 13pt;
                    font-weight: 600;
                }}
                QPushButton:hover:enabled {{
                    background-color: {theme.with_alpha("accent_hover", 0.86)};
                }}
                QPushButton:pressed {{
                    background-color: {theme.with_alpha("accent_pressed", 0.90)};
                    padding-top: 1px;
                }}
                QPushButton:focus {{
                    border: 1px solid {theme.with_alpha("accent_text", 0.5)};
                }}
                QPushButton:disabled {{
                    background-color: {theme.with_alpha("accent", 0.35)};
                    color: {theme.semantic_color("accent_text")};
                }}
            """)
        else:
            # 断开：玻璃描边（半透明白底 + accent 描边 + 顶部微光）
            self.connect_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.14);
                    color: {theme.semantic_color("accent")};
                    border: 2px solid {theme.with_alpha("accent", 0.85)};
                    border-radius: 6px;
                    font-size: 13pt;
                    font-weight: 600;
                }}
                QPushButton:hover:enabled {{
                    background-color: rgba(255, 255, 255, 0.22);
                }}
                QPushButton:pressed {{
                    background-color: rgba(255, 255, 255, 0.10);
                    padding-top: 1px;
                }}
            """)
```

（删除原 `padding-top` 之外沿用即可；保留原有注释要点。）

> 说明：`theme.with_alpha(name, a)` 产出 QSS 可用的 `rgba(...)`；`rgba(255,255,255,0.14)` 硬编码白色半透明在深浅色下都表现为"玻璃"。断开的浅色玻璃若在浅色主题偏淡，Task 4 真机再微调。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: PASS（注意既有 `test_disconnect_button_outlined_when_connected` 断言 `"border: 2px solid"` 仍成立）。

- [ ] **Step 5: 提交**

```bash
git add app/views/main_window.py tests/test_main_window.py
git commit -m "style(ui): 连接/断开主按钮改半透明玻璃"
```

---

## Task 4: 全量回归 + 真机验证

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 2: 真机验证（必须）**

源码启动 `uv run app/main.py`：
1. 连接后（校训淡入），**分段控件**与**主按钮**身后应透出**模糊的校训笔画**；浅色明显、深色很弱（可接受）。
2. 未连接（凭据区可见、校训隐藏）时，两个控件呈半透明玻璃、不突兀；连接/断开切换、hover/pressed 反馈正常。
3. 模式切换动画、按压 1px、禁用态、焦点环仍正常；**不得破坏原有交互与可读性**。
4. 深色/浅色、跟随系统切换时观感正常（玻璃色不随主题重算属已知；如明显异常记录）。

- [ ] **Step 3: 视观感微调（如需）**

若浅色下"断开"玻璃太淡或文字对比不足，调整背景 alpha / 描边 alpha；若模糊过强看不清控件，把 `blurRadius` 从 7 降到 5。

---

## 完成标准

- 连接态下，模式分段控件与连接/断开主按钮身后透出**模糊校训**（仿玻璃），确定生效。
- 未连接态呈半透明玻璃、不破坏可读性与既有交互（动画/按压/禁用/焦点环）。
- 全量测试通过、真机观感确认。
