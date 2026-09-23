"""TUN 特权服务安装引导对话框（独立窗口，风格与高级设置一致）。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from common import theme
from utils import helper_installer

_OPERATIONS = (
    "• 安装常驻特权服务到系统目录（/Library/PrivilegedHelperTools）\n"
    "• 注册开机自启的 LaunchDaemon（/Library/LaunchDaemons）\n"
    "• 自动清除应用的 quarantine 标记（免手动 xattr）\n"
    "• 之后连接 TUN 不再需要输入管理员密码"
)

_LATER_WARNING = (
    "选择“稍后”将回退为每次连接时授权（osascript），"
    "每次连接 TUN 都需要输入管理员密码。\n"
    "你稍后可在「设置 → 网络 → 高级 → 特权服务」里安装。"
)


class HelperSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("安装 TUN 特权服务")
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("启用 TUN 需要安装特权服务")
        font = title.font()
        font.setPointSize(15)
        font.setWeight(font.Weight.DemiBold)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "TUN 全局路由需要管理员权限创建虚拟网卡与路由。"
            "安装一次后，今后连接无需再输入密码。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        layout.addWidget(desc)

        ops = QLabel(_OPERATIONS)
        ops.setWordWrap(True)
        ops.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(ops)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton("稍后")
        self.cancel_button.setMinimumWidth(88)
        # 次级按钮同款 QSS 几何（与"安装"同 padding/圆角/字号/最小宽）——混用
        # "QSS 样式 + 原生样式"会因两边 sizeHint 计算路径不同而一大一小
        self.cancel_button.setStyleSheet(f"""
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
        self.cancel_button.clicked.connect(self._on_later)
        row.addWidget(self.cancel_button)

        self.install_button = QPushButton("安装")
        self.install_button.setMinimumWidth(88)
        self.install_button.setDefault(True)
        self.install_button.setStyleSheet(f"""
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
            QPushButton:disabled {{
                background-color: {theme.semantic_color("accent_disabled")};
            }}
        """)
        self.install_button.clicked.connect(self._on_install)
        row.addWidget(self.install_button)
        layout.addLayout(row)

    # ---- 供测试/外部读取 ----
    def operations_text(self) -> str:
        labels = self.findChildren(QLabel)
        for label in labels:
            if "PrivilegedHelperTools" in label.text():
                return label.text()
        return ""

    def status_text(self) -> str:
        return self._status.text()

    def later_warning_text(self) -> str:
        return _LATER_WARNING

    def _on_later(self):
        if self._confirm_later():
            self.reject()

    def _confirm_later(self) -> bool:
        """点"稍后"时的二次确认；返回 True = 确认稍后（回退每次授权）。"""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("将改用每次授权模式")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(_LATER_WARNING)
        back = box.addButton("返回安装", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("仍要稍后", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(back)
        box.exec()
        return box.clickedButton() is later

    # ---- 行为 ----
    def _on_install(self):
        self.install_button.setEnabled(False)
        # 授权框已弹出，关闭对话框并不能取消授权，故同时禁用"稍后"
        self.cancel_button.setEnabled(False)
        self._status.setText("等待管理员授权…")
        try:
            helper_installer.install_async(self._on_install_done)
        except Exception:
            # 同步抛异常（如提权进程无法拉起）也走同一套失败回退
            self._on_install_done(False)

    def _on_install_done(self, ok: bool):
        from shiboken6 import isValid

        # 回调可能晚于对话框销毁（授权期间窗口被关），此时不可再碰控件
        if not isValid(self):
            return
        if ok:
            self._status.setText("安装完成")
            self.accept()
            return
        self.install_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self._status.setText("安装失败或已取消授权，将回退为每次连接时授权。")
