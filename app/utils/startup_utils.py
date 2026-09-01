import os
import sys
from platform import system

from common.constants import APP_NAME

if system() == "Windows":
    import winreg
import subprocess


def set_launch_at_login(enable: bool):
    """Set application to launch at login"""
    if system() == "Windows":
        app_path = sys.argv[0]
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enable:
                    winreg.SetValueEx(
                        key, APP_NAME, 0, winreg.REG_SZ, f'"{app_path}"'
                    )
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
        except OSError:
            pass

    elif system() == "Darwin":
        try:
            app_path = sys.argv[0]
            if ".app/Contents/MacOS/" in app_path:
                # Extract path to the .app bundle
                app_path = app_path.split(".app/Contents/MacOS/")[0] + ".app"

            if enable:
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'tell application "System Events" to make login item at end with properties {{path:"{app_path}", hidden:false}}',
                    ]
                )
            else:
                app_name = os.path.basename(app_path).replace(".app", "")
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'tell application "System Events" to delete login item "{app_name}"',
                    ]
                )
        except subprocess.SubprocessError:
            pass


def get_launch_at_login() -> bool:
    """Check if application is set to launch at login"""
    if system() == "Windows":
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except WindowsError:
            return False

    elif system() == "Darwin":
        try:
            # B6：打包后 argv[0] 是 <App>.app/Contents/MacOS/<二进制名>，
            # 二进制名 ≠ 登录项名，须与 set_launch_at_login 同款路径推导
            app_path = sys.argv[0]
            if ".app/Contents/MacOS/" in app_path:
                app_path = app_path.split(".app/Contents/MacOS/")[0] + ".app"
            app_name = os.path.basename(app_path).replace(".app", "")
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get the name of every login item'],
                capture_output=True, text=True,
            )
            return app_name in result.stdout
        except subprocess.SubprocessError:
            return False

    return False
