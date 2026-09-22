"""本地密码加密：不访问系统钥匙串，密码不明文落盘（纯标准库）。

方案：以「应用内置 secret + 本机持久化随机盐」经 PBKDF2-HMAC-SHA256 派生
加密密钥与认证密钥；密文用 SHA256 计数器密钥流异或，附 HMAC-SHA256 校验。

盐（salt）在首次加密时随机生成并持久化到 QSettings（键 `cred_salt`），此后
所有加解密复用同一个盐。刻意 **不使用** 主机名/用户名/MAC 等运行时标识——
打包分发（Nuitka）后这些标识不稳定，会导致同一台机器加密、重启后解不开。

安全边界说明：这是「防明文直读」级别，不是强安全边界——应用内置 secret 与
随机盐都可从本地取得。任何纯本地、无系统钥匙串的方案都无法抵御「能读配置
文件 + 反编译」的攻击者，这里的目标只是不把密码明文写进 QSettings。
"""
import base64
import hashlib
import hmac
import os

# 应用内置 secret（本地混淆用；非密钥管理边界，可被反编译提取）
_APP_SECRET = (
    b"BITZH-Connect//local-credential//v1//"
    b"7f3a1c9e5b204d68a1f0c3e7d9b28465//"
    b"e2c5a8f14b6d9037af12c4e6b8d0573a"
)
_PREFIX = "enc2:"
# 旧格式（机器指纹派生）前缀：新版无法解密，仅用于识别与提示
_LEGACY_PREFIX = "enc1:"
_SALT_LEN = 32
_NONCE_LEN = 16
_TAG_LEN = 32
_PBKDF2_ITERS = 120_000


def generate_salt() -> str:
    """生成新的随机盐（base64 urlsafe 字符串，可直接存 QSettings）。"""
    return base64.urlsafe_b64encode(os.urandom(_SALT_LEN)).decode("ascii")


def _derive_keys(salt_b64: str) -> tuple[bytes, bytes]:
    """从持久化盐派生 (加密密钥, 认证密钥)。"""
    salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
    master = hashlib.pbkdf2_hmac(
        "sha256", _APP_SECRET, salt, _PBKDF2_ITERS, dklen=32
    )
    enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"mac", hashlib.sha256).digest()
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(enc_key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


def is_encrypted(value) -> bool:
    """是否为当前格式（enc2:）密文。"""
    return isinstance(value, str) and value.startswith(_PREFIX)


def is_legacy_encrypted(value) -> bool:
    """是否为旧格式（enc1:，机器指纹派生）密文——新版无法解密，仅供识别。"""
    return isinstance(value, str) and value.startswith(_LEGACY_PREFIX)


def encrypt_password(plaintext: str, salt_b64: str) -> str:
    """用给定盐加密为可存 QSettings 的字符串；空串原样返回空串。"""
    if not plaintext:
        return ""
    enc_key, mac_key = _derive_keys(salt_b64)
    nonce = os.urandom(_NONCE_LEN)
    data = plaintext.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return _PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def decrypt_password(token: str, salt_b64: str) -> str | None:
    """用给定盐解密；非本格式、缺盐、校验失败返回 None。"""
    if not is_encrypted(token) or not salt_b64:
        return None
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX):].encode("ascii"))
        if len(blob) < _NONCE_LEN + _TAG_LEN:
            return None
        nonce = blob[:_NONCE_LEN]
        tag = blob[_NONCE_LEN:_NONCE_LEN + _TAG_LEN]
        ct = blob[_NONCE_LEN + _TAG_LEN:]
        enc_key, mac_key = _derive_keys(salt_b64)
        expected = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return None
        data = bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))
        return data.decode("utf-8")
    except Exception:
        return None
