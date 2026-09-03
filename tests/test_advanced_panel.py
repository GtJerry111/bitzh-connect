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


def test_multi_line_positive_wording_inverted_storage(dialog):
    """"自动切换备用线路"肯定句 UI，存储键 disable_multi_line 取反（双重否定消除）"""
    assert dialog.auto_multi_line_switch.text() == "自动切换备用线路"
    assert dialog.auto_multi_line_switch.isChecked() is True
    assert dialog.get_settings()["disable_multi_line"] is False
    dialog.auto_multi_line_switch.setChecked(False)
    assert dialog.get_settings()["disable_multi_line"] is True
    base = dict(
        server="1.2.3.4", port="443", dns="", proxy=True,
        connect_startup=False, silent_mode=False, check_update=True,
    )
    dialog.set_settings(**base, disable_multi_line=True)
    assert dialog.auto_multi_line_switch.isChecked() is False


def test_button_box_save_is_default_and_macos_order(dialog):
    """QDialogButtonBox：保存为主按钮（macOS 惯例取消左、保存右，由平台自动排布）"""
    from PySide6.QtWidgets import QDialogButtonBox

    save_btn = dialog.button_box.button(QDialogButtonBox.Save)
    assert save_btn.isDefault()
    assert save_btn.text() == "保存"
    assert dialog.button_box.button(QDialogButtonBox.Cancel).text() == "取消"


def test_general_tab_comes_first(dialog):
    """macOS 惯例：通用 tab 在前；帮助 tab（原菜单栏收编）殿后"""
    from PySide6.QtWidgets import QTabWidget

    tab_widget = dialog.findChild(QTabWidget)
    assert tab_widget.tabText(0) == "通用"
    assert tab_widget.tabText(1) == "网络"
    assert tab_widget.tabText(2) == "帮助"


def test_hidden_cert_group_config_roundtrip(dialog):
    """证书组 UI 已隐藏，但配置键必须原样往返保留（不丢用户既有配置）"""
    base = dict(
        server="1.2.3.4", port="443", dns="", proxy=True,
        connect_startup=False, silent_mode=False, check_update=True,
    )
    dialog.set_settings(**base, cert_file="/tmp/cert.p12", cert_password="pw123")
    settings = dialog.get_settings()
    assert settings["cert_file"] == "/tmp/cert.p12"
    assert settings["cert_password"] == "pw123"


def test_show_advanced_settings_wires_auto_reconnect_and_subtitle(
    qtbot, monkeypatch
):
    """保存后：auto_reconnect 写回 window 并同步 reconnect_manager；
    server 变化时同步仪表盘副标题中的服务器小字。"""
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
                "appearance": "system",
                "tun_mode": False,
            }

    monkeypatch.setattr("views.menu_utils.AdvancedSettingsDialog", FakeDialog)
    from views.menu_utils import show_advanced_settings

    show_advanced_settings(win)

    # 打开对话框时应把当前 auto_reconnect（默认 True）、appearance、tun_mode 传入 set_settings
    assert captured["args"][-3] is True
    assert captured["args"][-2] == "system"
    assert captured["args"][-1] is False
    # 保存后写回 window 并联动重连开关
    assert win.auto_reconnect is False
    assert win.reconnect_manager._enabled is False
    # server 变了 → 仪表盘同步
    assert win.status_panel.subtitle.text() == "9.9.9.9"


def test_show_advanced_settings_keeps_subtitle_when_unchanged(qtbot, monkeypatch):
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
                "appearance": "system",
                "tun_mode": False,
            }

    monkeypatch.setattr("views.menu_utils.AdvancedSettingsDialog", FakeDialog)
    from views.menu_utils import show_advanced_settings

    win.status_panel.subtitle.setText("sentinel")
    show_advanced_settings(win)
    assert win.status_panel.subtitle.text() == "sentinel"
