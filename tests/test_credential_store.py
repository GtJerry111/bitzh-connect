from utils.credential_store import CredentialStore


class FakeBackend:
    """内存 keyring 后端，模拟 (service, username) -> password"""

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


class BrokenBackend(FakeBackend):
    def get_password(self, service, username):
        raise RuntimeError("no secret service")

    def set_password(self, service, username, password):
        raise RuntimeError("no secret service")


def test_roundtrip():
    store = CredentialStore(backend=FakeBackend())
    assert store.available
    store.set_password("user1", "secret")
    assert store.get_password("user1") == "secret"
    store.delete_password("user1")
    assert store.get_password("user1") is None


def test_unavailable_backend_reports_not_available():
    store = CredentialStore(backend=BrokenBackend())
    assert not store.available
    assert store.get_password("user1") is None  # 不抛异常
