"""本地密码加密与凭据存取（不依赖系统钥匙串）。"""
from utils.credential_crypto import (
    decrypt_password,
    encrypt_password,
    is_encrypted,
)


def test_roundtrip_including_non_ascii():
    token = encrypt_password("s3cret-密码-01")
    assert is_encrypted(token)
    assert "s3cret" not in token
    assert decrypt_password(token) == "s3cret-密码-01"


def test_ciphertext_randomized_per_call():
    assert encrypt_password("same") != encrypt_password("same")


def test_empty_password_roundtrips_as_empty():
    assert encrypt_password("") == ""
    assert decrypt_password("") is None


def test_plaintext_is_not_decryptable():
    assert decrypt_password("just-a-plaintext") is None


def test_tampered_tag_rejected():
    token = encrypt_password("secret")
    payload = list(token)
    # 篡改 base64 正文末位（密文/标签区），HMAC 校验必须失败
    payload[-1] = "A" if payload[-1] != "A" else "B"
    assert decrypt_password("".join(payload)) is None


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
