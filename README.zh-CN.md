<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="AI Usage Clock 图标" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>看见每个 AI 额度，掌握每次重置。</strong></p>

<p align="center">
  AI 服务用得一多，额度就散在各家；Codex 和 Claude 的重置，有的提前预告，有的说来就来。<br />
  AI Usage Clock 把各家额度收进桌面上的一个小组件，并抓取这两家的重置公告：<br />
  有预告可以早做准备，用量突然清零也能查查是不是刚重置过。
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-TW.md">繁體中文</a> · <strong>简体中文</strong> · <a href="README.ja.md">日本語</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="测试状态" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="支持 Windows、macOS、Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 许可证" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="下载最新版" /></a>
  <a href="https://aiusageclock.com/zh-cn/"><img src="https://img.shields.io/badge/Website-aiusageclock.com-c2410c?style=for-the-badge" alt="访问官网" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="Windows 上的 AI Usage Clock：Claude 和 Codex 的用量、Antigravity 额度，以及 Codex 和 Claude 的重置公告" width="520" />
</p>

<p align="center"><sub>Windows 小组件，截自实际运行的发布版；图中用量是截图当时的数值。</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="紧凑模式：每个服务缩成一个胶囊" width="440" />
</p>

<p align="center"><sub>紧凑模式下，每个服务缩成一个胶囊（示例数据）。</sub></p>

## 主要功能

- **各家额度，一处看完**：Claude、Codex、Antigravity、OpenCode Go、GitHub Copilot、OpenRouter、Linear 并排显示，每家单独一条进度条。已经开始计时的额度，进度条旁边还会显示剩余时间。
- **有预告早知道，突然清零查得到**：开启重置公告后，程序就会去抓 Codex 和 Claude 发的公告。有的重置会提前预告（Codex 的预告公告，外加一行由 AI 预测重置可能性的 **Watch**），可以早做准备；有的说来就来，卡片会一直显示最新一条公告，用量突然清零时可以看看是不是刚重置过，一键就能打开原帖。
- **新公告出来就通知**：可以设置在新公告出现时发通知（Windows 上是系统原生通知），每种类型单独开关。公告来自独立的第三方追踪网站，可能延迟，也可能判断错，请以原帖为准。这个功能默认关闭。
- **在本机运行**：没有 AI Usage Clock 账号，没有服务器，也没有遥测。API 密钥存在操作系统的安全存储里；Claude 和 ChatGPT 的登录会话也存在那里，程序专用的浏览器配置目录里另有一份。

## 三步上手

1. **下载**：到[最新 Release](https://github.com/AIUsageClock/ai-usage-clock/releases/latest) 下载对应系统的压缩包：`ai-usage-clock-<version>-windows.zip`、`ai-usage-clock-<version>-macos.tar.gz` 或 `ai-usage-clock-<version>-linux.tar.gz`。
2. **解压运行**：
   - Windows：运行 `ai-usage-clock.exe`
   - macOS：把 `ai-usage-clock.app` 拖进“应用程序”文件夹，再打开
   - Linux：运行 `./ai-usage-clock/ai-usage-clock`
3. **接入服务**：Claude 和 Codex 直接在程序里登录；用 API 密钥的服务，到 **Settings**（设置）里粘贴密钥。详见[设置指南](docs/setup.zh-CN.md)。

发行版没有做代码签名，第一次打开时 Windows 或 macOS 可能会弹出警告，[解决办法看这里](#首次启动时出现-smartscreen-或-gatekeeper-警告)。

## 支持的服务

| 服务 | 显示什么 | 怎么接入 |
| --- | --- | --- |
| **Claude** | 会话额度和每周额度（套餐带每周 Fable 额度的，也会一起显示） | 用浏览器登录（支持 Google 账号和通行密钥），或者粘贴会话 Cookie |
| **Codex**（ChatGPT） | 会话额度和每周额度 | 同 Claude |
| **Antigravity** | Gemini、Claude+GPT 两组用量，各有 5 小时额度和每周额度 | 读取本机的 `agy` 命令行工具，程序里不用登录账号，也不用填密钥 |
| **OpenCode Go** | 滚动窗口、每周、每月用量 | OpenCode API 密钥 |
| **GitHub Copilot** | 本月已用的 AI 积分，对照套餐内含的额度，每月 1 日重置 | GitHub 细粒度个人访问令牌（fine-grained PAT） |
| **OpenRouter** | 今天和本月的花费，可设每日预算；填了管理密钥，还能看余额和各模型用量 | OpenRouter API 密钥 |
| **Linear** | 免费方案的 issue 数量，对照 250 个的上限（付费方案显示“no limit”） | Linear 个人 API 密钥 |

Claude、Codex 和 GitHub Copilot 默认开启；其他服务和重置公告要到 **Settings** 里手动开启。Claude、Codex 和 OpenCode Go 都支持添加多个账号。

## 给 AI Agent 用（MCP）

程序内置一个可选的本地 MCP 服务器，默认关闭。编程 Agent 可以在开始耗额度的任务之前先查一下用量，到了你设的上限就暂停。它只读取一份脱敏后的本地用量缓存，不会读取凭据。配置方法见 [docs/mcp.md](docs/mcp.md)（英文）。

## 常见问题

### 重置公告怎么用？

默认关闭。在 **Settings → General**（设置 → 常规）里开启 **Codex Resets** 或 **Claude Resets**（分别对应 Codex 和 Claude 的重置公告）就行。开启后，程序会从两个独立的第三方追踪网站读取数据：

- codex-resets.com：用 AI 给 @thsottiaux 发的帖子分类；
- claude-resets.com：汇总 @ClaudeDevs 和 Claude Code 团队成员发的帖子。

程序运行期间，每个网站最多每 15 分钟查询一次；重启程序会重新查询。

卡片上显示最新一条事件、距今多久，并标明类型：

- **Announced**（预告）：提前宣布了重置。只有 Codex 有这一类。
- **Reset**（已重置）：额度已经补满。
- **Banked**（重置券）：你获得了一张重置券，可以自己兑换。

Codex 的卡片还多一行 **Watch**（预测），是 AI 对重置可能性的预测，不是官方公告，也从不发通知。点击 ↗ 打开原帖，点击 ✕ 隐藏这张卡片，等下一条出现时再显示。

要接收哪些通知，在 **Settings → Reset alerts**（设置 → 重置提醒）里选：Codex 可选 Announced、Reset、Banked，Claude 可选 Reset、Banked。每个追踪网站，程序第一次抓到的事件只记录，不通知。

通知方式因系统而异：

- **Windows**：系统原生通知，点击就打开原帖。
- **其他系统**：有系统托盘时，用托盘气泡通知。
- **macOS 菜单栏模式、没有托盘的 Linux**：不发通知，但卡片照常更新。

这些数据由第三方整理，可能延迟或出错（Claude 的新条目最长 24 小时内可能仍是暂定状态），一切以原帖为准。

### 是官方出品吗？

不是。AI Usage Clock 是独立的开源项目，非官方的本地桌面软件；它显示的各家服务都没有参与开发，也没有为它背书。各家的页面和 API 随时可能变，不一定会提前通知。

### 数据存在哪？会连哪些网站？

设置、用量历史和登录会话都保存在本机。

- 会话和 API 密钥交给操作系统的凭据存储保管：Windows 用凭据管理器和 DPAPI，macOS 用钥匙串，Linux 用 Secret Service。Claude 和 ChatGPT 的会话另外还存在程序专用的浏览器配置目录里。
- 没有遥测，也没有 AI Usage Clock 服务器。
- 程序直接连接你开启的服务：Claude 和 ChatGPT 的用量页面（在内置浏览器里加载），以及 GitHub、OpenCode、OpenRouter、Linear 的 API；发给 Linear（api.linear.app）的只有你的 API 密钥和一个查询 issue 数量的请求。
- Antigravity 的用量来自本机的 `agy` 工具，由程序代为运行；`agy` 的网络连接由它自己处理。
- 开启重置公告后，还会访问 codex-resets.com 和 claude-resets.com，这两个网站能看到你的 IP 地址，以及程序的名称和版本号。
- 可选的本地费用统计会读取本机的 Claude Code 和 Codex 日志，不上传任何内容。

详见 [SECURITY.md](SECURITY.md)（英文）。

### 首次启动时出现 SmartScreen 或 Gatekeeper 警告

发行版没有做代码签名，每个压缩包旁边都附有 SHA256 校验值。

- **Windows**：如果 SmartScreen 弹出警告，点击 **更多信息**，再点击 **仍要运行**。
- **macOS**：第一次打开会被 Gatekeeper 拦下。先尝试打开一次，然后进入“系统设置”→“隐私与安全”，在“安全性”部分找到这个应用，点击“打开”，再点击“仍要打开”，输入登录密码后点击“好”（“仍要打开”按钮在尝试打开后大约一小时内可用）。也可以运行一次 `xattr -dr com.apple.quarantine ai-usage-clock.app`。
- **Linux**：没有签名机制。如果 `ai-usage-clock` 还没有可执行权限，先加上。

更多细节（包括 macOS 上的 MCP 辅助程序）见 [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds)（英文）。

### 需要装 Python 吗？

下载版不需要，Python 和浏览器引擎都已经打包在里面。只有从源码运行或参与开发，才需要 Python 3.11 及以上版本，见 [docs/build.md](docs/build.md)（英文）。

### macOS 和 Linux 能用吗？

能用，不过目前是测试版。Windows 是主要开发平台，也用真实账号测过；macOS 版（以菜单栏图标代替悬浮小组件）和 Linux 版都已发布，自动化测试在三个系统上都会跑，但用真实账号刷新用量只在 Windows 11 上验证过。各系统的重置通知不太一样，见第一个问题。用着有问题，欢迎[提 issue](https://github.com/AIUsageClock/ai-usage-clock/issues)。

### 免费吗？

免费，采用 MIT 许可证开源。它显示的各家服务，需要你自己有账号或订阅。

## 相关链接

[设置指南](docs/setup.zh-CN.md) · [日常使用](docs/usage.zh-CN.md) · [MCP 用量防护](docs/mcp.md)（英文） · [从源码构建](docs/build.md)（英文） · [参与贡献](CONTRIBUTING.md) · [安全](SECURITY.md) · [许可证（MIT）](LICENSE)

当前版本：**1.0.0** · [更新日志](CHANGELOG.md)

AI Usage Clock 与 Anthropic、OpenAI、Google、GitHub、Microsoft、OpenCode、OpenRouter、Linear 以及其他任何服务商都没有关联。文中的产品名称归各自的所有者。
