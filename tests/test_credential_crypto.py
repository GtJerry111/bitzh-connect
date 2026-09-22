"""本地密码加密与凭据存取（不依赖系统钥匙串）。"""
from utils.credential_crypto import (
    decrypt_password,
    encrypt_password,
    generate_salt,
    is_encrypted,
    is_legacy_encrypted,
)


def test_roundtrip_including_non_ascii():
    salt = generate_salt()
    token = encrypt_password("s3cret-密码-01", salt)
    assert is_encrypted(token)
    assert "s3cret" not in token
    assert decrypt_password(token, salt) == "s3cret-密码-01"


def test_ciphertext_randomized_per_call():
    salt = generate_salt()
    assert encrypt_password("same", salt) != encrypt_password("same", salt)


def test_empty_password_roundtrips_as_empty():
    assert encrypt_password("", generate_salt()) == ""
    assert decrypt_password("", generate_salt()) is None


def test_plaintext_is_not_decryptable():
    assert decrypt_password("just-a-plaintext", generate_salt()) is None


def test_tampered_tag_rejected():
    salt = generate_salt()
    token = encrypt_password("secret", salt)
    payload = list(token)
    # 篡改 base64 正文末位（密文/标签区），HMAC 校验必须失败
    payload[-1] = "A" if payload[-1] != "A" else "B"
    assert decrypt_password("".join(payload), salt) is None


def test_decrypt_with_wrong_salt_rejected():
    token = encrypt_password("secret", generate_salt())
    assert decrypt_password(token, generate_salt()) is None


def test_independent_of_runtime_identity(monkeypatch):
    """回归：加解密只依赖持久化盐，不依赖主机名/用户名/MAC。

    打包（Nuitka）后这些运行时标识会变化，是这个 bug 的根因；
    本用例确保即使它们全变，密文仍可解。
    """
    import utils.credential_crypto as cc

    salt = generate_salt()
    token = cc.encrypt_password("pw", salt)

    monkeypatch.setattr("platform.node", lambda: "changed-host")
    monkeypatch.setattr("getpass.getuser", lambda: "changed-user")
    monkeypatch.setattr("uuid.getnode", lambda: 123)
    assert cc.decrypt_password(token, salt) == "pw"


def test_legacy_prefix_detected():
    assert is_legacy_encrypted("enc1:abc")
    assert not is_encrypted("enc1:abc")
    assert is_encrypted("enc2:abc")
    assert not is_legacy_encrypted("enc2:abc")


def test_load_credentials_migrates_legacy_plaintext(qtbot):
    from utils.config_utils import load_config, save_config
    from utils.credential_utils import load_credentials

    config = load_config()
    config["username"] = "u1"
    config["password"] = "legacy-plain"
    save_config(config)

    assert load_credentials() == ("u1", "legacy-plain")
    # 迁移后配置里已是密文，且再次读取仍能解出
    assert is_encrypted(load_config()["password"])
    assert load_credentials() == ("u1", "legacy-plain")


def test_save_credentials_encrypts_and_roundtrips(qtbot):
    from utils.config_utils import load_config
    from utils.credential_utils import load_credentials, save_credentials

    class _Field:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Check:
        def __init__(self, checked):
            self._checked = checked

        def isChecked(self):
            return self._checked

    class _FakeWindow:
        remember_cb = _Check(True)
        username_input = _Field("2024000001")
        password_input = _Field("pw-秘密")

    save_credentials(_FakeWindow())
    config = load_config()
    assert config["username"] == "2024000001"
    assert is_encrypted(config["password"])
    assert "pw-秘密" not in config["password"]
    assert load_credentials() == ("2024000001", "pw-秘密")


def test_save_credentials_clears_when_not_remembered(qtbot):
    from utils.config_utils import load_config
    from utils.credential_utils import save_credentials

    class _Field:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Check:
        def isChecked(self):
            return False

    class _FakeWindow:
        remember_cb = _Check()
        username_input = _Field("u")
        password_input = _Field("p")

    save_credentials(_FakeWindow())
    config = load_config()
    assert config["username"] == ""
    assert config["password"] == ""


def test_save_credentials_persists_salt_and_reuses_it(qtbot):
    """保存时盐落盘；再次保存复用同一个盐（不每次换盐）。"""
    from utils.config_utils import load_config
    from utils.credential_utils import load_credentials, save_credentials

    class _Field:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Check:
        def isChecked(self):
            return True

    class _FakeWindow:
        def __init__(self, password):
            self.username_input = _Field("2024000001")
            self.password_input = _Field(password)

        remember_cb = _Check()

    save_credentials(_FakeWindow("pw-1"))
    salt_1 = load_config()["cred_salt"]
    assert salt_1
    assert load_credentials() == ("2024000001", "pw-1")

    save_credentials(_FakeWindow("pw-2"))
    assert load_config()["cred_salt"] == salt_1
    assert load_credentials() == ("2024000001", "pw-2")


def test_legacy_enc1_password_reported_unreadable(qtbot):
    from utils.config_utils import load_config, save_config
    from utils.credential_utils import load_credentials_detailed

    config = load_config()
    config["username"] = "u1"
    config["password"] = "enc1:AAAABBBBCCCC"  # 旧机器指纹密文
    config["remember"] = True
    save_config(config)

    username, password, unreadable = load_credentials_detailed()
    assert username == "u1"     # 用户名保留，不让用户重输
    assert password == ""       # 密码清空
    assert unreadable is True   # 标记需提示重输


def test_enc2_without_salt_reported_unreadable(qtbot):
    from utils.config_utils import load_config, save_config
    from utils.credential_crypto import encrypt_password, generate_salt
    from utils.credential_utils import load_credentials_detailed

    config = load_config()
    config["username"] = "u1"
    config["password"] = encrypt_password("pw", generate_salt())
    config["cred_salt"] = ""  # 盐丢失
    save_config(config)

    _, password, unreadable = load_credentials_detailed()
    assert password == "" and unreadable is True
