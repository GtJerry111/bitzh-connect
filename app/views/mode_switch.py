# app/views/mode_switch.py
"""连接模式分段选择器（代理模式 | TUN 模式）——macOS 分段控件风格。

QPainter 自绘：圆角轨道 + 选中项药丸（150ms OutCubic 滑动，可打断；
reduce-motion 即时切换）。无原生分段控件可用，自绘保证深浅色一致。
"""
from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from common import theme
from utils.motion_utils import reduce_motion


class SegmentedModeSwitch(QWidget):
    """两段分段选择器：0=代理模式，1=TUN 模式（全局路由）。"""

    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self._current = 0
        self._pill_pos = 0.0  # 药丸位置（0.0~1.0，段索引浮点，动画驱动）
        self._segments = ["代理模式", "TUN 模式"]

    def currentIndex(self) -> int:
        return self._current

    def setCurrentIndex(self, index: int, animate: bool = False):
        """编程设置（默认不发动画不发信号——外部同步用）。"""
        index = max(0, min(index, len(self._segments) - 1))
        if index == self._current:
            return
        self._current = index
        self._pill_pos = float(index)
        self.update()

    def _set_current(self, index: int):
        """用户点击：发信号 + 药丸滑动。"""
        if index == self._current:
            return
        self._current = index
        if reduce_motion():
            self._pill_pos = float(index)
            self.update()
        else:
            old = getattr(self, "_pill_anim", None)
            if old is not None:
                self._pill_anim = None
                if isValid(old):
                    old.stop()
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setStartValue(self._pill_pos)
            anim.setEndValue(float(index))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._on_pill_frame)
            self._pill_anim = anim
            anim.start()
        self.currentChanged.emit(index)

    def _on_pill_frame(self, v):
        self._pill_pos = float(v)
        self.update()

    def mousePressEvent(self, event):
        seg_w = self.width() / len(self._segments)
        self._set_current(int(event.position().x() // seg_w))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        seg_w = w / len(self._segments)

        # 轨道
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.semantic_color("track")))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # 选中药丸（2px 内缩 + 1px 下沉假阴影）
        pill = QRectF(self._pill_pos * seg_w + 2, 2, seg_w - 4, h - 4)
        shadow = pill.translated(0, 1)
        shadow_color = QColor(0, 0, 0, 40)
        painter.setBrush(shadow_color)
        painter.drawRoundedRect(shadow, 6, 6)
        painter.setBrush(QColor(theme.semantic_color("pill")))
        painter.drawRoundedRect(pill, 6, 6)

        # 文案：选中项 DemiBold，未选中常规
        painter.setPen(QColor(theme.semantic_color("ink")))
        for i, name in enumerate(self._segments):
            font = painter.font()
            font.setWeight(QFont.DemiBold if i == self._current else QFont.Normal)
            painter.setFont(font)
            painter.drawText(QRectF(i * seg_w, 0, seg_w, h), Qt.AlignCenter, name)
        painter.end()
