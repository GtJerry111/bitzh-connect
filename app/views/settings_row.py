"""设置项行：左标签（+可选说明）+ 右控件，底部一条主题化细分隔线。"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from common import theme


class SettingRow(QWidget):
    def __init__(self, text: str, control: QWidget, description: str = "", parent=None):
        super().__init__(parent)
        self.control = control
        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 8, 2, 8)
        outer.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(2)
        self._label = QLabel(text)
        left.addWidget(self._label)
        if description:
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setFont(theme.card_title_font())
            desc.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
            left.addWidget(desc)
        outer.addLayout(left, 1)
        control.setCursor(Qt.PointingHandCursor)
        outer.addWidget(control, 0, Qt.AlignVCenter)

    def label_text(self) -> str:
        return self._label.text()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        # QPainter 用 QColor：with_alpha 是 QSS 专用（rgba() 字符串 QColor 不认），
        # 这里必须走 theme.qcolor 才能拿到带透明度的有效颜色
        painter.setPen(QPen(theme.qcolor("separator", 0.5), 1))
        y = self.height() - 1
        painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
        painter.end()
