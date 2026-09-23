import subprocess

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QWidget,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
)
from PySide6.QtGui import QGuiApplication, QColor, QPainter
from PySide6.QtCore import QEasingCurve, QPointF, Qt, QVariantAnimation, Signal
from utils.config_utils import save_config, load_config
from utils.startup_utils import set_launch_at_login, get_launch_at_login
from utils import helper_installer
from utils import diagnostics
from platform import system

if system() == "Darwin":
    from utils.macos_utils import hide_dock_icon
from common.version import get_version
from common.constants import APP_NAME, DEFAULT_SERVER, REPO_URL
from common import resources
from common import theme
from views.chevron import Chevron
from views.toggle_switch import ToggleSwitch
from views.settings_row import SettingRow

VERSION = get_version()

# 外观三态取值（与下拉框索引一一对应）
_APPEARANCE_MODES = ["system", "light", "dark"]


def _open_path(path: str):
    """用系统默认方式打开目录/文件（失败静默）。"""
    try:
        if system() == "Darwin":
            subprocess.Popen(["open", path])
        elif system() == "Windows":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


class DisclosureHeader(QWidget):
    """分组折叠头：chevron（展开旋转 90°，150ms OutCubic）+ 标题 + 细分隔线。

    整行可点；hover 时文字微亮（桌面端"它在听"的第一层反馈）。
    """

    toggled = Signal(bool)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._expanded = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(8)
        self._chevron = Chevron(self)
        layout.addWidget(self._chevron)
        self._label = QLabel(text)
        font = self._label.font()
        font.setPointSize(13)
        font.setWeight(font.Weight.DemiBold)
        self._label.setFont(font)
        layout.addWidget(self._label)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.semantic_color('separator')};")
        layout.addWidget(line, 1)

    def isExpanded(self) -> bool:
        return self._expanded

    def setExpanded(self, expanded: bool):
        if expanded == self._expanded:
            return
        self._expanded = expanded
        from utils.motion_utils import reduce_motion

        if reduce_motion():
            self._chevron.set_angle(90.0 if expanded else 0.0)
        else:
            old = getattr(self, "_chevron_anim", None)
            if old is not None:
                self._chevron_anim = None
                old.stop()
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setStartValue(self._chevron._angle)
            anim.setEndValue(90.0 if expanded else 0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._chevron.set_angle)
            self._chevron_anim = anim
            anim.start()
        self.toggled.emit(expanded)

    def mousePressEvent(self, event):
        self.setExpanded(not self._expanded)

    def enterEvent(self, event):
        self._label.setStyleSheet(f"color: {theme.semantic_color('ink')};")

    def leaveEvent(self, event):
        self._label.setStyleSheet("")


class AdvancedSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级设置")
        self.setMinimumWidth(420)
        # 证书配置在 UI 中隐藏（BITZH 服务端为账号密码认证，用不到 .p12 客户端证书），
        # 但配置键保留往返：从 window 读入、随保存写回，不丢用户既有配置
        self._cert_file = ""
        self._cert_password = ""
        self._tab_overhead = None  # 标签栏+面框高度开销（首次贴合时实测）
        self.setup_ui()
        # 深浅色/外观切换时重放 tab QSS（QSS 里内联了语义色，需随主题重算）
        theme.on_scheme_changed(self._apply_tab_qss)

    # ---- 分组与说明行（说明文字从 tooltip 落地为可见的灰字，Nielsen #10）----

    def _card_group(self, layout, title):
        """分组卡片：小号标题 + 圆角卡片容器；返回卡片内容的 QVBoxLayout。"""
        label = QLabel(title)
        font = label.font()
        font.setPointSize(12)
        font.setWeight(font.Weight.DemiBold)
        label.setFont(font)
        label.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; margin: 10px 4px 4px 4px;"
        )
        layout.addWidget(label)

        card = QWidget()
        card.setObjectName("SettingsCard")
        card.setStyleSheet(
            f"#SettingsCard {{ background: {theme.card_background()};"
            f" border-radius: 10px; }}"
        )
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 2, 0, 2)
        inner.setSpacing(0)
        layout.addWidget(card)
        return inner

    def _description(self, text):
        """12pt 次要色说明行（替代藏在 tooltip 里的关键信息）。"""
        label = QLabel(text)
        label.setFont(theme.card_title_font())
        label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        label.setWordWrap(True)
        return label

    def _toggle_row(self, layout, text, *, checked=None, description="", enabled=True):
        """往 layout 追加一行"标签 + iOS 开关"，返回 (row, switch)。"""
        switch = ToggleSwitch()
        if checked is not None:
            switch.setChecked(checked)
        switch.setEnabled(enabled)
        row = SettingRow(text, switch, description)
        layout.addWidget(row)
        return row, switch

    def setup_ui(self):
        layout = QVBoxLayout()

        tab_widget = QTabWidget()

        # ================= 通用 tab =================
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setSpacing(8)

        startup_inner = self._card_group(general_layout, "启动")
        self.startup_row, self.startup_switch = self._toggle_row(
            startup_inner, "开机启动", checked=get_launch_at_login()
        )

        self.silent_mode_row, self.silent_mode_switch = self._toggle_row(
            startup_inner,
            "静默启动",
            description="启动时不显示主窗口，仅驻留系统托盘",
        )

        self.connect_startup_row, self.connect_startup_switch = self._toggle_row(
            startup_inner,
            "启动时自动连接",
            description="启动后自动连接 VPN（需已保存凭据）",
        )

        appearance_inner = self._card_group(general_layout, "外观与更新")

        self.check_update_row, self.check_update_switch = self._toggle_row(
            appearance_inner, "启动时检查更新"
        )

        self.auto_reconnect_row, self.auto_reconnect_switch = self._toggle_row(
            appearance_inner,
            "断线自动重连",
            checked=True,
            description="非认证失败导致的掉线将自动重连，连续失败 3 次后暂停",
        )

        # 外观三态（跟随系统 / 浅色 / 深色）：与开关行同左边距的普通行，不用表单右对齐
        appearance_row = QHBoxLayout()
        appearance_row.setContentsMargins(2, 6, 2, 6)  # 与 SettingRow 同边距对齐
        appearance_row.addWidget(QLabel("外观"))
        self.appearance_combo = QComboBox()
        self.appearance_combo.addItems(["跟随系统", "浅色", "深色"])
        appearance_row.addWidget(self.appearance_combo)
        appearance_row.addStretch()
        appearance_inner.addLayout(appearance_row)

        # Hide dock icon option (only for macOS)
        if system() == "Darwin":
            self.hide_dock_icon_row, self.hide_dock_icon_switch = self._toggle_row(
                appearance_inner,
                "隐藏 Dock 图标",
                description="隐藏后应用仅驻留菜单栏托盘；设置入口在主窗口右下角",
            )

        general_layout.addStretch()

        # ================= 网络 tab =================
        network_tab = QWidget()
        network_layout = QVBoxLayout(network_tab)
        network_layout.setSpacing(8)

        # ---- 连接 ----
        connect_inner = self._card_group(network_layout, "连接")
        connect_form = QFormLayout()
        connect_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        connect_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        server_row = QHBoxLayout()
        server_row.setSpacing(8)
        self.server_input = QLineEdit(DEFAULT_SERVER)
        server_row.addWidget(self.server_input, 1)
        server_row.addWidget(QLabel("端口"))
        self.port_input = QLineEdit("443")
        self.port_input.setMaximumWidth(60)
        server_row.addWidget(self.port_input)
        connect_form.addRow("VPN 服务端地址", server_row)
        connect_inner.addLayout(connect_form)

        # DNS：开关行在上、输入框在下（控制与被控的空间从属即因果自解释）
        self.auto_dns_row, self.auto_dns_switch = self._toggle_row(
            connect_inner, "自动配置 DNS", checked=True
        )
        self.auto_dns_switch.toggled.connect(self.toggle_dns_input)
        dns_row = QHBoxLayout()
        dns_row.setContentsMargins(24, 0, 0, 0)  # 缩进从属于"自动配置 DNS"
        dns_row.addWidget(QLabel("DNS 服务器地址"))
        self.dns_input = QLineEdit("")
        self.dns_input.setPlaceholderText("留空则禁用远端 DNS")
        dns_row.addWidget(self.dns_input, 1)
        connect_inner.addLayout(dns_row)

        # ---- 代理 ----
        proxy_inner = self._card_group(network_layout, "代理")
        proxy_form = QFormLayout()
        proxy_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        proxy_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.socks_bind_input = QLineEdit()
        self.socks_bind_input.setPlaceholderText("1080")
        proxy_form.addRow("SOCKS5 代理监听端口", self.socks_bind_input)
        self.http_bind_input = QLineEdit()
        self.http_bind_input.setPlaceholderText("1081")
        proxy_form.addRow("HTTP 代理监听端口", self.http_bind_input)
        proxy_inner.addLayout(proxy_form)

        self.proxy_row, self.proxy_switch = self._toggle_row(
            proxy_inner,
            "自动配置代理",
            description="连接后自动配置系统代理，将网络流量通过 VPN 转发（TUN 模式下不生效）",
        )

        # 特权服务：独立「系统」分组卡片（原位于高级折叠之上）
        if system() == "Darwin" and helper_installer.is_supported():
            system_inner = self._card_group(network_layout, "系统")
            self.helper_button = QPushButton()
            self.helper_button.setStyleSheet(self._primary_button_style())
            self.helper_button.clicked.connect(self._on_helper_button)
            self.helper_row = SettingRow("特权服务", self.helper_button, "")
            system_inner.addWidget(self.helper_row)
            self._refresh_helper_row()
        else:
            # 平台不支持时保留隐藏行（配置/测试契约不变），不占可见版面
            self.helper_button = QPushButton()
            self.helper_button.setVisible(False)
            self.helper_row = SettingRow("特权服务", self.helper_button, "")
            self.helper_row.setVisible(False)
            network_layout.addWidget(self.helper_row)

        # ---- 高级（默认折叠）：整块是一张卡片，折叠头作为卡片标题行 ----
        advanced_card = QWidget()
        advanced_card.setObjectName("SettingsCard")
        self._advanced_card = advanced_card  # 折叠时用于失效 sizeHint 缓存
        advanced_card.setStyleSheet(
            f"#SettingsCard {{ background: {theme.card_background()};"
            f" border-radius: 10px; }}"
        )
        advanced_card_layout = QVBoxLayout(advanced_card)
        advanced_card_layout.setContentsMargins(0, 2, 0, 2)
        advanced_card_layout.setSpacing(0)

        self.advanced_toggle = DisclosureHeader("高级")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        advanced_card_layout.addWidget(self.advanced_toggle)

        self.advanced_area = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_area)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)

        self.keep_alive_row, self.keep_alive_switch = self._toggle_row(
            advanced_layout,
            "定时保活",
            description="开启后，BITZH Connect 会定时发送心跳包以保持连接",
        )

        self.debug_dump_row, self.debug_dump_switch = self._toggle_row(
            advanced_layout,
            "调试模式",
            description="开启后，BITZH Connect 会记录详细的调试信息到日志文件",
        )

        # 肯定句表述（原"禁用备用线路检测"勾选=禁用是双重否定）；存储时取反
        self.auto_multi_line_row, self.auto_multi_line_switch = self._toggle_row(
            advanced_layout,
            "自动切换备用线路",
            checked=True,
            description="当前线路不稳定时自动切换到备用线路",
        )

        tun_note = (
            "所有流量（含 SSH 等裸 TCP）都走 VPN，默认开启；需要管理员授权；"
            "可与 Clash/FlClash 的 TUN 共存（按 IP 直连校园网；对方需未开启严格路由）"
        )
        if system() == "Windows":
            tun_note += "（本期仅 macOS/Linux）"
        # 本期 TUN 仅 macOS/Linux：Windows 提权链路（.bat + UAC）未验证，honest 置灰
        self.tun_mode_row, self.tun_mode_switch = self._toggle_row(
            advanced_layout,
            "TUN 模式（全局路由）",
            enabled=system() != "Windows",
            description=tun_note,
        )

        # ---- 运行日志（打开时同步主窗口日志缓冲，存活期间实时跟随）----
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QTextEdit

        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMinimumHeight(120)
        self.log_viewer.setMaximumHeight(160)
        log_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        log_font.setPointSize(11)
        self.log_viewer.setFont(log_font)
        advanced_layout.addWidget(self.log_viewer)
        log_btn_row = QHBoxLayout()
        log_btn_row.addStretch()
        copy_log_btn = QPushButton("复制日志")
        copy_log_btn.clicked.connect(self._copy_log)
        log_btn_row.addWidget(copy_log_btn)
        self.open_log_button = QPushButton("打开日志目录")
        self.open_log_button.clicked.connect(
            lambda: _open_path(diagnostics.log_dir())
        )
        log_btn_row.addWidget(self.open_log_button)
        advanced_layout.addLayout(log_btn_row)
        advanced_layout.addWidget(
            self._description("复制后可粘贴给维护者排查；日志仅包含内核输出，不含密码")
        )
        source = getattr(self.parent(), "output_text", None)
        if source is not None:
            self.log_viewer.setPlainText(source.toPlainText())
            self.log_viewer.verticalScrollBar().setValue(
                self.log_viewer.verticalScrollBar().maximum()
            )
            source.textChanged.connect(self._sync_log)

        self.advanced_area.setVisible(False)  # 默认折叠
        advanced_card_layout.addWidget(self.advanced_area)
        network_layout.addWidget(advanced_card)

        network_layout.addStretch()

        # ================= 帮助 tab（原菜单栏"帮助"收编到这里） =================
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        help_layout.setSpacing(8)

        # ---- 关于（卡片：应用信息 + 检查更新行）----
        about_inner = self._card_group(help_layout, "关于")
        accent = theme.semantic_color("accent")
        link_style = f"color: {accent}; text-decoration: none;"
        about = QLabel(
            f"<p style='font-size:15pt; font-weight:600; margin-bottom:2px;'>{APP_NAME}</p>"
            f"<p style='margin:0;'>版本 {VERSION}</p>"
            f"<p style='margin:0;'><a href='{REPO_URL}' style='{link_style}'>GitHub 仓库</a></p>"
            f"<p style='margin:0; color:{theme.semantic_color('secondary_text')};'>"
            f"基于 <a href='https://github.com/kowyo/hitsz-connect-verge' style='{link_style}'>"
            f"HITSZ Connect Verge</a>"
            f"，内核 <a href='https://github.com/Mythologyli/zju-connect' style='{link_style}'>"
            f"ZJU Connect</a></p>"
        )
        about.setOpenExternalLinks(True)
        about.setContentsMargins(14, 10, 14, 10)
        self._help_links_label = about  # 供测试/主题重算定位链接色
        about_inner.addWidget(about)

        about_sep = QFrame()
        about_sep.setFrameShape(QFrame.HLine)
        about_sep.setStyleSheet(f"color: {theme.semantic_color('separator')};")
        about_inner.addWidget(about_sep)

        # 检查更新：左标签 + 右侧绿实心按钮（按钮旁小旋转弧指示检查中）
        from views.busy_spinner import BusySpinner

        update_row = QWidget()
        ur = QHBoxLayout(update_row)
        ur.setContentsMargins(14, 10, 14, 10)
        ur.setSpacing(12)
        ur.addWidget(QLabel("检查更新"))
        ur.addStretch()
        self.update_btn = QPushButton("立即检查")
        self.update_btn.setStyleSheet(self._primary_button_style())
        self.update_btn.clicked.connect(self._check_update)
        ur.addWidget(self.update_btn, 0, Qt.AlignVCenter)
        self.update_spinner = BusySpinner(self, diameter=16)
        ur.addWidget(self.update_spinner, 0, Qt.AlignVCenter)
        about_inner.addWidget(update_row)

        # ---- 校园网支持（方案 A：校内管理 + 网管中心电话，两行卡片）----
        support_inner = self._card_group(help_layout, "校园网支持")

        # 行1：校内管理（左信息 + 右绿链接）
        manage_row = QWidget()
        mr = QHBoxLayout(manage_row)
        mr.setContentsMargins(14, 10, 14, 10)
        mr.setSpacing(12)
        mleft = QVBoxLayout()
        mleft.setSpacing(1)
        mleft.addWidget(QLabel("校园网校内管理"))
        mleft.addWidget(self._description("需连接校园网（或本 VPN）后访问"))
        mr.addLayout(mleft, 1)
        campus_link = QLabel(
            f"<a href='http://10.7.0.103:9066/' style='color: {accent};"
            f" text-decoration: none;'>打开 ↗</a>"
        )
        campus_link.setOpenExternalLinks(True)
        campus_link.setCursor(Qt.PointingHandCursor)
        mr.addWidget(campus_link, 0, Qt.AlignVCenter)
        support_inner.addWidget(manage_row)

        support_sep = QFrame()
        support_sep.setFrameShape(QFrame.HLine)
        support_sep.setStyleSheet(f"color: {theme.semantic_color('separator')};")
        support_inner.addWidget(support_sep)

        # 行2：电话（左信息 + 右"复制"按钮）
        phone_row = QWidget()
        pr = QHBoxLayout(phone_row)
        pr.setContentsMargins(14, 10, 14, 10)
        pr.setSpacing(12)
        pleft = QVBoxLayout()
        pleft.setSpacing(1)
        pleft.addWidget(QLabel("校园网络中心电话"))
        pleft.addWidget(self._description("(0756) 3835303"))
        pr.addLayout(pleft, 1)
        self.copy_phone_btn = QPushButton("复制")
        self.copy_phone_btn.setStyleSheet(self._secondary_button_style())
        self.copy_phone_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText("(0756) 3835303")
        )
        pr.addWidget(self.copy_phone_btn, 0, Qt.AlignVCenter)
        support_inner.addWidget(phone_row)

        help_layout.addStretch()

        # macOS 惯例：General 在前；帮助殿后
        tab_widget.addTab(general_tab, "通用")
        tab_widget.addTab(network_tab, "网络")
        tab_widget.addTab(help_tab, "帮助")
        layout.addWidget(tab_widget)
        self._tabs = tab_widget
        self._apply_tab_qss()

        # 按钮盒：平台惯例自动排布（macOS：取消左、保存右），保存为主按钮；
        # 两按钮同宽（自定义样式只改颜色不改尺寸，避免一大一小）
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.button_box.button(QDialogButtonBox.Save).setText("保存")
        self.button_box.button(QDialogButtonBox.Cancel).setText("取消")
        save_btn = self.button_box.button(QDialogButtonBox.Save)
        cancel_btn = self.button_box.button(QDialogButtonBox.Cancel)
        save_btn.setDefault(True)
        for btn in (save_btn, cancel_btn):
            btn.setMinimumWidth(88)
        # 两按钮同款 QSS 几何（同 padding/圆角/字号）——混用"QSS 样式 + 原生样式"
        # 会因两边 sizeHint 计算路径不同而一大一小，必须两个都走 QSS
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: none;
                border-radius: 6px;
                padding: 6px 0px;
                font-size: 13pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {theme.semantic_color("accent_hover")};
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("accent_pressed")};
            }}
        """)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.card_background()};
                color: {theme.semantic_color("ink")};
                border: 1px solid {theme.semantic_color("separator")};
                border-radius: 6px;
                padding: 6px 0px;
                font-size: 13pt;
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("separator")};
            }}
        """)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

        # macOS 偏好设置式：窗口高度跟随当前 tab 内容（通用 tab 不再有大片留白）。
        # 注意 QTabWidget.sizeHint 不认页面的 Ignored 策略（恒取最大页），
        # 经典 QStackedLayout Ignored 技巧在此无效，需显式按当前页高度贴合
        layout.setSizeConstraint(QVBoxLayout.SetFixedSize)
        tab_widget.currentChanged.connect(self._fit_to_tab)
        self._fit_to_tab(0)

    def _apply_tab_qss(self):
        """tab 选中色 QSS 兜底：macOS 原生 tab 不认 palette Highlight（A 方案无效），
        显式把选中 tab 刷成校徽绿；未选中 tab 用淡墨底 + 次要文字色。"""
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background: {theme.with_alpha("ink", 0.06)};
                color: {theme.semantic_color("secondary_text")};
                padding: 4px 14px;
                margin-right: 2px;
                border-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
            }}
        """)

    def _fit_to_tab(self, index: int):
        """对话框高度贴合当前 tab：tab 控件定高 = 当前页 sizeHint + 实测开销。"""
        if self._tab_overhead is None:
            self._tab_overhead = self._tabs.sizeHint().height() - max(
                self._tabs.widget(i).sizeHint().height()
                for i in range(self._tabs.count())
            )
        page = self._tabs.widget(index)
        # 内容藏在子卡片内时，隐藏/显示只异步投递 LayoutRequest，父布局里该卡片的
        # QWidgetItem sizeHint 缓存不会即时刷新；显式 updateGeometry + 失效布局缓存，
        # 保证折叠后高度即时收回（不留白）
        card = getattr(self, "_advanced_card", None)
        if card is not None:
            card.updateGeometry()
            card.layout().invalidate()
        page.layout().invalidate()
        self._tabs.setFixedHeight(page.sizeHint().height() + self._tab_overhead)
        self.adjustSize()

    def _sync_log(self):
        """日志缓冲有新内容时实时跟随（含自动滚到底部）。"""
        source = getattr(self.parent(), "output_text", None)
        if source is None:
            return
        self.log_viewer.setPlainText(source.toPlainText())
        scrollbar = self.log_viewer.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _copy_log(self):
        """复制主窗口运行日志到剪贴板（帮助 tab 按钮）。"""
        from PySide6.QtWidgets import QMessageBox

        window = self.window()
        if window is self or not hasattr(window, "output_text"):
            return  # 无父窗口（测试场景）不动作
        QGuiApplication.clipboard().setText(window.output_text.toPlainText())
        QMessageBox.information(self, "复制日志", "日志已复制到剪贴板")

    def _check_update(self):
        """帮助 tab 的检查更新（复用 menu_utils 的完整弹窗流程）；
        点击后转圈 + 按钮禁用，任一结果（有新版本/已最新/失败）停转恢复。"""
        from .menu_utils import check_for_updates  # 局部导入避免循环依赖

        self.update_btn.setEnabled(False)
        self.update_spinner.start()
        signals = check_for_updates(self.window(), VERSION)

        def _done(*_args):
            self.update_spinner.stop()
            self.update_btn.setEnabled(True)

        signals.update_available.connect(_done)
        signals.up_to_date.connect(_done)
        signals.error.connect(_done)

    def toggle_dns_input(self):
        """Toggle DNS input field based on auto DNS checkbox"""
        self.dns_input.setEnabled(not self.auto_dns_switch.isChecked())

    def _toggle_advanced(self, expanding: bool):
        """高级区展开/收起：对话框高度即时贴合（tab 定高制），内容只做淡入/淡出。

        不做区域高度动画：per-tab 定高下内容长高会撞固定高度；对话框即时贴合 +
        内容淡入淡出，等效 macOS 系统设置的分组展开观感。
        """
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        from utils.motion_utils import reduce_motion

        if reduce_motion():
            self.advanced_area.setVisible(expanding)
            self._fit_to_tab(self._tabs.currentIndex())
            return

        effect = QGraphicsOpacityEffect(self.advanced_area)
        self.advanced_area.setGraphicsEffect(effect)
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setStartValue(0.0 if expanding else 1.0)
        anim.setEndValue(1.0 if expanding else 0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(effect.setOpacity)

        def _finish():
            self.advanced_area.setGraphicsEffect(None)  # 常驻会关文字子像素渲染
            if not expanding:
                self.advanced_area.setVisible(False)
                # 收回后对话框高度同步收回（内容隐藏后才重新贴合，否则留白残留）
                self._fit_to_tab(self._tabs.currentIndex())

        anim.finished.connect(_finish)
        if expanding:
            self.advanced_area.setVisible(True)
        self._fit_to_tab(self._tabs.currentIndex())
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def get_settings(self):
        settings = {
            "server": self.server_input.text(),
            "port": self.port_input.text(),
            "dns": self.dns_input.text(),
            "auto_dns": self.auto_dns_switch.isChecked(),
            "proxy": self.proxy_switch.isChecked(),
            "connect_startup": self.connect_startup_switch.isChecked(),
            "silent_mode": self.silent_mode_switch.isChecked(),
            "check_update": self.check_update_switch.isChecked(),
            "keep_alive": self.keep_alive_switch.isChecked(),
            "debug_dump": self.debug_dump_switch.isChecked(),
            # 肯定句 UI → 存储键取反（配置键名与语义保持不变）
            "disable_multi_line": not self.auto_multi_line_switch.isChecked(),
            "http_bind": self.http_bind_input.text(),
            "socks_bind": self.socks_bind_input.text(),
            # 证书组 UI 已隐藏（BITZH 用不到证书认证），配置键原样往返保留
            "cert_file": self._cert_file,
            "cert_password": self._cert_password,
            "auto_reconnect": self.auto_reconnect_switch.isChecked(),
            "appearance": _APPEARANCE_MODES[self.appearance_combo.currentIndex()],
            "tun_mode": self.tun_mode_switch.isChecked(),
        }

        if system() == "Darwin":
            settings["hide_dock_icon"] = self.hide_dock_icon_switch.isChecked()

        return settings

    def set_settings(
        self,
        server,
        port,
        dns,
        proxy,
        connect_startup,
        silent_mode,
        check_update,
        hide_dock_icon=False,
        keep_alive=False,
        debug_dump=False,
        disable_multi_line=False,
        http_bind="",
        socks_bind="",
        auto_dns=True,
        cert_file="",
        cert_password="",
        auto_reconnect=True,
        appearance="system",
        tun_mode=False,
    ):
        """Set dialog values from main window values"""
        self.server_input.setText(server)
        self.port_input.setText(port)
        self.dns_input.setText(dns)
        self.auto_dns_switch.setChecked(auto_dns)
        self.proxy_switch.setChecked(proxy)
        self.connect_startup_switch.setChecked(connect_startup)
        self.silent_mode_switch.setChecked(silent_mode)
        self.check_update_switch.setChecked(check_update)
        if system() == "Darwin":
            self.hide_dock_icon_switch.setChecked(hide_dock_icon)
        self.keep_alive_switch.setChecked(keep_alive)
        self.debug_dump_switch.setChecked(debug_dump)
        self.auto_multi_line_switch.setChecked(not disable_multi_line)
        self.http_bind_input.setText(http_bind)
        self.socks_bind_input.setText(socks_bind)
        self._cert_file = cert_file
        self._cert_password = cert_password
        self.auto_reconnect_switch.setChecked(auto_reconnect)
        # 脏值守卫：手改坏的 QSettings 值（如 "blue"）兜底回 system，防 ValueError
        appearance = appearance if appearance in _APPEARANCE_MODES else "system"
        self.appearance_combo.setCurrentIndex(_APPEARANCE_MODES.index(appearance))
        self.tun_mode_switch.setChecked(tun_mode)

        # Enable/disable DNS input based on auto DNS setting
        self.toggle_dns_input()

    def _primary_button_style(self) -> str:
        """与对话框"保存"同款绿实心按钮（③A）。"""
        return f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {theme.semantic_color("accent_hover")};
            }}
            QPushButton:disabled {{
                background-color: {theme.semantic_color("accent_disabled")};
            }}
        """

    def _secondary_button_style(self) -> str:
        """次级描边小按钮（卡底 / 墨字 / 1px 描边），用于帮助页"复制"。"""
        return f"""
            QPushButton {{
                background-color: {theme.card_background()};
                color: {theme.semantic_color("ink")};
                border: 1px solid {theme.semantic_color("separator")};
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12pt;
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("separator")};
            }}
        """

    def _refresh_helper_row(self):
        if not hasattr(self, "helper_button") or not helper_installer.is_supported():
            return
        if helper_installer.is_installed():
            self.helper_button.setText("卸载特权服务")
            self.helper_button.setEnabled(True)
        else:
            self.helper_button.setText("安装特权服务")
            self.helper_button.setEnabled(helper_installer.can_install())

    def _on_helper_button(self):
        if helper_installer.is_installed():
            self._uninstall_helper()
        else:
            self._install_helper()

    def _install_helper(self):
        from views import helper_setup_dialog

        dialog = helper_setup_dialog.HelperSetupDialog(self)
        dialog.exec()
        self._refresh_helper_row()

    def _uninstall_helper(self):
        """卸载 TUN 特权服务（一次授权），完成后刷新为"安装"态。"""
        self.helper_button.setEnabled(False)

        def _done(ok: bool):
            self.helper_button.setEnabled(True)
            self._refresh_helper_row()

        helper_installer.uninstall_async(_done)

    def accept(self):
        """Save settings before closing"""
        current_config = load_config()
        settings = self.get_settings()

        settings["username"] = current_config.get("username", "")
        settings["password"] = current_config.get("password", "")
        settings["remember"] = current_config.get("remember", False)

        save_config(settings)
        set_launch_at_login(enable=self.startup_switch.isChecked())

        if system() == "Darwin" and self.parent() is not None:
            self.parent().hide_dock_icon = settings["hide_dock_icon"]
            hide_dock_icon(settings["hide_dock_icon"])

        super().accept()
