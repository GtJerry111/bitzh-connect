# app/views/nav_section.py
"""校内网站导航（已连接态）：折叠条 + 按校区分组的双列网格。

- 折叠条常驻：chevron + "校内导航" + 右侧站点计数；点击整条展开/收起
- 展开面板：双列 160px 单元格（22px 单字圆标 + 短名），组标题承担校区前缀
- 圆标：accent 10% 底 + accent 字，深浅色自动适配（单字圆标是本 App 排版语言
  的延续；不做彩色 emoji / 线条图标）
- 展开状态写 QSettings nav_expanded（重启记忆）；断开连接整区随一收一放隐藏，
  重连恢复记忆态；点开链接后不自动收起（可能连开多站）
"""
from PySide6.QtCore import QEasingCurve, Qt, QUrl, QVariantAnimation
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from common import theme
from common.constants import NAV_GROUPS
from utils.config_utils import load_config, save_config
from utils.motion_utils import reduce_motion
from views.chevron import Chevron


class _NavBar(QWidget):
    """折叠条：chevron + 标题。整行可点（计数文案经真实使用反馈删除——噪音）。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        # QSS :hover 要在纯 QWidget 上生效必须开 WA_StyledBackground
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(34)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 10, 0)
        row.setSpacing(6)
        self.chevron = Chevron(self)
        row.addWidget(self.chevron)
        title_label = QLabel(title)
        font = title_label.font()
        font.setPointSize(12)
        font.setWeight(font.Weight.DemiBold)
        title_label.setFont(font)
        row.addWidget(title_label)
        row.addStretch()
        self.refresh_theme()

    def refresh_theme(self):
        self.setStyleSheet(f"""
            _NavBar {{ border-radius: 6px; }}
            _NavBar:hover {{ background: {theme.with_alpha("accent", 0.05)}; }}
        """)


class NavSection(QWidget):
    """折叠导航条 + 分组网格（已连接态由主窗口一收一放控制整体显隐）。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 4)
        layout.setSpacing(6)

        self._bar = _NavBar("校内导航", self)
        layout.addWidget(self._bar)

        self._panel = QWidget()
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        self._cells = []
        self._has_group = False
        for group_name, items in NAV_GROUPS:
            panel_layout.addWidget(self._group_title(group_name))
            panel_layout.addLayout(self._group_grid(items))
        self._panel.setVisible(False)
        layout.addWidget(self._panel)

        self._expanded = False
        # 展开状态记忆（重启保持）；断开连接整区隐藏、重连恢复
        if load_config().get("nav_expanded", False):
            self._panel.setVisible(True)
            self._expanded = True
            self._bar.chevron.set_angle(90.0)

        self._bar.mousePressEvent = lambda _e: self.set_expanded(not self._expanded)
        self.refresh_theme()

    def _group_title(self, text: str) -> QWidget:
        from PySide6.QtGui import QFont

        label = QLabel(text)
        font = label.font()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Medium)
        font.setLetterSpacing(QFont.PercentageSpacing, 107)
        label.setFont(font)
        label.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; padding-left: 6px;"
        )
        label.setFixedHeight(18)
        wrapper = QWidget()
        w_layout = QVBoxLayout(wrapper)
        w_layout.setContentsMargins(0, 10 if getattr(self, "_has_group", False) else 2, 0, 4)
        self._has_group = True
        w_layout.addWidget(label)
        return wrapper

    def _group_grid(self, items) -> QVBoxLayout:
        """双列网格：两两一行。"""
        grid = QVBoxLayout()
        grid.setSpacing(4)
        for i in range(0, len(items), 2):
            row = QHBoxLayout()
            row.setSpacing(8)
            for glyph, name, url, tip in items[i : i + 2]:
                cell = self._make_cell(glyph, name, url, tip)
                row.addWidget(cell, 1)
            grid.addLayout(row)
        return grid

    def _make_cell(self, glyph: str, name: str, url: str, tip: str) -> QPushButton:
        cell = QPushButton()
        cell.setCursor(Qt.PointingHandCursor)
        cell.setFixedHeight(28)
        cell.setToolTip(tip)
        cell.setAttribute(Qt.WA_AlwaysShowToolTips)

        row = QHBoxLayout(cell)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(8)
        badge = QLabel(glyph)
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignCenter)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        # 圆标：accent 10% 底 + accent 字（深浅色自适应）
        badge_font = badge.font()
        badge_font.setPointSize(9)
        badge.setFont(badge_font)
        badge.setStyleSheet(f"""
            QLabel {{
                background: {theme.with_alpha("accent", 0.10)};
                color: {theme.semantic_color("accent")};
                border-radius: 11px;
            }}
        """)
        row.addWidget(badge)
        text = QLabel(name)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        text.setFont(theme.subtitle_font())
        row.addWidget(text, 1)
        self._cells.append(cell)

        cell.clicked.connect(
            lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u))
        )
        return cell

    def set_expanded(self, expanded: bool):
        if expanded == self._expanded:
            return
        self._expanded = expanded
        # 展开状态记忆
        config = load_config()
        config["nav_expanded"] = expanded
        save_config(config)
        # chevron 旋转
        if reduce_motion():
            self._bar.chevron.set_angle(90.0 if expanded else 0.0)
        else:
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setStartValue(self._bar.chevron._angle)
            anim.setEndValue(90.0 if expanded else 0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._bar.chevron.set_angle)
            anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
        # 面板高度动画（窗口随动）
        from utils.motion_utils import animated_height_toggle

        animated_height_toggle(
            self._panel,
            expanded,
            max_height=max(self._panel.sizeHint().height(), 1),
            fade=True,
            on_frame=lambda: self.window().adjustSize(),
        )

    def refresh_theme(self):
        """深浅色切换刷新（圆标/计数文字/hover 底色）。"""
        self._bar.refresh_theme()
        for cell in self._cells:
            cell.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    border-radius: 6px;
                    background: transparent;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: {theme.with_alpha("accent", 0.06)};
                }}
                QPushButton:pressed {{
                    background: {theme.with_alpha("accent", 0.12)};
                }}
            """)
            badge = cell.findChild(QLabel)
            if badge is not None:
                badge.setStyleSheet(f"""
                    QLabel {{
                        background: {theme.with_alpha("accent", 0.10)};
                        color: {theme.semantic_color("accent")};
                        border-radius: 11px;
                    }}
                """)

    @property
    def is_expanded(self) -> bool:
        return self._expanded
