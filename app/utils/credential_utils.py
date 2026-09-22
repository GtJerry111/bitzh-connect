from .config_utils import load_config, save_config
from .credential_crypto import (
    decrypt_password,
    encrypt_password,
    generate_salt,
    is_encrypted,
    is_legacy_encrypted,
)


def _ensure_salt(config) -> str:
    """取现有盐；没有则生成并写回 config（仅加密路径调用）。"""
    salt = config.get("cred_salt", "")
    if not salt:
        salt = generate_salt()
        config["cred_salt"] = salt
    return salt


def save_credentials(window):
    """按“记住密码”保存/清除凭据；密码用持久化盐加密后存 QSettings。"""
    config = load_config()
    remember = window.remember_cb.isChecked()
    config["remember"] = remember

    if remember:
        config["username"] = window.username_input.text()
        password = window.password_input.text()
        config["password"] = (
            encrypt_password(password, _ensure_salt(config)) if password else ""
        )
    else:
        config["username"] = ""
        config["password"] = ""

    save_config(config)


def load_credentials_detailed():
    """返回 (username, password, password_unreadable)。

    - 当前格式（enc2:）：用持久化盐解密，成功返回明文；
    - 旧格式（enc1:）/缺盐/校验失败：密码置空并标记 unreadable（调用方提示重输）；
    - 旧版明文：本次直接返回，并原地迁移为密文。
    """
    config = load_config()
    username = config.get("username", "")
    raw = config.get("password", "")

    if not raw:
        return username, "", False

    if is_encrypted(raw):
        salt = config.get("cred_salt", "")
        password = decrypt_password(raw, salt) if salt else None
        if password is None:
            return username, "", True
        return username, password, False

    if is_legacy_encrypted(raw):
        # 旧版机器指纹密文：换机/打包环境下已无法解密
        return username, "", True

    # 旧版明文（或旧钥匙串时代的回退明文）：本次使用并迁移为新格式
    password = raw
    config["password"] = encrypt_password(password, _ensure_salt(config))
    save_config(config)
    return username, password, False


def load_credentials():
    """返回 (username, password)；忽略"是否需要提示"标记（兼容旧调用）。"""
    username, password, _ = load_credentials_detailed()
    return username, password
