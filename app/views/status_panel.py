"""状态面板骨架（Task 8 将填充真正的 UI）。

当前仅提供 5 个状态切换方法的无操作实现，
让连接流程（connection_utils / reconnect_manager）先跑通。
QWidget 子类，Task 8 可直接在原位置替换为真实组件。
"""
from PySide6.QtWidgets import QWidget


class StatusPanel(QWidget):
    """连接状态展示面板。Task 8 替换为真实组件。"""

    def set_connecting(self):
        """进入"连接中"状态。"""
        pass

    def set_connected(self, ip):
        """进入"已连接"状态，展示虚拟 IP。"""
        pass

    def set_disconnected(self, reason=""):
        """进入"未连接"状态，可附带原因（如认证失败）。"""
        pass

    def set_reconnecting(self, attempt, delay):
        """进入"等待重连"状态：第 attempt 次重试，delay 秒后发起。"""
        pass

    def set_reconnect_paused(self):
        """重试次数耗尽，暂停自动重连。"""
        pass
