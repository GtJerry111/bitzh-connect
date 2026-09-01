"""B10 托盘文案 + B12 版本读取兜底。"""


def test_tray_connect_action_label(qtbot):
    from PySide6.QtWidgets import QPushButton, QSystemTrayIcon

    from utils.tray_utils import create_tray_menu

    class FakeWindow:
        def __init__(self):
            self.connect_button = QPushButton()
            self.connect_button.setCheckable(True)

        def show(self):
            pass

        def raise_(self):
            pass

        def quit_app(self):
            pass

    tray = QSystemTrayIcon()
    create_tray_menu(FakeWindow(), tray)
    texts = [action.text() for action in tray.contextMenu().actions()]
    assert "VPN 连接" in texts
    assert "系统代理" not in texts
    tray.deleteLater()


def test_get_version_fallback_returns_0_0_0(monkeypatch):
    """资源读取失败时返回 "0.0.0" 而不是 None（B12）。"""
    import common.version as version_mod

    class BrokenFile:
        def __init__(self, *args):
            pass

        def open(self, mode):
            return False

        def close(self):
            pass

    monkeypatch.setattr(version_mod, "QFile", BrokenFile)
    assert version_mod.get_version() == "0.0.0"
