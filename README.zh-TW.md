<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="AI Usage Clock 應用程式圖示" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>看見每個 AI 額度，掌握每次重置。</strong></p>

<p align="center">
  一個桌面小工具，把各家 AI 服務的用量上限集中在一處，<br />
  並抓取 Codex 與 Claude 的重置公告：事先預告時讓你有心理準備，突然歸零時也有地方可以查看原因。
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>繁體中文</strong> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="測試狀態" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="支援 Windows、macOS 與 Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 授權" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="下載最新版本" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="Windows 上的 AI Usage Clock，顯示 Claude 與 Codex 用量、Antigravity 額度，以及 Codex 與 Claude 的重置公告" width="520" />
</p>

<p align="center"><sub>Windows 浮動小工具，擷取自執行中的發行版本。用量數值為擷取當下的狀態。</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="精簡模式：每項服務一顆膠囊" width="440" />
</p>

<p align="center"><sub>精簡模式會把小工具縮成每項服務一顆膠囊（範例資料）。</sub></p>

## 為什麼選 AI Usage Clock

- **你的 AI 額度，一個地方看完。** Claude、Codex、Antigravity、OpenCode Go、GitHub Copilot 與 OpenRouter 並排顯示，每項各有一條用量條；進行中的額度，用量條旁還會標示剩餘時間。
- **提前預告有準備，突然歸零有原因。** 開啟重置公告後，AI Usage Clock 會抓取 Codex 與 Claude 的重置公告。有些重置會事先預告（Codex 的預告，以及 AI 預測的 Watch 列），讓你先有心理準備；有些來得很突然，方塊會一直保留最新的公告，所以用量一下子歸零時，你可以看一下是不是剛重置，並一鍵開啟原始貼文。
- **新公告出現就通知你。** 可選擇在公告出現時發出通知（Windows 為原生通知），且每種公告都能個別設定。公告來自獨立的第三方追蹤站，可能延遲或誤判，請以原始貼文為準；這項功能預設關閉。
- **在你的電腦上執行。** 沒有 AI Usage Clock 帳號、伺服器或遙測。API 金鑰由作業系統的安全儲存機制保管；Claude 與 ChatGPT 的登入工作階段除了存在那裡，也存在程式自己的瀏覽器設定檔資料夾。

## 三步驟上手

1. **下載**：到[最新版本](https://github.com/AIUsageClock/ai-usage-clock/releases/latest)下載對應系統的壓縮檔：`ai-usage-clock-<version>-windows.zip`、`ai-usage-clock-<version>-macos.tar.gz` 或 `ai-usage-clock-<version>-linux.tar.gz`。
2. **解壓縮後執行。**
   - Windows：執行 `ai-usage-clock.exe`
   - macOS：把 `ai-usage-clock.app` 拖曳到「應用程式」資料夾，然後開啟
   - Linux：執行 `./ai-usage-clock/ai-usage-clock`
3. **連上你的服務。** 在程式中登入 Claude 與 Codex，或在 **Settings** 貼上 API 金鑰。詳見[設定指南](docs/setup.zh-TW.md)。

發行版本尚未簽署，第一次啟動時 Windows 或 macOS 可能會跳出警告，[處理方式在這裡](#首次啟動時出現-smartscreen-或-gatekeeper-警告)。

## 支援的服務

| 服務 | 你會看到什麼 | 連線方式 |
| --- | --- | --- |
| **Claude** | Session 與 Weekly 額度（方案有每週 Fable 額度時一併顯示） | 透過瀏覽器登入（支援 Google 與密碼金鑰 passkey），或貼上工作階段 cookie |
| **Codex**（ChatGPT） | Session 與 Weekly 額度 | 同 Claude |
| **Antigravity** | Gemini 與 Claude+GPT 兩組，各有 5 小時與每週額度 | 讀取本機的 `agy` 命令列工具，程式內不需要帳號或金鑰 |
| **OpenCode Go** | Rolling、Weekly 與 Monthly 用量 | OpenCode API 金鑰 |
| **GitHub Copilot** | 本月已用的 AI 點數，相對於方案內含額度，每月 1 日重置 | fine-grained GitHub 個人存取權杖（PAT） |
| **OpenRouter** | 今日與本月花費、可選的每日預算；加上管理金鑰還能看餘額與各模型用量 | OpenRouter API 金鑰 |

Claude、Codex 與 GitHub Copilot 預設啟用；其他服務與重置公告需要在 **Settings** 中開啟。Claude、Codex 與 OpenCode Go 都可以同時追蹤多個帳號。

## 給 AI 代理程式用（MCP）

AI Usage Clock 內建選用的本機 MCP 伺服器，預設關閉。它讓寫程式用的 AI 代理程式在開始耗用額度的工作之前，先查詢你的用量，並在達到你設定的上限時暫停。它只讀取已去除敏感資訊的本機用量快取，不會取得你的憑證。設定方式見 [docs/mcp.md](docs/mcp.md)（英文）。

## 常見問題

### 重置公告是怎麼運作的？

預設關閉。到 **Settings → General** 勾選 **Codex Resets** 或 **Claude Resets** 即可開啟。AI Usage Clock 會向兩個獨立的第三方追蹤站取得資料：codex-resets.com（以 AI 分類 @thsottiaux 的貼文）與 claude-resets.com（彙整 @ClaudeDevs 與 Claude Code 團隊成員的貼文），程式執行期間，每個站最多每 15 分鐘查詢一次，重新啟動時會再查一次。

方塊會顯示最新一則事件與發生至今的時間，並標明類型：

- **Announced**（預告）：重置事先宣布。目前只有 Codex 會有這一類。
- **Reset**（已重置）：額度已經補滿。
- **Banked**（重置額度）：你獲得一次可以自行兌換的重置額度。

Codex 的方塊另有一列 **Watch**，是 AI 預測的重置可能性，不是官方公告，也不會發通知。點 ↗ 可開啟原始貼文，點 ✕ 可先隱藏，等到下一則出現再顯示。

在 **Settings → Reset alerts** 可以選擇哪些類型要通知（Codex：預告、已重置、重置額度；Claude：已重置、重置額度）。程式第一次從某個追蹤站找到的事件只會記錄，不會通知。Windows 使用原生通知，點一下就會開啟原始貼文；其他系統在有系統匣時改用系統匣氣泡通知；macOS 選單列模式與沒有系統匣的 Linux 不會跳通知，但方塊仍會更新。

這些資料由第三方彙整，可能延遲或誤判（Claude 的新條目最長 24 小時內可能是暫定的），請以原始貼文為準。

### 這是官方應用程式嗎？

不是。AI Usage Clock 是獨立的開放原始碼專案，屬於非官方的本機桌面小工具，與它所顯示的各項服務皆無隸屬關係，也未經這些服務認可。各服務的頁面與 API 可能隨時異動。

### 我的資料會傳到哪裡？

你的設定、用量歷史與登入工作階段都留在你的電腦上。工作階段與 API 金鑰存放在作業系統提供的安全儲存機制：Windows 的認證管理員與 DPAPI、macOS 的鑰匙圈、Linux 的 Secret Service。Claude 與 ChatGPT 的工作階段另外也存在程式自己的瀏覽器設定檔資料夾。沒有遙測，也沒有 AI Usage Clock 的伺服器。程式只會直接連到你開啟的服務：Claude 與 ChatGPT 的用量頁面（在內建瀏覽器中載入），以及 GitHub、OpenCode 與 OpenRouter 的 API。Antigravity 的用量則是由程式執行你電腦上的 `agy` 工具取得，`agy` 自己負責它的連線。若開啟重置公告，另會連到 codex-resets.com 與 claude-resets.com，對方看得到你的 IP 位址，以及程式名稱與版本。選用的本機費用追蹤會讀取你電腦上的 Claude Code 與 Codex 記錄檔，不會上傳任何東西。詳見 [SECURITY.md](SECURITY.md)（英文）。

### 首次啟動時出現 SmartScreen 或 Gatekeeper 警告

發行版本尚未經過程式碼簽署，每個壓縮檔旁都附有 SHA256 雜湊值可供核對。

- **Windows：** 若 SmartScreen 出現警告，點選「其他資訊」，再點選「仍要執行」。
- **macOS：** Gatekeeper 第一次會擋下這個 App。先試著開啟一次，再到「系統設定」→「隱私權與安全性」，在「安全性」區域找到它並按「打開」，接著按「強制打開」，輸入登入密碼後按「好」（「強制打開」按鈕在嘗試開啟後約一小時內可用）。你也可以改為執行一次 `xattr -dr com.apple.quarantine ai-usage-clock.app`。
- **Linux：** 沒有簽署機制。若 `ai-usage-clock` 還沒有執行權限，請先加上。

更多細節（包含 macOS 上的 MCP 輔助程式）見 [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds)（英文）。

### 需要安裝 Python 嗎？

下載版不需要：Python 與瀏覽器引擎都已經內含。只有從原始碼執行或參與開發時，才需要 Python 3.11 以上版本，見 [docs/build.md](docs/build.md)（英文）。

### macOS 與 Linux 也能用嗎？

可以，但有但書。Windows 是主要的開發平台，也是用真實帳號測試過的平台。macOS（以選單列項目取代浮動小工具）與 Linux 版本也有發布，自動化測試在三個系統上都會執行，但以真實帳號重新整理用量，目前只在 Windows 11 驗證過，所以請把 macOS 與 Linux 視為早期階段。重置通知在各系統的差異見前面。遇到問題歡迎[開 issue](https://github.com/AIUsageClock/ai-usage-clock/issues) 回報。

### 免費嗎？

免費，以 MIT 授權開放原始碼。你所查看的各項服務仍需要各自的帳號或訂閱。

## 更多資訊

[設定指南](docs/setup.zh-TW.md) · [日常使用](docs/usage.zh-TW.md) · [MCP 用量防護](docs/mcp.md)（英文） · [從原始碼建置](docs/build.md)（英文） · [參與貢獻](CONTRIBUTING.md) · [安全性](SECURITY.md) · [授權（MIT）](LICENSE)

目前版本：**1.0.0** · [變更記錄](CHANGELOG.md)

AI Usage Clock 與 Anthropic、OpenAI、Google、GitHub、Microsoft、OpenCode、OpenRouter 或任何其他服務供應商皆無隸屬關係。產品名稱歸各自的所有者所有。
