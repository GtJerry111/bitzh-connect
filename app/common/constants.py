# app/common/constants.py
"""BITZH Connect 全局常量（单一事实源）：品牌、仓库、默认服务器。"""

APP_NAME = "BITZH Connect"
ORG_NAME = "BITZH Connect"

# GitHub fork 信息：更新检查与"关于"页链接都从这里取（grilling 已确认账号）
REPO_OWNER = "GtJerry111"
REPO_NAME = "bitzh-connect"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
UPDATE_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
RELEASES_URL = f"{REPO_URL}/releases/latest"

# BITZH VPN 默认服务器（已验证为标准深信服 EasyConnect）
DEFAULT_SERVER = "112.91.150.228"
DEFAULT_PORT = "443"
DEFAULT_DNS = ""  # 留空即可：默认开启 auto_dns 从服务端获取
