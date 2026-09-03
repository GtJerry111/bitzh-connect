from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QApplication,
    QTabWidget,
    QWidget,
    QFileDialog,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from utils.config_utils import save_config, load_config
from utils.startup_utils import set_launch_at_login, get_launch_at_login
from platform import system

if system() == "Darwin":
    from utils.macos_utils import hide_dock_icon
from common.version import get_version
from common.constants import DEFAULT_SERVER
from common import resources
from common import theme

VERSION = get_version()

# 外观三态取值（与下拉框索引一一对应）
_APPEARANCE_MODES = ["system", "light", "dark"]


class AdvancedSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级设置")
        self.setMinimumWidth(420)
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

        # 外观三态（跟随系统 / 浅色 / 深色）
        appearance_form = QFormLayout()
        appearance_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.appearance_combo = QComboBox()
        self.appearance_combo.addItems(["跟随系统", "浅色", "深色"])
        appearance_form.addRow("外观", self.appearance_combo)
        general_layout.addLayout(appearance_form)

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
            self._description("连接后自动配置系统代理，将网络流量通过 VPN 转发")
        )

        # ---- 证书 ----
        network_layout.addWidget(self._group_header("证书"))
        cert_form = QFormLayout()
        cert_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cert_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        cert_row = QHBoxLayout()
        cert_row.setSpacing(8)
        self.cert_file_input = QLineEdit()
        self.cert_file_input.setPlaceholderText("选择 .p12 证书文件")
        self.cert_file_input.setReadOnly(True)
        cert_row.addWidget(self.cert_file_input, 1)
        self.cert_browse_button = QPushButton("浏览…")
        self.cert_browse_button.clicked.connect(self.browse_cert_file)
        cert_row.addWidget(self.cert_browse_button)
        # 文本按钮"清除"替代语义错误的红色 ❌（SP_DialogCancelButton 是"取消"不是"清除"）
        self.cert_clear_button = QPushButton("清除")
        self.cert_clear_button.setStyleSheet(
            f"QPushButton {{ color: {theme.semantic_color('secondary_text')};"
            f" border: none; padding: 4px 6px; }}"
        )
        self.cert_clear_button.clicked.connect(self.clear_cert_file)
        cert_row.addWidget(self.cert_clear_button)
        cert_form.addRow("证书路径", cert_row)

        self.cert_password_input = QLineEdit()
        self.cert_password_input.setPlaceholderText("输入证书密码")
        self.cert_password_input.setEchoMode(QLineEdit.Password)
        cert_form.addRow("证书密码", self.cert_password_input)
        network_layout.addLayout(cert_form)

        # ---- 高级 ----
        network_layout.addWidget(self._group_header("高级"))

        self.keep_alive_switch = QCheckBox("定时保活")
        network_layout.addWidget(self.keep_alive_switch)
        network_layout.addWidget(
            self._description("开启后，ZJU Connect 会定时发送心跳包以保持连接")
        )

        self.debug_dump_switch = QCheckBox("调试模式")
        network_layout.addWidget(self.debug_dump_switch)
        network_layout.addWidget(
            self._description("开启后，ZJU Connect 会记录详细的调试信息到日志文件")
        )

        # 肯定句表述（原"禁用备用线路检测"勾选=禁用是双重否定）；存储时取反
        self.auto_multi_line_switch = QCheckBox("自动切换备用线路")
        self.auto_multi_line_switch.setChecked(True)
        network_layout.addWidget(self.auto_multi_line_switch)
        network_layout.addWidget(
            self._description("当前线路不稳定时自动切换到备用线路")
        )

        self.tun_mode_switch = QCheckBox("TUN 模式（全局路由）")
        if system() == "Windows":
            # 本期 TUN 仅 macOS/Linux：Windows 提权链路（.bat + UAC）未验证，honest 置灰
            self.tun_mode_switch.setEnabled(False)
        network_layout.addWidget(self.tun_mode_switch)
        tun_note = "所有流量（含 SSH 等裸 TCP）都走 VPN；需要管理员授权；与 Clash TUN 模式互斥"
        if system() == "Windows":
            tun_note += "（本期仅 macOS/Linux）"
        network_layout.addWidget(self._description(tun_note))

        network_layout.addStretch()

        # macOS 惯例：General 在前
        tab_widget.addTab(general_tab, "通用")
        tab_widget.addTab(network_tab, "网络")
        layout.addWidget(tab_widget)

        # 按钮盒：平台惯例自动排布（macOS：取消左、保存右），保存为主按钮
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.button_box.button(QDialogButtonBox.Save).setText("保存")
        self.button_box.button(QDialogButtonBox.Cancel).setText("取消")
        save_btn = self.button_box.button(QDialogButtonBox.Save)
        save_btn.setDefault(True)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {theme.semantic_color("accent_hover")};
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("accent_pressed")};
            }}
        """)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def toggle_dns_input(self):
        """Toggle DNS input field based on auto DNS checkbox"""
        self.dns_input.setEnabled(not self.auto_dns_switch.isChecked())

    def browse_cert_file(self):
        """Open file dialog to browse for certificate file"""
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("Certificate files (*.p12)")
        file_dialog.setFileMode(QFileDialog.ExistingFile)

        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.cert_file_input.setText(selected_files[0])

    def clear_cert_file(self):
        """Clear the selected certificate file"""
        self.cert_file_input.clear()
        self.cert_password_input.clear()

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
            "cert_file": self.cert_file_input.text(),
            "cert_password": self.cert_password_input.text(),
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
        self.cert_file_input.setText(cert_file)
        self.cert_password_input.setText(cert_password)
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

        if system() == "Darwin":
            hide_dock_icon(self.hide_dock_icon_switch.isChecked())

            from .menu_utils import setup_menubar

            main_window = self.parent()
            main_window.hide_dock_icon = self.hide_dock_icon_switch.isChecked()
            setup_menubar(main_window, VERSION)

            main_window.show()
            main_window.raise_()

            icon_path = ":/icons/icon.icns"

            app_icon = QIcon(icon_path)
            app = QApplication.instance()
            app.setWindowIcon(app_icon)

        super().accept()
