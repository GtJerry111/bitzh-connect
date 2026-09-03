# app/common/constants.py
"""BITZH Connect 全局常量（单一事实源）：品牌、仓库、默认服务器。"""

APP_NAME = "BITZH Connect"
ORG_NAME = "BITZH Connect"

# GitHub fork 信息：更新检查与"关于"页链接都从这里取（grilling 已确认账号）
REPO_OWNER = "GtJerry111"
REPO_NAME = "bitzh-connect"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
# 注意：/releases/latest（API 与网页同规则）不返回预发布/草稿——发版流水线默认
# prerelease:true，必须查列表取最新一条非草稿，否则"检查更新"永远查不到
RELEASES_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"
RELEASES_URL = f"{REPO_URL}/releases"

# BITZH VPN 默认服务器（已验证为标准深信服 EasyConnect）
DEFAULT_SERVER = "112.91.150.228"
DEFAULT_PORT = "443"
DEFAULT_DNS = ""  # 留空即可：默认开启 auto_dns 从服务端获取

# 校内资源入口（用户明确只需要这两个，不做自定义管理）
# 注意：按钮文案不含 emoji——真机渲染为彩色 emoji，与单色描边胶囊的克制感冲突
RESOURCES = [
    ("电子图书馆", "http://elib.bitzh.edu.cn:8080/interlibSSO/main/main.jsp"),
    ("统一门户", "https://s.bitzh.edu.cn"),
]
