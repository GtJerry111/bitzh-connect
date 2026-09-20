# app/views/panel_tuner.py
"""菜单栏面板调参窗（真机调参用，非产品功能）。

为什么存在：面板底板是系统 NSGlassEffectView，模糊/白纱由系统管理，只有
style（Regular/Clear）与圆角可调；其余观感全部来自 Qt 自绘层。在 HTML 里做
滑杆必然与真机对不上，所以调参必须跑在真面板上。

入口：环境变量 BITZH_PANEL_TUNER=1 启动（见 main.py）。调参期间面板被钉住
（关掉失焦自动收起），调完点「定稿」把参数写入 panel-material.json。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from common import panel_material as pm

_SLIDER_STEPS = 1000


class PanelTuner(QWidget):
    def __init__(self, panel):
        super().__init__()
        self._panel = panel
        self._params = pm.defaults()
        self._mode = "light"
        self._rows = {}

        self.setWindowTitle("面板调参 · BITZH Connect")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ---- 底板（系统材质） ----
        root.addWidget(self._group_label("底板（系统 Liquid Glass）"))
        glass_row = QHBoxLayout()
        glass_row.addWidget(QLabel("Style"))
        self._style_btns = {}
        for key, text in (("regular", "磨砂 Regular"), ("clear", "清透 Clear")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c=False, k=key: self._set_style(k))
            self._style_btns[key] = btn
            glass_row.addWidget(btn)
        glass_row.addStretch()
        root.addLayout(glass_row)
        root.addLayout(self._slider_row("corner_radius", "圆角", 8.0, 30.0, False))

        # ---- 深浅色 ----
        root.addWidget(self._group_label("参数模式"))
        mode_row = QHBoxLayout()
        self._mode_btns = {}
        for key, text in (("light", "浅色"), ("dark", "深色")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c=False, k=key: self._set_mode(k))
            self._mode_btns[key] = btn
            mode_row.addWidget(btn)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # ---- Qt 自绘层 ----
        root.addWidget(self._group_label("Qt 自绘层（浅/深各存一套）"))
        for key in pm.ORDER:
            lo, hi, is_int = pm.RANGES[key]
            root.addLayout(self._slider_row(key, pm.LABELS[key], lo, hi, is_int))

        # ---- 动作 ----
        actions = QHBoxLayout()
        actions.addStretch()
        reset = QPushButton("重置")
        reset.clicked.connect(self._reset)
        apply_btn = QPushButton("定稿并写入")
        apply_btn.clicked.connect(self._commit)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        for b in (reset, apply_btn, close):
            actions.addWidget(b)
        root.addLayout(actions)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #888;")
        root.addWidget(self._status)

        self._sync_widgets()
        self._apply()
        self._panel.set_pinned(True)
        if not self._panel.isVisible():
            self._panel.show_panel(animated=False)

    # ---- 构建小工具 ----

    def _group_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: 600; margin-top: 6px;")
        return label

    def _slider_row(self, key: str, label: str, lo: float, hi: float, is_int: bool):
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(92)
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(_SLIDER_STEPS)
        value = QLabel("")
        value.setFixedWidth(56)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda _v, k=key: self._on_slider(k))
        row.addWidget(name)
        row.addWidget(slider, 1)
        row.addWidget(value)
        self._rows[key] = {
            "slider": slider, "value": value,
            "lo": lo, "hi": hi, "is_int": is_int,
        }
        return row

    # ---- 值读写 ----

    def _get(self, key: str):
        if key == "corner_radius":
            return self._params["corner_radius"]
        return self._params[self._mode][key]

    def _set(self, key: str, value):
        if key == "corner_radius":
            self._params["corner_radius"] = float(value)
        else:
            self._params[self._mode][key] = value

    def _to_slider(self, key: str, value) -> int:
        info = self._rows[key]
        span = info["hi"] - info["lo"]
        return int(round((float(value) - info["lo"]) / span * _SLIDER_STEPS))

    def _from_slider(self, key: str, pos: int):
        info = self._rows[key]
        value = info["lo"] + (info["hi"] - info["lo"]) * pos / _SLIDER_STEPS
        return int(round(value)) if info["is_int"] else round(value, 3)

    def _fmt(self, key: str, value) -> str:
        if key == "corner_radius":
            return f"{value:.1f}px"
        if self._rows[key]["is_int"]:
            return str(int(value))
        return f"{value:.2f}"

    # ---- 事件 ----

    def _on_slider(self, key: str):
        value = self._from_slider(key, self._rows[key]["slider"].value())
        self._set(key, value)
        self._rows[key]["value"].setText(self._fmt(key, value))
        self._apply()

    def _set_mode(self, mode: str):
        if mode != self._mode:
            self._mode = mode
            self._sync_widgets()
            self._apply()

    def _set_style(self, style: str):
        self._params["glass_style"] = style
        self._sync_widgets()
        self._apply()

    def _reset(self):
        self._params = pm.defaults()
        self._sync_widgets()
        self._apply()
        self._status.setText("已重置为默认值")

    def _commit(self):
        path = pm.save(self._params)
        self._status.setText(f"已写入：{path}")

    def _sync_widgets(self):
        for key, btn in self._style_btns.items():
            btn.setChecked(self._params["glass_style"] == key)
        for key, btn in self._mode_btns.items():
            btn.setChecked(self._mode == key)
        for key, info in self._rows.items():
            value = self._get(key)
            info["slider"].blockSignals(True)
            info["slider"].setValue(self._to_slider(key, value))
            info["slider"].blockSignals(False)
            info["value"].setText(self._fmt(key, value))

    def _apply(self):
        self._panel.apply_material(self._params)

    def showEvent(self, event):
        super().showEvent(event)
        # 贴着面板右缘放，避免挡住被观察的对象；夹紧到屏内
        from PySide6.QtWidgets import QApplication

        rect = self._panel.frameGeometry()
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = rect.right() + 12
        if x + self.width() > area.right() - 8:
            x = rect.left() - self.width() - 12  # 右侧放不下就放左侧
        x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
        y = max(area.top() + 8, min(rect.top(), area.bottom() - self.height() - 8))
        self.move(x, y)

    def closeEvent(self, event):
        self._panel.set_pinned(False)
        super().closeEvent(event)
