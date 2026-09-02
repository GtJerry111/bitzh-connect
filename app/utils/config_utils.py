from PySide6.QtCore import QSettings
from common.constants import APP_NAME, ORG_NAME, DEFAULT_SERVER, DEFAULT_PORT, DEFAULT_DNS
from .startup_utils import get_launch_at_login


def save_config(config):
    """Save config using QSettings"""
    settings = QSettings(ORG_NAME, APP_NAME)
    for key, value in config.items():
        settings.setValue(key, value)
    settings.sync()


def load_config():
    """Load config from QSettings"""
    settings = QSettings(ORG_NAME, APP_NAME)
    default_config = {
        "username": "",
        "password": "",
        "remember": False,
        "server": DEFAULT_SERVER,
        "port": DEFAULT_PORT,
        "dns": DEFAULT_DNS,
        "auto_dns": True,
        "proxy": True,
        "launch_at_login": get_launch_at_login(),
        "connect_startup": False,
        "silent_mode": False,
        "check_update": True,
        "hide_dock_icon": False,
        "keep_alive": True,
        "debug_dump": False,
        "disable_multi_line": False,
        "auto_reconnect": True,
        "socks_bind": "1080",
        "http_bind": "1081",
        "cert_file": "",
        "cert_password": "",
        "appearance": "system",
        "tun_mode": False,
    }

    for key in default_config.keys():
        value = settings.value(key, default_config[key])
        if isinstance(default_config[key], bool):
            value = str(value).lower() == "true"
        default_config[key] = value

    return default_config


def load_settings(self):
    """Load advanced settings from QSettings"""
    config = load_config()
    self.username = config["username"]
    self.password = config["password"]
    self.remember = config["remember"]
    self.server_address = config["server"]
    self.port = config["port"]
    self.dns_server = config["dns"]
    self.auto_dns = config["auto_dns"]
    self.proxy = config["proxy"]
    self.connect_startup = config["connect_startup"]
    self.silent_mode = config["silent_mode"]
    self.check_update = config["check_update"]
    self.hide_dock_icon = config["hide_dock_icon"]
    self.keep_alive = config["keep_alive"]
    self.debug_dump = config["debug_dump"]
    self.disable_multi_line = config["disable_multi_line"]
    self.http_bind = config["http_bind"]
    self.socks_bind = config["socks_bind"]
    self.cert_file = config["cert_file"]
    self.cert_password = config["cert_password"]
    self.auto_reconnect = config["auto_reconnect"]
    self.appearance = config["appearance"]
    self.tun_mode = config["tun_mode"]
