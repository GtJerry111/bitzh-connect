from platform import system

from PySide6.QtWidgets import (
    QMainWindow,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from utils.tray_utils import handle_close_event, quit_app, init_tray_icon
from utils.credential_utils import save_credentials
from utils.connection_utils import start_connection, stop_connection
from utils.password_utils import toggle_password_visibility
from views.menu_utils import check_for_updates, show_advanced_settings
from utils.config_utils import load_config, load_settings, save_config
from services.reconnect_manager import ReconnectManager
from utils.set_proxy import cleanup_residue_proxy
from common.constants import APP_NAME
from common.version import get_version

VERSION = get_version()

# 校训水印透明度：浅色模式下笔画本身是 #D4D4D4 淡灰，需较高不透明度才可见；
# 深色模式下浅灰笔画对比天然偏高，压低不透明度保持"水印"克制
_WATERMARK_OPACITY = {"light": 0.60, "dark": 0.14}


class WatermarkContainer(QWidget):
    """中央容器：在内容层之下绘制校训竖排书法水印（右侧垂直居中）。

    素材：BIT 视觉识别系统校训"德以明理 学以精工"（透明底淡灰 PNG）。
    水印是最底层背景：子控件（输入框/按钮/标签）背景透明，直接叠在其上。
    显隐与凭据区联动：凭据可见时（未连接）校训淡出（避免被输入框遮挡）；
    连接成功凭据收起后淡入——连接成功即品牌时刻。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watermark = QPixmap(":/brand/motto.png")
        self._motto_level = 0.0  # 0=隐藏 1=显示（乘在深浅色基准透明度上）
        self._motto_visible = False

    def set_motto_visible(self, visible: bool):
        """校训淡入淡出（250ms，可打断；reduce-motion 即时）。"""
        if visible == self._motto_visible:
            return
        self._motto_visible = visible
        from utils.motion_utils import ANIMATION_DURATION_MS, reduce_motion
        from PySide6.QtCore import QEasingCurve, QVariantAnimation

        if reduce_motion():
            self._motto_level = 1.0 if visible else 0.0
            self.update()
            return
        old = getattr(self, "_motto_anim", None)
        if old is not None:
            self._motto_anim = None
            old.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(ANIMATION_DURATION_MS)
        anim.setStartValue(self._motto_level)
        anim.setEndValue(1.0 if visible else 0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._set_motto_level)
        self._motto_anim = anim
        anim.start()

    def _set_motto_level(self, level):
        self._motto_level = float(level)
        self.update()

    def paintEvent(self, event):
        if not self._watermark.isNull() and self._motto_level > 0.0:
            from common import theme

            painter = QPainter(self)
            # 高度取窗口 66%（封顶 500，素材原生高度），右侧留 8px 边距
            target_h = min(int(self.height() * 0.66), 500)
            scaled = self._watermark.scaledToHeight(
                target_h, Qt.SmoothTransformation
            )
            x = self.width() - scaled.width() - 8
            y = (self.height() - scaled.height()) // 2
            base = _WATERMARK_OPACITY["dark" if theme.is_dark() else "light"]
            painter.setOpacity(base * self._motto_level)
            painter.drawPixmap(x, y, scaled)
            painter.end()
        super().paintEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        self._ready = False  # 启动宽限期标志：静默启动时 Dock 激活不弹主窗口
        self.worker = None
        self.version = VERSION
        self.load_settings()
        from common import theme

        theme.set_appearance(self.appearance)
        self.setup_ui()
        # 无菜单栏（设置/帮助入口在主窗口右下角与对话框"帮助"tab）；
        # ⌘, 快捷键保留 macOS 惯例
        QShortcut(
            QKeySequence.Preferences, self,
            activated=lambda: show_advanced_settings(self),
        )
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

        # 休眠/唤醒联动（仅 macOS 实装）：休眠抑制重连，唤醒立即重连
        from utils.sleep_wake import install_sleep_wake_hooks

        install_sleep_wake_hooks(self)

        # Dock 激活兜底入口（仅 macOS）：托盘图标被拥挤菜单栏挤出时，
        # 点 Dock 图标/Cmd-Tab 也能唤出主窗口。启动宽限期 1.5s（静默启动不弹窗）
        if system() == "Darwin":
            from utils.macos_utils import install_activation_hook

            install_activation_hook(self)
        QTimer.singleShot(1500, self._mark_ready)

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
        from views.nav_section import NavSection
        from views.status_panel import StatusPanel

        # 高度下限取未连接态内容自然高度（hero+凭据+按钮，统计行未连接不显示）；
        # 连接后凭据区收起，adjustSize 会把窗口收到接近内容高度，不留大段空白
        self.setMinimumSize(360, 340)
        layout = QVBoxLayout()
        # 间距体系：边距 16/8/16/12，区块间距 12（4/8/12/16 四档制）
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(12)

        # 状态仪表盘（hero 布局）
        self.status_panel = StatusPanel(server_text=self.server_address)
        layout.addWidget(self.status_panel)

        # 资源区（初始隐藏，连接成功展开）
        self.nav_area = NavSection()
        self.nav_area.setVisible(False)
        layout.addWidget(self.nav_area)

        # 凭据区（容器化，连接成功收起）
        self.cred_area = QWidget()
        cred_layout = QVBoxLayout(self.cred_area)
        cred_layout.setSpacing(8)
        cred_layout.setContentsMargins(0, 0, 0, 0)

        saved_username, saved_password = load_credentials()

        # 下划线式输入（spec 定稿：无边框 QLineEdit + 底部 1px 线，focus 时 accent 加粗）；
        # 标签定宽对齐两个输入框的左缘（"用户名"3 字 vs "密码"2 字自然宽度会错开）
        user_row = QHBoxLayout()
        user_row.setSpacing(8)
        user_label = QLabel("用户名")
        user_label.setFixedWidth(44)
        user_row.addWidget(user_label)
        self.username_input = QLineEdit()
        self.username_input.setText(saved_username)
        self.username_input.setPlaceholderText("学号/工号")
        user_row.addWidget(self.username_input)
        cred_layout.addLayout(user_row)

        pass_row = QHBoxLayout()
        pass_row.setSpacing(8)
        pass_label = QLabel("密码")
        pass_label.setFixedWidth(44)
        pass_row.addWidget(pass_label)
        self.password_input = QLineEdit()
        self.password_input.setText(saved_password)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("统一身份认证密码")
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

        # 连接按钮（BIT 绿 accent，悬停微亮/按下加深/禁用衰减，焦点环兜底）；
        # 收窄定宽 240px 居中（与资源胶囊组 248px 视觉成组），不再是全宽大色块
        self.connect_button = QPushButton("连接")
        self.connect_button.setCheckable(True)
        self.connect_button.setFixedWidth(240)
        self.connect_button.setMinimumHeight(38)
        self.connect_button.setCursor(Qt.PointingHandCursor)
        self.connect_button.setAttribute(Qt.WA_AlwaysShowToolTips)  # 窗口 inactive 时也显示 tooltip
        # Qt 不向 disabled widget 派发 tooltip 事件，须由 eventFilter 拦截补发
        self.connect_button.installEventFilter(self)
        # 小号次要退出按钮（grilling 确认保留旧 UI 元素；须在 _apply_theme_styles 前创建）
        self.exit_button = QPushButton("退出")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.clicked.connect(self.quit_app)
        # 窗口内设置入口（macOS 真机菜单栏在屏幕顶部，窗口内需要可发现的锚点）
        self.settings_button = QPushButton("设置")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(lambda: show_advanced_settings(self))
        self._apply_theme_styles()
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

        # 连接模式分段选择（代理 | TUN 全局路由）——常驻连接按钮上方，两态可见：
        # 已连接时切换 = 先断后连立即生效（见 _on_mode_changed）
        from views.mode_switch import SegmentedModeSwitch

        self.mode_switch = SegmentedModeSwitch()
        self.mode_switch.setCurrentIndex(1 if self.tun_mode else 0)
        self.mode_switch.currentChanged.connect(self._on_mode_changed)
        if system() == "Windows":
            # 与高级设置同款 honest 置灰（提权链路未验证）
            self.mode_switch.setEnabled(False)
            self.mode_switch.setToolTip("本期 TUN 仅支持 macOS/Linux")
        layout.addWidget(self.mode_switch)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.connect_button)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 输入框回车直接发起连接（桌面表单惯例）
        self.username_input.returnPressed.connect(self._connect_on_return)
        self.password_input.returnPressed.connect(self._connect_on_return)

        # 内联校验：凭据不全即禁用（连接中保持可点以便断开）
        self._animated_height_toggle = animated_height_toggle
        self.username_input.textChanged.connect(self._refresh_connect_button)
        self.password_input.textChanged.connect(self._refresh_connect_button)
        self._refresh_connect_button()

        # 底部工具行：退出/设置在右（运行日志已收进设置对话框的"帮助" tab，
        # 主窗口不再陈列）；日志缓冲 output_text 保留为隐藏存储（各处 append 路径不动）
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        bottom_row.addStretch()
        bottom_row.addWidget(self.exit_button)
        bottom_row.addWidget(self.settings_button)
        layout.addLayout(bottom_row)

        self.output_text = QTextEdit(self)  # 隐藏日志缓冲：不进布局、永不显示
        self.output_text.setReadOnly(True)
        self.output_text.setVisible(False)
        self.output_text.document().setMaximumBlockCount(5000)  # B9: 日志上限

        # 一收一放：仪表盘状态驱动凭据区/资源区显隐动画（带淡出，不硬裁）
        self._cred_visible = True
        self._res_visible = False
        self.status_panel.areas_changed.connect(self._apply_area_visibility)

        container = WatermarkContainer()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 深浅色切换时刷新样式（含水印透明度重绘）
        theme.on_scheme_changed(self._apply_theme_styles)
        theme.on_scheme_changed(self.status_panel.refresh_theme)
        theme.on_scheme_changed(self.nav_area.refresh_theme)
        theme.on_scheme_changed(container.update)

    def _connect_on_return(self):
        """回车触发连接：仅凭据齐全且当前未连接时（disabled 态不响应）。"""
        if self.connect_button.isEnabled() and not self.connect_button.isChecked():
            self.connect_button.click()

    def _apply_area_visibility(self, cred_visible: bool, res_visible: bool):
        """凭据区/资源区一收一放（250ms 高度+淡出，可打断，幂等）。

        校训水印与凭据区联动：凭据可见时水印退出（避免被输入框遮挡），
        凭据收起时（已连接/连接中断）水印淡入。
        """
        if cred_visible == self._cred_visible and res_visible == self._res_visible:
            return
        self._cred_visible = cred_visible
        self._res_visible = res_visible
        self._animated_height_toggle(
            self.cred_area, cred_visible, max_height=140, on_frame=self.adjustSize,
            fade=True,
        )
        self._animated_height_toggle(
            self.nav_area, res_visible,
            max_height=max(self.nav_area.sizeHint().height(), 1),
            on_frame=self.adjustSize,
            fade=True,
        )
        self.centralWidget().set_motto_visible(not cred_visible)

    def _apply_theme_styles(self):
        """主题相关样式统一入口（深浅色切换时重放）。"""
        from common import theme

        self.connect_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: 2px solid transparent;
                border-radius: 6px;
                font-size: 13pt;
                font-weight: 600;
            }}
            QPushButton:hover:enabled {{
                background-color: {theme.semantic_color("accent_hover")};
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("accent_pressed")};
            }}
            QPushButton:focus {{
                border: 2px solid {theme.with_alpha("accent", 0.5)};
            }}
            QPushButton:disabled {{
                background-color: {theme.semantic_color("accent_disabled")};
                color: {theme.semantic_color("accent_text")};
            }}
        """)
        # 退出/设置：次要文字按钮（无边框灰字，hover 升到主文字色）
        # 字号用 pt 不用 px：QSS 的 px 是物理像素，Retina 下比同值 pt 小一截
        text_button_style = f"""
            QPushButton {{
                color: {theme.semantic_color('secondary_text')};
                border: none;
                padding: 4px 8px;
                font-size: 11pt;
            }}
            QPushButton:hover {{
                color: {theme.semantic_color('ink')};
            }}
        """
        self.exit_button.setStyleSheet(text_button_style)
        self.settings_button.setStyleSheet(text_button_style)
        # 下划线式输入框：无边框 + 底部 1px separator，focus 时 accent 2px
        input_style = f"""
            QLineEdit {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {theme.semantic_color('separator')};
                padding: 5px 2px;
                selection-background-color: {theme.semantic_color('accent')};
            }}
            QLineEdit:focus {{
                border-bottom: 2px solid {theme.semantic_color('accent')};
            }}
            QLineEdit:disabled {{
                color: {theme.semantic_color('secondary_text')};
                border-bottom: 1px dotted {theme.semantic_color('separator')};
            }}
        """
        self.username_input.setStyleSheet(input_style)
        self.password_input.setStyleSheet(input_style)
        # placeholder 颜色：QSS 管不了，走 QPalette（次要色 70% 透明）
        from PySide6.QtGui import QPalette

        placeholder = QColor(theme.semantic_color("secondary_text"))
        placeholder.setAlphaF(0.7)
        for line_edit in (self.username_input, self.password_input):
            palette = line_edit.palette()
            palette.setColor(QPalette.PlaceholderText, placeholder)
            line_edit.setPalette(palette)

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

    def _mark_ready(self):
        """启动宽限期结束：此后 Dock 激活/唤醒等事件才响应。"""
        self._ready = True

    def _on_app_activate(self):
        """应用被激活（Dock 图标点击/Cmd-Tab 切换）：主窗口隐藏则唤出。

        托盘图标被拥挤的菜单栏裁掉时，Dock 是打开主界面的兜底入口。
        启动宽限期（静默启动）与退出流程中不响应。
        """
        if not getattr(self, "_ready", False) or getattr(self, "_quitting", False):
            return
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def _on_mode_changed(self, index: int):
        """主界面模式切换：立即持久化（与高级设置的 TUN 开关同一配置键）；
        已连接则 bounce 重连让新模式立即生效（TUN 断开零弹窗；切回 TUN 弹一次授权）。"""
        self.tun_mode = index == 1
        config = load_config()
        config["tun_mode"] = self.tun_mode
        save_config(config)
        if self.connect_button.isChecked():
            self.output_text.append("[BITZH Connect] 正在切换连接模式，重新连接…\n")
            self._bounce_connection()

    def _bounce_connection(self):
        """先断后连：worker 收尾（finished→复位）需要一拍，1s 后重连足够稳。"""
        self._bounce_pending = True
        self.connect_button.setChecked(False)
        QTimer.singleShot(1000, self._bounce_reconnect)

    def _bounce_reconnect(self):
        """bounce 第二拍（一次性守卫：这一拍内用户操作过则不强行重连）。"""
        if getattr(self, "_bounce_pending", False):
            self._bounce_pending = False
            self.connect_button.setChecked(True)

    def _on_system_sleep(self):
        """系统休眠：取消在途重连退避——盒盖期间触发重连只会在无人理会时弹授权框。"""
        self._asleep = True
        self.reconnect_manager.cancel()

    def _on_system_wake(self):
        """唤醒：处于"应连接"态（非手动断开、非认证失败）则立即重连。

        两种情形：内核假死（按钮仍勾选）→ 先走后连 bounce；内核已在休眠期死亡
        （按钮被收尾复位）→ 直接重连。TUN 断开走停止标记零弹窗，重连弹一次授权框
        （用户刚开盖在场，时机合理）。
        """
        self._asleep = False
        if self._manual_stop or self._auth_failed:
            return
        if not (self.username_input.text() and self.password_input.text()):
            return
        self.output_text.append("[BITZH Connect] 检测到系统从休眠唤醒，正在重新连接…\n")
        if self.connect_button.isChecked():
            self._bounce_connection()
        else:
            self.connect_button.setChecked(True)

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
        """连接成功后启动速率监控。

        TUN 模式：psutil 读 utun 网卡（网卡创建可能滞后，最多等 5s）；
        代理模式（仅 macOS）：nettop 按进程采样 zju-connect（过滤 loopback 镜像）。
        """
        self.stop_rate_monitor()
        from platform import system

        from services.rate_monitor import ProxyRateMonitor, RateMonitor, find_tun_interface

        self._rate_monitor_gen += 1
        gen = self._rate_monitor_gen
        on_rates = self.status_panel.set_rates
        on_sample = self.status_panel.append_rate_sample

        if getattr(self, "tun_mode", False):
            def _try_start(attempts=0):
                if gen != self._rate_monitor_gen:
                    return  # 断连/重连已翻篇，丢弃在途重试
                interface = find_tun_interface(virtual_ip)
                if interface:
                    self._rate_monitor = RateMonitor(interface, on_rates, on_sample, self)
                    self._rate_monitor.start()
                elif attempts < 10:
                    QTimer.singleShot(500, lambda: _try_start(attempts + 1))

            self._rate_monitor = None
            _try_start()
            return

        if system() == "Darwin":
            worker = self.worker
            pid = getattr(getattr(worker, "process", None), "pid", None)
            if pid is not None:
                self._rate_monitor = ProxyRateMonitor(pid, on_rates, on_sample, self)
                self._rate_monitor.start()

    def stop_rate_monitor(self):
        self._rate_monitor_gen += 1  # 作废在途重试链
        if getattr(self, "_rate_monitor", None):
            self._rate_monitor.stop()
            self._rate_monitor = None

    def load_settings(self):
        load_settings(self)

    def check_updates_startup(self):
        check_for_updates(self, self.version, startup=True)
