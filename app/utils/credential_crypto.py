"""本地密码加密：不访问系统钥匙串，密码不明文落盘（纯标准库）。

方案：以「应用内置 secret + 本机标识（主机名/用户名/MAC）」经 PBKDF2-HMAC-SHA256
派生加密密钥与认证密钥；密文用 SHA256 计数器密钥流异或，附 HMAC-SHA256 校验。
密文与本机绑定：换机/换用户后无法解密（需重输密码）。

安全边界说明：这是「防明文直读」级别，不是强安全边界——应用内置 secret 可被
反编译提取。任何纯本地、无系统钥匙串的方案都无法抵御「能读配置文件 + 反编译」
的攻击者，这里的目标只是不把密码明文写进 QSettings。
"""
import base64
import getpass
import hashlib
import hmac
import os
import platform
import uuid
from functools import lru_cache

# 应用内置 secret（本地混淆用；非密钥管理边界，可被反编译提取）
_APP_SECRET = (
    b"BITZH-Connect//local-credential//v1//"
    b"7f3a1c9e5b204d68a1f0c3e7d9b28465//"
    b"e2c5a8f14b6d9037af12c4e6b8d0573a"
)
_PREFIX = "enc1:"
_NONCE_LEN = 16
_TAG_LEN = 32
_PBKDF2_ITERS = 120_000


def _machine_salt() -> bytes:
    """本机标识 → 固定盐；换机/换用户即不可解。"""
    raw = "|".join([platform.node(), getpass.getuser(), str(uuid.getnode())])
    return hashlib.sha256(raw.encode("utf-8")).digest()


@lru_cache(maxsize=1)
def _derive_keys() -> tuple[bytes, bytes]:
    """派生 (加密密钥, 认证密钥)。本机标识在进程内不变，缓存一次。"""
    master = hashlib.pbkdf2_hmac(
        "sha256", _APP_SECRET, _machine_salt(), _PBKDF2_ITERS, dklen=32
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
    """是否为本模块生成的密文（用于旧版明文迁移判定）。"""
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt_password(plaintext: str) -> str:
    """加密为可存 QSettings 的字符串；空串原样返回空串。"""
    if not plaintext:
        return ""
    enc_key, mac_key = _derive_keys()
    nonce = os.urandom(_NONCE_LEN)
    data = plaintext.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return _PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def decrypt_password(token: str) -> str | None:
    """解密；非本格式、校验失败或换机后返回 None（调用方按需回退）。"""
    if not is_encrypted(token):
        return None
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX):].encode("ascii"))
        if len(blob) < _NONCE_LEN + _TAG_LEN:
            return None
        nonce = blob[:_NONCE_LEN]
        tag = blob[_NONCE_LEN:_NONCE_LEN + _TAG_LEN]
        ct = blob[_NONCE_LEN + _TAG_LEN:]
        enc_key, mac_key = _derive_keys()
        expected = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return None
        data = bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))
        return data.decode("utf-8")
    except Exception:
        return None
