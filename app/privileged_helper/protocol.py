"""GUI 与特权 helper 之间的共享协议（纯标准库，无任何第三方依赖）。

单一真源：socket 位置、安装位置、命令常量、JSON 行编解码都定义在这里；
GUI 侧与 helper 侧统一以包路径 import
（`from privileged_helper.protocol import ...`）共用本文件。
"""
import json

# 协议版本：GUI 与 helper 握手比对；不兼容时提示用户更新特权服务
PROTOCOL_VERSION = 1

# ---- 运行时通信 ----
SOCKET_PATH = "/var/run/bitzh-connect-helper.sock"

# ---- 安装位置（安装脚本、helper 自检、卸载都以这里为准）----
HELPER_DIR = "/Library/PrivilegedHelperTools/bitzh-connect"
HELPER_BIN = HELPER_DIR + "/bitzh-helper"
KERNEL_BIN = HELPER_DIR + "/zju-connect"
LAUNCHD_LABEL = "com.bitzh-connect.helper"
LAUNCHD_PLIST = "/Library/LaunchDaemons/" + LAUNCHD_LABEL + ".plist"

# ---- 命令 ----
CMD_HELLO = "hello"
CMD_PING = "ping"
CMD_STATUS = "status"
CMD_START = "start"
CMD_STOP = "stop"


def encode(obj: dict) -> bytes:
    """把请求/响应编码为单行 JSON（换行结尾，便于按行读取）。"""
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
