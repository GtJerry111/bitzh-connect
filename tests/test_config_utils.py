from types import SimpleNamespace

from utils.config_utils import load_config, load_settings, save_config


def test_menu_bar_speed_default_off(qtbot):
    assert load_config()["menu_bar_speed"] is False


def test_direct_ip_defaults_are_off_and_empty():
    config = load_config()
    assert config["direct_ip_enabled"] is False
    assert config["direct_ips"] == ""


def test_direct_ip_roundtrip_and_load_settings():
    save_config(
        {
            "direct_ip_enabled": True,
            "direct_ips": "10.182.37.18\n10.182.37.19",
        }
    )
    window = SimpleNamespace()
    load_settings(window)
    assert window.direct_ip_enabled is True
    assert window.direct_ips == ["10.182.37.18", "10.182.37.19"]


def test_update_mirror_default_and_roundtrip():
    config = load_config()
    assert config["update_mirror"] == "auto"
    save_config({"update_mirror": "https://gh-proxy.com/"})
    window = SimpleNamespace()
    load_settings(window)
    assert window.update_mirror == "https://gh-proxy.com/"
