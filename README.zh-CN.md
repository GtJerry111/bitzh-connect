<div align="center">

# HITSZ Connect Verge

[中文](README.zh-CN.md) | [English](README.md)

![Action](https://github.com/kowyo/hitsz-connect-verge/actions/workflows/release.yml/badge.svg)
![Release](https://img.shields.io/github/v/release/kowyo/hitsz-connect-verge)
![Downloads](https://img.shields.io/github/downloads/kowyo/hitsz-connect-verge/total)
![License](https://img.shields.io/github/license/kowyo/hitsz-connect-verge)
![License](https://img.shields.io/github/stars/kowyo/hitsz-connect-verge)

</div>

## 简介

HITSZ Connect Verge 是 [ZJU Connect](https://github.com/Mythologyli/zju-connect) 的图形用户界面（GUI）。它可以帮助你远程连接到哈尔滨工业大学（深圳）的校园网络。

## 功能特点

- 与 **EasyConnect** 相比，无需安装便可使用，移除后也不会将任何纪录（[注册表](https://zh.wikipedia.org/wiki/注册表)消息等）留在本机电脑上。
- 简化的用户界面和 Fluent UI（仅限 Windows）。
- 使用 PySide6 和 Python 构建，易于初学者贡献和维护。
- 支持多平台，提供开箱即用的体验，无需执行额外的脚本。
- 高级设置（即将推出）。

## 安装

你可以通过两种方式安装 HITSZ Connect Verge：下载预构建的二进制文件或从源代码构建。

> [!NOTE]
>
> 1. 用户名和密码与你在[统一身份认证平台](https://ids.hit.edu.cn)上登录时使用的相同。
> 2. 如果下载速度较慢，你可以尝试使用 [GitHub 文件加速代理](https://gh-proxy.com) 下载。

### 方法一：下载预构建的二进制文件

HITSZ Connect Verge 提供开箱即用的体验。你可以从[发布页面](https://github.com/kowyo/hitsz-connect-verge/releases/latest)下载最新版本。

> [!IMPORTANT]
> 对于 macOS 版本，你需要通过运行以下命令授予应用程序访问权限：
>
> ```bash
> sudo xattr -rd com.apple.quarantine hitsz-connect-verge.app
> ```
>
> 在某些情况下，你需要前往 macOS 的 `设置` -> `系统偏好设置` -> `安全性与隐私` -> `仍要打开`。

### 方法二：从源代码构建

1. 克隆仓库：

    ```bash
    git clone https://github.com/kowyo/hitsz-connect-verge.git
    cd hitsz-connect-verge
    ```

2. 安装依赖：

    强烈建议使用虚拟环境。你可以通过以下命令创建虚拟环境：

    ```bash
    python -m venv venv
    source venv/bin/activate # 激活虚拟环境
    ```

    然后，安装依赖：

    ```bash
    pip install -r requirements.txt
    ```

3. 运行应用程序：

    ```bash
    python main.py
    ```

4. （可选）构建二进制文件：

    你可以通过以下命令为 Windows 构建二进制文件：

    ```bash
    pyinstaller --clean --onefile --noconsole `
    --icon assets/Graphicloads-Colorful-Long-Shadow-Cloud.ico `
    --add-data "assets;assets" `
    --add-data "core/zju-connect;core" `
    -n hitsz-connect-verge main.py
    ```

    对于 macOS/Linux，你可以运行以下命令：

    ```bash
    pyinstaller --clean --onefile --noconsole --windowed \
    --icon assets/Graphicloads-Colorful-Long-Shadow-Cloud.icns \
    --add-data "assets:assets" \
    --add-data "core/zju-connect:core" \
    -n hitsz-connect-verge main.py
    ```

## 截图

|   Windows   |   Mac   |  Linux   |
| ---- | ---- | ---- |
|  <img width="412" alt="windows" src="https://github.com/user-attachments/assets/ebb28817-0adb-45fc-84ae-d849ba2193a6" />   | <img width="412" alt="mac" src="assets/mac.png" />  | <img width="412" alt="linux" src="assets/linux.png" />  |

目前，Linux 版本仅支持从源代码构建。

## 贡献

欢迎贡献！你可以随时提交问题或拉取请求。对于重大更改，请先提交问题以讨论你想要更改的内容。

此外，欢迎修复任何拼写错误。

## 相关项目

- [chenx-dust/HITsz-Connect-for-Windows](https://github.com/chenx-dust/HITsz-Connect-for-Windows): HITsz 版的 ZJU-Connect-for-Windows。支持高级设置和多平台。
- [Co-ding-Man/hitsz-connect-for-windows](https://github.com/Co-ding-Man/hitsz-connect-for-windows): 开箱即用的 zju-connect 简单 GUI，适用于 HITSZ。
