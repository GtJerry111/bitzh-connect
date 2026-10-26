import os
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from packaging import version
from requests.exceptions import RequestException

from common.constants import (
    RELEASES_API_URL,
    UPDATE_MIRROR_AUTO,
    UPDATE_MIRROR_DEFAULT_URL,
    UPDATE_MIRROR_GITHUB,
)
from utils.update_installer import sha256_file


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    body: str
    html_url: str
    assets: tuple[dict, ...]
    published_at: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "ReleaseInfo":
        tag = str(data.get("tag_name") or "")
        return cls(
            version=tag.lstrip("v"),
            tag=tag,
            body=str(data.get("body") or ""),
            html_url=str(data.get("html_url") or ""),
            assets=tuple(data.get("assets") or ()),
            published_at=str(data.get("published_at") or ""),
        )


def apply_mirror(url: str, mirror: str | None) -> str:
    """把 GitHub URL 套到镜像前缀/模板上。"""
    if not url or mirror == UPDATE_MIRROR_GITHUB:
        return url
    if not mirror or mirror == UPDATE_MIRROR_AUTO:
        mirror = UPDATE_MIRROR_DEFAULT_URL
    if "{url}" in mirror:
        return mirror.replace("{url}", url)
    return mirror.rstrip("/") + "/" + url.lstrip("/")


def api_urls(mirror: str | None) -> list[str]:
    if mirror == UPDATE_MIRROR_GITHUB:
        return [RELEASES_API_URL]
    if not mirror or mirror == UPDATE_MIRROR_AUTO:
        return [RELEASES_API_URL, apply_mirror(RELEASES_API_URL, UPDATE_MIRROR_AUTO)]
    custom = apply_mirror(RELEASES_API_URL, mirror)
    return [custom, RELEASES_API_URL] if custom != RELEASES_API_URL else [RELEASES_API_URL]


def download_urls(asset_url: str, mirror: str | None) -> list[str]:
    if mirror == UPDATE_MIRROR_GITHUB:
        return [asset_url]
    if not mirror or mirror == UPDATE_MIRROR_AUTO:
        return [asset_url, apply_mirror(asset_url, UPDATE_MIRROR_AUTO)]
    custom = apply_mirror(asset_url, mirror)
    return [custom, asset_url] if custom != asset_url else [asset_url]


def fetch_asset_text(asset: dict, mirror: str | None) -> str:
    """下载小文本资产（如 checksums-darwin-arm64.txt），失败返回空串。"""
    asset_url = str(asset.get("browser_download_url") or "")
    if not asset_url:
        return ""
    for url in download_urls(asset_url, mirror):
        try:
            response = requests.get(url, timeout=10)
            status = getattr(response, "status_code", 200)
            if status >= 400:
                continue
            return str(getattr(response, "text", "") or "")
        except (RequestException, ValueError):
            continue
    return ""


def source_label(url: str) -> str:
    host = urlparse(url).hostname or url
    if host in ("gh-proxy.com", "www.gh-proxy.com"):
        return "gh-proxy.com（镜像）"
    if host.endswith("github.com") or host == "api.github.com":
        return "GitHub"
    return host


class UpdateSignals(QObject):
    """Signals for update checking process"""

    update_available = Signal(str)
    release_available = Signal(object)
    up_to_date = Signal()
    error = Signal(str)


class UpdateChecker(QRunnable):
    """Worker class to check for updates in background"""

    def __init__(self, current_version, mirror: str | None = None):
        super().__init__()
        self.current_version = current_version
        self.mirror = mirror or UPDATE_MIRROR_AUTO
        self.last_release: ReleaseInfo | None = None
        self.signals = UpdateSignals()

    @Slot()
    def run(self):
        try:
            latest_version = self.get_latest_version()
            if not latest_version:
                self.signals.error.emit("Failed to retrieve version information")
                return

            if version.parse(latest_version) > version.parse(self.current_version):
                if self.last_release is not None:
                    self.signals.release_available.emit(self.last_release)
                self.signals.update_available.emit(latest_version)
            else:
                self.signals.up_to_date.emit()

        except Exception as e:
            self.signals.error.emit(f"Update check failed: {str(e)}")

    def _fetch_releases(self) -> list[dict]:
        last_error: Exception | None = None
        for url in api_urls(self.mirror):
            try:
                response = requests.get(
                    url,
                    timeout=10,
                    headers={"Accept": "application/vnd.github+json"},
                )
                status = getattr(response, "status_code", 200)
                if status >= 400:
                    raise RequestException(f"HTTP {status}")
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError("release payload is not a list")
                return data
            except (RequestException, ValueError, TypeError) as exc:
                last_error = exc
        raise RequestException(str(last_error) if last_error else "update check failed")

    def get_latest_version(self):
        """最新版本号 + release 信息。

        仍保留这个入口名：既有测试/调用只关心版本号；last_release 供更新弹窗使用。
        """
        try:
            for release in self._fetch_releases():
                if release.get("draft", False):
                    continue
                self.last_release = ReleaseInfo.from_api(release)
                return self.last_release.version
            self.last_release = None
            return None
        except Exception as e:
            print(f"Failed to check for updates: {e}")
            self.last_release = None
            return None


class DownloadSignals(QObject):
    progress = Signal(int, int)       # downloaded, total (0 = unknown)
    source = Signal(str)              # currently attempted URL
    finished = Signal(str)            # local zip path
    error = Signal(str)
    cancelled = Signal()


class _Cancelled(Exception):
    pass


class UpdateDownloader(QRunnable):
    def __init__(self, asset: dict, checksum: str | None, mirror: str | None,
                 dest_dir: str):
        super().__init__()
        self.asset = dict(asset)
        self.checksum = checksum
        self.mirror = mirror or UPDATE_MIRROR_AUTO
        self.dest_dir = dest_dir
        self.signals = DownloadSignals()
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        asset_url = str(self.asset.get("browser_download_url") or "")
        asset_name = str(self.asset.get("name") or "update.zip")
        if not asset_url:
            self.signals.error.emit("更新资产缺少下载地址")
            return
        errors: list[str] = []
        for url in download_urls(asset_url, self.mirror):
            if self._cancel_requested:
                self.signals.cancelled.emit()
                return
            self.signals.source.emit(url)
            part_path = os.path.join(self.dest_dir, asset_name + ".part")
            try:
                path = self._download_one(url, asset_name, part_path)
                if self.checksum and not self._verify(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                    errors.append(f"{source_label(url)} 校验失败")
                    continue
                self.signals.finished.emit(path)
                return
            except _Cancelled:
                try:
                    os.unlink(part_path)
                except OSError:
                    pass
                self.signals.cancelled.emit()
                return
            except Exception as exc:
                try:
                    os.unlink(part_path)
                except OSError:
                    pass
                errors.append(f"{source_label(url)}: {exc}")
        self.signals.error.emit("；".join(errors) or "下载失败")

    def _download_one(self, url: str, asset_name: str, part_path: str) -> str:
        response = requests.get(url, stream=True, timeout=(10, 60))
        status = getattr(response, "status_code", 200)
        if status >= 400:
            raise RequestException(f"HTTP {status}")
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        os.makedirs(self.dest_dir, exist_ok=True)
        with open(part_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if self._cancel_requested:
                    raise _Cancelled()
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                self.signals.progress.emit(done, total)
        final_path = os.path.join(self.dest_dir, asset_name)
        os.replace(part_path, final_path)
        return final_path

    def _verify(self, path: str) -> bool:
        try:
            return sha256_file(path) == str(self.checksum).lower()
        except OSError:
            return False


class UpdateService:
    """Service to handle update checking and downloads"""

    def __init__(self):
        self.thread_pool = QThreadPool()
        self._workers = []  # 持有引用，防止 QRunnable 自动删除后信号丢失

    def check_for_updates(self, current_version, mirror: str | None = None):
        worker = UpdateChecker(current_version, mirror)
        self._workers.append(worker)

        def release(_arg=None, w=worker):
            if w in self._workers:
                self._workers.remove(w)

        worker.signals.release_available.connect(release)
        worker.signals.update_available.connect(release)
        worker.signals.up_to_date.connect(release)
        worker.signals.error.connect(release)
        QTimer.singleShot(0, lambda: self.thread_pool.start(worker))
        return worker.signals

    def download_update(self, asset: dict, checksum: str | None,
                        mirror: str | None, dest_dir: str):
        worker = UpdateDownloader(asset, checksum, mirror, dest_dir)
        self._workers.append(worker)

        def release(_arg=None, w=worker):
            if w in self._workers:
                self._workers.remove(w)

        worker.signals.finished.connect(release)
        worker.signals.error.connect(release)
        worker.signals.cancelled.connect(release)
        QTimer.singleShot(0, lambda: self.thread_pool.start(worker))
        return worker
