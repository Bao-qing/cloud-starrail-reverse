# Cloud StarRail Reverse 🌸

一个基于 Python 的云游戏连接实验项目，用于研究《崩坏：星穹铁道》米哈游云游戏 Web 端的调度、WebSocket 信令、WebRTC 媒体流、输入通道和 SDK 回调流程。项目当前提供 Tkinter 图形界面、可脚本化 demo，以及拆分后的 `core` 运行库。

## 目录
- [✨ 功能概览](#-功能概览)
- [🚀 快速开始](#-快速开始)
- [🖥️ TK GUI 使用方法](#️-tk-gui-使用方法)
- [🧪 Demo 运行](#-demo-运行)
- [🧭 获取cookies](#获取cookies)
	  - [安全提醒 ⚠️⚠️⚠️](#安全提醒-️️️)
- [⚙️ client_profile.json 配置说明](#️-client_profilejson-配置说明)
	  - [`session_profile` （通常只需要改这个）](#session_profile-通常只需要改这个)
	  - [可选配置示例](#可选配置示例)
- [📦 作为库使用](#-作为库使用)
- [🧱 代码结构](#-代码结构)
- [⚠️ 免责声明](#️-免责声明)

> ⚠️ 本项目仅用于协议学习、个人研究和本地实验。请先阅读文末免责声明。

## ✨ 功能概览

### 已实现

- 🔑 扫码登录：通行证 SDK 二维码登录、cookie 探活，自动维护 `credentials.json`
- 🚀 调度云游戏实例：网页登录同步、节点选择、排队、获取 `finish_result` （游戏主机连接凭证）
- 🎮 连接云游戏会话：WebSocket 信令 + WebRTC 音视频流
- 🖱️ 输入转发：鼠标、键盘、滚轮、IME 文本、剪贴板
- 🖼️ 视频帧预览与截图：GUI 实时预览，demo 可按需保存 JPEG
- 📊 查询账号信息：剩余时长、免费队列/星云币队列预估

### 未实现

- 🔊 音频捕获：对 WebRTC 媒体流中音频轨道的提取、解码播放及本地录制

### 已知问题

-  偶现连接游戏服务器无响应，可以重连解决，原因目前未知

## 🚀 快速开始

###  环境要求

- Python 3.11+，当前开发环境为 Python 3.12
- Linux 环境下 Tkinter GUI 需要系统手动安装 `python3-tk` 等包；Windows 和 macOS 通常在安装 Python 时默认已内置 Tkinter，一般无需额外安装
- 可访问米哈游相关云游戏接口的网络环境
- 有效的登录 Cookie

安装系统 Tkinter（Linux / Debian / Ubuntu 示例）：

```bash
sudo apt install python3-tk
```
### 1. 创建虚拟环境

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Windows (CMD):

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖包括：

- `aiortc`：WebRTC 连接和媒体轨道处理
- `websockets`：异步 WebSocket 客户端
- `cryptography`：SDK game-data AES 加解密
- `requests`：HTTP 调度和账号同步
- `pillow`：视频帧转图片、GUI 显示和截图保存

### 3. 配置凭据

最快的路径：

```bash
python qrcode_login.py login   # 终端 + log/ 目录显示二维码，米游社 App 扫一下即可
```

二维码确认后，脚本会写出项目根目录的 `credentials.json`。文件已在 `.gitignore`，不要提交、不要发给他人。

也可以**跳过这一步**直接 `python demo.py`：示例代码里前置了 `cloud_game.ensure_login(auto_login=True)`，缺失或失效时会自动唤起同一套扫码流程。GUI（`python ui.py`）会在需要登录时弹出二维码窗口，扫码确认后自动写回 `credentials.json`。

如果需要走传统路径（比如机器没法扫码），可以从浏览器 DevTools 里手动复制 cookie 写入 `credentials.json`，详见下文 [获取 cookies](#获取cookies) 一节。校验当前凭据是否有效：

```bash
python qrcode_login.py check
```

### 4. 可选：调整客户端画像

`client_profile.json` 会覆盖 `core.config.DEFAULT_CORE_CONFIG` 中的默认配置。可调整：

- `device_profile`：设备 ID、系统、CPU、GPU、屏幕、DPI
- `browser_profile`：User-Agent、Sec-CH-UA、App 版本
- `protocol_profile`：SDK WebView UA、客户端库标识
- `session_profile`：分辨率、FPS、码率、画质模式、码率倍率

如果不需要定制，可以保留现有文件。

### 5. 运行

三种入口任选：

```bash
python qrcode_login.py login   # 仅扫码登录 / 刷新 credentials.json
python ui.py                   # Tkinter GUI: 视频预览 + 输入 + 调度按钮
python demo.py                 # 命令行示例: 截图、输入、兑换码等
```

`ui.py` 和 `demo.py` 都内置了登录态校验，详见 [🖥️ TK GUI 使用方法](#️-tk-gui-使用方法) 与 [🧪 Demo 运行](#-demo-运行)。要把核心库嵌进自己的代码，参考 [📦 作为库使用](#-作为库使用)。

## 🖥️ TK GUI 使用方法

请先打开虚拟环境...

启动图形界面：

```bash
python ui.py
```

最大化一下显示完全。

界面顶部包含：
- `finish_result`：调度结果保存/读取路径，默认 `finish_result.json`
- `seconds`：连接持续时间，`0` 表示不主动限时
- `payload limit`：WebSocket 日志载荷显示长度
- `队列`：选择免费队列或星云币队列
- `Dispatch + Start`：调度并立即连接
- `Dispatch Only`：只执行调度并保存 `finish_result`
- `Connect Only`：读取已有 `finish_result` 并连接
- `Stop`：请求停止当前流程
- `Auto Click`：输入可用后每秒点击画面中心，维持连接活跃
- 鼠标位置（归一化坐标）

GUI 左侧显示视频画面，右侧显示 WebSocket 和输入日志。点击画面后可直接发送鼠标和键盘输入。底部输入框支持：
- `Send`：发送 IME 文本
- `Sync`：读取本机剪贴板并同步到远端剪贴板
- `Paste`：向远端发送 Ctrl+V

每次按下 `Login` / `Dispatch + Start` / `Dispatch Only` / `Connect Only`，GUI 都会重新读 `credentials.json` 并跑一次 `webVerifyForGame` 探活。Cookie 缺失或失效时会弹出二维码窗口，请用米游社或云·星穹铁道移动端扫码并在手机上确认；确认后会自动更新 `credentials.json` 并继续当前流程。

## 🧪 Demo 运行

`demo.py` 提供多个异步示例。每个示例在创建 `CloudGame` 之后都会先调用一次 `authenticate(cloud_game)` —— 它包了一层 `cloud_game.ensure_login(auto_login=True)`，会从 `credentials.json` 读取并探活 cookie，缺失/失效时直接在终端弹出二维码登录。所以**首次运行无需任何手动准备**，直接：

```bash
python demo.py
```

如果跑在没有交互终端的环境（CI、容器），把 demo 里 `authenticate` 的 `auto_login` 改成 `False`，cookie 失效时会抛清晰错误而不是阻塞等扫码。

当前入口在文件底部：

```python
if __name__ == "__main__":
    queue_type = QUEUE_TYPE_COIN # QUEUE_TYPE_NORMAL
    asyncio.run(redeem_code_demo())
```

切换 demo 时，注释/取消注释对应行：

- `account_info()`：查询剩余时长和免费/星云币队列预估
- `snapshot_interval()`：连接后按固定间隔自动保存截图
- `snapshot_manual()`：连接后手动等待下一帧并保存截图
- `input_demo()`：进入游戏、中心点击、打开背包和菜单并截图
- `redeem_code_demo()`：进入游戏、打开兑换码入口、输入示例兑换码并逐步截图

示例截图会写入当前目录，例如：

```text
input_demo_01_before_enter.jpg
redeem_demo_03_menu_open.jpg
manual_frame_<timestamp>_f000001.jpg
```

注意：`input_demo()` 和 `redeem_code_demo()` 会真实发送点击、按键和文本输入。运行前确认当前账号、队列类型和脚本坐标符合你的预期。

## 🧭获取cookies

本项目需要浏览器登录态 Cookie 才能调用云游戏接口。请只提取你自己账号的 Cookie，并妥善保存 credentials.json，不要提交到 Git，也不要发给他人。

### 推荐方式 1：扫码登录（最省事）

程序会自动调起扫码登录，如果仅登录：

```bash
python qrcode_login.py login
```

脚本会调用米哈游通行证 SDK 的 `createQRLogin` 接口，把二维码同时打印到终端、保存到 `log/qrcode_<时间戳>.png`，再轮询 `queryQRLoginStatus` 直到「米游社」App 扫码确认，最后追加一次 `webVerifyForGame` 刷新 cookie，并写出 `credentials.json`。

常用参数：

```bash
python qrcode_login.py login --no-terminal       # 不在终端打印二维码（只保存 PNG）
python qrcode_login.py login --no-png            # 只在终端打印（无 PNG 落盘）
python qrcode_login.py login --light-terminal    # 浅色终端反色还原
python qrcode_login.py login --output other.json # 写到其他路径
```

校验当前 cookie 是否仍然有效：

```bash
python qrcode_login.py check          # 退出码 0 = 有效；输出 aid/mid/mobile
python qrcode_login.py check --json   # 适合脚本调用
```

代码层面的等价用法 (`Authenticator` / `CloudGame.ensure_login` / `CloudGame.login`) 详见下文 [📦 作为库使用](#-作为库使用) 章节。

### 推荐方式 2：从 Network 请求复制（旧路径）

由于部分关键 Cookie 是 HttpOnly，网页脚本无法通过 document.cookie 读取。也可以直接从浏览器实际发送的请求里复制完整 Cookie。
1. 使用浏览器打开云游戏网页并登录账号。
2. 按 F12 打开 DevTools。
3. 切到 Network 面板。
4. 刷新页面，点击进入云游戏，让页面产生登录/调度请求。
5. 找下面任意一个请求：
  - webVerifyForGame
  - webLogin
  - wallet/get
  - statusCheck
  - 或者任何一个cookies包含 cookie_token_v2 的

1. 点开该请求，进入 Headers。
2. 在 Request Headers 中找到 cookie:。
3. 复制 cookie: 后面的完整内容。注意要复制全，同时不要复制到下一个字段，成功的复制一般不换行，如果有换行检查是否复制了下一个字段，如果没有就手动删去换行
4. 在项目根目录创建或更新 credentials.json：

```json
{
	"cookie": "这里粘贴完整 Cookie 字符串"
}
```

### 检查 Cookie 是否完整

推荐用上节的 `python qrcode_login.py check`，会真的跑一次 `webVerifyForGame` 探活并打印 aid/mid/mobile。

仓库里另外还保留了一个纯字段检查脚本 `check_cookies.py`，只看 `cookie_token_v2`、`ltoken_v2` 等必需字段是否齐全，不发任何网络请求：

```bash
python check_cookies.py
```

如果输出提示缺少 cookie_token_v2、ltoken_v2 等字段，说明 Cookie 不完整。常见原因是使用了 document.cookie，它会漏掉 HttpOnly 字段。请改用扫码登录或 DevTools 的 Network 请求复制完整 Cookie。

### 不推荐：控制台 document.cookie

不要依赖下面这种方式：

document.cookie

它只能读取当前页面可见、非 HttpOnly 的 Cookie。浏览器请求里实际会发送的登录 Cookie，网页脚本不一定能读到。因此用它生成的 credentials.json 可能会提示登录态失效。

### 安全提醒 ⚠️⚠️⚠️

- credentials.json 等同于账号登录凭据，请不要公开。
- 如果 Cookie 泄露⚠️，立即退出登录并重新登录刷新凭据，必要时进入米哈游通行证踢出设备
-  任何拥有云游戏cookies的人都可以直接进入游戏，对账号进行任意操作，包括任意毁号，请务必务必保管好

## ⚙️ client_profile.json 配置说明

`client_profile.json` 是运行时客户端画像文件，GUI 默认会读取它，`demo.py` 中也预留了 `load_core_config()` 的接入方式。

配置会按字段深度合并到 `DEFAULT_CORE_CONFIG`：只写需要覆盖的字段即可，未写字段继续使用默认值。

### `device_profile`

描述调度阶段和协议上报使用的设备信息。一般不需要动，除非你知道自己在做什么。

| 字段 | 说明 |
| --- | --- |
| `device_id` | 设备 ID。调度请求会优先使用 Cookie 中的 `_MHYUUID`，缺失时使用这里的值。 |
| `os` / `sys_version` | 操作系统描述，分别用于设备信息和调度请求头。 |
| `model` / `device_name` | 设备型号和设备名。 |
| `cpu_cores` / `cpu_freq` / `cpu_type` | CPU 核心数、频率和类型。 |
| `memory_gb` / `soc` / `gpu_model` | 内存、SoC 和 GPU 描述。 |
| `screen_width` / `screen_height` | 上报屏幕尺寸，也影响部分设备信息字段。 |
| `dpi` | 调度 `user_data` 中的 DPI。 |

### `browser_profile`

描述 Web 端浏览器特征，主要用于 HTTP 请求头。

| 字段 | 说明 |
| --- | --- |
| `user_agent` | 调度、网页登录、WebSocket 控制通道使用的 User-Agent。 |
| `sec_ch_ua` | `sec-ch-ua` 请求头。 |
| `app_version` | 调度接口中的客户端版本。 |
| `web_device_name` | 网页登录请求头中的设备名，通常为浏览器名。 |
| `web_device_model` | 网页登录请求头中的设备型号，当前示例使用 URL 编码形式。 |
| `web_device_os` | 网页登录请求头中的系统描述，当前示例使用 URL 编码形式。 |

### `protocol_profile`

描述 SDK/协议层上报的客户端信息。

| 字段 | 说明 |
| --- | --- |
| `client_lib` | `SdkDeviceInfo` 中的客户端库标识，默认 `python-aiortc`。 |
| `sdk_webview_ua` | SDK `webview.get_global_user_agent` 回调返回的 UA。 |

### `session_profile` （通常只需要改这个）

描述云游戏会话启动参数。

连接 WebRTC 后客户端会向云端发送
graphics_mode，同时发送 bitrate_multiplier 作为码率倍率。按官方网页逻辑，只有高画质档会使用较高的 bitrate_multiplier，省流和极致省流都会把倍率设为 1；极致省流还会把帧率限制为 30。
高画质使用 graphics_mode: 0、bitrate_multiplier: 1.875；
省流使用 graphics_mode: 1、bitrate_multiplier: 1.0；
极致省流使用 graphics_mode: 2、bitrate_multiplier: 1.0

| 字段 | 说明 | 常见/可选值                                                                                                           |
| --- | --- |------------------------------------------------------------------------------------------------------------------|
| `graphics_mode` | 启动后发送的画质模式。 | 0 = kHighQuality：高画质 / 超高清;1 = kTrafficSaving：省流画质 / 标清，约 0.35GB/15分钟;2 = kExtremeSaving：极致省流 / 低清，约 0.17GB/15分钟 |
| `bitrate_multiplier` | 启动后发送的码率倍率。 | 官方极致画质对应 1.875，只在最高画质生效，其他都默认1                                                                                   |
| `resolution` | 调度请求中的目标分辨率。 | 常用 `1280x720、1920x1080、2560x1440` 太怪的可能会被服务器忽略                                                                   |
| `fps` | 调度请求中的目标帧率。 | 常用 `30` ，不知传60行不行，大概最高就30了                                                                                       |
| `bit_rate` | 调度请求中的目标码率，单位为 bit/s。 | 初始码率请求，后续码率由服务器决定                                                                                                |

最小覆盖示例：

```json
{
  "session_profile": {
    "resolution": "1920x1080",
    "fps": 30
  }
}
```

修改建议：

- 保持 `resolution` 与 GUI 默认游戏画面比例一致，避免输入坐标换算偏移。
- `bit_rate` 过高可能增加网络压力，过低会降低画质。
- `device_id`、UA、版本号等画像字段会影响调度和网页登录兼容性；接口变更时优先检查这些字段。
- 不要把真实账号标识、Cookie、token 写入 `client_profile.json`。

### 可选配置示例

低带宽/更稳优先：

```json
{
  "session_profile": {
    "resolution": "1280x720",
    "fps": 30,
    "bit_rate": 3000000,
    "bitrate_multiplier": 1.25
  }
}
```

高清/画质优先：

```json
{
  "session_profile": {
    "resolution": "1920x1080",
    "fps": 60,
    "bit_rate": 10000000,
    "bitrate_multiplier": 1.875
  }
}
```

只覆盖浏览器版本：

```json
{
  "browser_profile": {
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "sec_ch_ua": "\"Not:A-Brand\";v=\"99\", \"Google Chrome\";v=\"146\", \"Chromium\";v=\"146\"",
    "app_version": "4.3.1",
    "web_device_model": "Chrome%20146.0.0.0"
  },
  "protocol_profile": {
    "sdk_webview_ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
  }
}
```

只覆盖设备画像：

```json
{
  "device_profile": {
    "device_id": "a1b2c3d4-0000-4000-8000-000000000000",
    "os": "Linux 6.12.65",
    "model": "XPS 15 9520",
    "device_name": "XPS-15-9520",
    "gpu_model": "Intel Iris Xe Graphics",
    "screen_width": 1920,
    "screen_height": 1080
  }
}
```

最小默认配置可以只保留一个空对象，完全使用默认配置：

```json
{}
```

也可以删除 `client_profile.json`，此时程序会使用 `core.config.DEFAULT_CORE_CONFIG` 中的内置默认值。


## 📦 作为库使用

`core` 包主要对外导出 `CloudGame`、`CloudGameConfig`、队列常量和日志工具。登录凭据在公开 API 里直接使用单行 Cookie 字符串；`combo_token`、`channel_token`、`sdk_login` 都是 `CloudGame.account` 里的运行时派生态，不需要也不应该由调用方保存或传入。
- 如果外部已有 cookie，可以通过 `CloudGame(cookie=...)` 直接传入。
- `cookie=None` 表示外部没有提供 cookie；`cookie=""` 会被当作外部显式提供的 Cookie 字符串继续参与校验。
- `load_credentials(path)` 同时记住路径，`ensure_login(auto_login=True)` 触发扫码登录后会自动写回到该路径；不需要外部再保存一次。

### 在 CloudGame 里前置认证：`load_credentials` / `ensure_login` / `login`

`CloudGame.ensure_login(auto_login=...)` 会：

1. 使用 `cloud_game.account.cookie`（由构造时的 `cookie=` 或 `load_credentials` 写入）；`None` 表示没有 cookie，空字符串会按真实 cookie 校验；
2. 跑 `webVerifyForGame` 探活；
3. 缺失或失效时根据 `auto_login`：
   - `True`  → 调用内部登录封装启动扫码登录，新 cookie 应用到 `cloud_game`；如果之前调用过 `load_credentials(path)`，还会写回该 JSON 文件；
   - `False` → 抛 `RuntimeError`，由调用方决定如何引导用户重登；
4. 成功时把 cookie 应用到 `cloud_game.account` 并重建内部 `Dispatcher`。

```python
from core import CloudGame

cg = CloudGame(qr_dir="log")
cg.load_credentials("credentials.json")    # 读 cookie 并记住写回路径
cg.ensure_login(auto_login=True)           # 失效时自动扫码并写回 credentials.json
```

也可以直接传 cookie，不读盘：

```python
cg = CloudGame(cookie=external_cookie)
cg.ensure_login(auto_login=False)          # 失效返回None，由调用方处理
```

强制重新扫码：

```python
cg.login(timeout=180)
```

完成认证后，`cloud_game.dispatch()` / `cloud_game.connect()` / `cloud_game.run()` 都会用最新 cookie。

### 多账号 / 自定义路径

多账号时让每个 `CloudGame` 实例 `load_credentials` 不同 JSON：

```python
cg = CloudGame(qr_dir="accounts/qr/")
cg.load_credentials("accounts/alice.json")
cg.ensure_login(auto_login=False)
```

### 完整端到端示例

```python
import asyncio

from core import CloudGame, QUEUE_TYPE_NORMAL
from core.models import CloudGameConfig


async def main() -> None:
    cg = CloudGame(
        config=CloudGameConfig(queue_type=QUEUE_TYPE_NORMAL),
        qr_dir="log",
    )
    cg.load_credentials("credentials.json")              # 1. 读 cookie + 记住路径
    cg.ensure_login(auto_login=True)                     # 2. 探活 / 必要时扫码
    finish_result = await asyncio.to_thread(cg.dispatch) # 3. 排队 + 拿 finish_result
    await cg.connect(finish_result=finish_result)        # 4. WebSocket + WebRTC


asyncio.run(main())
```

仅查询账号信息（不进入游戏）：

```python
import asyncio
from core import CloudGame


async def main() -> None:
    cg = CloudGame()
    cg.load_credentials("credentials.json")
    cg.ensure_login(auto_login=True)
    wallet = await asyncio.to_thread(cg.get_wallet_info)
    summary = wallet.get("summary") or {}
    print("剩余免费时长:", summary.get("free_time_minutes"), "分钟")


asyncio.run(main())
```


## 🧱 代码结构

```text
.
├── ui.py                       # Tkinter GUI，视频预览、输入绑定、调度/连接按钮
├── demo.py                     # CLI/脚本示例：账号、截图、输入、兑换码流程
├── qrcode_login.py             # 通行证 SDK 扫码登录 / cookie 探活 CLI
├── check_cookies.py            # 纯字段检查脚本，不发网络请求
├── client_profile.json         # 客户端画像覆盖配置
├── credentials.json.example    # Cookie 配置模板
├── requirements.txt            # Python 依赖
└── core/
    ├── __init__.py             # 对外导出 CloudGame、队列常量、日志工具
    ├── cloud_game.py           # 高层门面：串联 dispatch、session 与登录态管理
    ├── auth.py                 # 通行证 SDK 常量、cookie 工具与 Authenticator
    ├── dispatcher.py           # HTTP 账号同步、钱包、队列预估、实例调度
    ├── session.py              # WebSocket/WebRTC 生命周期、输入、SDK 回调、视频帧
    ├── protocol.py             # 二进制协议、帧封装、输入编码、AES、ICE candidate
    ├── models.py               # CloudGameConfig、InputAction 等数据模型
    ├── config.py               # 默认画像、JSON 注释剥离、CoreConfig 合并逻辑
    └── log.py                  # 项目 logger 和回调兼容工具
```

核心调用链：

```text
ui.py / demo.py / qrcode_login.py
    -> CloudGame
        -> Authenticator.check() / .login_qrcode()    # 仅在 ensure_login()/login() 时触达
        -> Dispatcher.init() / wallet_info() / queue_estimate() / run()
        -> GameSession.run()
            -> Protocol.* 编解码
            -> GameControlChannel 或 RTC DataChannel 发送输入
```

`Authenticator` 与 `Dispatcher` 是**完全解耦**的两条 HTTP 链路：前者负责通行证账号生命周期（扫码登录 / cookie 探活），后者负责调度阶段的账号同步与排队。两者只共享 `core/auth.py` 顶部的纯工具函数与端点常量。

## ⚠️ 免责声明

本项目仅用于学习和研究网络协议、WebRTC、Python 编程与自动化。使用者应自行确保行为符合平台服务条款和账号使用规范。因使用本项目造成的账号风险、资产损失、服务限制、网络费用或其他后果，均由使用者自行承担。

请勿将本项目用于商业用途、批量自动化、绕过限制、破坏服务、侵犯他人权益或任何未授权行为。请勿公开传播 Cookie、token、调度结果、账号截图等敏感信息。
