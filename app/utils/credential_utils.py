from .config_utils import load_config, save_config
from .credential_store import CredentialStore

_store = CredentialStore()


def _log(window, msg):
    if hasattr(window, "output_text"):
        window.output_text.append(msg)


def save_credentials(window):
    config = load_config()
    remember = window.remember_cb.isChecked()
    config["remember"] = remember

    if remember:
        username = window.username_input.text()
        password = window.password_input.text()
        config["username"] = username
        if _store.set_password(username, password):
            config["password"] = ""  # 已入钥匙串，清掉明文
        else:
            config["password"] = password  # 回退明文
            _log(window, "[BITZH Connect] 警告：系统钥匙串不可用，密码将以明文保存\n")
    else:
        _store.delete_password(window.username_input.text())
        config["username"] = ""
        config["password"] = ""

    save_config(config)


def load_credentials():
    """返回 (username, password)。含一次性明文→钥匙串迁移。"""
    config = load_config()
    username = config.get("username", "")
    password = _store.get_password(username) or ""

    legacy_plaintext = config.get("password", "")
    if username and not password and legacy_plaintext:
        password = legacy_plaintext
        if _store.set_password(username, legacy_plaintext):
            config["password"] = ""
            save_config(config)

    return username, password
