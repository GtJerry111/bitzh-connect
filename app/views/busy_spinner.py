"""连接中旋转弧指示器。系统开启"减少动态效果"时 start() 为空操作（保持隐藏）。"""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from common import theme
from utils.motion_utils import reduce_motion


class BusySpinner(QWidget):
    def __init__(self, parent=None, diameter: int = 16):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self):
        if reduce_motion():
            return
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.semantic_color("working")))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        painter.drawArc(rect, -self._angle * 16, 270 * 16)  # drawArc 单位为 1/16 度
        painter.end()
