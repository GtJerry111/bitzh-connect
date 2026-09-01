"""凭据存储：密码优先存系统钥匙串，后端不可用时调用方负责回退。

用户名不敏感，仍存 QSettings；这里只管密码。
"""
import keyring

SERVICE_NAME = "BITZH Connect"


class CredentialStore:
    def __init__(self, backend=None):
        self._backend = backend if backend is not None else keyring
        self._available = self._probe()

    def _probe(self) -> bool:
        try:
            self._backend.get_password(SERVICE_NAME, "__probe__")
            return True
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return self._available

    def get_password(self, username: str) -> str | None:
        if not self._available or not username:
            return None
        try:
            return self._backend.get_password(SERVICE_NAME, username)
        except Exception:
            return None

    def set_password(self, username: str, password: str) -> bool:
        """成功返回 True；后端不可用/失败返回 False（调用方回退明文）。"""
        if not self._available or not username:
            return False
        try:
            self._backend.set_password(SERVICE_NAME, username, password)
            return True
        except Exception:
            return False

    def delete_password(self, username: str):
        if not self._available or not username:
            return
        try:
            self._backend.delete_password(SERVICE_NAME, username)
        except Exception:
            pass
