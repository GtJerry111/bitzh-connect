"""应用内更新弹窗：发现更新 → 下载进度 → 安装确认。"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from common import theme
from common.constants import RELEASES_URL
from services.update_service import ReleaseInfo, UpdateService, source_label
from utils import update_installer


def _fmt_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


class UpdateDialog(QDialog):
    def __init__(self, release: ReleaseInfo, asset: dict | None,
                 checksum: str | None, mirror: str, parent=None,
                 current_version: str = ""):
        super().__init__(parent)
        self.release = release
        self._current_version_text = current_version
        self.asset = asset
        self.checksum = checksum
        self.mirror = mirror
        self._service = UpdateService()
        self._download_worker = None
        self._temp_dir: str | None = None
        self._zip_path: str | None = None
        self._new_app: Path | None = None
        self._installing = False
        self._download_started = 0.0
        self._last_done = 0
        self._last_total = 0
        self.setWindowTitle("软件更新")
        self.setModal(True)
        self.setMinimumWidth(480)
        self._build_ui()
        self._apply_styles()
        self._set_stage(0)

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        self.stage_row = QHBoxLayout()
        self.stage_row.setSpacing(6)
        self._stage_labels = []
        for index, text in enumerate(("检查", "下载", "安装")):
            label = QLabel(f"{index + 1}  {text}")
            label.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text')}; font-size: 11px;"
            )
            self._stage_labels.append(label)
            self.stage_row.addWidget(label)
            if index < 2:
                line = QLabel("—")
                line.setStyleSheet(
                    f"color: {theme.semantic_color('separator')}; font-size: 11px;"
                )
                self.stage_row.addWidget(line)
        self.stage_row.addStretch()
        root.addLayout(self.stage_row)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_available_page())
        self.stack.addWidget(self._build_download_page())
        self.stack.addWidget(self._build_install_page())
        self.stack.addWidget(self._build_error_page())
        root.addWidget(self.stack)

    def _title_label(self, text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setPointSize(16)
        font.setWeight(font.Weight.DemiBold)
        label.setFont(font)
        return label

    def _sub_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        return label

    def _button(self, text: str, primary: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        if primary:
            btn.setStyleSheet(
                f"QPushButton {{ background: {theme.semantic_color('accent')};"
                f" color: {theme.semantic_color('accent_text')}; border: none;"
                " border-radius: 7px; padding: 6px 16px; font-weight: 600; }"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: {theme.card_background()};"
                f" color: {theme.semantic_color('ink')};"
                f" border: 1px solid {theme.semantic_color('separator')};"
                " border-radius: 7px; padding: 6px 16px; }"
            )
        return btn

    def _build_available_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title_label(f"发现新版本 {self.release.version}"))
        published = self.release.published_at[:10]
        subtitle = f"当前版本 {self._current_version()}"
        if published:
            subtitle += f" · {published}"
        layout.addWidget(self._sub_label(subtitle))

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(110)
        self.notes.setMaximumHeight(170)
        self.notes.setStyleSheet(
            f"QTextBrowser {{ background: {theme.with_alpha('ink', 0.04)};"
            f" border: 1px solid {theme.semantic_color('separator')};"
            " border-radius: 8px; padding: 8px; }"
        )
        body = (self.release.body or "").strip()
        if body:
            self.notes.setMarkdown(body)
        else:
            self.notes.setPlainText("暂无更新说明。")
        layout.addWidget(self.notes)

        actions = QHBoxLayout()
        actions.addStretch()
        self.later_btn = self._button("稍后")
        self.later_btn.clicked.connect(self.reject)
        actions.addWidget(self.later_btn)
        self.download_btn = self._button("下载并安装", primary=True)
        self.download_btn.clicked.connect(self._start_download)
        actions.addWidget(self.download_btn)
        layout.addLayout(actions)

        if self.release.html_url:
            link = QLabel(
                f"<a href='{self.release.html_url}'>在 GitHub 查看 ›</a>"
            )
            link.setOpenExternalLinks(True)
            link.setStyleSheet(
                f"color: {theme.semantic_color('accent')}; font-size: 11px;"
            )
            layout.addWidget(link)
        return page

    def _build_download_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title_label(f"正在下载 {self.release.version}"))
        layout.addWidget(self._sub_label("下载完成后会自动校验文件。"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setStyleSheet(
            f"QProgressBar {{ border: none; background:"
            f" {theme.semantic_color('track')}; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {theme.semantic_color('accent')};"
            " border-radius: 4px; }"
        )
        layout.addWidget(self.progress)
        meta_row = QHBoxLayout()
        self.progress_meta = QLabel("准备下载…")
        self.progress_meta.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; font-size: 11px;"
        )
        self.speed_meta = QLabel("")
        self.speed_meta.setAlignment(Qt.AlignRight)
        self.speed_meta.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; font-size: 11px;"
        )
        meta_row.addWidget(self.progress_meta)
        meta_row.addStretch()
        meta_row.addWidget(self.speed_meta)
        layout.addLayout(meta_row)
        self.source_meta = QLabel("")
        self.source_meta.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; font-size: 11px;"
        )
        layout.addWidget(self.source_meta)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_btn = self._button("取消")
        self.cancel_btn.clicked.connect(self._cancel_download)
        actions.addWidget(self.cancel_btn)
        layout.addLayout(actions)
        return page

    def _build_install_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title_label(f"准备安装 {self.release.version}"))
        self.install_status = self._sub_label("文件已下载，正在准备校验…")
        layout.addWidget(self.install_status)
        self.install_warning = QLabel(
            "更新会退出 App 并重新启动。\n"
            "VPN 会断开，公司/学校 SSH 会短暂中断；安装时需要一次管理员授权。"
        )
        self.install_warning.setWordWrap(True)
        self.install_warning.setStyleSheet(
            f"background: {theme.with_alpha('working', 0.12)};"
            f" border: 1px solid {theme.with_alpha('working', 0.35)};"
            f" color: {theme.semantic_color('working')};"
            " border-radius: 8px; padding: 9px 11px; font-size: 12px;"
        )
        layout.addWidget(self.install_warning)
        actions = QHBoxLayout()
        actions.addStretch()
        self.install_later_btn = self._button("稍后")
        self.install_later_btn.clicked.connect(self.reject)
        actions.addWidget(self.install_later_btn)
        self.install_btn = self._button("现在更新", primary=True)
        self.install_btn.clicked.connect(self._install)
        actions.addWidget(self.install_btn)
        layout.addLayout(actions)
        return page

    def _build_error_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title_label("下载失败"))
        self.error_message = QLabel("")
        self.error_message.setWordWrap(True)
        self.error_message.setStyleSheet(
            f"background: {theme.with_alpha('error', 0.12)};"
            f" border: 1px solid {theme.with_alpha('error', 0.35)};"
            f" color: {theme.semantic_color('error')};"
            " border-radius: 8px; padding: 9px 11px; font-size: 12px;"
        )
        layout.addWidget(self.error_message)
        actions = QHBoxLayout()
        actions.addStretch()
        self.retry_btn = self._button("重试")
        self.retry_btn.clicked.connect(self._retry_download)
        actions.addWidget(self.retry_btn)
        self.open_page_btn = self._button("打开下载页")
        self.open_page_btn.clicked.connect(self._open_page)
        actions.addWidget(self.open_page_btn)
        self.error_cancel_btn = self._button("取消")
        self.error_cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.error_cancel_btn)
        layout.addLayout(actions)
        return page

    def _apply_styles(self):
        self.setStyleSheet(
            f"QDialog {{ background: {theme.card_background()}; }}"
        )

    def _current_version(self) -> str:
        return self._current_version_text

    def _set_stage(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, label in enumerate(self._stage_labels):
            if i < index:
                color = theme.semantic_color("accent")
                prefix = "✓"
            elif i == index:
                color = theme.semantic_color("ink")
                prefix = str(i + 1)
            else:
                color = theme.semantic_color("secondary_text")
                prefix = str(i + 1)
            label.setText(f"{prefix}  {('检查', '下载', '安装')[i]}")
            label.setStyleSheet(f"color: {color}; font-size: 11px;")

    # ---------------- 下载 ----------------

    def _start_download(self):
        if not self.asset:
            self._show_error("当前版本没有可用的 macOS 更新包，请前往下载页。")
            return
        self._cleanup_temp()
        self._temp_dir = tempfile.mkdtemp(prefix="bitzh-update-")
        self._zip_path = None
        self._new_app = None
        self._download_started = time.monotonic()
        self._last_done = 0
        self._last_total = 0
        self.progress.setRange(0, 0)
        self.progress_meta.setText("准备下载…")
        self.speed_meta.setText("")
        self.source_meta.setText("")
        self._set_stage(1)
        worker = self._service.download_update(
            self.asset, self.checksum, self.mirror, self._temp_dir
        )
        self._download_worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.source.connect(self._on_source)
        worker.signals.finished.connect(self._on_downloaded)
        worker.signals.error.connect(self._on_download_error)
        worker.signals.cancelled.connect(self._on_cancelled)

    def _on_source(self, url: str):
        self.source_meta.setText(f"下载源：{source_label(url)}")

    def _on_progress(self, done: int, total: int):
        self._last_done = done
        self._last_total = total
        if total > 0:
            percent = min(100, int(done * 100 / total))
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self.progress_meta.setText(f"{percent}% · {_fmt_bytes(done)} / {_fmt_bytes(total)}")
            elapsed = time.monotonic() - self._download_started
            if elapsed < 0.5 or done < 64 * 1024:
                self.speed_meta.setText("正在计算速度…")
            else:
                speed = done / elapsed
                if total > done and speed > 0:
                    remaining = max(0, total - done) / speed
                    if remaining < 3600:
                        time_text = f"约 {int(remaining)} 秒"
                    else:
                        time_text = f"约 {remaining / 60:.0f} 分钟"
                    self.speed_meta.setText(
                        f"{_fmt_bytes(int(speed))}/s · {time_text}"
                    )
                else:
                    self.speed_meta.setText(f"{_fmt_bytes(int(speed))}/s")
        else:
            self.progress.setRange(0, 0)
            self.progress_meta.setText(f"已下载 {_fmt_bytes(done)}")
            self.speed_meta.setText("")

    def _on_downloaded(self, path: str):
        self._download_worker = None
        self._zip_path = path
        try:
            extracted = os.path.join(self._temp_dir or "", "extracted")
            self._new_app = update_installer.prepare_update(
                path, extracted, self.release.version
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        if self.checksum:
            self.install_status.setText("文件已下载并通过 SHA256 校验。")
        else:
            self.install_status.setText("文件已下载；发布方未提供校验文件，无法验证完整性。")
        self._set_stage(2)
        self.install_btn.setEnabled(True)

    def _on_download_error(self, message: str):
        self._download_worker = None
        self._show_error(message)

    def _on_cancelled(self):
        self._download_worker = None
        self._cleanup_temp()
        if self.isVisible():
            self.reject()

    def _show_error(self, message: str):
        self.error_message.setText(message)
        self.stack.setCurrentIndex(3)

    def _retry_download(self):
        self._start_download()

    def _cancel_download(self):
        if self._download_worker is not None:
            self._download_worker.cancel()
            self._download_worker = None
        self._cleanup_temp()
        self.reject()

    def _open_page(self):
        QDesktopServices.openUrl(QUrl(self.release.html_url or RELEASES_URL))

    def _cleanup_temp(self):
        if self._installing:
            return
        if self._temp_dir:
            update_installer.cleanup_dir(self._temp_dir)
            self._temp_dir = None

    # ---------------- 安装 ----------------

    def _install(self):
        if not self._new_app:
            QMessageBox.warning(self, "无法更新", "更新包尚未准备好，请重新下载。")
            return
        bundle = update_installer.app_bundle_path()
        if not update_installer.is_update_supported_bundle(bundle):
            QMessageBox.warning(
                self,
                "无法内置更新",
                "请先将 BITZH Connect 放入 Applications，再使用应用内更新；"
                "也可以前往 GitHub 手动下载。",
            )
            self._open_page()
            return
        self.install_btn.setEnabled(False)
        main_window = self._main_window()
        button = getattr(main_window, "connect_button", None)
        if button is not None and button.isChecked():
            self.install_status.setText("正在断开 VPN，随后会退出 App…")
            try:
                main_window.stop_connection()
            except Exception:
                pass
            QTimer.singleShot(1200, lambda: self._launch_installer(bundle))
        else:
            self._launch_installer(bundle)

    def _main_window(self):
        widget = self.parent()
        while widget is not None and not hasattr(widget, "connect_button"):
            widget = widget.parent()
        return widget

    def _launch_installer(self, bundle: Path):
        try:
            script = update_installer.write_install_script(
                bundle, self._new_app, os.getpid()
            )
            ok = update_installer.launch_installer(script)
        except Exception as exc:
            ok = False
            QMessageBox.critical(self, "更新失败", str(exc))
        if not ok:
            self.install_btn.setEnabled(True)
            self.install_status.setText("未获得管理员授权，更新未开始。")
            return
        self._installing = True
        self.accept()
        QTimer.singleShot(0, lambda: QApplication.instance().quit())

    # ---------------- 关闭 ----------------

    def reject(self):
        if not self._installing:
            if self._download_worker is not None:
                self._download_worker.cancel()
                self._download_worker = None
            self._cleanup_temp()
        super().reject()

    def closeEvent(self, event):
        if not self._installing:
            if self._download_worker is not None:
                self._download_worker.cancel()
                self._download_worker = None
            self._cleanup_temp()
        super().closeEvent(event)


# 局部导入避免顶层循环；QApplication 仅退出时使用
from PySide6.QtWidgets import QApplication  # noqa: E402
