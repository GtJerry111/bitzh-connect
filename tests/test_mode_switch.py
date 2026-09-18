# tests/test_mode_switch.py
"""SegmentedModeSwitch 按压下沉反馈（自绘控件，paintEvent 整体下移 1px）。"""
from views.mode_switch import SegmentedModeSwitch


def test_press_sets_pressed_state(qtbot):
    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    assert w._pressed is False
    qtbot.mousePress(w, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton)
    assert w._pressed is True


def test_release_clears_pressed_state(qtbot):
    from PySide6.QtCore import Qt

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    qtbot.mousePress(w, Qt.LeftButton)
    qtbot.mouseRelease(w, Qt.LeftButton)
    assert w._pressed is False


def test_leave_clears_pressed_state(qtbot):
    """按住拖出控件：按压态必须恢复（否则控件卡在下沉态）。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt, QPointF

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    qtbot.mousePress(w, Qt.LeftButton)
    assert w._pressed is True
    leave = QEvent(QEvent.Leave)
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(w, leave)
    assert w._pressed is False


def test_press_does_not_break_segment_switch(qtbot):
    """按压反馈不得影响原有点击切换逻辑（mousePress 即切换 + 发信号）。"""
    from PySide6.QtCore import QPoint, Qt

    w = SegmentedModeSwitch()
    qtbot.addWidget(w)
    received = []
    w.currentChanged.connect(received.append)
    # 点击右半段（TUN 模式）：段切换 + 信号发射与按压状态互不干扰
    qtbot.mousePress(w, Qt.LeftButton, pos=QPoint(w.width() - 5, w.height() // 2))
    assert w.currentIndex() == 1
    assert received == [1]
    assert w._pressed is True  # 按压态独立置位
