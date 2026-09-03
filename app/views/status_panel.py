# app/views/status_panel.py
"""状态仪表盘（方案 B：极简大状态居中，VI 品牌色版）。

hero：自绘圆点/旋转弧（同位互斥）+ 26pt 状态词（带状态色）+ 12pt 副标题
     （状态词保持短，原因进副标题——原 F3；已连接副标题只给"内网 IP"，
      服务器地址挪 tooltip，不再双裸 IP 并排）。
状态色：圆点与状态词同色——未连接 ink 黑、连接中赭石、已连接 BIT 绿（带柔光）、
     失败红；圆点颜色 250ms 平滑过渡，状态词换字带 160ms 淡入。
统计行：时长/上行/下行无边框纯文字（tnum 防每秒抖动），仅已连接态展开
     （未连接/连接中不陈列空数据）；无数据的 "—" 占位符染次要色退后，
     真数据带 ↑↓ 前缀用主文字色跳出。
区域联动：areas_changed(credentials_visible, resources_visible) 由主窗口消费，
驱动"凭据区收起 / 资源区展开"的一收一放动画。
"""
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from common import theme
from utils.motion_utils import (
    ANIMATION_DURATION_MS,
    animate_label_color,
    animated_height_toggle,
    reduce_motion,
)
from views.busy_spinner import BusySpinner
from views.rate_graph import RateGraph


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class StatusDot(QWidget):
    """自绘状态圆点：20px 槽位内 12px 正圆（尺寸/基线可控，与 spinner 等径不跳）。

    初始色即 idle——修复"启动第一眼是黑点"（字形方案无人给初始态上色）。
    已连接态由面板挂 QGraphicsDropShadowEffect 柔光（spec 的"绿+柔光"）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self._color = QColor(theme.semantic_color("idle"))

    def setColor(self, color):
        """QVariantAnimation 逐帧回调入口（QColor 或 hex str）。"""
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        d = 12.0
        painter.drawEllipse(
            QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)
        )
        painter.end()


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
        self._dot_state = "idle"  # 当前语义色名（refresh_theme 重解析用）
        # 波形图是否有数据源（TUN 网卡计数，或 macOS 代理模式的 nettop 按进程采样）；
        # 无数据源的平台/模式不陈列空图（"不陈列空数据"的同款克制）
        self._graph_supported = False

        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(0, 24, 0, 0)

        # ---- hero：圆点/旋转弧（同槽位等径互斥）+ 状态词 + 副标题 ----
        self.spinner = BusySpinner(self, diameter=20)
        self.status_dot = StatusDot(self)
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
        self.subtitle.setFont(theme.subtitle_font())
        self.subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.subtitle)

        # ---- 统计区（容器化：仅已连接态展开，空态不陈列）----
        # 结构：统计行（时长/上行/下行）+ 实时波形图（仅在有数据源时显示）
        self.stats_area = QWidget()
        stats_col = QVBoxLayout(self.stats_area)
        # 已连接态的呼吸感：统计区上下留白加大（窗口"长一些"的主要来源之一）
        stats_col.setContentsMargins(0, 20, 0, 16)
        stats_col.setSpacing(8)
        stats = QHBoxLayout()
        stats.setSpacing(0)
        self._stat_labels = []
        self.duration_value = self._add_stat(stats, "时长")
        self.up_value = self._add_stat(stats, "上行")
        self.down_value = self._add_stat(stats, "下行")
        stats_col.addLayout(stats)
        self.rate_graph = RateGraph()
        self.rate_graph.setVisible(False)
        stats_col.addWidget(self.rate_graph)
        self.stats_area.setVisible(False)
        layout.addWidget(self.stats_area)

        self.setLayout(layout)

        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._tick)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)

        # 三个值标签统一进占位符态（"—" 灰化）
        for value in (self.duration_value, self.up_value, self.down_value):
            self._set_value(value, "—", placeholder=True)

        self.refresh_theme()

    def _add_stat(self, row, caption):
        row.addStretch()
        col = QVBoxLayout()
        col.setSpacing(2)
        value = QLabel("—")
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

    # ---- 内部：值标签 / 统计行 / hero ----

    def _set_value(self, label, text: str, placeholder: bool, color_name: str | None = None):
        """占位符染次要色退后；真数据可用语义色（数字与波形颜色自映射）。

        property 双记录（placeholder/valuecolor）供 refresh_theme 深浅色重放。
        """
        label.setText(text)
        label.setProperty("placeholder", placeholder)
        label.setProperty("valuecolor", color_name)
        color = theme.semantic_color(
            "secondary_text" if placeholder else (color_name or "ink")
        )
        label.setStyleSheet(f"color: {color};")

    def _set_stats_visible(self, visible: bool):
        """统计区展开/收起（250ms 高度+淡出，可打断；reduce-motion 即时）。

        波形图只在展开时显隐（收起由 stats_area 整体淡出覆盖，graph 不单独处理）。
        """
        if visible == getattr(self, "_stats_visible", False):
            return
        self._stats_visible = visible
        if visible:
            self.rate_graph.setVisible(self._graph_supported)
        # 波形图存在时展开终值加大（仅影响动画终点，完成后高度由内容决定）
        max_height = 148 if (visible and self._graph_supported) else 76
        animated_height_toggle(
            self.stats_area, visible, max_height=max_height, fade=True,
            on_frame=lambda: self.window().adjustSize(),
        )

    def _animate_dot_color(self, target: str):
        """圆点颜色过渡（与 animate_label_color 同款可打断/守卫纪律）。"""
        dot = self.status_dot
        old = getattr(dot, "_color_anim", None)
        if old is not None:
            dot._color_anim = None
            if isValid(old):
                old.stop()
        if reduce_motion():
            dot.setColor(target)
            return
        anim = QVariantAnimation(dot)
        anim.setDuration(ANIMATION_DURATION_MS)
        anim.setStartValue(dot._color)
        anim.setEndValue(QColor(target))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(dot.setColor)
        dot._color_anim = anim  # 身份守卫 + 持有引用防 GC
        anim.start()

    def _fade_in_hero(self):
        """状态词换字后 160ms 淡入（状态切换是核心叙事，值得一次呼吸）。"""
        if reduce_motion():
            return
        old = getattr(self, "_hero_fade", None)
        if old is not None:
            self._hero_fade = None
            if isValid(old):
                old.stop()
        effect = QGraphicsOpacityEffect(self.status_text)
        self.status_text.setGraphicsEffect(effect)
        anim = QVariantAnimation(self.status_text)
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(effect.setOpacity)

        def _cleanup():
            if getattr(self, "_hero_fade", None) is not anim:
                return
            # 终态移除效果：常驻 QGraphicsOpacityEffect 会关掉文字子像素渲染
            self.status_text.setGraphicsEffect(None)

        anim.finished.connect(_cleanup)
        self._hero_fade = anim
        anim.start()

    def refresh_theme(self):
        """深浅色/外观切换时刷新依赖主题色的样式（含圆点/状态词当前态重解析）。

        注：深色卡片分层方案已撤回——不透明卡片会盖住校训水印，得不偿失；
        深浅色统一保持透明，水印即质感。
        """
        self.setStyleSheet("")
        secondary = theme.semantic_color("secondary_text")
        self.subtitle.setStyleSheet(f"color: {secondary};")
        for label in self._stat_labels:
            label.setStyleSheet(f"color: {secondary};")
        for value in (self.duration_value, self.up_value, self.down_value):
            self._set_value(
                value, value.text(),
                bool(value.property("placeholder")),
                value.property("valuecolor"),
            )
        self.rate_graph.update()  # 波形颜色 paintEvent 现取，触发一次重绘即可
        # 状态色按当前语义重解析（不走动画，切外观是瞬时场景）
        self.status_dot.setColor(theme.semantic_color(self._dot_state))
        hero_color = "ink" if self._dot_state == "idle" else self._dot_state
        self.status_text.setStyleSheet(
            f"color: {theme.semantic_color(hero_color)};"
        )
        if self._dot_state == "connected":
            self._apply_glow(True)

    def _apply_glow(self, on: bool):
        """已连接态圆点柔光（品牌绿 60% 透明，半径 16，无偏移）。"""
        if on:
            glow = QGraphicsDropShadowEffect(self.status_dot)
            glow.setBlurRadius(16)
            color = QColor(theme.semantic_color("connected"))
            color.setAlphaF(0.6)
            glow.setColor(color)
            glow.setOffset(0, 0)
            self.status_dot.setGraphicsEffect(glow)
        else:
            self.status_dot.setGraphicsEffect(None)

    def _set_hero(self, text: str, color_name: str, subtitle: str):
        self._dot_state = color_name
        self.status_text.setText(text)
        self._fade_in_hero()
        self.subtitle.setText(subtitle)
        self._animate_dot_color(theme.semantic_color(color_name))
        # 状态词同色（idle 除外：灰词太弱，未连接用主文字色）
        hero_color = "ink" if color_name == "idle" else color_name
        animate_label_color(self.status_text, theme.semantic_color(hero_color))
        self._apply_glow(color_name == "connected")

    def _tick(self):
        if self._connected_since:
            self._set_value(
                self.duration_value,
                _fmt_duration(int((datetime.now() - self._connected_since).total_seconds())),
                placeholder=False,
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
        self._set_stats_visible(False)
        self.areas_changed.emit(True, False)

    def set_connected(self, virtual_ip: str):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._connected_since = datetime.now()
        self._virtual_ip = virtual_ip
        # 副标题只给"内网 IP"（用户语言）；服务器地址挪 tooltip（技术细节退后）
        self._set_hero("已连接", "connected", f"内网 IP {virtual_ip}")
        self.subtitle.setToolTip(self._server_text)
        self._set_value(self.duration_value, "00:00:00", placeholder=False)
        self._set_value(self.up_value, "—", placeholder=True)
        self._set_value(self.down_value, "—", placeholder=True)
        # 无速率数据源时的克制提示：常驻像素为零，tooltip 需要时在那里
        rate_tooltip = (
            "" if self._graph_supported
            else "当前平台的代理模式不支持速率统计（可在高级设置开启 TUN 模式）"
        )
        self.up_value.setToolTip(rate_tooltip)
        self.down_value.setToolTip(rate_tooltip)
        self._duration_timer.start()
        self._set_stats_visible(True)
        self.areas_changed.emit(False, True)

    def set_reconnecting(self, attempt: int, delay: float):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._duration_timer.stop()  # 重连中断期间时长冻结，连接成功由 set_connected 重启
        self._retry_attempt = attempt
        self._countdown_remaining = int(delay)
        self._set_hero("连接中断", "working", f"{self._countdown_remaining}s 后第 {attempt} 次重连…")
        self._countdown_timer.start()
        self.rate_graph.clear()  # 断点即清空：重连后不画跨断点的假连续
        self._set_stats_visible(False)
        self.areas_changed.emit(False, False)

    def set_reconnect_paused(self):
        self.spinner.stop()
        self.status_dot.setVisible(True)
        self._countdown_timer.stop()
        self._set_hero("自动重连已暂停", "error", "连续失败 3 次，请手动连接")
        self._set_stats_visible(False)
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
        self.subtitle.setToolTip("")
        self._set_value(self.duration_value, "—", placeholder=True)
        self._set_value(self.up_value, "—", placeholder=True)
        self._set_value(self.down_value, "—", placeholder=True)
        self.rate_graph.clear()  # 断连即清空：重连不画跨断点的假连续
        self._set_stats_visible(False)
        self.areas_changed.emit(True, False)

    def set_rates(self, up_text: str, down_text: str):
        """速率喂数（数字与波形颜色自映射：上行赭石、下行绿，图例因此多余）。"""
        self._set_value(self.up_value, f"↑ {up_text}", placeholder=False, color_name="working")
        self._set_value(self.down_value, f"↓ {down_text}", placeholder=False, color_name="accent")

    # ---- 波形图接口 ----

    def set_graph_supported(self, supported: bool):
        """连接发起时告知是否有速率数据源（TUN 网卡 / macOS nettop 进程采样）。"""
        self._graph_supported = supported

    def append_rate_sample(self, up_bps: float, down_bps: float):
        """波形图数值通道（与 set_rates 的格式化字符串通道分离，精度不损）。"""
        self.rate_graph.append_sample(up_bps, down_bps)
