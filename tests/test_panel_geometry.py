from PySide6.QtCore import QRect, QSize

from utils.panel_geometry import panel_geometry

SCREEN = QRect(0, 0, 1920, 1080)       # availableGeometry
PANEL = QSize(360, 480)


def test_centered_under_icon():
    icon = QRect(900, 0, 24, 22)  # 菜单栏内图标
    geo = panel_geometry(icon, SCREEN, PANEL)
    assert geo.width() == 360 and geo.height() == 480
    assert geo.center().x() == icon.center().x()
    assert geo.top() == icon.bottom() + 4


def test_clamped_to_screen_right():
    icon = QRect(1900, 0, 20, 22)  # 最右侧图标：居中会溢出
    geo = panel_geometry(icon, SCREEN, PANEL)
    assert geo.right() <= SCREEN.right() - 8


def test_clamped_to_screen_left():
    icon = QRect(0, 0, 20, 22)
    geo = panel_geometry(icon, SCREEN, PANEL)
    assert geo.left() >= SCREEN.left() + 8


def test_invalid_icon_falls_back_to_top_right():
    geo = panel_geometry(None, SCREEN, PANEL)
    assert geo.right() == SCREEN.right() - 12
    assert geo.top() == SCREEN.top() + 4
