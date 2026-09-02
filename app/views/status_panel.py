# app/views/status_panel.py
"""状态仪表盘（方案 B：极简大状态居中）。

hero：圆点/旋转弧 + 26pt 状态词 + 12pt 副标题（状态词保持短，原因进副标题，
     彻底解决长文案截断问题——原 F3）。
统计行：时长/上行/下行无边框纯文字（tnum 防每秒抖动）。
代理模式拿不到速率计数，恒显示 "—"；TUN 模式由 RateMonitor 驱动 set_rates。
区域联动：areas_changed(credentials_visible, resources_visible) 由主窗口消费，
驱动"凭据区收起 / 资源区展开"的一收一放动画。
"""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from common import theme
from utils.motion_utils import animate_label_color
from views.busy_spinner import BusySpinner


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class StatusPanel(QWidget):
    # (凭据区是否可见, 资源区是否可见)
    areas_changed = Signal(bool, bool)

    def __init__(self, server_text: str = "", parent=None):
        super().__init__(parent)
        self._server_text = server_text
        self._connected_since: datetime | None = None
        self._virtual_ip: str | None = None
        self._countdown_remaining = 0
        self._retry_attempt = 0

        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(0, 12, 0, 0)

        # ---- hero：圆点/旋转弧（同位互斥）+ 状态词 + 副标题 ----
        self.spinner = BusySpinner(self, diameter=18)
        self.status_dot = QLabel("●")
        self.status_dot.setAlignment(Qt.AlignCenter)
        dot_row = QHBoxLayout()
        dot_row.setAlignment(Qt.AlignCenter)
        dot_row.addWidget(self.spinner)
        dot_row.addWidget(self.status_dot)
        layout.addLayout(dot_row)

        self.status_text = QLabel("未连接")
        self.status_text.setFont(theme.hero_font())
        self.status_text.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_text)

        self.subtitle = QLabel(server_text)
        self.subtitle.setFont(theme.card_title_font())
        self.subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.subtitle)

        # ---- 统计行：无边框纯文字三列 ----
        stats = QHBoxLayout()
        stats.setSpacing(0)
        stats.setContentsMargins(0, 10, 0, 4)
        self._stat_labels = []
        self.duration_value = self._add_stat(stats, "00:00:00", "时长")
        self.up_value = self._add_stat(stats, "—", "↑ 上行")
        self.down_value = self._add_stat(stats, "—", "↓ 下行")
        layout.addLayout(stats)

        self.setLayout(layout)

        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._tick)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)

        self.refresh_theme()

    def _add_stat(self, row, initial, caption):
        row.addStretch()
        col = QVBoxLayout()
        col.setSpacing(2)
        value = QLabel(initial)
        value.setFont(theme.card_value_font())
        value.setAlignment(Qt.AlignCenter)
        label = QLabel(caption)
        label.setFont(theme.card_title_font())
        label.setAlignment(Qt.AlignCenter)
        col.addWidget(value)
        col.addWidget(label)
        row.addLayout(col)
        row.addStretch()
        self._stat_labels.append(label)
        return value

    # ---- 便捷只读属性（测试与外部断言用） ----

    @property
    def ip_text(self) -> str:
        return self._virtual_ip or "—"

    @property
    def duration_text(self) -> str:
        return self.duration_value.text()

    @property
    def up_text(self) -> str:
        return self.up_value.text()

    @property
    def down_text(self) -> str:
        return self.down_value.text()

    def refresh_theme(self):
        """深浅色/外观切换时刷新依赖主题色的样式。"""
        secondary = theme.semantic_color("secondary_text")
        self.subtitle.setStyleSheet(f"color: {secondary};")
        for label in self._stat_labels:
            label.setStyleSheet(f"color: {secondary};")

    def _set_hero(self, text: str, color_name: str, subtitle: str):
        self.status_text.setText(text)
        self.subtitle.setText(subtitle)
        animate_label_color(self.status_dot, theme.semantic_color(color_name))

    def _tick(self):
        if self._connected_since:
            self.duration_value.setText(
                _fmt_duration(int((datetime.now() - self._connected_since).total_seconds()))
            )

    def _countdown_tick(self):
        self._countdown_remaining = max(0, self._countdown_remaining - 1)
        self.subtitle.setText(f"{self._countdown_remaining}s 后第 {self._retry_attempt} 次重连…")
        if self._countdown_remaining == 0:
            self._countdown_timer.stop()

    def set_server_text(self, text: str):
        """高级设置改了服务器地址后同步副标题（未连接/连接中显示）。"""
        self._server_text = text
        if self.status_text.text() in ("未连接", "连接中…"):
            self.subtitle.setText(text)

    # ---- 对外状态接口 ----

    def set_connecting(self):
        self._countdown_timer.stop()
        self.spinner.start()  # 减少动态效果时为空操作（保持隐藏）
        # 互斥谓词必须用 isHidden（控件自身标志）：isVisible 是有效可见性，
        # 主窗口隐藏（托盘发起连接/silent_mode 自连）时恒 False，会导致 dot 与 spinner 同屏并现
        self.status_dot.setVisible(self.spinner.isHidden())
        self._set_hero("连接中…", "working", self._server_text)
        self.areas_changed.emit(True, False)

    def set_connected(self, virtual_ip: str):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._connected_since = datetime.now()
        self._virtual_ip = virtual_ip
        self._set_hero("已连接", "connected", f"{virtual_ip} · {self._server_text}")
        self._duration_timer.start()
        self.areas_changed.emit(False, True)

    def set_reconnecting(self, attempt: int, delay: float):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._duration_timer.stop()  # 重连中断期间时长冻结，连接成功由 set_connected 重启
        self._retry_attempt = attempt
        self._countdown_remaining = int(delay)
        self._set_hero("连接中断", "working", f"{self._countdown_remaining}s 后第 {attempt} 次重连…")
        self._countdown_timer.start()
        self.areas_changed.emit(False, False)

    def set_reconnect_paused(self):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._set_hero("自动重连已暂停", "error", "连续失败 3 次，请手动连接")
        self.areas_changed.emit(True, False)

    def set_disconnected(self, hero: str = "未连接", detail: str = ""):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._connected_since = None
        self._virtual_ip = None
        self._duration_timer.stop()
        is_error = hero != "未连接"
        self._set_hero(hero, "error" if is_error else "idle", detail or self._server_text)
        self.duration_value.setText("00:00:00")
        self.up_value.setText("—")
        self.down_value.setText("—")
        self.areas_changed.emit(True, False)

    def set_rates(self, up_text: str, down_text: str):
        """TUN 模式速率喂数（代理模式不调用，保持 "—"）。"""
        self.up_value.setText(up_text)
        self.down_value.setText(down_text)
