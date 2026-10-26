# app/views/direct_ip_reconnect_dialog.py
"""修改直连 IP 后的“稍后 / 现在重连”确认弹窗。"""
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from common import theme


class DirectIpReconnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("应用直连 IP 配置？")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        title = QLabel("应用直连 IP 配置？")
        f = title.font()
        f.setPointSize(14)
        f.setWeight(f.Weight.DemiBold)
        title.setFont(f)
        layout.addWidget(title)
        body = QLabel(
            "直连 IP 已修改。应用新配置需要断开并重连 VPN，"
            "学校 SSH 会短暂断开；公司 SSH 也需要重新连接。"
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        layout.addWidget(body)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.keep_btn = QPushButton("稍后")
        self.keep_btn.setDefault(True)
        self.keep_btn.clicked.connect(self.reject)
        buttons.addWidget(self.keep_btn)
        self.reconnect_btn = QPushButton("现在重连")
        self.reconnect_btn.setDefault(False)
        self.reconnect_btn.clicked.connect(self.accept)
        buttons.addWidget(self.reconnect_btn)
        layout.addLayout(buttons)

    @classmethod
    def ask(cls, parent=None) -> bool:
        return cls(parent).exec() == QDialog.Accepted
