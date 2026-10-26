from PySide6.QtCore import QObject, Signal

from services.update_service import ReleaseInfo
from views import menu_utils


class _Out:
    def __init__(self):
        self.lines = []

    def append(self, line):
        self.lines.append(line)


class FakeSignals(QObject):
    release_available = Signal(object)
    update_available = Signal(str)
    up_to_date = Signal()
    error = Signal(str)


def _release():
    return ReleaseInfo(
        version="1.5.0",
        tag="v1.5.0",
        body="notes",
        html_url="https://example/rel",
        assets=(
            {
                "name": "bitzh-connect-darwin-arm64.zip",
                "browser_download_url": "https://example/arm64.zip",
            },
            {
                "name": "checksums-darwin-arm64.txt",
                "browser_download_url": "https://example/checksums.txt",
            },
        ),
    )


def test_release_signal_opens_update_dialog(qtbot, monkeypatch):
    fake = FakeSignals()
    captured = {}

    class FakeDialog:
        def __init__(self, release, asset, checksum, mirror, parent, current_version):
            captured.update(
                version=release.version,
                asset=asset["name"],
                checksum=checksum,
                mirror=mirror,
            )

        def exec(self):
            return 0

    monkeypatch.setattr(menu_utils.update_service, "check_for_updates",
                        lambda *a, **k: fake)
    monkeypatch.setattr(menu_utils, "UpdateDialog", FakeDialog)
    monkeypatch.setattr(menu_utils, "current_arch", lambda: "arm64")
    monkeypatch.setattr(menu_utils, "fetch_asset_text",
                        lambda asset, mirror: "abc123  bitzh-connect-darwin-arm64.zip\n")
    parent = type("P", (), {"update_mirror": "auto", "version": "1.4.0",
                            "output_text": _Out()})()
    menu_utils.check_for_updates(parent, "1.4.0")
    fake.release_available.emit(_release())
    assert captured == {
        "version": "1.5.0",
        "asset": "bitzh-connect-darwin-arm64.zip",
        "checksum": "abc123",
        "mirror": "auto",
    }


def test_startup_release_does_not_open_dialog(monkeypatch):
    fake = FakeSignals()
    monkeypatch.setattr(menu_utils.update_service, "check_for_updates",
                        lambda *a, **k: fake)
    monkeypatch.setattr(menu_utils, "UpdateDialog", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    parent = type("P", (), {"update_mirror": "auto", "version": "1.4.0",
                            "output_text": _Out()})()
    menu_utils.check_for_updates(parent, "1.4.0", startup=True)
    fake.release_available.emit(_release())
    assert any("1.5.0" in line for line in parent.output_text.lines)
