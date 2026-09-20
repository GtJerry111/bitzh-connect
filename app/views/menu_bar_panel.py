# app/views/menu_bar_panel.py
"""菜单栏快捷面板（macOS 专属，液态玻璃范式，布局 A：连接卡 + 裸行 + 工具条）。

定位：主窗口是唯一完整 UI；面板是状态栏图标左键唤出的快捷操作面。
状态镜像：只读 MainWindow/StatusPanel（state_changed 信号即时 + 1s 轮询时长/速率），
不复制状态机；toggle 拨动 = main.connect_button.setChecked（校验早退会复位按钮，
面板经 toggled 镜像弹回）。
外壳：无边框置顶透明窗口 + 22px 玻璃/毛玻璃 + 图标锚定定位 +
慢开快收动画 + Esc/失焦收起 + 抢焦点激活。
"""
from platform import system

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from common import theme
from common.constants import NAV_GROUPS
from utils.macos_sf_symbols import sf_symbol_pixmap
from utils.motion_utils import animated_height_toggle, reduce_motion
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
        # 填充式齿轮（环 + 8 齿，内孔减除）：描边式齿轮在小尺寸下像"亮度/深色模式"太阳
        from PySide6.QtGui import QPainterPath, QTransform

        ring = QPainterPath()
        ring.addEllipse(QPointF(12, 12), 7.4, 7.4)
        for i in range(8):
            # 齿直接在中心系建造（顶部齿），与环外缘交叠 1.5 格防游离；
            # QPainterPath 无 transformed()：T⁻¹→R→T 绕中心旋转，用 QTransform.map
            tooth = QPainterPath()
            tooth.addRoundedRect(QRectF(12 - 1.9, 12 - 10.2, 3.8, 4.3), 0.9, 0.9)
            transform = QTransform().translate(12, 12).rotate(i * 45).translate(-12, -12)
            ring |= transform.map(tooth)
        hole = QPainterPath()
        hole.addEllipse(QPointF(12, 12), 3.2, 3.2)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(painter.pen().color())
        painter.drawPath(ring.subtracted(hole))
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


class _Icon(QWidget):
    """行内线条图标：SF Symbols 优先（官方字重统一），取不到回退 _draw_icon 自绘。"""

    def __init__(self, kind: str, size: int = 15, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        pm = sf_symbol_pixmap(
            self._kind, self.width(), theme.semantic_color("secondary_text")
        )
        if pm is not None:
            painter = QPainter(self)
            painter.drawPixmap(QPointF(0, 0), pm)
            painter.end()
            return
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


class _RadioRow(QWidget):
    """radio 行（参考图圆点列表）：左圆点 + 名称 + 右侧说明，整行可点。

    全 QPainter 自绘（圆点/文字/hover 底），颜色现取主题（深浅色 update 即可）。
    """

    clicked = Signal()

    def __init__(self, title: str, sub: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._sub = sub
        self._on = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)

    def set_on(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def is_on(self) -> bool:
        return self._on

    def mousePressEvent(self, event):
        self.clicked.emit()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor("accent", 0.08))
            painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
        # 圆点：选中 = accent 实心 + 白内点；未选 = secondary 细环
        cx, cy = 6 + 8.5, h / 2
        if self._on:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor("accent"))
            painter.drawEllipse(QPointF(cx, cy), 8.5, 8.5)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
        else:
            pen = QPen(theme.qcolor("secondary_text"))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), 7.75, 7.75)
        painter.setPen(theme.qcolor("ink"))
        font = painter.font()
        font.setPointSize(12.5)
        painter.setFont(font)
        painter.drawText(QRectF(30, 0, w - 30, h), Qt.AlignVCenter, self._title)
        if self._sub:
            sub_font = painter.font()
            sub_font.setPointSize(10)
            painter.setFont(sub_font)
            painter.setPen(theme.qcolor("secondary_text"))
            painter.drawText(
                QRectF(0, 0, w - 8, h), Qt.AlignRight | Qt.AlignVCenter, self._sub
            )
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


class _GlassButton(QAbstractButton):
    """玻璃 chip 按钮（QPainter 自绘：圆角填充 + 1px 高光描边 + 图标/可选文字）。

    QSS 的 1px 半透边框在透明底（WA_TranslucentBackground）窗口上抗锯齿向错误
    底色混合，边缘出毛刺；自绘走 QPainter 路径（与 ToggleSwitch 同款），边缘干净。
    颜色在 paintEvent 现取主题——深浅色切换只需 update()，无需重建资源。
    """

    def __init__(self, icon_kind: str, text: str = "", tooltip: str = "", parent=None):
        super().__init__(parent)
        self._icon_kind = icon_kind
        self._text = text
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setFixedHeight(28)
        if not text:
            self.setFixedWidth(28)

    def sizeHint(self):
        from PySide6.QtCore import QSize

        if not self._text:
            return QSize(28, 28)
        from PySide6.QtGui import QFontMetrics

        fm = QFontMetrics(self.font())
        # 左右各 12 内边距 + 13px 图标 + 6px 图标文字间距 + 文字宽
        return QSize(12 + 13 + 6 + fm.horizontalAdvance(self._text) + 12, 28)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        dark = theme.is_dark()
        w, h = self.width(), self.height()
        # 有玻璃件（clear 液态玻璃）时材质归原生：只画内容；
        # 无玻璃件（旧系统/offscreen）自绘底：填充 + 发丝描边
        if getattr(self, "_glass_piece", None) is None:
            # 填充：常态 = 二级材质；hover 微亮；pressed 加深
            if self.isDown():
                fill = QColor(64, 64, 68, 170) if dark else QColor(255, 255, 255, 80)
            elif self._hover:
                fill = QColor(64, 64, 68, 160) if dark else QColor(255, 255, 255, 140)
            else:
                fill = QColor(64, 64, 68, 128) if dark else QColor(255, 255, 255, 107)
            # 浅色：白描边在亮玻璃上不可见，用深色发丝线（Apple 玻璃对比惯例）
            border = QColor(255, 255, 255, 36) if dark else QColor(60, 60, 67, 30)
            pen = QPen(border)
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(fill)
            # 0.5px 内缩：描边骑缝在边界上，避免外缘超出控件矩形被裁
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), h / 2, h / 2)
        # 内容（图标 + 可选文字）整体居中；图标 SF Symbols 优先，回退自绘
        ink_name = theme.semantic_color("ink")
        ink = QColor(ink_name)
        icon_px = 13
        text_w = 0
        if self._text:
            text_w = painter.fontMetrics().horizontalAdvance(self._text)
        total = icon_px + (6 + text_w if self._text else 0)
        x = (w - total) / 2
        pm = sf_symbol_pixmap(self._icon_kind, icon_px, ink_name)
        if pm is not None:
            painter.drawPixmap(QPointF(x, (h - icon_px) / 2), pm)
        else:
            painter.save()
            painter.translate(x, (h - icon_px) / 2)
            painter.scale(icon_px / 24.0, icon_px / 24.0)
            icon_pen = QPen(ink)
            icon_pen.setWidthF(1.5)
            icon_pen.setCapStyle(Qt.RoundCap)
            icon_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(icon_pen)
            painter.setBrush(Qt.NoBrush)
            _draw_icon(painter, self._icon_kind)
            painter.restore()
        if self._text:
            painter.setPen(ink)
            painter.drawText(
                QRectF(x + icon_px + 6, 0, text_w, h), Qt.AlignVCenter, self._text
            )
        painter.end()


class MenuBarPanel(QWidget):
    """快捷面板：连接卡 + 模式/导航裸行 + 底部工具条。"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self._hint_active = False
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(_PANEL_WIDTH)
        self._build_ui()
        self._apply_styles()
        theme.on_scheme_changed(self._refresh_theme)
        # 状态镜像：state_changed 即时；1s 轮询补时长/速率（仅可见时）
        main_window.status_panel.state_changed.connect(self._sync_from_main)
        main_window.connect_button.toggled.connect(self._sync_toggle)
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._sync_metrics)
        self._sync_from_main()
        self._sync_metrics()

        # Esc 收起（面板无标题栏/关闭按钮，Esc 是显式收起的键盘路径）
        from PySide6.QtGui import QKeySequence, QShortcut

        self._esc = QShortcut(QKeySequence("Esc"), self)
        self._esc.setContext(Qt.WindowShortcut)
        self._esc.activated.connect(self._on_esc)
        self.winId()  # 真实化 NSWindow，供玻璃垫层安装
        from utils.macos_glass import GLASS_STYLE_REGULAR, install_glass

        # 材质分层（参考图定稿）：底板 = regular 乳白玻璃（整窗），
        # 卡片/工具条按钮 = clear 玻璃件（独立折射高光，官方交互光学响应）
        if not install_glass(self, corner_radius=22.0, style=GLASS_STYLE_REGULAR):
            from utils.macos_vibrancy import install_vibrancy

            install_vibrancy(self, corner_radius=22.0)
        self._install_glass_pieces()
        # 窗口 frame 同半径圆角：否则系统按矩形窗口算阴影，四角露出方形阴影残角
        from utils.macos_panel_shape import round_panel_window

        round_panel_window(self)
        self.installEventFilter(self)  # LayoutRequest/Resize → 玻璃件几何跟随

    def _install_glass_pieces(self):
        """卡片与工具条按钮安装 clear 玻璃件；无底板/旧系统时安静回退 QSS 卡面。"""
        from utils.macos_glass import install_glass_piece

        self._glass_targets = [
            (self.conn_card, 14.0), (self._rows, 14.0),
            (self._nav_header, 14.0), (self._nav_card, 14.0),
            (self._mode_header, 14.0), (self._mode_card, 14.0),
            (self._open_btn, 14.0), (self._settings_btn, 14.0),
            (self._quit_btn, 14.0),
        ]
        for w, radius in self._glass_targets:
            install_glass_piece(self, w, corner_radius=radius)

    def _sync_glass_pieces(self):
        from utils.macos_glass import sync_glass_piece

        for w, _radius in getattr(self, "_glass_targets", []):
            sync_glass_piece(self, w)

    def eventFilter(self, obj, event):
        """布局/尺寸变化 → 玻璃件 frame 跟随。

        Resize 时布局已完成 → 立即同步；LayoutRequest 发布局前 → 事件循环
        下一轮同步（singleShot(0) 让布局先跑完，几何才正确）。
        """
        if obj is self:
            if event.type() == QEvent.Resize:
                self._sync_glass_pieces()
            elif event.type() == QEvent.LayoutRequest:
                QTimer.singleShot(0, self._sync_glass_pieces)
        return super().eventFilter(obj, event)

    # ---- 结构（QStackedWidget 三页：主页 / 导航页 / 模式页） ----

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        from PySide6.QtWidgets import QStackedWidget

        self._stack = QStackedWidget(self)
        root.addWidget(self._stack)

        # ===== 主页 =====
        page_main = QWidget()
        main = QVBoxLayout(page_main)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(6)

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

        # 卡内细分隔线：颜色统一由 _apply_styles 按当前主题发放（存引用供刷新）
        self._card_hairline = QFrame()
        self._card_hairline.setFrameShape(QFrame.HLine)
        stats_box.addWidget(self._card_hairline)
        row = QHBoxLayout()
        row.setSpacing(0)
        self._duration = self._add_stat(row, "时长")
        self._up = self._add_stat(row, "↑ 上行")
        self._down = self._add_stat(row, "↓ 下行")
        stats_box.addLayout(row)
        self._stats_area.setVisible(False)
        card.addWidget(self._stats_area)
        main.addWidget(self.conn_card)

        # 行卡（两个导航入口，› 二级页语义；行间 0.5px hairline）
        self._rows = QWidget()
        self._rows.setObjectName("PanelCard")
        self._rows.setAttribute(Qt.WA_StyledBackground, True)
        rows = QVBoxLayout(self._rows)
        rows.setContentsMargins(0, 4, 0, 4)  # 卡片上下呼吸位
        rows.setSpacing(0)
        self._mode_row = _Row("swap", "连接模式")
        self._mode_row.set_trailing(_Icon("chevron_right", 10))
        self._mode_row.clicked.connect(lambda: self._switch_page(2))
        rows.addWidget(self._mode_row)
        # 行间 0.5px hairline：颜色统一由 _apply_styles 按当前主题发放
        self._row_sep = QFrame()
        self._row_sep.setFrameShape(QFrame.HLine)
        rows.addWidget(self._row_sep)
        self._nav_row = _Row("grid", "校内导航")
        self._nav_row.set_trailing(_Icon("chevron_right", 10))
        self._nav_row.clicked.connect(lambda: self._switch_page(1))
        rows.addWidget(self._nav_row)
        main.addWidget(self._rows)

        # 底部工具条（自绘玻璃 chip：QSS 半透描边在透明底窗口上抗锯齿失真）
        bar = QHBoxLayout()
        bar.setSpacing(7)
        self._open_btn = _GlassButton("window", "打开主窗口")
        self._open_btn.clicked.connect(lambda: self._main.open_main_window())
        bar.addWidget(self._open_btn)
        bar.addStretch()
        self._settings_btn = _GlassButton("gear", tooltip="设置")
        self._settings_btn.clicked.connect(self._open_settings)
        self._quit_btn = _GlassButton("power", tooltip="退出")
        self._quit_btn.clicked.connect(self._main.quit_app)
        bar.addWidget(self._settings_btn)
        bar.addWidget(self._quit_btn)
        main.addLayout(bar)

        self._stack.addWidget(page_main)
        self._stack.addWidget(self._build_nav_page())
        self._stack.addWidget(self._build_mode_page())

    def _make_page_header(self, icon_kind: str, title: str):
        """二级页标题卡：图标 + 标题（DemiBold）+ ⌄，整行点击返回主页。"""
        card = QWidget()
        card.setObjectName("PanelCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        row = _Row(icon_kind, title)
        font = row.title.font()
        font.setWeight(QFont.DemiBold)
        row.title.setFont(font)
        row.set_trailing(_Icon("chevron_down", 10))
        row.clicked.connect(lambda: self._switch_page(0))
        lay.addWidget(row)
        return card

    def _build_nav_page(self):
        """导航页：标题卡 + 站点 chips 卡（只剩导航内容）。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self._nav_header = self._make_page_header("grid", "校内导航")
        v.addWidget(self._nav_header)
        self._nav_card = QWidget()
        self._nav_card.setObjectName("PanelCard")
        self._nav_card.setAttribute(Qt.WA_StyledBackground, True)
        nav = QVBoxLayout(self._nav_card)
        nav.setContentsMargins(8, 8, 8, 8)
        nav.setSpacing(4)
        # 分组小标题 + 双列 chip（单字圆标 + 短名，App 纯排版语言）
        self._nav_badges = []
        self._nav_group_labels = []  # 组标题：_refresh_nav_chips 随主题重设颜色
        for gi, (group_name, items) in enumerate(NAV_GROUPS):
            label = QLabel(group_name)
            if gi:
                label.setContentsMargins(0, 6, 0, 0)
            self._nav_group_labels.append(label)
            nav.addWidget(label)
            for i in range(0, len(items), 2):
                chip_row = QHBoxLayout()
                chip_row.setSpacing(4)
                for glyph, name, url, tip in items[i : i + 2]:
                    chip_row.addWidget(self._make_chip(glyph, name, url, tip), 1)
                nav.addLayout(chip_row)
        v.addWidget(self._nav_card)
        return page

    def _build_mode_page(self):
        """模式页：标题卡 + radio 选择卡（只剩模式选择；对标参考图圆点列表）。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self._mode_header = self._make_page_header("swap", "连接模式")
        v.addWidget(self._mode_header)
        self._mode_card = QWidget()
        self._mode_card.setObjectName("PanelCard")
        self._mode_card.setAttribute(Qt.WA_StyledBackground, True)
        col = QVBoxLayout(self._mode_card)
        col.setContentsMargins(4, 4, 4, 4)
        col.setSpacing(0)
        self._mode_radios = []
        for idx, (name, sub) in enumerate((("代理", "HTTP/SOCKS5"), ("TUN 全局路由", "默认"))):
            radio = _RadioRow(name, sub)
            radio.clicked.connect(lambda _checked=False, i=idx: self._on_mode_radio(i))
            col.addWidget(radio)
            self._mode_radios.append(radio)
        v.addWidget(self._mode_card)
        return page

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

    def _make_chip(self, glyph: str, name: str, url: str, tip: str) -> QPushButton:
        chip = QPushButton()
        chip.setCursor(Qt.PointingHandCursor)
        chip.setFixedHeight(26)
        chip.setToolTip(tip)
        chip.setAttribute(Qt.WA_AlwaysShowToolTips)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)
        badge = QLabel(glyph)
        badge.setFixedSize(18, 18)
        badge.setAlignment(Qt.AlignCenter)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        bf = badge.font()
        bf.setPointSize(8.5)
        badge.setFont(bf)
        self._nav_badges.append(badge)
        lay.addWidget(badge)
        text = QLabel(name)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        tf = text.font()
        tf.setPointSize(11.5)
        text.setFont(tf)
        lay.addWidget(text, 1)
        chip.setProperty("navchip", True)
        chip.clicked.connect(
            lambda _c=False, u=url: QDesktopServices.openUrl(QUrl(u))
        )
        return chip

    def _refresh_nav_chips(self):
        for chip in self._nav_card.findChildren(QPushButton):
            chip.setStyleSheet(f"""
                QPushButton[navchip="true"] {{
                    border: none; border-radius: 6px;
                    background: transparent; text-align: left;
                }}
                QPushButton[navchip="true"]:hover {{
                    background: {theme.with_alpha("accent", 0.10)};
                }}
            """)
        for badge in self._nav_badges:
            badge.setStyleSheet(f"""
                QLabel {{
                    background: {theme.with_alpha("accent", 0.10)};
                    color: {theme.semantic_color("accent")};
                    border-radius: 9px;
                }}
            """)
        # 组标题随主题重设颜色（仅换 color，字号/左内距语义不变）
        for label in self._nav_group_labels:
            label.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text')};"
                "font-size: 10px; padding-left: 4px;"
            )

    # ---- 样式 ----

    def _refresh_theme(self):
        """深浅色切换统一刷新：垫层外观 + 样式 + 分隔线/镜像色。"""
        from utils.macos_glass import update_glass_appearance
        from utils.macos_vibrancy import update_vibrancy_appearance

        update_glass_appearance(self)     # 未安装一侧安静返回
        update_vibrancy_appearance(self)
        self._apply_styles()
        self._sync_from_main()            # _status/_dot 颜色按新主题重解析

    def _apply_styles(self):
        # 材质分层：有玻璃件的卡片 Qt 侧全透（折射高光归原生 clear 玻璃件）；
        # 无玻璃件（旧系统毛玻璃/offscreen）保留 QSS 半透卡兜底
        for card in (self.conn_card, self._rows, self._nav_header, self._nav_card,
                     self._mode_header, self._mode_card):
            if getattr(card, "_glass_piece", None) is not None:
                card.setStyleSheet(
                    "QWidget#PanelCard { background: transparent; border: none; }"
                )
            else:
                card.setStyleSheet(
                    f"QWidget#PanelCard {{ {theme.card_qss(glass=True)} }}"
                )
        # 分隔线随主题重算（面板懒创建且永驻，不能停留在旧主题色）
        self._card_hairline.setStyleSheet(
            f"color: {theme.with_alpha('separator', 0.6)};"
        )
        self._row_sep.setStyleSheet(f"color: {theme.with_alpha('separator', 0.4)};")
        self._mode_row.refresh_theme()
        self._nav_row.refresh_theme()
        if not self._hint_active:
            self._subtitle.setStyleSheet(
                f"color: {theme.semantic_color('secondary_text')};"
            )
        # 玻璃 chip 按钮颜色在 paintEvent 现取主题：深浅色切换触发重绘即可
        for btn in (self._open_btn, self._settings_btn, self._quit_btn):
            btn.update()
        self._refresh_nav_chips()

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

    def _switch_page(self, index: int):
        """主页(0) ↔ 导航页(1) / 模式页(2)：切换 + 高度动画（顶边钉住）+ 新页淡入。

        高度用 QPropertyAnimation 驱动 stack maximumHeight（共享 on_frame 重锚定
        纪律——animated_height_toggle 只覆盖 0↔max 语义，页面切换是任意两值）。
        """
        stack = self._stack
        if index == stack.currentIndex():
            return
        if index == 2:
            self._sync_mode_radios()  # 进模式页前同步选中态
        if reduce_motion():
            stack.setCurrentIndex(index)
            self.adjustSize()
            self._sync_glass_pieces()
            return
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        new_page = stack.widget(index)
        start_h = stack.height()
        stack.setCurrentIndex(index)
        end_h = max(stack.sizeHint().height(), 1)
        # 高度动画：顶边钉住，向下伸缩
        anim = QPropertyAnimation(stack, b"maximumHeight", self)
        anim.setDuration(250)
        anim.setStartValue(start_h)
        anim.setEndValue(end_h)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(lambda _v: self.adjustSize())

        def _height_finish():
            if getattr(stack, "_page_height_anim", None) is not anim:
                return  # 被新动画顶替的旧动画不得决定终态
            stack.setMaximumHeight(16777215)
            self.adjustSize()  # 终态重锚定（掉帧兜底，同 motion_utils 纪律）

        anim.finished.connect(_height_finish)
        stack._page_height_anim = anim  # 身份守卫 + 防 GC
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        # 新页淡入（终态移除效果：常驻 QGraphicsOpacityEffect 会关文字子像素渲染）
        effect = QGraphicsOpacityEffect(new_page)
        new_page.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.finished.connect(lambda: new_page.setGraphicsEffect(None))
        self._page_fade = fade  # 防 GC
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._sync_glass_pieces()

    def _on_mode_radio(self, index: int):
        """radio 选择 → 切换模式（已连接走 bounce 重连）；稍停让勾选入眼再回主页。"""
        self._main.set_connection_mode(index == 1)
        self._sync_mode_radios()
        self._sync_mode_label()
        QTimer.singleShot(250, lambda: self._switch_page(0))

    def _sync_mode_radios(self):
        tun = bool(self._main.tun_mode)
        for i, radio in enumerate(self._mode_radios):
            radio.set_on((i == 1) == tun)

    def _on_esc(self):
        """Esc：二级页 → 返回主页；主页 → 收起面板。"""
        if self._stack.currentIndex() == 0:
            self.hide_panel()
        else:
            self._switch_page(0)

    def _open_settings(self):
        from views.menu_utils import show_advanced_settings

        show_advanced_settings(self._main)

    # ---- 显隐（位置：图标下缘居中并由 panel_geometry 夹紧到屏内） ----

    def toggle(self):
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_panel()

    # 展开 220ms 下滑 8px+淡入；收起 160ms 淡出（grilling 定稿"慢开快收"）
    _SHOW_MS = 220
    _HIDE_MS = 160
    _SLIDE_PX = 8

    def show_panel(self, animated: bool = True):
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        from PySide6.QtWidgets import QApplication
        from utils.panel_geometry import panel_geometry

        self._anim_gen = getattr(self, "_anim_gen", 0) + 1
        self._stop_hide_anim()
        self._stack.setCurrentIndex(0)  # 每次展开回到主页（失焦收起重开是新鲜会话）
        self._sync_from_main()
        self._sync_metrics()
        self.adjustSize()
        item = getattr(self._main, "_mac_status_item", None)
        icon_rect = item.icon_global_rect() if item is not None else None
        screen = None
        if icon_rect is not None:
            screen = QApplication.screenAt(icon_rect.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        geo = panel_geometry(icon_rect, screen.availableGeometry(), self.size())
        self.move(geo.topLeft())
        self._sync_glass_pieces()  # 页面复位/尺寸就位后同步玻璃件 frame
        animated = animated and not reduce_motion()
        if not animated:
            self.setWindowOpacity(1.0)
            self.show()
            self._poll.start()
            self._activate()
            return
        self.setWindowOpacity(0.0)
        target = self.pos()
        self.move(target.x(), target.y() - self._SLIDE_PX)
        self.show()
        anim_pos = QPropertyAnimation(self, b"pos", self)
        anim_pos.setDuration(self._SHOW_MS)
        anim_pos.setStartValue(self.pos())
        anim_pos.setEndValue(target)
        anim_pos.setEasingCurve(QEasingCurve.OutCubic)
        anim_opacity = QPropertyAnimation(self, b"windowOpacity", self)
        anim_opacity.setDuration(self._SHOW_MS)
        anim_opacity.setStartValue(0.0)
        anim_opacity.setEndValue(1.0)
        anim_opacity.setEasingCurve(QEasingCurve.OutCubic)
        self._show_anims = (anim_pos, anim_opacity)  # 防 GC
        anim_pos.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        anim_opacity.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._poll.start()
        self._activate()

    def hide_panel(self):
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation

        self._anim_gen = getattr(self, "_anim_gen", 0) + 1
        gen = self._anim_gen
        self._stop_hide_anim()
        self._stop_show_anims()
        if reduce_motion() or not self.isVisible():
            self.hide()
            self.setWindowOpacity(1.0)
            self._poll.stop()
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(self._HIDE_MS)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            if getattr(self, "_anim_gen", 0) != gen:
                return  # 期间又 show/hide 过：陈旧回调不得决定终态
            self.hide()
            self.setWindowOpacity(1.0)
            self._poll.stop()

        anim.finished.connect(_finish)
        self._hide_anim = anim
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_show_anims(self):
        anims = getattr(self, "_show_anims", None)
        self._show_anims = None
        for anim in anims or ():
            try:
                if isValid(anim):
                    anim.stop()
            except RuntimeError:
                pass

    def _stop_hide_anim(self):
        anim = getattr(self, "_hide_anim", None)
        self._hide_anim = None
        if anim is not None:
            try:
                if isValid(anim):
                    anim.stop()
            except RuntimeError:
                pass

    def _activate(self):
        """Accessory 策略下抢键盘焦点（Esc/点击控件依赖）。"""
        from PySide6.QtWidgets import QApplication

        self.raise_()
        self.activateWindow()
        if system() == "Darwin" and QApplication.platformName() == "cocoa":
            try:
                import ctypes

                import objc

                nsapp = objc.lookUpClass("NSApplication").sharedApplication()
                nsapp.activateIgnoringOtherApps_(True)
                view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
                view.window().makeKeyAndOrderFront_(None)
            except Exception:
                pass

    def event(self, e):
        """失焦自动收起（IME 候选窗不触发本事件，中文输入不误关）。"""
        if e.type() == QEvent.WindowDeactivate and self.isVisible():
            self.hide_panel()
        return super().event(e)
