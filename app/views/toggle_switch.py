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
