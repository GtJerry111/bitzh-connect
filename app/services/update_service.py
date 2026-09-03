from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Slot, QTimer
import requests
from requests.exceptions import RequestException
from packaging import version
from common.constants import RELEASES_API_URL


class UpdateSignals(QObject):
    """Signals for update checking process"""

    update_available = Signal(str)
    up_to_date = Signal()
    error = Signal(str)


class UpdateChecker(QRunnable):
    """Worker class to check for updates in background"""

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        self.signals = UpdateSignals()

    @Slot()
    def run(self):
        try:
            latest_version = self.get_latest_version()
            if not latest_version:
                self.signals.error.emit("Failed to retrieve version information")
                return

            if version.parse(latest_version) > version.parse(self.current_version):
                self.signals.update_available.emit(latest_version)
            else:
                self.signals.up_to_date.emit()

        except Exception as e:
            self.signals.error.emit(f"Update check failed: {str(e)}")

    def get_latest_version(self):
        """最新版本号：查 releases 列表取第一条非草稿（/releases/latest 不返回
        预发布，而发版流水线默认 prerelease:true，latest 接口会永远 404）。"""
        try:
            response = requests.get(RELEASES_API_URL, timeout=10)
            for release in response.json():
                if not release.get("draft", False):
                    return release["tag_name"].lstrip("v")
            return None  # 列表为空或全是草稿：还没发过版
        except RequestException as e:
            print(f"Failed to check for updates: {e}")
            return None
        except (KeyError, ValueError, TypeError) as e:
            print(f"Failed to parse version information: {e}")
            return None


class UpdateService:
    """Service to handle update checking and notifications"""

    def __init__(self):
        self.thread_pool = QThreadPool()
        self._workers = []  # 持有引用，防止 QRunnable 自动删除后信号丢失

    def check_for_updates(self, current_version):
        worker = UpdateChecker(current_version)
        self._workers.append(worker)
        worker.signals.update_available.connect(
            lambda _v, w=worker: self._workers.remove(w)
        )
        # 延迟到事件循环下一轮再 start：调用方先连信号，消除竞态
        QTimer.singleShot(0, lambda: self.thread_pool.start(worker))
        return worker.signals
