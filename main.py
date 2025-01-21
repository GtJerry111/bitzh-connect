import keyring
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit, QCheckBox, QPushButton, 
    QTextEdit, QVBoxLayout, QHBoxLayout, QWidget, QSystemTrayIcon, QMenu,
    QMessageBox, QDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
import subprocess
import platform
import shlex
from utils.set_proxy import CommandWorker
import requests
from packaging import version
import webbrowser
if platform.system() == "Windows":
    from subprocess import CREATE_NO_WINDOW

VERSION = "0.2.3"  # Add version constant at top level

# Main Window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HITSZ Connect Verge")
        self.setFixedSize(300, 450)
        self.service_name = "hitsz-connect-verge"
        self.username_key = "username"    
        self.password_key = "password"    
        
        # Initialize system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        if platform.system() == "Windows":
            icon_path = self.get_resource_path("assets/icon.ico")
        elif platform.system() == "Darwin":
            icon_path = self.get_resource_path("assets/icon.icns")
        elif platform.system() == "Linux":
            icon_path = self.get_resource_path("assets/icon.png")
        
        self.tray_icon.setIcon(QIcon(icon_path))
        self.create_tray_menu()
        self.tray_icon.show()
        
        self.worker = None
        self.setup_menubar()  # Add this line before setup_ui()
        self.setup_ui()
        self.load_credentials()

    def setup_menubar(self):
        menubar = self.menuBar()
        
        # Settings Menu
        settings_menu = menubar.addMenu("设置")
        
        # Advanced Settings Action
        self.advanced_action = settings_menu.addAction("高级设置")
        self.advanced_action.triggered.connect(self.toggle_advanced_settings)
        
        # Help Menu
        about_menu = menubar.addMenu("帮助")
        about_menu.addAction("查看日志").triggered.connect(self.show_log)
        about_menu.addAction("检查更新").triggered.connect(self.check_for_updates)
        about_menu.addAction("关于").triggered.connect(self.show_about)

    def toggle_advanced_settings(self, checked):
        QMainWindow.resize(self, 300, 450 if checked else 300)
        self.server_label.setVisible(checked)

    def check_for_updates(self):
        """Check for updates using GitHub API."""
        try:
            response = requests.get(
                "https://api.github.com/repos/kowyo/hitsz-connect-verge/releases/latest",
                timeout=5
            )
            response.raise_for_status()
            latest_version = response.json()["tag_name"].lstrip('v')
            
            if version.parse(latest_version) > version.parse(VERSION):
                dialog = QDialog(self)
                dialog.setWindowTitle("检查更新")
                dialog.setMinimumWidth(300)
                
                layout = QVBoxLayout()
                layout.setSpacing(15)
                layout.setContentsMargins(20, 20, 20, 20)
                
                message = f"""<div style='text-align: center;'>
                <h3 style='margin-bottom: 15px;'>发现新版本！</h3>
                <p>当前版本：{VERSION}</p>
                <p>最新版本：{latest_version}</p>
                </div>"""
                message_label = QLabel(message)
                message_label.setTextFormat(Qt.RichText)
                layout.addWidget(message_label)
                
                button_layout = QHBoxLayout()
                button_layout.setSpacing(10)
                
                download_button = QPushButton("下载更新")
                download_button.clicked.connect(lambda: webbrowser.open("https://github.com/kowyo/hitsz-connect-verge/releases/latest"))
                button_layout.addWidget(download_button)
                
                close_button = QPushButton("关闭")
                close_button.setObjectName("closeBtn")
                close_button.clicked.connect(dialog.close)
                button_layout.addWidget(close_button)
                
                layout.addLayout(button_layout)
                dialog.setLayout(layout)
                dialog.exec()
            else:
                QMessageBox.information(self, "检查更新", "当前已是最新版本！")
                
        except requests.RequestException:
            QMessageBox.warning(self, "检查更新", "检查更新失败，请检查网络连接。")

    def show_about(self):
        about_text = f'''<p style="font-size: 15pt;">HITSZ Connect Verge</p>
        <p style="font-size: 10pt;">Version: {VERSION}</p>
        <p style="font-size: 10pt;">Repository: <a href="https://github.com/kowyo/hitsz-connect-verge">github.com/kowyo/hitsz-connect-verge</a></p>
        <p style="font-size: 10pt;">Author: <a href="https://github.com/kowyo">kowyo</a></p> '''
        QMessageBox.about(self, "关于 HITSZ Connect Verge", about_text)

    def show_log(self):
        """Show the log window."""        
        dialog = QDialog(self)
        dialog.setWindowTitle("查看日志")
        dialog.setMinimumSize(300, 400)
        
        layout = QVBoxLayout()
        
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setText(self.output_text.toPlainText())
        layout.addWidget(log_text)
        
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(log_text.toPlainText()))
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.close)

        button_layout = QHBoxLayout()
        button_layout.addWidget(copy_button)
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        dialog.show()

    def setup_ui(self):
        # Layouts
        layout = QVBoxLayout()
        
        # Account and Password
        layout.addWidget(QLabel("用户名"))
        self.username_input = QLineEdit()
        layout.addWidget(self.username_input)

        layout.addWidget(QLabel("密码"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        self.show_password_cb = QCheckBox("显示密码")
        self.show_password_cb.stateChanged.connect(self.toggle_password_visibility)
        layout.addWidget(self.show_password_cb)

        self.remember_cb = QCheckBox("记住密码")
        layout.addWidget(self.remember_cb)
        
        # Server and DNS (store labels as class members)
        self.server_label = QLabel("SSL VPN 服务端地址：")
        layout.addWidget(self.server_label)
        self.server_label.hide()
        
        self.server_input = QLineEdit("vpn.hitsz.edu.cn")
        layout.addWidget(self.server_input)
        self.server_input.hide()

        self.dns_label = QLabel("DNS 服务器地址：")
        layout.addWidget(self.dns_label)
        self.dns_label.hide()
        
        self.dns_input = QLineEdit("10.248.98.30")
        layout.addWidget(self.dns_input)
        self.dns_input.hide()
        
        # Proxy Control
        self.proxy_cb = QCheckBox("自动配置代理")
        self.proxy_cb.setChecked(True)
        # layout.addWidget(self.proxy_cb)

        # Status and Output
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("运行信息"))
        layout.addLayout(status_layout)
        status_layout.addStretch()
        self.status_label = QLabel("状态: 未连接")
        status_layout.addWidget(self.status_label)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text)

        # Buttons
        button_layout = QHBoxLayout()
        self.connect_button = QPushButton("连接")
        self.connect_button.setCheckable(True)
        self.connect_button.toggled.connect(lambda: self.start_connection() if self.connect_button.isChecked() else self.stop_connection())
        self.connect_button.toggled.connect(lambda: self.connect_button.setText("断开") if self.connect_button.isChecked() else self.connect_button.setText("连接"))
        self.connect_button.clicked.connect(self.save_credentials)
        button_layout.addWidget(self.connect_button)

        button_layout.addStretch()

        self.exit_button = QPushButton("退出")
        self.exit_button.clicked.connect(self.stop_connection) 
        self.exit_button.clicked.connect(self.quit_app)
        button_layout.addWidget(self.exit_button)
        layout.addLayout(button_layout)

        # Set main widget
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def create_tray_menu(self):
        menu = QMenu()
        show_action = menu.addAction("打开面板")
        show_action.triggered.connect(self.show)
        hide_action = menu.addAction("隐藏面板")
        hide_action.triggered.connect(self.hide)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self.quit_app)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            self.quit_app()

    def quit_app(self):
        self.stop_connection()
        self.tray_icon.hide()
        QApplication.quit()

    def toggle_password_visibility(self):
        if self.show_password_cb.isChecked():
            self.password_input.setEchoMode(QLineEdit.Normal)
        else:
            self.password_input.setEchoMode(QLineEdit.Password)

    def load_credentials(self):
        """Load stored credentials from keyring."""
        saved_username = keyring.get_password(self.service_name, self.username_key)
        saved_password = keyring.get_password(self.service_name, self.password_key)
        if saved_username:
            self.username_input.setText(saved_username)
        if saved_password:
            self.password_input.setText(saved_password)
            self.remember_cb.setChecked(True)

    def save_credentials(self):
        """Save credentials to keyring if 'Remember Password' is checked."""
        username = self.username_input.text()
        password = self.password_input.text()

        if self.remember_cb.isChecked():
            keyring.set_password(self.service_name, self.username_key, username)
            keyring.set_password(self.service_name, self.password_key, password)
        else:
            # Remove credentials if the user unchecks the remember box
            keyring.delete_password(self.service_name, self.username_key)
            keyring.delete_password(self.service_name, self.password_key)

    def start_connection(self):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("状态: 正在运行")
            return

        username = self.username_input.text()
        password = self.password_input.text()
        server_address = self.server_input.text()
        dns_server_address = self.dns_input.text()

        import os, sys
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        if platform.system() == "Windows":
            command = os.path.join(base_path, "core", "zju-connect.exe")
        else:
            command = os.path.join(base_path, "core", "zju-connect")
            # Ensure executable permissions on Unix-like systems
            if os.path.exists(command):
                os.chmod(command, 0o755)

        command_args = [
            command, "-server", shlex.quote(server_address),
            "-zju-dns-server", shlex.quote(dns_server_address),
            "-username", shlex.quote(username), "-password", shlex.quote(password)
        ]
        
        self.worker = CommandWorker(command_args, self.proxy_cb.isChecked())
        self.worker.output.connect(self.append_output)
        self.worker.finished.connect(self.on_connection_finished)
        self.worker.start()

        self.status_label.setText("状态: 正在运行")

    def stop_connection(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None

        self.status_label.setText("状态: 未连接")

    def append_output(self, text):
        self.output_text.append(text)

    def on_connection_finished(self):
        self.worker = None
        self.status_label.setText("状态: 未连接")

    @staticmethod
    def get_resource_path(relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller"""
        import os, sys
        if getattr(sys, 'frozen', False):
            # Running as bundled exe
            base_path = sys._MEIPASS
        else:
            # Running as script
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

# Run the application
if __name__ == "__main__":
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    
    if platform.system() == "Windows":
        icon_path = MainWindow.get_resource_path("assets/icon.ico")
    elif platform.system() == "Darwin":
        icon_path = MainWindow.get_resource_path("assets/icon.icns")
    elif platform.system() == "Linux":
        icon_path = MainWindow.get_resource_path("assets/icon.png")
    app_icon = QIcon(icon_path)
    app.setWindowIcon(app_icon)
    
    window = MainWindow()
    window.show()
    app.exec()
