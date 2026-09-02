from PySide6.QtWidgets import (
    QMainWindow,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QTextEdit,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)
from PySide6.QtCore import QEvent, QTimer, Qt
from utils.tray_utils import handle_close_event, quit_app, init_tray_icon
from utils.credential_utils import save_credentials
from utils.connection_utils import start_connection, stop_connection
from utils.password_utils import toggle_password_visibility
from views.menu_utils import setup_menubar, check_for_updates
from utils.config_utils import load_settings
from services.reconnect_manager import ReconnectManager
from utils.set_proxy import cleanup_residue_proxy
from common.constants import APP_NAME
from common.version import get_version

VERSION = get_version()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        self.worker = None
        self.version = VERSION
        self.load_settings()
        from common import theme

        theme.set_appearance(self.appearance)
        setup_menubar(self, self.version)
        self.setup_ui()
        self.virtual_ip = None
        self._manual_stop = True
        self._auth_failed = False
        self._rate_monitor = None
        self._rate_monitor_gen = 0  # 在途重试链世代号：stop/重启即翻篇，防止断连后建起残留 monitor
        self.reconnect_manager = ReconnectManager(
            reconnect_action=lambda: self.connect_button.setChecked(True),
        )
        self.reconnect_manager.set_enabled(self.auto_reconnect)
        self.reconnect_manager.retry_scheduled.connect(
            lambda attempt, delay: self.status_panel.set_reconnecting(attempt, delay)
        )
        self.reconnect_manager.retries_exhausted.connect(
            lambda: self.status_panel.set_reconnect_paused()
        )
        if cleanup_residue_proxy(self):
            self.output_text.append("[BITZH Connect] 已清理上次异常退出残留的系统代理\n")
        self.tray_icon = init_tray_icon(self)

        # B11：启动自动连接前先确认凭据存在，避免拉起一个注定失败的进程
        if self.connect_startup:
            if self.username_input.text() and self.password_input.text():
                QTimer.singleShot(5000, lambda: self.connect_button.setChecked(True))
            else:
                self.output_text.append(
                    "[BITZH Connect] 已开启启动时自动连接，但未保存凭据，跳过自动连接\n"
                )

        if self.check_update:
            self.check_updates_startup()

    def setup_ui(self):
        from common import theme
        from utils.credential_utils import load_credentials
        from utils.motion_utils import animated_height_toggle
        from views.resource_section import ResourceSection
        from views.status_panel import StatusPanel

        self.setMinimumSize(360, 520)
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # 状态仪表盘（hero 布局）
        self.status_panel = StatusPanel(server_text=self.server_address)
        layout.addWidget(self.status_panel)

        # 资源区（初始隐藏，连接成功展开）
        self.resource_area = ResourceSection()
        self.resource_area.setVisible(False)
        layout.addWidget(self.resource_area)

        # 凭据区（容器化，连接成功收起）
        self.cred_area = QWidget()
        cred_layout = QVBoxLayout(self.cred_area)
        cred_layout.setSpacing(8)
        cred_layout.setContentsMargins(0, 0, 0, 0)

        saved_username, saved_password = load_credentials()

        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("用户名"))
        self.username_input = QLineEdit()
        self.username_input.setText(saved_username)
        self.username_input.setPlaceholderText("学号/工号")
        user_row.addWidget(self.username_input)
        cred_layout.addLayout(user_row)

        pass_row = QHBoxLayout()
        pass_row.addWidget(QLabel("密码"))
        self.password_input = QLineEdit()
        self.password_input.setText(saved_password)
        self.password_input.setEchoMode(QLineEdit.Password)
        pass_row.addWidget(self.password_input)
        cred_layout.addLayout(pass_row)

        opt_row = QHBoxLayout()
        self.remember_cb = QCheckBox("记住密码")
        self.remember_cb.setChecked(self.remember)
        self.remember_cb.stateChanged.connect(self.save_credentials)
        opt_row.addWidget(self.remember_cb)
        self.show_password_cb = QCheckBox("显示密码")
        self.show_password_cb.stateChanged.connect(
            lambda checked: toggle_password_visibility(self.password_input, checked)
        )
        opt_row.addWidget(self.show_password_cb)
        opt_row.addStretch()
        cred_layout.addLayout(opt_row)

        layout.addWidget(self.cred_area)

        # 连接按钮（BIT 绿 accent，按下即时加深反馈）
        self.connect_button = QPushButton("连接")
        self.connect_button.setCheckable(True)
        self.connect_button.setMinimumHeight(38)
        self.connect_button.setCursor(Qt.PointingHandCursor)
        self.connect_button.setAttribute(Qt.WA_AlwaysShowToolTips)  # 窗口 inactive 时也显示 tooltip
        # Qt 不向 disabled widget 派发 tooltip 事件，须由 eventFilter 拦截补发
        self.connect_button.installEventFilter(self)
        # 小号次要退出按钮（grilling 确认保留旧 UI 元素；须在 _apply_button_style 前创建）
        self.exit_button = QPushButton("退出")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.clicked.connect(self.quit_app)
        self._apply_button_style()
        self.connect_button.toggled.connect(
            lambda: self.start_connection()
            if self.connect_button.isChecked()
            else self.stop_connection()
        )
        self.connect_button.toggled.connect(
            lambda: self.connect_button.setText("断开")
            if self.connect_button.isChecked()
            else self.connect_button.setText("连接")
        )
        self.connect_button.toggled.connect(self.save_credentials)
        # 输入框禁用态跟随按钮实时勾选态（而非 toggled 参数）：
        # start_connection 凭据校验早退已在前面槽位复位按钮，用参数会把输入框重新禁用
        self.connect_button.toggled.connect(
            lambda checked: self.username_input.setDisabled(
                self.connect_button.isChecked()
            )
        )
        self.connect_button.toggled.connect(
            lambda checked: self.password_input.setDisabled(
                self.connect_button.isChecked()
            )
        )
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.connect_button, 1)
        btn_row.addWidget(self.exit_button)
        layout.addLayout(btn_row)

        # 内联校验：凭据不全即禁用（连接中保持可点以便断开）
        self._animated_height_toggle = animated_height_toggle
        self.username_input.textChanged.connect(self._refresh_connect_button)
        self.password_input.textChanged.connect(self._refresh_connect_button)
        self._refresh_connect_button()

        # 折叠日志区（默认收起，高度动画可中途反向）
        self.log_toggle = QToolButton()
        self.log_toggle.setText("运行日志")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(False)
        self.log_toggle.setArrowType(Qt.RightArrow)
        self.log_toggle.setStyleSheet("QToolButton {border: none;}")
        self.log_toggle.toggled.connect(self._toggle_log)
        layout.addWidget(self.log_toggle)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setVisible(False)
        self.output_text.document().setMaximumBlockCount(5000)  # B9: 日志上限
        layout.addWidget(self.output_text)

        # 一收一放：仪表盘状态驱动凭据区/资源区显隐动画
        self._cred_visible = True
        self._res_visible = False
        self.status_panel.areas_changed.connect(self._apply_area_visibility)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 深浅色切换时刷新样式
        theme.on_scheme_changed(self._apply_button_style)
        theme.on_scheme_changed(self.status_panel.refresh_theme)
        theme.on_scheme_changed(self.resource_area.refresh_theme)

    def _apply_area_visibility(self, cred_visible: bool, res_visible: bool):
        """凭据区/资源区一收一放（250ms，可打断，幂等）。"""
        if cred_visible == self._cred_visible and res_visible == self._res_visible:
            return
        self._cred_visible = cred_visible
        self._res_visible = res_visible
        self._animated_height_toggle(
            self.cred_area, cred_visible, max_height=140, on_frame=self.adjustSize
        )
        self._animated_height_toggle(
            self.resource_area, res_visible, max_height=40, on_frame=self.adjustSize
        )

    def _apply_button_style(self):
        from common import theme

        self.connect_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: none;
                border-radius: 6px;
                font-size: 15px;
                font-weight: 600;
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("accent_pressed")};
            }}
            QPushButton:disabled {{
                background-color: {theme.semantic_color("idle")};
                color: {theme.semantic_color("accent_text")};
            }}
        """)
        # 退出按钮：次要样式（无边框灰字），随深浅色刷新
        self.exit_button.setStyleSheet(
            f"QPushButton {{ color: {theme.semantic_color('secondary_text')};"
            f" border: none; padding: 8px 12px; }}"
        )

    def eventFilter(self, obj, event):
        # 禁用态下 Qt 不派发 tooltip：拦截后手动弹出（内联校验的提示依赖此路径）
        if (
            obj is self.connect_button
            and event.type() == QEvent.ToolTip
            and not self.connect_button.isEnabled()
        ):
            QToolTip.showText(
                event.globalPos(), self.connect_button.toolTip(), self.connect_button
            )
            return True
        return super().eventFilter(obj, event)

    def _refresh_connect_button(self):
        filled = bool(self.username_input.text() and self.password_input.text())
        self.connect_button.setEnabled(filled or self.connect_button.isChecked())
        self.connect_button.setToolTip("" if filled else "请输入用户名和密码")

    def _toggle_log(self, expanding):
        self.log_toggle.setArrowType(Qt.DownArrow if expanding else Qt.RightArrow)
        self._animated_height_toggle(
            self.output_text, expanding, max_height=200, on_frame=self.adjustSize
        )

    def closeEvent(self, event):
        handle_close_event(self, event, self.tray_icon)

    def quit_app(self):
        quit_app(self, self.tray_icon)

    def save_credentials(self):
        save_credentials(self)

    def start_connection(self):
        start_connection(self)

    def stop_connection(self):
        stop_connection(self)

    def start_rate_monitor(self, virtual_ip: str):
        """TUN 连接成功后启动速率监控（tun 网卡创建可能滞后，最多等 5s）。"""
        self.stop_rate_monitor()
        from services.rate_monitor import RateMonitor, find_tun_interface

        self._rate_monitor_gen += 1
        gen = self._rate_monitor_gen

        def _try_start(attempts=0):
            if gen != self._rate_monitor_gen:
                return  # 断连/重连已翻篇，丢弃在途重试
            interface = find_tun_interface(virtual_ip)
            if interface:
                self._rate_monitor = RateMonitor(interface, self.status_panel.set_rates, self)
                self._rate_monitor.start()
            elif attempts < 10:
                QTimer.singleShot(500, lambda: _try_start(attempts + 1))

        self._rate_monitor = None
        _try_start()

    def stop_rate_monitor(self):
        self._rate_monitor_gen += 1  # 作废在途重试链
        if getattr(self, "_rate_monitor", None):
            self._rate_monitor.stop()
            self._rate_monitor = None

    def load_settings(self):
        load_settings(self)

    def check_updates_startup(self):
        check_for_updates(self, self.version, startup=True)
