from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
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
from platform import system

if system() == "Darwin":
    from utils.macos_utils import hide_dock_icon
from common.version import get_version
from common.constants import APP_NAME, DEFAULT_SERVER, REPO_URL
from common import resources
from common import theme
from views.chevron import Chevron

VERSION = get_version()

# 外观三态取值（与下拉框索引一一对应）
_APPEARANCE_MODES = ["system", "light", "dark"]


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

    # ---- 分组与说明行（说明文字从 tooltip 落地为可见的灰字，Nielsen #10）----

    def _group_header(self, text):
        """分组小标题：13pt DemiBold + 细分隔线。"""
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 10, 0, 4)
        layout.setSpacing(4)
        label = QLabel(text)
        font = label.font()
        font.setPointSize(13)
        font.setWeight(font.Weight.DemiBold)
        label.setFont(font)
        layout.addWidget(label)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.semantic_color('separator')};")
        layout.addWidget(line)
        return wrapper

    def _description(self, text):
        """11pt 次要色说明行（替代藏在 tooltip 里的关键信息）。"""
        label = QLabel(text)
        label.setFont(theme.card_title_font())
        label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        label.setWordWrap(True)
        return label

    def setup_ui(self):
        layout = QVBoxLayout()

        tab_widget = QTabWidget()

        # ================= 通用 tab =================
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setSpacing(8)

        general_layout.addWidget(self._group_header("启动"))
        self.startup_switch = QCheckBox("开机启动")
        self.startup_switch.setChecked(get_launch_at_login())
        general_layout.addWidget(self.startup_switch)

        self.silent_mode_switch = QCheckBox("静默启动")
        general_layout.addWidget(self.silent_mode_switch)
        general_layout.addWidget(self._description("启动时不显示主窗口，仅驻留系统托盘"))

        self.connect_startup_switch = QCheckBox("启动时自动连接")
        general_layout.addWidget(self.connect_startup_switch)
        general_layout.addWidget(self._description("启动后自动连接 VPN（需已保存凭据）"))

        general_layout.addWidget(self._group_header("外观与更新"))

        self.check_update_switch = QCheckBox("启动时检查更新")
        general_layout.addWidget(self.check_update_switch)

        self.auto_reconnect_switch = QCheckBox("断线自动重连")
        self.auto_reconnect_switch.setChecked(True)
        general_layout.addWidget(self.auto_reconnect_switch)
        general_layout.addWidget(
            self._description("非认证失败导致的掉线将自动重连，连续失败 3 次后暂停")
        )

        # 外观三态（跟随系统 / 浅色 / 深色）：与复选框同左边距的普通行，不用表单右对齐
        appearance_row = QHBoxLayout()
        appearance_row.setContentsMargins(0, 0, 0, 0)
        appearance_row.addWidget(QLabel("外观"))
        self.appearance_combo = QComboBox()
        self.appearance_combo.addItems(["跟随系统", "浅色", "深色"])
        appearance_row.addWidget(self.appearance_combo)
        appearance_row.addStretch()
        general_layout.addLayout(appearance_row)

        # Hide dock icon option (only for macOS)
        if system() == "Darwin":
            self.hide_dock_icon_switch = QCheckBox("隐藏 Dock 图标")
            general_layout.addWidget(self.hide_dock_icon_switch)
            general_layout.addWidget(
                self._description("隐藏后应用仅驻留菜单栏托盘；设置入口在主窗口右下角")
            )

        general_layout.addStretch()

        # ================= 网络 tab =================
        network_tab = QWidget()
        network_layout = QVBoxLayout(network_tab)
        network_layout.setSpacing(8)

        # ---- 连接 ----
        network_layout.addWidget(self._group_header("连接"))
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
        network_layout.addLayout(connect_form)

        # DNS：复选框在上、输入框在下（控制与被控的空间从属即因果自解释）
        self.auto_dns_switch = QCheckBox("自动配置 DNS")
        self.auto_dns_switch.setChecked(True)
        self.auto_dns_switch.toggled.connect(self.toggle_dns_input)
        network_layout.addWidget(self.auto_dns_switch)
        dns_row = QHBoxLayout()
        dns_row.setContentsMargins(24, 0, 0, 0)  # 缩进从属于"自动配置 DNS"
        dns_row.addWidget(QLabel("DNS 服务器地址"))
        self.dns_input = QLineEdit("")
        self.dns_input.setPlaceholderText("留空则禁用远端 DNS")
        dns_row.addWidget(self.dns_input, 1)
        network_layout.addLayout(dns_row)

        # ---- 代理 ----
        network_layout.addWidget(self._group_header("代理"))
        proxy_form = QFormLayout()
        proxy_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        proxy_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.socks_bind_input = QLineEdit()
        self.socks_bind_input.setPlaceholderText("1080")
        proxy_form.addRow("SOCKS5 代理监听端口", self.socks_bind_input)
        self.http_bind_input = QLineEdit()
        self.http_bind_input.setPlaceholderText("1081")
        proxy_form.addRow("HTTP 代理监听端口", self.http_bind_input)
        network_layout.addLayout(proxy_form)

        self.proxy_switch = QCheckBox("自动配置代理")
        network_layout.addWidget(self.proxy_switch)
        network_layout.addWidget(
            self._description("连接后自动配置系统代理，将网络流量通过 VPN 转发（TUN 模式下不生效）")
        )

        # ---- 高级（默认折叠，点 chevron 行展开；展开/收起随对话框高度平滑伸缩）----
        self.advanced_toggle = DisclosureHeader("高级")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        network_layout.addWidget(self.advanced_toggle)

        self.advanced_area = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_area)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)

        self.keep_alive_switch = QCheckBox("定时保活")
        advanced_layout.addWidget(self.keep_alive_switch)
        advanced_layout.addWidget(
            self._description("开启后，BITZH Connect 会定时发送心跳包以保持连接")
        )

        self.debug_dump_switch = QCheckBox("调试模式")
        advanced_layout.addWidget(self.debug_dump_switch)
        advanced_layout.addWidget(
            self._description("开启后，BITZH Connect 会记录详细的调试信息到日志文件")
        )

        # 肯定句表述（原"禁用备用线路检测"勾选=禁用是双重否定）；存储时取反
        self.auto_multi_line_switch = QCheckBox("自动切换备用线路")
        self.auto_multi_line_switch.setChecked(True)
        advanced_layout.addWidget(self.auto_multi_line_switch)
        advanced_layout.addWidget(
            self._description("当前线路不稳定时自动切换到备用线路")
        )

        self.tun_mode_switch = QCheckBox("TUN 模式（全局路由）")
        if system() == "Windows":
            # 本期 TUN 仅 macOS/Linux：Windows 提权链路（.bat + UAC）未验证，honest 置灰
            self.tun_mode_switch.setEnabled(False)
        advanced_layout.addWidget(self.tun_mode_switch)
        tun_note = "所有流量（含 SSH 等裸 TCP）都走 VPN，默认开启；需要管理员授权；与 Clash TUN 模式互斥"
        if system() == "Windows":
            tun_note += "（本期仅 macOS/Linux）"
        advanced_layout.addWidget(self._description(tun_note))

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
        network_layout.addWidget(self.advanced_area)

        network_layout.addStretch()

        # ================= 帮助 tab（原菜单栏"帮助"收编到这里） =================
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        help_layout.setSpacing(8)

        help_layout.addWidget(self._group_header("关于"))
        about = QLabel(
            f"<p style='font-size:15pt; font-weight:600; margin-bottom:2px;'>{APP_NAME}</p>"
            f"<p style='margin:0;'>版本 {VERSION}</p>"
            f"<p style='margin:0;'><a href='{REPO_URL}'>GitHub 仓库</a></p>"
            f"<p style='margin:0; color:{theme.semantic_color('secondary_text')};'>"
            f"基于 <a href='https://github.com/kowyo/hitsz-connect-verge'>HITSZ Connect Verge</a>"
            f"，内核 <a href='https://github.com/Mythologyli/zju-connect'>ZJU Connect</a></p>"
        )
        about.setOpenExternalLinks(True)
        help_layout.addWidget(about)

        # ---- 校园网支持（校内管理门户 + 网管中心电话）----
        help_layout.addWidget(self._group_header("校园网支持"))
        campus_link = QLabel(
            f"<a href='http://10.7.0.103:9066/' style='color: {theme.semantic_color('accent')};"
            f" text-decoration: none;'>校园网校内管理 ↗</a>"
        )
        campus_link.setOpenExternalLinks(True)
        campus_link.setCursor(Qt.PointingHandCursor)
        help_layout.addWidget(campus_link)
        help_layout.addWidget(self._description("需连接校园网（或本 VPN）后访问"))
        phone = QLabel("校园网络中心电话：(0756) 3835303")
        phone.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 电话号可选中复制
        help_layout.addWidget(phone)

        # 支持：只有一个按钮，不再单独起分组标题（组标题是噪音）
        support_row = QHBoxLayout()
        support_row.setSpacing(8)
        update_btn = QPushButton("检查更新")
        update_btn.clicked.connect(self._check_update)
        support_row.addWidget(update_btn)
        support_row.addStretch()
        help_layout.addLayout(support_row)

        help_layout.addStretch()

        # macOS 惯例：General 在前；帮助殿后
        tab_widget.addTab(general_tab, "通用")
        tab_widget.addTab(network_tab, "网络")
        tab_widget.addTab(help_tab, "帮助")
        layout.addWidget(tab_widget)
        self._tabs = tab_widget

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

    def _fit_to_tab(self, index: int):
        """对话框高度贴合当前 tab：tab 控件定高 = 当前页 sizeHint + 实测开销。"""
        if self._tab_overhead is None:
            self._tab_overhead = self._tabs.sizeHint().height() - max(
                self._tabs.widget(i).sizeHint().height()
                for i in range(self._tabs.count())
            )
        page = self._tabs.widget(index)
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
        """帮助 tab 的检查更新（复用 menu_utils 的完整弹窗流程）。"""
        from .menu_utils import check_for_updates  # 局部导入避免循环依赖

        check_for_updates(self.window(), VERSION)

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
            # 菜单栏已整体移除，隐藏 Dock 只需切换激活策略，无需重建菜单栏
            hide_dock_icon(self.hide_dock_icon_switch.isChecked())
            self.parent().hide_dock_icon = self.hide_dock_icon_switch.isChecked()

        super().accept()
