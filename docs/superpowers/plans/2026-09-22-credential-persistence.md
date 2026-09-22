# 密码保存持久化修复 Implementation Plan（阶段 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复"勾选记住密码后，完全退出软件再启动仍要重输密码"——根因是加密盐依赖运行时机器标识（打包后不稳定）。

**Architecture:** 把盐来源从「运行时机器指纹（hostname/user/MAC）」改为「首次加密时生成、持久化到 QSettings 的随机盐」。加解密只依赖该盐，彻底与运行环境解耦；新格式前缀 `enc2:`，旧 `enc1:` 密文判为不可解（保留用户名、清空密码、提示用户重输一次）。

**Tech Stack:** Python 3.11 / PySide6 QSettings / pytest（`QT_QPA_PLATFORM=offscreen`，见 `tests/conftest.py`）。

**Spec:** 本会话 grilling 结论（问题 1）。无独立 spec 文件。

---

## 背景（给零上下文的工程师）

- `app/utils/credential_crypto.py` 现状：用 `sha256(platform.node()|getpass.getuser()|uuid.getnode())` 当盐派生密钥（第 32-46 行）。
- 打包成 `.app`（Nuitka）后 `uuid.getnode()` 会不稳定（回退随机值），导致**加密时的盐 ≠ 解密时的盐**，密文永远解不开；而 `load_credentials()` 解不开时静默返回空密码，于是每次启动都要重输。
- 结论：盐必须**持久化**，不能用任何运行时标识。
- 现有测试命令：`.venv/bin/python -m pytest <path> -q`（无需 activate）。
- 测试用独立的 QSettings 命名空间 `BITZH Connect Test`（`tests/conftest.py` 自动清理并 patch `utils.config_utils.APP_NAME/ORG_NAME`），不会碰真实用户配置。

## File Structure

- `app/utils/credential_crypto.py` — 重写：盐参数化、`enc2:` 前缀、`generate_salt()`、`is_legacy_encrypted()`
- `app/utils/config_utils.py` — 默认配置新增 `cred_salt` 键
- `app/utils/credential_utils.py` — 持久化盐的读写、`load_credentials_detailed()`、旧密文处理
- `app/views/main_window.py` — 读取到不可解密文时给一次提示
- `tests/test_credential_crypto.py` — 更新签名 + 新增回归/迁移用例
- `tests/test_main_window.py` — 新增"旧密文提示"用例

---

## Task 1: credential_crypto 改用持久化盐

**Files:**
- Modify: `app/utils/credential_crypto.py`
- Test: `tests/test_credential_crypto.py`

- [ ] **Step 1: 更新测试（改签名 + 新增回归用例）**

把 `tests/test_credential_crypto.py` **整个文件**替换为：

```python
"""本地密码加密与凭据存取（不依赖系统钥匙串）。"""
from utils.credential_crypto import (
    decrypt_password,
    encrypt_password,
    generate_salt,
    is_encrypted,
    is_legacy_encrypted,
)


def test_roundtrip_including_non_ascii():
    salt = generate_salt()
    token = encrypt_password("s3cret-密码-01", salt)
    assert is_encrypted(token)
    assert "s3cret" not in token
    assert decrypt_password(token, salt) == "s3cret-密码-01"


def test_ciphertext_randomized_per_call():
    salt = generate_salt()
    assert encrypt_password("same", salt) != encrypt_password("same", salt)


def test_empty_password_roundtrips_as_empty():
    assert encrypt_password("", generate_salt()) == ""
    assert decrypt_password("", generate_salt()) is None


def test_plaintext_is_not_decryptable():
    assert decrypt_password("just-a-plaintext", generate_salt()) is None


def test_tampered_tag_rejected():
    salt = generate_salt()
    token = encrypt_password("secret", salt)
    payload = list(token)
    # 篡改 base64 正文末位（密文/标签区），HMAC 校验必须失败
    payload[-1] = "A" if payload[-1] != "A" else "B"
    assert decrypt_password("".join(payload), salt) is None


def test_decrypt_with_wrong_salt_rejected():
    token = encrypt_password("secret", generate_salt())
    assert decrypt_password(token, generate_salt()) is None


def test_independent_of_runtime_identity(monkeypatch):
    """回归：加解密只依赖持久化盐，不依赖主机名/用户名/MAC。

    打包（Nuitka）后这些运行时标识会变化，是这个 bug 的根因；
    本用例确保即使它们全变，密文仍可解。
    """
    import utils.credential_crypto as cc

    salt = generate_salt()
    token = cc.encrypt_password("pw", salt)

    monkeypatch.setattr("platform.node", lambda: "changed-host")
    monkeypatch.setattr("getpass.getuser", lambda: "changed-user")
    monkeypatch.setattr("uuid.getnode", lambda: 123)
    assert cc.decrypt_password(token, salt) == "pw"


def test_legacy_prefix_detected():
    assert is_legacy_encrypted("enc1:abc")
    assert not is_encrypted("enc1:abc")
    assert is_encrypted("enc2:abc")
    assert not is_legacy_encrypted("enc2:abc")


def test_load_credentials_migrates_legacy_plaintext(qtbot):
    from utils.config_utils import load_config, save_config
    from utils.credential_utils import load_credentials

    config = load_config()
    config["username"] = "u1"
    config["password"] = "legacy-plain"
    save_config(config)

    assert load_credentials() == ("u1", "legacy-plain")
    # 迁移后配置里已是密文，且再次读取仍能解出
    assert is_encrypted(load_config()["password"])
    assert load_credentials() == ("u1", "legacy-plain")


def test_save_credentials_encrypts_and_roundtrips(qtbot):
    from utils.config_utils import load_config
    from utils.credential_utils import load_credentials, save_credentials

    class _Field:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Check:
        def __init__(self, checked):
            self._checked = checked

        def isChecked(self):
            return self._checked

    class _FakeWindow:
        remember_cb = _Check(True)
        username_input = _Field("2024000001")
        password_input = _Field("pw-秘密")

    save_credentials(_FakeWindow())
    config = load_config()
    assert config["username"] == "2024000001"
    assert is_encrypted(config["password"])
    assert "pw-秘密" not in config["password"]
    assert load_credentials() == ("2024000001", "pw-秘密")


def test_save_credentials_clears_when_not_remembered(qtbot):
    from utils.config_utils import load_config
    from utils.credential_utils import save_credentials

    class _Field:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Check:
        def isChecked(self):
            return False

    class _FakeWindow:
        remember_cb = _Check()
        username_input = _Field("u")
        password_input = _Field("p")

    save_credentials(_FakeWindow())
    config = load_config()
    assert config["username"] == ""
    assert config["password"] == ""


def test_save_credentials_persists_salt_and_reuses_it(qtbot):
    """保存时盐落盘；再次保存复用同一个盐（不每次换盐）。"""
    from utils.config_utils import load_config
    from utils.credential_utils import load_credentials, save_credentials

    class _Field:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _Check:
        def isChecked(self):
            return True

    class _FakeWindow:
        def __init__(self, password):
            self.username_input = _Field("2024000001")
            self.password_input = _Field(password)

        remember_cb = _Check()

    save_credentials(_FakeWindow("pw-1"))
    salt_1 = load_config()["cred_salt"]
    assert salt_1
    assert load_credentials() == ("2024000001", "pw-1")

    save_credentials(_FakeWindow("pw-2"))
    assert load_config()["cred_salt"] == salt_1
    assert load_credentials() == ("2024000001", "pw-2")


def test_legacy_enc1_password_reported_unreadable(qtbot):
    from utils.config_utils import load_config, save_config
    from utils.credential_utils import load_credentials_detailed

    config = load_config()
    config["username"] = "u1"
    config["password"] = "enc1:AAAABBBBCCCC"  # 旧机器指纹密文
    config["remember"] = True
    save_config(config)

    username, password, unreadable = load_credentials_detailed()
    assert username == "u1"     # 用户名保留，不让用户重输
    assert password == ""       # 密码清空
    assert unreadable is True   # 标记需提示重输


def test_enc2_without_salt_reported_unreadable(qtbot):
    from utils.config_utils import load_config, save_config
    from utils.credential_crypto import encrypt_password, generate_salt
    from utils.credential_utils import load_credentials_detailed

    config = load_config()
    config["username"] = "u1"
    config["password"] = encrypt_password("pw", generate_salt())
    config["cred_salt"] = ""  # 盐丢失
    save_config(config)

    _, password, unreadable = load_credentials_detailed()
    assert password == "" and unreadable is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_credential_crypto.py -q`
Expected: 收集/导入失败或大量 FAIL（`generate_salt`/`is_legacy_encrypted` 不存在、`encrypt_password` 缺参数）。

- [ ] **Step 3: 重写 credential_crypto.py**

把 `app/utils/credential_crypto.py` **整个文件**替换为：

```python
"""本地密码加密：不访问系统钥匙串，密码不明文落盘（纯标准库）。

方案：以「应用内置 secret + 本机持久化随机盐」经 PBKDF2-HMAC-SHA256 派生
加密密钥与认证密钥；密文用 SHA256 计数器密钥流异或，附 HMAC-SHA256 校验。

盐（salt）在首次加密时随机生成并持久化到 QSettings（键 `cred_salt`），此后
所有加解密复用同一个盐。刻意 **不使用** 主机名/用户名/MAC 等运行时标识——
打包分发（Nuitka）后这些标识不稳定，会导致同一台机器加密、重启后解不开。

安全边界说明：这是「防明文直读」级别，不是强安全边界——应用内置 secret 与
随机盐都可从本地取得。任何纯本地、无系统钥匙串的方案都无法抵御「能读配置
文件 + 反编译」的攻击者，这里的目标只是不把密码明文写进 QSettings。
"""
import base64
import hashlib
import hmac
import os

# 应用内置 secret（本地混淆用；非密钥管理边界，可被反编译提取）
_APP_SECRET = (
    b"BITZH-Connect//local-credential//v1//"
    b"7f3a1c9e5b204d68a1f0c3e7d9b28465//"
    b"e2c5a8f14b6d9037af12c4e6b8d0573a"
)
_PREFIX = "enc2:"
# 旧格式（机器指纹派生）前缀：新版无法解密，仅用于识别与提示
_LEGACY_PREFIX = "enc1:"
_SALT_LEN = 32
_NONCE_LEN = 16
_TAG_LEN = 32
_PBKDF2_ITERS = 120_000


def generate_salt() -> str:
    """生成新的随机盐（base64 urlsafe 字符串，可直接存 QSettings）。"""
    return base64.urlsafe_b64encode(os.urandom(_SALT_LEN)).decode("ascii")


def _derive_keys(salt_b64: str) -> tuple[bytes, bytes]:
    """从持久化盐派生 (加密密钥, 认证密钥)。"""
    salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
    master = hashlib.pbkdf2_hmac(
        "sha256", _APP_SECRET, salt, _PBKDF2_ITERS, dklen=32
    )
    enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"mac", hashlib.sha256).digest()
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(enc_key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


def is_encrypted(value) -> bool:
    """是否为当前格式（enc2:）密文。"""
    return isinstance(value, str) and value.startswith(_PREFIX)


def is_legacy_encrypted(value) -> bool:
    """是否为旧格式（enc1:，机器指纹派生）密文——新版无法解密，仅供识别。"""
    return isinstance(value, str) and value.startswith(_LEGACY_PREFIX)


def encrypt_password(plaintext: str, salt_b64: str) -> str:
    """用给定盐加密为可存 QSettings 的字符串；空串原样返回空串。"""
    if not plaintext:
        return ""
    enc_key, mac_key = _derive_keys(salt_b64)
    nonce = os.urandom(_NONCE_LEN)
    data = plaintext.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return _PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def decrypt_password(token: str, salt_b64: str) -> str | None:
    """用给定盐解密；非本格式、缺盐、校验失败返回 None。"""
    if not is_encrypted(token) or not salt_b64:
        return None
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX):].encode("ascii"))
        if len(blob) < _NONCE_LEN + _TAG_LEN:
            return None
        nonce = blob[:_NONCE_LEN]
        tag = blob[_NONCE_LEN:_NONCE_LEN + _TAG_LEN]
        ct = blob[_NONCE_LEN + _TAG_LEN:]
        enc_key, mac_key = _derive_keys(salt_b64)
        expected = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return None
        data = bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))
        return data.decode("utf-8")
    except Exception:
        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_credential_crypto.py -q`
Expected: 部分通过、`load_credentials_detailed` 相关用例仍 FAIL（Task 3 实现）。此时允许失败项仅为 `test_legacy_enc1_password_reported_unreadable`、`test_enc2_without_salt_reported_unreadable`、`test_save_credentials_persists_salt_and_reuses_it`（依赖 Task 2/3）。

- [ ] **Step 5: 提交**

```bash
git add app/utils/credential_crypto.py tests/test_credential_crypto.py
git commit -m "refactor(credential): 加密盐改为持久化随机盐，弃用运行时机器指纹"
```

---

## Task 2: config_utils 增加 cred_salt 默认键

**Files:**
- Modify: `app/utils/config_utils.py:19-46`
- Test: `tests/test_credential_crypto.py`（Task 1 已覆盖）

- [ ] **Step 1: 在 `load_config()` 的 `default_config` 字典中新增键**

在 `"password": "",` 下一行插入：

```python
        "cred_salt": "",
```

修改后该片段为：

```python
    default_config = {
        "username": "",
        "password": "",
        "cred_salt": "",
        "remember": False,
```

- [ ] **Step 2: 运行测试确认不破坏现有用例**

Run: `.venv/bin/python -m pytest tests/test_credential_crypto.py -q`
Expected: 与 Task 1 Step 4 相同的通过集合，无新增失败（`load_config` 读取新增字符串键不影响 bool 转换分支）。

- [ ] **Step 3: 提交**

```bash
git add app/utils/config_utils.py
git commit -m "feat(config): 新增 cred_salt 配置键"
```

---

## Task 3: credential_utils 持久化盐与 detailed 读取

**Files:**
- Modify: `app/utils/credential_utils.py`
- Test: `tests/test_credential_crypto.py`（Task 1 已写）

- [ ] **Step 1: 重写 credential_utils.py**

把 `app/utils/credential_utils.py` **整个文件**替换为：

```python
from .config_utils import load_config, save_config
from .credential_crypto import (
    decrypt_password,
    encrypt_password,
    generate_salt,
    is_encrypted,
    is_legacy_encrypted,
)


def _ensure_salt(config) -> str:
    """取现有盐；没有则生成并写回 config（仅加密路径调用）。"""
    salt = config.get("cred_salt", "")
    if not salt:
        salt = generate_salt()
        config["cred_salt"] = salt
    return salt


def save_credentials(window):
    """按“记住密码”保存/清除凭据；密码用持久化盐加密后存 QSettings。"""
    config = load_config()
    remember = window.remember_cb.isChecked()
    config["remember"] = remember

    if remember:
        config["username"] = window.username_input.text()
        password = window.password_input.text()
        config["password"] = (
            encrypt_password(password, _ensure_salt(config)) if password else ""
        )
    else:
        config["username"] = ""
        config["password"] = ""

    save_config(config)


def load_credentials_detailed():
    """返回 (username, password, password_unreadable)。

    - 当前格式（enc2:）：用持久化盐解密，成功返回明文；
    - 旧格式（enc1:）/缺盐/校验失败：密码置空并标记 unreadable（调用方提示重输）；
    - 旧版明文：本次直接返回，并原地迁移为密文。
    """
    config = load_config()
    username = config.get("username", "")
    raw = config.get("password", "")

    if not raw:
        return username, "", False

    if is_encrypted(raw):
        salt = config.get("cred_salt", "")
        password = decrypt_password(raw, salt) if salt else None
        if password is None:
            return username, "", True
        return username, password, False

    if is_legacy_encrypted(raw):
        # 旧版机器指纹密文：换机/打包环境下已无法解密
        return username, "", True

    # 旧版明文（或旧钥匙串时代的回退明文）：本次使用并迁移为新格式
    password = raw
    config["password"] = encrypt_password(password, _ensure_salt(config))
    save_config(config)
    return username, password, False


def load_credentials():
    """返回 (username, password)；忽略"是否需要提示"标记（兼容旧调用）。"""
    username, password, _ = load_credentials_detailed()
    return username, password
```

- [ ] **Step 2: 运行测试确认全部通过**

Run: `.venv/bin/python -m pytest tests/test_credential_crypto.py -q`
Expected: 全部 PASS（含 Task 1 新增的持久化/迁移/不可解用例）。

- [ ] **Step 3: 提交**

```bash
git add app/utils/credential_utils.py
git commit -m "fix(credential): 盐持久化读写 + 旧密文标记不可读"
```

---

## Task 4: 主窗口提示旧密文需重输

**Files:**
- Modify: `app/views/main_window.py:167,195,324-327`
- Test: `tests/test_main_window.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_main_window.py` 末尾追加：

```python
def test_legacy_password_prompt_shown(qtbot):
    """读到旧版不可解密文：保留用户名、密码留空，并给一次重输提示。"""
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["username"] = "u1"
    config["password"] = "enc1:AAAABBBBCCCC"
    config["remember"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    text = w.output_text.toPlainText()
    assert "重新输入" in text
    assert w.username_input.text() == "u1"
    assert w.password_input.text() == ""
    w.reconnect_manager.cancel()


def test_no_prompt_when_no_saved_password(window):
    """没有保存过密码时不得误报提示。"""
    assert "重新输入" not in window.output_text.toPlainText()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_main_window.py::test_legacy_password_prompt_shown -q`
Expected: FAIL（当前 `load_credentials()` 不返回标记，主窗口也不会打提示）。

- [ ] **Step 3: 修改 main_window.py**

3a. 第 167 行的函数内导入改为：

```python
        from utils.credential_utils import load_credentials_detailed
```

3b. 第 195 行改为：

```python
        saved_username, saved_password, password_unreadable = load_credentials_detailed()
```

3c. 在 `self.output_text = QTextEdit(self)` 及其后两行（`setReadOnly`/`setVisible`）之后、`document().setMaximumBlockCount(5000)` 之前，插入：

```python
        if password_unreadable:
            self.output_text.append(
                "[BITZH Connect] 检测到旧版保存的密码已无法读取，请重新输入一次密码\n"
            )
```

即该段最终为：

```python
        self.output_text = QTextEdit(self)  # 隐藏日志缓冲：不进布局、永不显示
        self.output_text.setReadOnly(True)
        self.output_text.setVisible(False)
        if password_unreadable:
            self.output_text.append(
                "[BITZH Connect] 检测到旧版保存的密码已无法读取，请重新输入一次密码\n"
            )
        self.output_text.document().setMaximumBlockCount(5000)  # B9: 日志上限
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/views/main_window.py tests/test_main_window.py
git commit -m "feat(main-window): 旧版密码无法读取时提示重输"
```

---

## Task 5: 全量回归 + 真机验证

**Files:** 无代码改动

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS（无回归）。

- [ ] **Step 2: 真机验证（必须，不能只信单测）**

1. 用本项目源码启动：`source .venv/bin/activate && uv run app/main.py`（或按你的开发启动方式）。
2. 输入用户名/密码，**勾选"记住密码"**，点连接，连接成功后退出软件（完全退出，非隐藏）。
3. 重新启动软件，确认：**用户名和密码已自动填充**，无需重输。
4. 打开 `~/Library/Preferences/com.bitzh-connect.BITZH Connect.plist`（或对应源码运行的 plist），确认其中出现了 `cred_salt` 键、`password` 为 `enc2:` 开头。
5. 若旧配置里残留 `enc1:` 密文：首次启动应看到"检测到旧版保存的密码已无法读取，请重新输入一次密码"提示，用户名保留、密码为空；重输并保存后恢复正常。

- [ ] **Step 3: 无提交（验证任务）**

---

## 完成标准

- 勾选"记住密码"→ 完全退出 → 重启，密码自动填充（真机验证通过）。
- `enc2:` 加解密不依赖任何运行时机器标识（回归测试锁定）。
- 旧 `enc1:` 数据不崩溃、不误清用户名、给一次明确提示。
