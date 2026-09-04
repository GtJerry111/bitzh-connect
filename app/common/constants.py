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

# 校内网站导航（已连接态"校内导航"折叠条展开的分组网格）。
# 结构：(组名, [(圆标单字, 短名, URL, tooltip 全称), ...])
# 分组按校区（域名天然即 taxonomy：bitzh=珠海、bit.edu.cn=本部）；
# 顺序按日常频率；圆标用单字——本 App 是纯排版语言，不做线条图标/彩色 emoji。
NAV_GROUPS = [
    ("珠海校区", [
        ("门", "统一门户", "https://s.bitzh.edu.cn", "北理珠统一门户 · s.bitzh.edu.cn"),
        ("教", "教务处", "https://jw.bitzh.edu.cn/", "北理珠教务处 · jw.bitzh.edu.cn"),
        ("图", "电子图书馆", "http://elib.bitzh.edu.cn:8080/interlibSSO/main/main.jsp",
         "电子图书馆 · elib.bitzh.edu.cn"),
        ("珠", "珠海官网", "https://zh.bit.edu.cn/index.htm",
         "北京理工大学（珠海）· zh.bit.edu.cn"),
    ]),
    ("校本部", [
        ("课", "本硕博教学系统", "https://jxzxehall.bit.edu.cn/",
         "北理工本硕博一体化教学系统 · jxzxehall.bit.edu.cn"),
        ("学", "学生综合事务", "https://stu.bit.edu.cn/",
         "北理工学生综合事务平台 · stu.bit.edu.cn"),
        ("研", "研究生院", "https://grd.bit.edu.cn/", "北理工研究生院 · grd.bit.edu.cn"),
        ("费", "校园收费平台", "https://easypay.info.bit.edu.cn/",
         "北理工校园收费平台 · easypay.info.bit.edu.cn"),
        ("W", "WebVPN", "https://webvpn.bit.edu.cn/", "北理工 WebVPN · webvpn.bit.edu.cn"),
        ("官", "本部官网", "https://www.bit.edu.cn/", "北理工官网 · www.bit.edu.cn"),
    ]),
]
