# app/views/chevron.py
"""共享的细描边 chevron 控件（disclosure 折叠指示）。

8px 细描边（1.5pt round cap）——QToolButton 的 ArrowType 又大又钝，
与细字重标题不匹配；自绘 + 旋转动画才有 macOS disclosure 的观感。
"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from common import theme


class Chevron(QWidget):
    """0°=右（收起），90°=下（展开）；角度由外部动画驱动（set_angle）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._angle = 0.0

    def set_angle(self, deg: float):
        self._angle = deg
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.semantic_color("secondary_text")))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.translate(6, 6)
        painter.rotate(self._angle)
        painter.drawLine(QPointF(-1.6, -4.0), QPointF(2.4, 0.0))
        painter.drawLine(QPointF(2.4, 0.0), QPointF(-1.6, 4.0))
        painter.end()
