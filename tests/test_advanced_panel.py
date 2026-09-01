"""Task 9 Step 5：高级设置 BITZH 默认值 + 断线自动重连开关 + 保存后接线。"""
import pytest


@pytest.fixture
def dialog(qtbot, monkeypatch):
    # 屏蔽 osascript / 注册表副作用（构造时会读取登录项状态）
    monkeypatch.setattr("views.advanced_panel.get_launch_at_login", lambda: False)
    monkeypatch.setattr("views.advanced_panel.set_launch_at_login", lambda enable: None)
    from views.advanced_panel import AdvancedSettingsDialog

    d = AdvancedSettingsDialog()
    qtbot.addWidget(d)
    return d


def test_server_default_is_bitzh_server(dialog):
    from common.constants import DEFAULT_SERVER

    assert dialog.server_input.text() == DEFAULT_SERVER


def test_dns_default_empty_with_placeholder(dialog):
    assert dialog.dns_input.text() == ""
    assert dialog.dns_input.placeholderText() == "留空则禁用远端 DNS"


def test_auto_reconnect_switch_default_checked(dialog):
    assert dialog.auto_reconnect_switch.text() == "断线自动重连"
    assert dialog.auto_reconnect_switch.isChecked() is True


def test_get_settings_includes_auto_reconnect(dialog):
    dialog.auto_reconnect_switch.setChecked(False)
    assert dialog.get_settings()["auto_reconnect"] is False
    dialog.auto_reconnect_switch.setChecked(True)
    assert dialog.get_settings()["auto_reconnect"] is True


def test_set_settings_applies_auto_reconnect(dialog):
    base = dict(
        server="1.2.3.4",
        port="443",
        dns="",
        proxy=True,
        connect_startup=False,
        silent_mode=False,
        check_update=True,
    )
    dialog.set_settings(**base, auto_reconnect=False)
    assert dialog.auto_reconnect_switch.isChecked() is False
    dialog.set_settings(**base)  # 缺省应为 True
    assert dialog.auto_reconnect_switch.isChecked() is True


def test_show_advanced_settings_wires_auto_reconnect_and_server_label(
    qtbot, monkeypatch
):
    """保存后：auto_reconnect 写回 window 并同步 reconnect_manager；
    server 变化时同步仪表盘右上角服务器小字。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.reconnect_manager.set_enabled(True)
    assert win.server_address != "9.9.9.9"

    captured = {}

    class FakeDialog:
        def __init__(self, parent):
            pass

        def set_settings(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def exec(self):
            return True

        def get_settings(self):
            return {
                "server": "9.9.9.9",
                "port": "443",
                "dns": "",
                "auto_dns": True,
                "proxy": True,
                "connect_startup": False,
                "silent_mode": False,
                "check_update": True,
                "keep_alive": True,
                "debug_dump": False,
                "disable_multi_line": False,
                "http_bind": "1081",
                "socks_bind": "1080",
                "cert_file": "",
                "cert_password": "",
                "auto_reconnect": False,
            }

    monkeypatch.setattr("views.menu_utils.AdvancedSettingsDialog", FakeDialog)
    from views.menu_utils import show_advanced_settings

    show_advanced_settings(win)

    # 打开对话框时应把当前 auto_reconnect（默认 True）传入 set_settings
    assert captured["args"][-1] is True
    # 保存后写回 window 并联动重连开关
    assert win.auto_reconnect is False
    assert win.reconnect_manager._enabled is False
    # server 变了 → 仪表盘同步
    assert win.status_panel.server_label.text() == "9.9.9.9"


def test_show_advanced_settings_keeps_server_label_when_unchanged(qtbot, monkeypatch):
    """server 没变时不去动仪表盘（防误刷）。"""
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    class FakeDialog:
        def __init__(self, parent):
            pass

        def set_settings(self, *args, **kwargs):
            pass

        def exec(self):
            return True

        def get_settings(self):
            return {
                "server": win.server_address,  # 未改
                "port": win.port,
                "dns": win.dns_server,
                "auto_dns": win.auto_dns,
                "proxy": win.proxy,
                "connect_startup": False,
                "silent_mode": False,
                "check_update": True,
                "keep_alive": True,
                "debug_dump": False,
                "disable_multi_line": False,
                "http_bind": "1081",
                "socks_bind": "1080",
                "cert_file": "",
                "cert_password": "",
                "auto_reconnect": True,
            }

    monkeypatch.setattr("views.menu_utils.AdvancedSettingsDialog", FakeDialog)
    from views.menu_utils import show_advanced_settings

    win.status_panel.server_label.setText("sentinel")
    show_advanced_settings(win)
    assert win.status_panel.server_label.text() == "sentinel"
