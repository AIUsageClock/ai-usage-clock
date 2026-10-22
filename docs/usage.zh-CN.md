# 使用 AI Usage Clock

[English](usage.md) · [繁體中文](usage.zh-TW.md) · **简体中文**

[返回 README](../README.zh-CN.md)

本页介绍日常使用方式和已知限制。如果还没有连接账号，请先看[设置指南](setup.zh-CN.md)。

## 日常使用

- **Windows / Linux：** 拖动悬浮小组件即可移动，并使用右下角的拖拽手柄调整大小。可将其折叠为紧凑的胶囊，或隐藏到系统托盘。在小组件或托盘图标上右键可打开完整菜单。在没有系统托盘的桌面环境中，请改为在小组件上右键。
- **macOS：** 菜单栏项会显示每个已启用服务或账号的最高用量。点击即可打开弹出窗口。
- Settings 可控制服务、账号、颜色、窗口行为、界面缩放、刷新时机和登录时自动启动。
- 当用量有变化时，每 5 分钟自动刷新一次，之后默认会逐步退避，最长间隔为 60 分钟。
- 刷新出错时，卡片会显示简短的原因；保留的数值会标记为 `<cause> · stale`（例如 `offline · stale` 或 `timeout · stale`），而没有保留数值的错误则显示 `error · <cause>`。

## 重置通知

重置提醒来自可选的 Codex Resets 和 Claude Resets 追踪站（见[可选：重置公告](setup.zh-CN.md#可选重置公告)）。

- 在 Windows 上，提醒会使用通知中心的原生通知；点击通知会在浏览器中打开原始帖子，即使 AI Usage Clock 已退出也一样。同时到达的提醒会同时显示。
- 如果原生通知失败，或在非 Windows 系统上，且有可用的 Qt 系统托盘时，会改用系统托盘气泡通知。气泡通知之间至少间隔 8 秒；点击气泡会打开最后一条气泡对应的帖子。
- macOS 菜单栏模式，以及没有系统托盘的 Linux 上，不会显示重置通知。重置卡片仍会在 macOS 弹出窗口和没有系统托盘的 Linux 悬浮小组件中更新。
- 如果 Windows 中已关闭气泡提示，则不会显示兜底气泡通知。
- AI Usage Clock 会在 `HKCU\Software\Classes\AppUserModelId\AIUsageClock.AIUsageClock` 下注册其通知名称和内置图标（`DisplayName` = `AI Usage Clock`，`IconUri` = 内置图标的路径）；卸载后，你可以删除此注册表项。

## 注意事项与限制

- 重置公告卡片没有百分比，且不会出现在 macOS 菜单栏摘要中。
- Antigravity 用量、重置卡片和原生通知仅在 Windows 11 上测试过；macOS 和 Linux 尚未测试。
- **为什么 Sign in 会打开另一个 Chrome 系窗口？** Google 会阻止内嵌 user-agent 中的 OAuth，而 Chrome 的应用绑定加密（App-Bound Encryption）又使 AI Usage Clock 无法读取你日常使用的浏览器配置文件。因此 AI Usage Clock 会打开一个全新的临时浏览器配置文件，通过 Chrome 的本地回环调试接口仅接收所选服务的 Cookie，将其导入应用，然后删除该临时配置文件。
- **Claude／Codex 的页面布局可能会变化。** 如果某个基于浏览器的服务卡片在服务更新 UI 后显示“error”，可能需要调整 `src/aiusageclock/providers/` 下的页面提取 JS — 应用的其余部分仍可正常运行。
- **远程桌面和没有 GPU 的会话需要注意一点。** 这个小组件本身是纯 Qt Widgets，可在任何环境运行，包括通过 RDP/XRDP，以及没有 GPU 的机器。Claude 和 Codex 是通过驱动内嵌的 Chromium 来读取的，这需要 OpenGL 环境；如果会话既不提供 GLX 也不提供 EGL，就无法提供该环境。在这种情况下，这些卡片会提示需要浏览器，而 OpenCode Go、GitHub Copilot、OpenRouter 和 Linear 使用 API 凭据，可正常工作。大多数 Linux 桌面环境会通过 Mesa 提供软件 GL，因此这只会出现在单纯的 X 服务器和部分远程会话上。如果 AI Usage Clock 误判了你的会话，请设置 `AIUSAGECLOCK_FORCE_WEBENGINE=1` 以跳过检查。
- Copilot REST 端点返回的是账单用量的当前自然月数据。小组件跟踪的是已消耗的 AI 积分总额相对于内含额度的使用情况；净数量／金额仅为需要付费的超额部分。重置时间按下个月 1 日计算。GitHub 目前并未提供可靠的个人方案额度字段，因此 Settings 使用方案下拉菜单，并提供“自定义”作为兜底。年付／按请求次数计费的账号，则以旧版 premium request 机制作为兜底处理。
- **Copilot 用量存在延迟。** Copilot REST 端点的更新速度明显比 Claude 或 Codex 慢 — 积分统计可能需要数小时才会反映最近的活动。小组件显示的是 GitHub 返回的最新数值；请将 Copilot 卡片视为滞后指标，而非实时数据。
- **Copilot AI 积分。** GitHub 已将 Copilot 从按请求次数计算的额度，改为基于 token 的 AI 积分。付费方案仍包含代码补全和下一处编辑建议，而 Chat、CLI、云端代理、Spaces、Spark 和第三方编码代理则会消耗 AI 积分。应用显示的是 GitHub 返回的积分用量；如果你的账号由组织计费，请填写计费组织，让 AI Usage Clock 读取该组织的计费积分池。
- **OpenRouter 使用两种密钥类型。** 推理密钥用于获取 `/key` 的花费数据。管理密钥则是获取 `/credits` 账户余额和 `/activity` 模型历史所必需的。没有管理密钥时，AI Usage Clock 仍会显示密钥级别的花费，但无法显示余额或模型活动。
- **OpenRouter 的时间窗口以 UTC 为准。** 今日／本月花费取自 OpenRouter 当前的 UTC 日和月字段。模型活动取自 OpenRouter 默认的 `/activity` 历史窗口：最近 30 个已完成的 UTC 日，不含当前的 UTC 日。
- **Linear 统计的是 issue 数量，不是 token。** Linear 卡片会显示这个 API 密钥能看到的所有 team 中未归档的 issue 数量，对照免费方案的上限 250（可在 Settings → Linear 调整），用一条 **Issues** 进度条呈现，没有重置时间。看不到所有 team 的密钥会少算。付费工作区没有 issue 上限，该行会显示“no limit”而不是进度条。
- **闲置的额度。** 用量为 0% 且计时窗口尚未开始的额度会显示 `idle`，而不是剩余时间；等你下次使用它时才开始计时。
