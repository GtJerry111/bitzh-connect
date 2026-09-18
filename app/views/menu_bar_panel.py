# app/views/menu_bar_panel.py
"""菜单栏快捷面板（macOS 专属，液态玻璃范式，布局 A：连接卡 + 裸行 + 工具条）。

定位：主窗口是唯一完整 UI；面板是状态栏图标左键唤出的快捷操作面。
状态镜像：只读 MainWindow/StatusPanel（state_changed 信号即时 + 1s 轮询时长/速率），
不复制状态机；toggle 拨动 = main.connect_button.setChecked（校验早退会复位按钮，
面板经 toggled 镜像弹回）。
外壳（flags/玻璃/定位/动画）见 Task 4——本文件结构与方法全集在此。
"""
from platform import system

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QRectF, Qt, QTimer, QUrl, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from common import theme
from common.constants import NAV_GROUPS
from utils.motion_utils import ANIMATION_DURATION_MS, animated_height_toggle, reduce_motion
from views.chevron import Chevron
from views.status_panel import StatusDot
from views.toggle_switch import ToggleSwitch

_PANEL_WIDTH = 300


def _draw_icon(painter: QPainter, kind: str):
    """24px 网格单色线条图标（swap/grid/gear/power/window/chevron_right）。

    颜色由调用方设 pen。行内图标用 secondary_text（退后），工具按钮用 ink。
    """
    if kind == "swap":
        painter.drawLine(QPointF(6, 8), QPointF(18, 8))
        painter.drawLine(QPointF(14, 4), QPointF(18, 8))
        painter.drawLine(QPointF(18, 8), QPointF(14, 12))
        painter.drawLine(QPointF(6, 16), QPointF(18, 16))
        painter.drawLine(QPointF(10, 12), QPointF(6, 16))
        painter.drawLine(QPointF(6, 16), QPointF(10, 20))
    elif kind == "grid":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.6, 1.6)
    elif kind == "gear":
        painter.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        for i in range(8):
            painter.save()
            painter.translate(12, 12)
            painter.rotate(i * 45)
            painter.drawLine(QPointF(0, -5.6), QPointF(0, -8.2))
            painter.restore()
    elif kind == "power":
        painter.drawLine(QPointF(12, 4), QPointF(12, 11))
        painter.drawArc(QRectF(5.5, 6.5, 13, 13), 130 * 16, 280 * 16)
    elif kind == "window":
        painter.drawRoundedRect(QRectF(4, 5, 16, 14), 2.5, 2.5)
        painter.drawLine(QPointF(4, 9.5), QPointF(20, 9.5))
    elif kind == "chevron_right":
        painter.drawLine(QPointF(9, 5), QPointF(16, 12))
        painter.drawLine(QPointF(16, 12), QPointF(9, 19))


def icon_pixmap(kind: str, size: int = 15, color: str | None = None) -> QPixmap:
    """把线条图标渲染成 QPixmap（@2x 保 Retina 清晰），供 QPushButton setIcon。"""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color or theme.semantic_color("ink")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.scale(size / 24.0, size / 24.0)
    _draw_icon(painter, kind)
    painter.end()
    return pm


class _Icon(QWidget):
    """行内线条图标（_draw_icon 的 widget 形态）。"""

    def __init__(self, kind: str, size: int = 15, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.semantic_color("secondary_text")))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.scale(self.width() / 24.0, self.width() / 24.0)
        _draw_icon(painter, self._kind)
        painter.end()


class _Row(QWidget):
    """菜单行：图标 + 标签 + 右侧值/指示，整行可点（hover 圆角亮底）。"""

    clicked = Signal()

    def __init__(self, icon_kind: str, title: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(33)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(8)
        row.addWidget(_Icon(icon_kind))
        self.title = QLabel(title)
        self.title.setFont(theme.subtitle_font())
        row.addWidget(self.title)
        row.addStretch()
        self.value = QLabel("")
        row.addWidget(self.value)
        self._trailing_slot = QHBoxLayout()
        row.addLayout(self._trailing_slot)
        self.refresh_theme()

    def set_trailing(self, widget):
        self._trailing_slot.addWidget(widget)

    def mousePressEvent(self, event):
        self.clicked.emit()

    def refresh_theme(self):
        self.setStyleSheet(f"""
            _Row {{ border-radius: 8px; }}
            _Row:hover {{ background: {theme.with_alpha("accent", 0.08)}; }}
        """)
        self.value.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")


class MenuBarPanel(QWidget):
    """快捷面板：连接卡 + 模式/导航裸行 + 底部工具条。"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self._nav_expanded = False
        self._hint_active = False
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(_PANEL_WIDTH)
        self._build_ui()
        self._apply_styles()
        theme.on_scheme_changed(self._apply_styles)
        # 状态镜像：state_changed 即时；1s 轮询补时长/速率（仅可见时）
        main_window.status_panel.state_changed.connect(self._sync_from_main)
        main_window.connect_button.toggled.connect(self._sync_toggle)
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._sync_metrics)
        self._sync_from_main()
        self._sync_metrics()

    # ---- 结构 ----

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # 连接卡
        self.conn_card = QWidget()
        self.conn_card.setObjectName("PanelCard")
        self.conn_card.setAttribute(Qt.WA_StyledBackground, True)
        card = QVBoxLayout(self.conn_card)
        card.setContentsMargins(12, 10, 12, 10)
        card.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        self._dot = StatusDot(self.conn_card)
        head.addWidget(self._dot)
        self._status = QLabel("未连接")
        font = self._status.font()
        font.setPointSize(14.5)
        font.setWeight(QFont.DemiBold)
        self._status.setFont(font)
        head.addWidget(self._status)
        head.addStretch()
        self._toggle = ToggleSwitch(self.conn_card)
        self._toggle.toggled.connect(self._on_toggle)
        head.addWidget(self._toggle)
        card.addLayout(head)
        self._subtitle = QLabel("")
        self._subtitle.setContentsMargins(18, 0, 0, 0)  # 与状态词左对齐（dot 20px 槽位）
        self._subtitle.setFont(theme.card_title_font())
        card.addWidget(self._subtitle)
        # 速率三列（卡内、细分隔线之下；仅已连接态展开）
        self._stats_area = QWidget()
        stats_box = QVBoxLayout(self._stats_area)
        stats_box.setContentsMargins(0, 0, 0, 0)
        stats_box.setSpacing(6)
        from PySide6.QtWidgets import QFrame

        hairline = QFrame()
        hairline.setFrameShape(QFrame.HLine)
        hairline.setStyleSheet(f"color: {theme.with_alpha('separator', 0.6)};")
        stats_box.addWidget(hairline)
        row = QHBoxLayout()
        row.setSpacing(0)
        self._duration = self._add_stat(row, "时长")
        self._up = self._add_stat(row, "↑ 上行")
        self._down = self._add_stat(row, "↓ 下行")
        stats_box.addLayout(row)
        self._stats_area.setVisible(False)
        card.addWidget(self._stats_area)
        root.addWidget(self.conn_card)

        # 裸行区（行间 0.5px hairline）
        self._rows = QWidget()
        rows = QVBoxLayout(self._rows)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self._mode_row = _Row("swap", "连接模式")
        self._mode_row.set_trailing(_Icon("chevron_right", 10))
        self._mode_row.clicked.connect(self._on_mode_row)
        rows.addWidget(self._mode_row)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {theme.with_alpha('separator', 0.4)};")
        rows.addWidget(sep)
        self._nav_row = _Row("grid", "校内导航")
        self._nav_chevron = Chevron()
        self._nav_chevron.set_angle(90.0)  # 收起态朝下（展开器语义）
        self._nav_row.set_trailing(self._nav_chevron)
        self._nav_row.clicked.connect(self._toggle_nav)
        rows.addWidget(self._nav_row)
        # 导航展开区（Task 6 填 chips；本任务为空容器）
        self._nav_area = QWidget()
        self._nav_area.setVisible(False)
        rows.addWidget(self._nav_area)
        root.addWidget(self._rows)

        # 底部工具条
        bar = QHBoxLayout()
        bar.setSpacing(7)
        self._open_btn = QPushButton(" 打开主窗口")
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.clicked.connect(lambda: self._main.open_main_window())
        bar.addWidget(self._open_btn)
        bar.addStretch()
        self._settings_btn = self._round_button("gear", "设置")
        self._settings_btn.clicked.connect(self._open_settings)
        self._quit_btn = self._round_button("power", "退出")
        self._quit_btn.clicked.connect(self._main.quit_app)
        bar.addWidget(self._settings_btn)
        bar.addWidget(self._quit_btn)
        root.addLayout(bar)

    def _add_stat(self, row, caption: str):
        col = QVBoxLayout()
        col.setSpacing(1)
        value = QLabel("—")
        value.setFont(theme.card_value_font())
        value.setAlignment(Qt.AlignCenter)
        label = QLabel(caption)
        label.setFont(theme.card_title_font())
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        col.addWidget(value)
        col.addWidget(label)
        row.addStretch()
        row.addLayout(col)
        row.addStretch()
        return value

    def _round_button(self, icon_kind: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setIcon(QIcon(icon_pixmap(icon_kind, 13)))
        btn.setProperty("chip", True)  # QSS 选择器用
        return btn

    # ---- 样式 ----

    def _apply_styles(self):
        self.conn_card.setStyleSheet(
            f"QWidget#PanelCard {{ {theme.card_qss(glass=True)} }}"
        )
        chip_bg = "rgba(255,255,255,107)" if not theme.is_dark() else "rgba(64,64,68,128)"
        chip_bd = "rgba(255,255,255,140)" if not theme.is_dark() else "rgba(255,255,255,36)"
        self._open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {chip_bg}; border: 1px solid {chip_bd};
                border-radius: 14px; padding: 5px 12px; font-size: 12px;
                color: {theme.semantic_color("ink")};
            }}
            QPushButton:pressed {{ padding-top: 6px; }}
        """)
        for btn in (self._settings_btn, self._quit_btn):
            btn.setStyleSheet(f"""
                QPushButton[chip="true"] {{
                    background: {chip_bg}; border: 1px solid {chip_bd};
                    border-radius: 14px;
                }}
                QPushButton[chip="true"]:pressed {{ background: {chip_bd}; }}
            """)
        self._mode_row.refresh_theme()
        self._nav_row.refresh_theme()
        if not self._hint_active:
            self._subtitle.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text')};"
            )
        # 图标颜色随主题（ink 经 icon_pixmap 烘焙，需重建）
        self._open_btn.setIcon(QIcon(icon_pixmap("window", 12)))
        self._settings_btn.setIcon(QIcon(icon_pixmap("gear", 13)))
        self._quit_btn.setIcon(QIcon(icon_pixmap("power", 13)))

    # ---- 状态镜像 ----

    def _sync_from_main(self):
        sp = self._main.status_panel
        state = sp.dot_state
        self._status.setText(sp.status_text.text())
        if not self._hint_active:
            self._subtitle.setText(sp.subtitle.text())
        color = theme.semantic_color("ink" if state == "idle" else state)
        self._status.setStyleSheet(f"color: {color};")
        self._dot.setColor(theme.semantic_color(state))
        self._set_stats_visible(state == "connected")
        self._sync_toggle(self._main.connect_button.isChecked())
        self._sync_mode_label()

    def _sync_toggle(self, checked: bool):
        # 同态 setChecked 不发信号，不回环；异态经 toggled 走 knob 动画
        self._toggle.setChecked(checked)

    def _sync_metrics(self):
        sp = self._main.status_panel
        for label, text in (
            (self._duration, sp.duration_text),
            (self._up, sp.up_text),
            (self._down, sp.down_text),
        ):
            label.setText(text)
            placeholder = text == "—"
            label.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text' if placeholder else 'ink')};"
            )
        self._sync_mode_label()
        # 兜底自愈：QSignalBlocker 静默复位 connect_button 的路径（进程意外退出/认证失败/
        # TUN 授权取消/冲突）不触发 toggled 回调，轮询里补一次 toggle 同步，
        # 避免面板卡在与实际不符的 ON 态（≤1s 收敛；面板隐藏时 show_panel 会再同步）。
        self._sync_toggle(self._main.connect_button.isChecked())

    def _sync_mode_label(self):
        self._mode_row.value.setText("TUN" if self._main.tun_mode else "代理")

    def _set_stats_visible(self, visible: bool):
        if visible == getattr(self, "_stats_visible", False):
            return
        self._stats_visible = visible
        animated_height_toggle(
            self._stats_area, visible, max_height=64, fade=True,
            on_frame=self.adjustSize,
        )

    # ---- 交互 ----

    def _on_toggle(self, checked: bool):
        btn = self._main.connect_button
        btn.setChecked(checked)
        if checked and not btn.isChecked():
            # 同步早退复位（start_connection 校验失败）：面板 toggle 也须弹回，
            # 否则 UI 显示已连接而实际未连。主窗口 _reset_connect_ui 用 QSignalBlocker
            # 屏蔽了 connect_button.toggled，故不会经 _sync_toggle 回调，须显式复位。
            self._sync_toggle(btn.isChecked())
            if not (self._main.username_input.text() and self._main.password_input.text()):
                self._show_credential_hint()
                self._main.open_main_window(focus_credentials=True)

    def _show_credential_hint(self):
        self._hint_active = True
        self._subtitle.setText("请先在主窗口填写凭据")
        self._subtitle.setStyleSheet(f"color: {theme.semantic_color('error')};")
        QTimer.singleShot(3000, self._clear_credential_hint)

    def _clear_credential_hint(self):
        self._hint_active = False
        self._subtitle.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')};"
        )
        self._sync_from_main()

    def _on_mode_row(self):
        """原生 NSMenu 弹出；模块未实装（Task 5 前）或桥接失败 → 兜底直接切换。

        popup_menu 用局部导入：Task 5 才创建该模块，顶层导入会让 Task 3 无法运行。
        """
        items = ["代理", "TUN 全局路由"]
        checked = 1 if self._main.tun_mode else 0
        try:
            from utils.macos_menu_popup import popup_menu

            choice = popup_menu(items, checked, self._mode_row.mapToGlobal(
                self._mode_row.rect().bottomRight()))
        except Exception:
            # 原生菜单不可用：退化为点击直接切换
            self._main.set_connection_mode(not self._main.tun_mode)
            return
        if choice is not None and choice != checked:
            self._main.set_connection_mode(choice == 1)
        self._sync_mode_label()

    def _toggle_nav(self):
        """校内导航内联展开（chips 网格 Task 6 填充；本任务展开空容器）。"""
        self._nav_expanded = not self._nav_expanded
        angle = 270.0 if self._nav_expanded else 90.0
        if reduce_motion():
            self._nav_chevron.set_angle(angle)
        else:
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setStartValue(self._nav_chevron._angle)
            anim.setEndValue(angle)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._nav_chevron.set_angle)
            anim.start()
        animated_height_toggle(
            self._nav_area, self._nav_expanded,
            max_height=max(self._nav_area.sizeHint().height(), 1),
            fade=True, on_frame=self.adjustSize,
        )

    def _open_settings(self):
        from views.menu_utils import show_advanced_settings

        show_advanced_settings(self._main)

    # ---- 显隐（Task 4 填动画/定位；先给最小可用） ----

    def toggle(self):
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_panel()

    def show_panel(self, animated: bool = True):
        self._sync_from_main()
        self._sync_metrics()
        self.show()
        self._poll.start()

    def hide_panel(self):
        self._poll.stop()
        self.hide()
