from .config_utils import load_config, save_config
from .credential_crypto import decrypt_password, encrypt_password, is_encrypted


def save_credentials(window):
    """按“记住密码”保存/清除凭据；密码本地加密后存 QSettings（不碰系统钥匙串）。"""
    config = load_config()
    remember = window.remember_cb.isChecked()
    config["remember"] = remember

    if remember:
        config["username"] = window.username_input.text()
        password = window.password_input.text()
        config["password"] = encrypt_password(password) if password else ""
    else:
        config["username"] = ""
        config["password"] = ""

    save_config(config)


def load_credentials():
    """返回 (username, password)。

    旧版明文（含旧钥匙串时代的回退明文）首次读取时迁移为本地密文。
    旧版“密码在系统钥匙串、配置为空”的条目无法再取回，用户重输一次即可。
    """
    config = load_config()
    username = config.get("username", "")
    raw = config.get("password", "")

    if not raw:
        return username, ""

    if is_encrypted(raw):
        return username, decrypt_password(raw) or ""

    # 旧版明文：本次直接使用，并原地迁移为密文
    password = raw
    config["password"] = encrypt_password(password)
    save_config(config)
    return username, password
