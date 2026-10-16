# 设置指南

[English](setup.md) · [繁體中文](setup.zh-TW.md) · **简体中文**

[返回 README](../README.zh-CN.md)

本页介绍各项服务的首次设置。日常使用方式请见[使用 AI Usage Clock](usage.zh-CN.md)。

首次启动时，小组件会显示已启用的服务卡片。Claude、Codex 和 GitHub Copilot 默认启用；OpenCode Go、OpenRouter、Antigravity 和两个重置追踪站默认关闭，需要在 **Settings → General** 中开启。Claude 和 Codex 使用 **Sign in**（登录）或 **Paste cookie**（粘贴 Cookie）流程；OpenCode Go、GitHub Copilot 和 OpenRouter 则需在 Settings 中用 API 凭据进行设置。你可以打开 Settings 停用不使用的服务，或添加更多 Claude、Codex 或 OpenCode Go 账号。

## 各服务的首次设置

### Claude.ai

**Sign in（推荐）：** 会询问要使用哪一个已安装的 Chrome 系浏览器并记住你的选择，支持 Google 和通行密钥（passkey），并自动接入获取到的 Claude 会话，无需复制 Cookie。**Paste cookie：** 仍保留作为恢复用的兜底方式。如需添加其他 Claude 订阅，请前往 **Settings → Claude**。

### ChatGPT Codex

与 Claude 相同。**Sign in** 会使用你选择的已安装浏览器，并自动接入 ChatGPT 会话，包括关联 Google 和使用通行密钥的账号。**Paste cookie** 仅作为兜底。如需添加其他 Codex 订阅，请前往 **Settings → Codex**。

### OpenCode Go

前往 <https://opencode.ai/auth> 登录并复制 API 密钥。在 **Settings → OpenCode** 中，将密钥粘贴到订阅名称旁边。每个订阅都有独立的密钥和卡片。AI Usage Clock 会将密钥存放在系统凭据存储中，并通过已认证的 Go API 读取 Rolling、Weekly 和 Monthly 用量。应用内使用较短的名称 **OpenCode**。

### GitHub Copilot

前往 <https://github.com/settings/personal-access-tokens/new> 创建 **fine-grained PAT**（细粒度个人访问令牌）。个人方案请添加 **Account permissions → Plan → Read**。将其粘贴到 Settings 中，并设置你每月的 AI 积分额度（Pro=1,500、Pro+=7,000、Max=20,000）。如果 Copilot 通过组织计费，请填写计费组织，并使用具有组织计费访问权限的令牌／账号，以及 **Organization permissions → Administration → Read**。

### OpenRouter

前往 <https://openrouter.ai/keys> 创建推理（inference）API 密钥，并粘贴到 Settings 中。若要显示账户余额和模型活动，另请前往 <https://openrouter.ai/settings/provisioning-keys> 创建管理密钥（management key）。管理密钥无法用于推理；AI Usage Clock 会将其单独存储，且仅用于 OpenRouter 的管理端点。每日花费预算为可选项。

### Antigravity

在 **Settings → General** 中启用 **Antigravity**。AI Usage Clock 会运行本地 `agy` CLI 的 `/quota` 命令；无需在 AI Usage Clock 中输入账号或 API 密钥。**agy CLI** 一栏留空即可自动检测（先找 `PATH` 中的 `agy`，Windows 上再找 `%LOCALAPPDATA%\agy\bin\agy.exe`），你也可以自行选择可执行文件。如果文件不存在，或文件名不是 `agy`，系统会报告错误且不会运行。卡片可显示 Gemini 和 Claude+GPT 的用量，各有 5 小时和每周上限；请在 Antigravity 标签页中选择要显示的分组。AI Usage Clock 在自行调用 `agy` 时会禁用其后台更新并隐藏其控制台窗口；这不会影响你自己运行 `agy` 时的更新。如果响应表明有 token 消耗，或结果无法确认未消耗，轮询会停止，直到重启 AI Usage Clock。

## 多个 Claude / Codex / OpenCode Go 账号

Claude、Codex 和 OpenCode Go 都可以同时跟踪多个订阅。打开该服务的 Settings 标签页，点击 **Add another**（添加其他账号），并为账号起一个简短的名称。每个 Claude 或 Codex 条目请使用 **Sign in** 或 **Paste cookie**；每个 OpenCode 条目则粘贴对应的 API 密钥。默认账号显示为 `Claude`、`Codex` 或 `OpenCode`；命名账号则显示为 `Claude (Work)`、`Codex (Account 2)`、`OpenCode (Team)` 等。Claude 和 Codex 账号各自保留独立的浏览器会话，OpenCode 账号则各自使用独立的系统钥匙串条目。

**General**（常规）标签页用于控制服务分组。启用 Claude、Codex 或 OpenCode 后，会显示该系列下所有已配置的账号。任何账号（包括最初的账号）都可以从其标签页中移除；当尚未配置任何账号时，**Add another** 按钮仍然可用。每个账号都有各自独立的凭据、小组件卡片状态和历史记录。

使用账号旁边的 **Clear sign-in**（清除登录）可从 AI Usage Clock 中移除该账号的会话。这会同时清除受操作系统保护的已保存 Cookie，以及该账号内嵌浏览器中的实时 Cookie。它不会撤销其他浏览器或设备上的会话；如需在所有位置退出登录，请使用服务提供商的安全设置。

## 可选：本地用量和费用

启用 **Settings → Local usage**（本地用量），即可估算本机上 Claude Code 和 Codex 的活动若按 API 价格计算会花费多少。AI Usage Clock 会将 token 数量、模型名称、时间戳和日志文件的基本信息（消息和会话 ID、Claude Code 版本、日志文件路径，以及 Codex 日志中的用量上限读数）存储在本地；不会上传任何数据，且这些估算值并非实际扣费。

打开 **Usage details**（用量详情），即可对比额度使用量与估算费用，并可按模型、日期和趋势查看。浏览器聊天、云端任务、其他电脑，以及在 AI Usage Clock 导入前已被删除的日志，均不包含在内。

## 可选：重置公告

两张重置卡片默认均为关闭。请在 **Settings → General** 中启用 **Codex Resets** 或 **Claude Resets**。这些第三方追踪站独立于 OpenAI 和 Anthropic，其 AI 分类可能会把含义模糊的帖子误判为已完成的重置；请打开所附的原始帖子加以确认。

- AI Usage Clock 运行期间，对每个追踪站最多每 15 分钟连接一次（请求失败后同样如此）；如果追踪站要求更长的等待时间，AI Usage Clock 会遵从。重新启动后会立刻再查一次。
- 这些网站会收到你的 IP 地址，以及 `ai-usage-clock/<version> (+https://github.com/AIUsageClock/ai-usage-clock)` 这个 User-Agent。请求会发送到 `https://codex-resets.com/api/v1/status` 和 `https://claude-resets.com/api/resets`。
- 每张卡片会显示最新事件以及它发生至今的时间，并标明类型：**Announced**（预告，重置提前宣布；只有 Codex 有这一类）、**Reset**（已重置，额度已补满）或 **Banked**（重置券，可自行兑换）。点击 ↗ 可打开原始帖子；点击 ✕ 会隐藏该卡片，直到出现新的条目。
- Codex 另外会显示一行由 AI 预测的 **Watch**（预测等级、可选的重置概率和时间范围）。它不是官方公告，也不会触发通知；预测到期后就会消失。
- Claude 的暂定事件会在提示文字中标注；未标记为 `reset` 的 Claude 条目（包括政策公告）会被省略。
- AI Usage Clock 仅会打开追踪站提供的、使用 `http` 或 `https` 的链接。
- 请在 **Settings → Reset alerts**（重置提醒）中选择重置通知类型：Codex 提供预告、已重置和重置券提醒；Claude 提供已重置和重置券提醒。程序第一次从某个追踪站发现的事件只会被记录，不会发出通知。如果你把追踪站关闭一阵子再开启，程序会拿最新事件和上次记录的做比对，所以关闭期间发布的事件可能会触发通知。

[数据来源：Codex Resets](https://codex-resets.com) · [数据来源：Claude Resets](https://claude-resets.com)

各系统如何发出这些通知，请见[使用 AI Usage Clock](usage.zh-CN.md#重置通知)。

## 浏览器登录的工作原理

Google 不允许在内嵌浏览器控件内进行 OAuth 登录，因此 AI Usage Clock 会改为打开 Chrome、Edge、Brave 或 Chromium。首次使用时会询问你要用哪一个并记住选择；之后可在 **Settings → General → Sign-in browser**（登录用浏览器）中更改。整个流程都在本地进行：

1. AI Usage Clock 会创建一个全新的临时浏览器配置文件，其中不包含你日常使用的浏览器的任何浏览历史、扩展、Cookie 或已保存的账号。
2. 你在该浏览器窗口中正常登录，包括使用 Google 或通行密钥。
3. AI Usage Clock 通过随机生成、仅限本地回环（loopback）的调试端口监视该临时浏览器，并且只接受所选服务的 Cookie：`claude.ai` 或 `chatgpt.com`。
4. 该服务的会话会被复制到该 AI Usage Clock 账号的持久化浏览器配置文件和受操作系统保护的机密存储中。Google 的 Cookie 以及无关网站的 Cookie 都会被忽略。
5. AI Usage Clock 会关闭临时浏览器、删除其临时配置文件，并验证该服务的用量页面已处于登录状态。

与外部浏览器并排显示的小型 AI Usage Clock 窗口，是状态和恢复用的对话框，而不是第二个活动的浏览器。内嵌 WebView 仅在你选择时才会加载。如果外部浏览器在认证完成前被关闭，AI Usage Clock 会回到浏览器选择界面，而不会自行打开兜底方式。在内嵌模式下，系统会自动验证已识别的会话；**I'm signed in**（我已登录）仍可作为手动兜底。

你日常使用的 Chrome／Edge 配置文件绝不会被打开或检查。导入的会话在 AI Usage Clock 重启后依然有效，因此只有在服务使其过期或撤销时，才需要重新登录。内嵌浏览器和手动的 **Paste cookie** 选项仍可作为恢复途径。

## 数据存放位置

会话和设置会在多次运行之间保留，存放在各操作系统的应用数据目录下：

| 操作系统 | 应用数据                                  | 机密存储后端                              |
| ------- | ----------------------------------------- | ----------------------------------------- |
| Windows | `%APPDATA%/ai-usage-clock/`                     | 凭据管理器（GitHub PAT、OpenRouter 密钥和 OpenCode Go 密钥）＋经 DPAPI 加密的 `secrets.dat`（用于 Cookie，因为凭据管理器的数据大小上限对 ChatGPT 的 JWT 来说太小） |
| macOS   | `~/Library/Application Support/ai-usage-clock/` | 登录钥匙串                                |
| Linux   | `~/.config/ai-usage-clock/`                     | Secret Service（GNOME Keyring / KWallet） |

AI Usage Clock 不含遥测功能，也没有后端服务。对各服务的请求均由本地应用直接向所配置的服务发出。有关安全和隐私的说明，请参阅 [SECURITY.md](../SECURITY.md)（英文）。

## Paste cookie（兜底方式）

如果自动浏览器登录无法启动，或无法导入该服务的会话，你仍然可以手动将现有的 Claude 或 Codex 会话 Cookie 复制到应用中。这是一种恢复途径；关联 Google 和使用通行密钥的账号应可通过常规的 **Sign in** 按钮完成登录。

1. 照常在 **Chrome / Edge / Firefox** 中登录该服务。
2. 对于 ChatGPT，按下 **F12** → **Network**（网络），刷新页面，点击任意 `chatgpt.com` 请求，并复制完整的 **Request Headers → Cookie:** 值。其中包含分段的会话 Cookie，以及 `__Secure-oai-is` 等配套认证 Cookie。
3. 对于 Claude，按下 **F12** → **Network**，刷新 `https://claude.ai/new#settings/usage`，点击任意 `claude.ai` 请求，并复制完整的 **Request Headers → Cookie:** 值。其中必须包含 `sessionKey`。
4. 在应用中，打开 Settings 里对应的标签页，点击 **Paste cookie**，粘贴请求头内容后保存。
