# tests/test_macos_menu_popup.py
import pytest
from PySide6.QtCore import QPoint


def test_popup_menu_raises_off_cocoa(qtbot):
    from utils.macos_menu_popup import popup_menu

    with pytest.raises(RuntimeError):
        popup_menu(["代理", "TUN 全局路由"], 1, QPoint(100, 100))
