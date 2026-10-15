<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="AI Usage Clock 应用图标" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>看见每个 AI 额度，掌握每次重置。</strong></p>

<p align="center">
  一个桌面小工具，把各家 AI 服务的用量上限集中在一处，<br />
  并抓取 Codex 和 Claude 的重置公告：提前预告时让你有心理准备，突然清零时也有地方可以查看原因。
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-TW.md">繁體中文</a> · <strong>简体中文</strong>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="测试状态" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="支持 Windows、macOS 和 Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 许可证" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="下载最新版本" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="Windows 上的 AI Usage Clock，显示 Claude 和 Codex 用量、Antigravity 额度，以及 Codex 和 Claude 的重置公告" width="520" />
</p>

<p align="center"><sub>Windows 悬浮小组件，截取自运行中的发行版。用量数值为截图时的状态。</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="紧凑模式：每项服务一颗胶囊" width="440" />
</p>

<p align="center"><sub>紧凑模式会把小组件缩成每项服务一颗胶囊（示例数据）。</sub></p>

## 为什么选 AI Usage Clock

- **你的 AI 额度，一个地方看完。** Claude、Codex、Antigravity、OpenCode Go、GitHub Copilot 和 OpenRouter 并排显示，每项各有一条用量条；进行中的额度，用量条旁还会标示剩余时间。
- **提前预告有准备，突然清零有原因。** 开启重置公告后，AI Usage Clock 会抓取 Codex 和 Claude 的重置公告。有些重置会提前预告（Codex 的预告，以及 AI 预测的 Watch 行），让你先有心理准备；有些来得很突然，磁贴会一直保留最新的公告，所以用量一下子清零时，你可以看一下是不是刚重置，并一键打开原始帖子。
- **新公告出现就通知你。** 可以选择在公告出现时发出通知（Windows 为原生通知），每种公告都能单独设置。公告来自独立的第三方追踪站，可能延迟或误判，请以原始帖子为准；这项功能默认关闭。
- **在你的电脑上运行。** 没有 AI Usage Clock 账号、服务器或遥测。API 密钥由操作系统的安全存储机制保管；Claude 和 ChatGPT 的登录会话除了存在那里，也存在程序自己的浏览器配置文件所在的文件夹。

## 三步上手

1. **下载**：到[最新版本](https://github.com/AIUsageClock/ai-usage-clock/releases/latest)下载对应系统的压缩包：`ai-usage-clock-<version>-windows.zip`、`ai-usage-clock-<version>-macos.tar.gz` 或 `ai-usage-clock-<version>-linux.tar.gz`。
2. **解压后运行。**
   - Windows：运行 `ai-usage-clock.exe`
   - macOS：把 `ai-usage-clock.app` 拖到“应用程序”文件夹，然后打开
   - Linux：运行 `./ai-usage-clock/ai-usage-clock`
3. **连上你的服务。** 在程序中登录 Claude 和 Codex，或在 **Settings** 中粘贴 API 密钥。详见[设置指南](docs/setup.zh-CN.md)。

发行版本尚未签名，第一次启动时 Windows 或 macOS 可能会弹出警告，[处理方式在这里](#首次启动时出现-smartscreen-或-gatekeeper-警告)。

## 支持的服务

| 服务 | 你会看到什么 | 连接方式 |
| --- | --- | --- |
| **Claude** | Session 和 Weekly 额度（方案有每周 Fable 额度时一并显示） | 通过浏览器登录（支持 Google 和通行密钥 passkey），或粘贴会话 Cookie |
| **Codex**（ChatGPT） | Session 和 Weekly 额度 | 同 Claude |
| **Antigravity** | Gemini 和 Claude+GPT 两组，各有 5 小时和每周额度 | 读取本地的 `agy` 命令行工具，程序内不需要账号或密钥 |
| **OpenCode Go** | Rolling、Weekly 和 Monthly 用量 | OpenCode API 密钥 |
| **GitHub Copilot** | 本月已用的 AI 积分，相对于方案内含额度，每月 1 日重置 | fine-grained GitHub 个人访问令牌（PAT） |
| **OpenRouter** | 今日和本月花费、可选的每日预算；加上管理密钥还能看余额和各模型用量 | OpenRouter API 密钥 |

Claude、Codex 和 GitHub Copilot 默认启用；其他服务和重置公告需要在 **Settings** 中开启。Claude、Codex 和 OpenCode Go 都可以同时跟踪多个账号。

## 给 AI 代理用（MCP）

AI Usage Clock 内置可选的本地 MCP 服务器，默认关闭。它让写代码用的 AI 代理在开始消耗额度的工作之前，先查询你的用量，并在达到你设定的上限时暂停。它只读取已去除敏感信息的本地用量缓存，不会获取你的凭据。设置方式见 [docs/mcp.md](docs/mcp.md)（英文）。

## 常见问题

### 重置公告是怎么运作的？

默认关闭。到 **Settings → General** 勾选 **Codex Resets** 或 **Claude Resets** 即可开启。AI Usage Clock 会从两个独立的第三方追踪站获取数据：codex-resets.com（用 AI 对 @thsottiaux 的帖子分类）和 claude-resets.com（汇总 @ClaudeDevs 和 Claude Code 团队成员的帖子），程序运行期间，每个站最多每 15 分钟查询一次，重新启动时会再查一次。

磁贴会显示最新一条事件以及它发生至今的时间，并标明类型：

- **Announced**（预告）：重置提前宣布。目前只有 Codex 有这一类。
- **Reset**（已重置）：额度已经补满。
- **Banked**（重置额度）：你获得了一次可以自行兑换的重置额度。

Codex 的磁贴另有一行 **Watch**，是 AI 预测的重置可能性，不是官方公告，也不会发通知。点击 ↗ 可打开原始帖子，点击 ✕ 可先隐藏，等下一条出现再显示。

在 **Settings → Reset alerts** 可以选择哪些类型要通知（Codex：预告、已重置、重置额度；Claude：已重置、重置额度）。程序第一次从某个追踪站发现的事件只会记录，不会通知。Windows 使用原生通知，点一下就会打开原始帖子；其他系统在有系统托盘时改用系统托盘气泡通知；macOS 菜单栏模式和没有系统托盘的 Linux 不会弹出通知，但磁贴仍会更新。

这些数据由第三方汇总，可能延迟或误判（Claude 的新条目最长 24 小时内可能是暂定的），请以原始帖子为准。

### 这是官方应用吗？

不是。AI Usage Clock 是独立的开源项目，属于非官方的本地桌面小工具，与它所显示的各项服务均无关联，也未经这些服务认可。各服务的页面和 API 可能随时变更。

### 我的数据会发到哪里？

你的设置、用量历史和登录会话都留在你的电脑上。会话和 API 密钥存放在操作系统提供的安全存储机制中：Windows 的凭据管理器和 DPAPI、macOS 的钥匙串、Linux 的 Secret Service。Claude 和 ChatGPT 的会话另外也存在程序自己的浏览器配置文件所在的文件夹。没有遥测，也没有 AI Usage Clock 的服务器。程序只会直接连接你开启的服务：Claude 和 ChatGPT 的用量页面（在内置浏览器中加载），以及 GitHub、OpenCode 和 OpenRouter 的 API。Antigravity 的用量则是由程序运行你电脑上的 `agy` 工具获取，`agy` 自己负责它的连接。如果开启重置公告，还会连接 codex-resets.com 和 claude-resets.com，对方能看到你的 IP 地址，以及程序名称和版本。可选的本地费用统计会读取你电脑上的 Claude Code 和 Codex 日志文件，不会上传任何内容。详见 [SECURITY.md](SECURITY.md)（英文）。

### 首次启动时出现 SmartScreen 或 Gatekeeper 警告

发行版本尚未经过代码签名，每个压缩包旁都附有 SHA256 哈希值可供核对。

- **Windows：** 如果 SmartScreen 弹出警告，点击 **More info**，再点击 **Run anyway**。
- **macOS：** Gatekeeper 第一次会拦下这个 App。先尝试打开一次，再到“系统设置”→“隐私与安全”，在“安全性”中找到它并点按“打开”，接着点按“仍要打开”，输入登录密码后点按“好”（“仍要打开”按钮在尝试打开后约一小时内可用）。你也可以改为运行一次 `xattr -dr com.apple.quarantine ai-usage-clock.app`。
- **Linux：** 没有签名机制。如果 `ai-usage-clock` 还没有执行权限，请先加上。

更多细节（包括 macOS 上的 MCP 辅助程序）见 [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds)（英文）。

### 需要安装 Python 吗？

下载版不需要：Python 和浏览器引擎都已经内置。只有从源码运行或参与开发时，才需要 Python 3.11 及以上版本，见 [docs/build.md](docs/build.md)（英文）。

### macOS 和 Linux 也能用吗？

可以，但有个前提。Windows 是主要的开发平台，也是用真实账号测试过的平台。macOS（用菜单栏项代替悬浮小组件）和 Linux 版本也有发布，自动化测试在三个系统上都会运行，但用真实账号刷新用量，目前只在 Windows 11 上验证过，所以请把 macOS 和 Linux 视为早期阶段。重置通知在各系统上的差异见前面。遇到问题欢迎[提交 issue](https://github.com/AIUsageClock/ai-usage-clock/issues) 反馈。

### 免费吗？

免费，以 MIT 许可证开源。你所查看的各项服务仍需要各自的账号或订阅。

## 更多信息

[设置指南](docs/setup.zh-CN.md) · [日常使用](docs/usage.zh-CN.md) · [MCP 用量防护](docs/mcp.md)（英文） · [从源码构建](docs/build.md)（英文） · [参与贡献](CONTRIBUTING.md) · [安全](SECURITY.md) · [许可证（MIT）](LICENSE)

当前版本：**1.0.0** · [更新日志](CHANGELOG.md)

AI Usage Clock 与 Anthropic、OpenAI、Google、GitHub、Microsoft、OpenCode、OpenRouter 或任何其他服务提供商均无关联。产品名称归各自的所有者所有。
