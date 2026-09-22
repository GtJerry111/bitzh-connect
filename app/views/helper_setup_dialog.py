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
        self.cancel_button.clicked.connect(self.reject)
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

    # ---- 行为 ----
    def _on_install(self):
        self.install_button.setEnabled(False)
        self._status.setText("等待管理员授权…")
        helper_installer.install_async(self._on_install_done)

    def _on_install_done(self, ok: bool):
        if ok:
            self._status.setText("安装完成")
            self.accept()
            return
        self.install_button.setEnabled(True)
        self._status.setText("安装失败或已取消授权，将回退为每次连接时授权。")
