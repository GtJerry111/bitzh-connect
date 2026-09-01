# app/views/status_panel.py
"""状态仪表盘：状态标题、时长、虚拟 IP、速率。

代理模式拿不到速率计数（内核不暴露），速率卡片恒显示 "—"；TUN 模式后续接入。
"""
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from common import theme
from utils.motion_utils import animate_label_color
from views.busy_spinner import BusySpinner


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class StatusPanel(QWidget):
    def __init__(self, server_text: str = "", parent=None):
        super().__init__(parent)
        self._connected_since: datetime | None = None
        self._countdown_remaining = 0
        self._retry_attempt = 0

        layout = QVBoxLayout()
        layout.setSpacing(10)

        # ---- 状态行：spinner + 圆点 + 大标题 + 服务器 ----
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.spinner = BusySpinner(self)
        status_row.addWidget(self.spinner)
        self.status_dot = QLabel("●")
        status_row.addWidget(self.status_dot)
        self.status_text = QLabel("未连接")
        self.status_text.setFont(theme.status_title_font())
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        self.server_label = QLabel(server_text)
        self.server_label.setFont(theme.card_title_font())
        status_row.addWidget(self.server_label)
        layout.addLayout(status_row)

        # ---- 2×2 圆角卡片 ----
        grid = QGridLayout()
        grid.setSpacing(8)
        self._card_frames = []
        self.duration_value = self._add_card(grid, 0, 0, "连接时长", "00:00:00")
        self.ip_value = self._add_card(grid, 0, 1, "虚拟 IP", "—")
        self.up_rate_value = self._add_card(grid, 1, 0, "↑ 上行速率", "—")
        self.down_rate_value = self._add_card(grid, 1, 1, "↓ 下行速率", "—")
        layout.addLayout(grid)

        self.setLayout(layout)

        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._tick)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)

        self.refresh_theme()

    def _add_card(self, grid, row, col, title, initial):
        frame = QFrame()
        frame.setObjectName("statCard")
        card = QVBoxLayout(frame)
        card.setContentsMargins(12, 8, 12, 8)
        card.setSpacing(2)
        title_label = QLabel(title)
        title_label.setFont(theme.card_title_font())
        title_label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        value_label = QLabel(initial)
        value_label.setFont(theme.card_value_font())
        card.addWidget(title_label)
        card.addWidget(value_label)
        grid.addWidget(frame, row, col)
        self._card_frames.append(frame)
        return value_label

    def refresh_theme(self):
        """深浅色切换时刷新所有依赖主题色的样式。"""
        for frame in self._card_frames:
            frame.setStyleSheet(
                f"QFrame#statCard {{ background-color: {theme.card_background()};"
                f" border-radius: 10px; }}"
            )
        self.server_label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")

    def _set_status(self, text: str, color_name: str):
        self.status_text.setText(text)
        animate_label_color(self.status_dot, theme.semantic_color(color_name))

    def _tick(self):
        if self._connected_since:
            self.duration_value.setText(
                _fmt_duration(int((datetime.now() - self._connected_since).total_seconds()))
            )

    def _countdown_tick(self):
        self._countdown_remaining = max(0, self._countdown_remaining - 1)
        self.status_text.setText(
            f"连接中断，{self._countdown_remaining}s 后第 {self._retry_attempt} 次重连…"
        )
        if self._countdown_remaining == 0:
            self._countdown_timer.stop()

    # ---- 对外状态接口 ----

    def set_connecting(self):
        self._countdown_timer.stop()
        self._set_status("连接中…", "working")
        self.spinner.start()

    def set_connected(self, virtual_ip: str):
        self.spinner.stop()
        self._countdown_timer.stop()
        self._connected_since = datetime.now()
        self._set_status("已连接", "connected")
        self.ip_value.setText(virtual_ip)
        self._duration_timer.start()

    def set_reconnecting(self, attempt: int, delay: float):
        self.spinner.stop()
        self._retry_attempt = attempt
        self._countdown_remaining = int(delay)
        self._set_status(
            f"连接中断，{self._countdown_remaining}s 后第 {attempt} 次重连…", "working"
        )
        self._countdown_timer.start()

    def set_reconnect_paused(self):
        self.spinner.stop()
        self._countdown_timer.stop()
        self._set_status("自动重连已暂停（连续失败 3 次），请手动连接", "error")

    def set_disconnected(self, reason: str = ""):
        self.spinner.stop()
        self._countdown_timer.stop()
        self._connected_since = None
        self._duration_timer.stop()
        self._set_status(reason or "未连接", "error" if reason else "idle")
        self.ip_value.setText("—")
        self.duration_value.setText("00:00:00")
        self.up_rate_value.setText("—")
        self.down_rate_value.setText("—")
