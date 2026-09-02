#!/usr/bin/env python3
"""EasyConnect 登录调试脚本：复刻 zju-connect 的登录流程，逐个变体尝试。

定位 BITZH 服务器（M7.6.8R2）认证失败的原因——官方客户端能登、zju-connect
两版内核都报 Invalid username or password，疑似密码编码/加密流程不兼容。

用法（密码用 getpass 输入，不会出现在命令行和 shell 历史里）：

    uv run python scripts/ec_login_debug.py

脚本会对每个变体打印服务器返回的 ErrorCode / Message，全量输出原文到
/tmp/ec_debug_last_response.xml 供排查。多次失败可能触发服务端锁定（一般 5-10
次），若官方客户端也开始失败，等 10 分钟再试。
"""
import getpass
import os
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://112.91.150.228:443"


def rsa_encrypt_pkcs1v15(n_hex: str, e: int, message: bytes) -> str:
    """纯 Python RSA PKCS#1 v1.5 加密，返回 hex 字符串。

    与 zju-connect 的 Go 实现（rsa.EncryptPKCS1v15）等价：
    EM = 0x00 || 0x02 || PS（随机非零字节，至少 8 个）|| 0x00 || M
    """
    n = int(n_hex, 16)
    k = (n.bit_length() + 7) // 8
    ps_len = k - len(message) - 3
    if ps_len < 8:
        raise ValueError("消息过长，无法加密")
    ps = bytearray()
    while len(ps) < ps_len:
        ps.extend(b for b in os.urandom(ps_len) if b != 0)
    em = b"\x00\x02" + bytes(ps[:ps_len]) + b"\x00" + message
    c = pow(int.from_bytes(em, "big"), e, n)
    return c.to_bytes(k, "big").hex()


def fetch_handshake(session: requests.Session) -> dict:
    """GET login_auth.csp，解析 TwfID / RSA 公钥 / CSRF 码 / RndImg 标志。"""
    r = session.get(f"{BASE}/por/login_auth.csp?apiversion=1", verify=False, timeout=10)

    def grab(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", r.text, re.S)
        return m.group(1) if m else None

    return {
        "twf": grab("TwfID"),
        "rsa_key": grab("RSA_ENCRYPT_KEY"),
        "rsa_exp": grab("RSA_ENCRYPT_EXP") or "65537",
        "csrf": grab("CSRF_RAND_CODE"),
        "rndimg": grab("RndImg"),  # 1 表示服务器要求图形验证码
        "version": grab("VPNVERSION"),
    }


def try_variant(username: str, password: bytes, use_csrf_suffix: bool, label: str,
                portal_style: bool = False) -> bool:
    """完整走一遍登录流程，返回是否成功。每个变体用全新会话（新 TWFID/CSRF）。

    portal_style=True 时严格按官方网页版的报文：URL 不带 type=cs、字段名 mitm_result。
    """
    s = requests.Session()
    s.headers.update({"User-Agent": "EasyConnect_windows"})
    hs = fetch_handshake(s)

    print(f"\n=== 变体 {label} ===")
    print(f"  服务器版本: {hs['version']}  RndImg(是否要求验证码): {hs['rndimg']}")

    message = password + b"_" + hs["csrf"].encode() if use_csrf_suffix else password
    enc = rsa_encrypt_pkcs1v15(hs["rsa_key"], int(hs["rsa_exp"]), message)

    s.cookies.set("TWFID", hs["twf"])
    if portal_style:
        # 官方 portal（auth_psw.js）的实际报文：无 type=cs、mitm_result 字段
        url = f"{BASE}/por/login_psw.csp?anti_replay=1&encrypt=1"
        form = {
            "mitm_result": "",
            "svpn_req_randcode": hs["csrf"],
            "svpn_name": username,
            "svpn_password": enc,
            "svpn_rand_code": "",
        }
    else:
        # zju-connect 的报文：带 type=cs、mitm 字段
        url = f"{BASE}/por/login_psw.csp?anti_replay=1&encrypt=1&type=cs"
        form = {
            "svpn_rand_code": "",
            "mitm": "",
            "svpn_req_randcode": hs["csrf"],
            "svpn_name": username,
            "svpn_password": enc,
        }
    r = s.post(url, data=form, verify=False, timeout=15)
    text = r.text

    # 留档最近一次完整响应（不含密码）供排查
    with open("/tmp/ec_debug_last_response.xml", "w") as f:
        f.write(text)

    result = re.search(r"<Result>(\d)</Result>", text)
    error_code = re.search(r"<ErrorCode>(\d+)</ErrorCode>", text)
    message_tag = re.search(r"<Message><!\[CDATA\[(.*?)\]\]></Message>", text, re.S)
    next_auth = re.search(r"<NextAuth>(-?\d+)</NextAuth>", text)

    print(f"  Result: {result.group(1) if result else '无'}  "
          f"ErrorCode: {error_code.group(1) if error_code else '无'}  "
          f"NextAuth: {next_auth.group(1) if next_auth else '无'}")
    print(f"  Message: {message_tag.group(1) if message_tag else '无'}")

    return bool(result and result.group(1) == "1")


def main():
    print("EasyConnect 登录调试（BITZH 112.91.150.228:443）")
    username = input("用户名: ").strip()
    password_str = getpass.getpass("密码（输入不显示）: ")

    variants = []

    utf8 = password_str.encode("utf-8")
    variants.append(("A: UTF-8 + CSRF + type=cs（zju-connect 原样复刻）", utf8, True, False))
    variants.append(("D: UTF-8 + CSRF 无 type=cs（官方 portal 报文）", utf8, True, True))

    if not password_str.isascii():
        try:
            gbk = password_str.encode("gbk")
            variants.append(("B: GBK + CSRF（密码含非 ASCII 时才有意义）", gbk, True, False))
        except UnicodeEncodeError:
            pass

    for label, pw, use_suffix, portal_style in variants:
        if try_variant(username, pw, use_suffix, label, portal_style):
            print(f"\n✅ 成功！变体 {label} 可以登录")
            print("请把这个结果发回给助手——这决定内核补丁怎么写")
            return

    print("\n❌ 全部变体都被服务器拒绝")
    print("完整响应已存到 /tmp/ec_debug_last_response.xml，请把每次的 ErrorCode/Message 发回给助手")
    print("若 ErrorCode 全是 20004，下一步需要抓官方客户端的包对比（mitmproxy）")


if __name__ == "__main__":
    main()
