<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="AI Usage Clock 圖示" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>看見每個 AI 額度，掌握每次重置。</strong></p>

<p align="center">
  同時在用好幾家 AI，額度還剩多少、剛剛是不是重置過，常常得一家一家點開來看。<br />
  AI Usage Clock 把這些用量上限收進桌面上的小視窗，<br />
  也會幫你抓 Codex 和 Claude 的重置公告：有預告的先讓你知道，<br />
  用量突然歸零的時候，也有地方可以確認是不是剛重置。
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>繁體中文</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="測試狀態" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="支援 Windows、macOS、Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 授權" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="下載最新版" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="Windows 上的 AI Usage Clock：Claude 和 Codex 用量、Antigravity 額度，還有 Codex 和 Claude 的重置公告" width="520" />
</p>

<p align="center"><sub>Windows 版浮動小工具，從實際執行中的發行版擷取；畫面上的用量是擷取當下的數字。</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="精簡模式：每個服務縮成一顆膠囊" width="440" />
</p>

<p align="center"><sub>精簡模式：每個服務縮成一顆膠囊（範例資料）。</sub></p>

## 它能幫你做什麼

- **各家 AI 額度，一個視窗看完。** Claude、Codex、Antigravity、OpenCode Go、GitHub Copilot、OpenRouter 並排顯示，每個服務都有自己的用量條；使用中的額度，旁邊還會標出剩餘時間。
- **有預告的先知道，沒預告的查得到。** 打開重置公告功能後，AI Usage Clock 會幫你抓 Codex 和 Claude 的重置公告。有些重置會事先預告（Codex 的公告，再加上 AI 預測的 Watch 列），讓你有時間準備；有些則是突然就來了，所以區塊會一直留著最新一則公告，等你發現用量突然歸零，就能看看是不是剛重置，點一下還能直接打開原始貼文。
- **有新公告時通知你。** 想要的話，可以在新公告出現時跳通知（Windows 用系統原生通知），每種公告類型都有自己的開關。這些公告來自獨立的第三方追蹤站，可能會晚到或判斷錯誤，請以原始貼文為準。這個功能預設關閉。
- **全部在你的電腦上跑。** 不必註冊 AI Usage Clock 帳號，沒有伺服器，也沒有遙測。API 金鑰交給作業系統的安全儲存區保管；Claude 和 ChatGPT 的登入工作階段也存在那裡，程式自己的瀏覽器設定檔資料夾裡另外還有一份。

## 三步驟上手

1. **下載**：到[最新版本](https://github.com/AIUsageClock/ai-usage-clock/releases/latest)下載你系統用的壓縮檔，檔名是 `ai-usage-clock-<version>-windows.zip`、`ai-usage-clock-<version>-macos.tar.gz` 或 `ai-usage-clock-<version>-linux.tar.gz`。
2. **解壓縮後執行**：
   - Windows：執行 `ai-usage-clock.exe`
   - macOS：把 `ai-usage-clock.app` 拖進「應用程式」，再打開它
   - Linux：執行 `./ai-usage-clock/ai-usage-clock`
3. **連上服務**：Claude 和 Codex 在程式裡直接登入；用 API 金鑰的服務，到 **Settings**（設定）貼上金鑰。詳細步驟見[設定指南](docs/setup.zh-TW.md)。

下載的版本沒有程式碼簽署，第一次開啟時 Windows 或 macOS 可能會跳出警告，[看這裡怎麼處理](#首次啟動時出現-smartscreen-或-gatekeeper-警告)。

## 支援的服務

| 服務 | 看得到什麼 | 怎麼連 |
| --- | --- | --- |
| **Claude** | Session 和 Weekly（每週）額度；方案有每週 Fable 額度的話也會顯示 | 用瀏覽器登入（Google 帳號、密碼金鑰都能用），或貼上工作階段 Cookie |
| **Codex**（ChatGPT） | Session 和 Weekly 額度 | 跟 Claude 一樣 |
| **Antigravity** | Gemini 和 Claude+GPT 兩組用量，各有 5 小時和每週額度 | 讀取你電腦上的 `agy` 命令列工具，不用在程式裡輸入帳號或金鑰 |
| **OpenCode Go** | Rolling、Weekly、Monthly（滾動、每週、每月）三種用量 | OpenCode API 金鑰 |
| **GitHub Copilot** | 本月用掉多少 AI 點數，對照方案內含的額度；每月 1 號重置 | GitHub 細粒度個人存取權杖（fine-grained PAT） |
| **OpenRouter** | 今天和本月的花費，可另設每日預算；有管理金鑰的話，還看得到餘額和各模型的使用情形 | OpenRouter API 金鑰 |

預設開啟的是 Claude、Codex 和 GitHub Copilot；其他服務和重置公告，要到 **Settings** 自己打開。Claude、Codex、OpenCode Go 都可以同時追蹤好幾個帳號。

## 讓 AI 代理程式先看額度（MCP）

程式內建一個本機 MCP 伺服器，預設關閉，需要的話再打開。打開之後，寫程式的 AI 代理程式在開始耗額度的工作前，可以先查用量；用到你設定的上限就會暫停。它只讀本機一份已經去掉敏感資訊的用量快取，碰不到任何憑證。設定方法見 [docs/mcp.md](docs/mcp.md)（英文）。

## 常見問答

### 重置公告是怎麼抓的？

預設是關的。到 **Settings → General**（一般）打開 **Codex Resets** 或 **Claude Resets**（兩家重置公告的開關），AI Usage Clock 就會去讀兩個獨立的第三方追蹤站：

- codex-resets.com：用 AI 判斷 @thsottiaux 的貼文屬於哪一類。
- claude-resets.com：收集 @ClaudeDevs 和 Claude Code 團隊成員的貼文。

程式開著的時候，每個追蹤站最多每 15 分鐘問一次；重新開啟程式會再問一次。

區塊會顯示最新一筆事件和距今多久，並標上類型：

- **Announced**（預告）：事前宣布要重置。只有 Codex 有這一類。
- **Reset**（已重置）：額度已經補滿。
- **Banked**（重置券）：你拿到一張重置券，可以留著自己兌換。

Codex 的區塊還多一列 **Watch**（觀察），是 AI 預測重置的機率有多高。它不是官方公告，也不會發任何通知。點 ↗ 打開原始貼文；點 ✕ 先把區塊藏起來，等下一筆新資料出現再顯示。

到 **Settings → Reset alerts**（重置提醒）選擇哪些類型要通知你：Codex 可選預告、已重置、重置券；Claude 可選已重置、重置券。程式第一次從某個追蹤站抓到的事件，只會記下來，不會通知。Windows 用系統原生通知，點一下就打開原始貼文；其他系統如果有系統匣，就改用系統匣的氣泡通知。macOS 的選單列模式和沒有系統匣的 Linux 都不會跳通知，但區塊還是會照常更新。

這些資料是第三方整理的，可能會晚到或判斷錯誤（Claude 的新條目最長可能 24 小時都還是暫定），一切以原始貼文為準。

### 這是官方出的嗎？

不是。AI Usage Clock 是獨立的開源專案，也是非官方的本機桌面工具，不是畫面上任何一家服務做的，也沒有經過它們背書。各家網頁和 API 隨時可能改，事前不會通知。

### 我的資料會傳到哪裡？

設定、用量歷史和登入工作階段，都留在你自己的電腦上。工作階段和 API 金鑰交給作業系統的憑證機制保管：Windows 是認證管理員和 DPAPI，macOS 是鑰匙圈，Linux 是 Secret Service。Claude 和 ChatGPT 的工作階段，另外也存在程式自己的瀏覽器設定檔資料夾。

沒有遙測，也沒有 AI Usage Clock 伺服器。程式會直接連到你打開的服務：Claude 和 ChatGPT 的用量頁面（在內建瀏覽器裡載入），還有 GitHub、OpenCode、OpenRouter 的 API。Antigravity 的用量是程式幫你執行電腦上的 `agy` 工具拿到的；至於 `agy` 本身要連到哪裡，由它自己處理。

如果打開重置公告，程式還會連到 codex-resets.com 和 claude-resets.com，這兩個網站看得到你的 IP 位址，還有程式名稱和版本。選用的本機費用追蹤會讀取電腦上的 Claude Code 和 Codex 記錄檔，不會上傳任何東西。詳情見 [SECURITY.md](SECURITY.md)（英文）。

### 首次啟動時出現 SmartScreen 或 Gatekeeper 警告

發行版本沒有程式碼簽署，每個壓縮檔旁邊都附有 SHA256 雜湊值。

- **Windows：** 如果 SmartScreen 跳出警告，點「其他資訊」，再點「仍要執行」。
- **macOS：** Gatekeeper 第一次會把它擋下來。先試著打開一次，再到「系統設定」→「隱私權與安全性」，在「安全性」區塊找到這個 App，按「打開」，接著按「強制打開」，輸入登入密碼後按「好」（試著開啟後大約一小時內，「強制打開」按鈕都還按得到）。也可以直接執行一次 `xattr -dr com.apple.quarantine ai-usage-clock.app`。
- **Linux：** 沒有簽署這一關。如果 `ai-usage-clock` 還沒有執行權限，幫它加上就好。

更多細節（包括 macOS 上的 MCP 輔助程式）見 [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds)（英文）。

### 需要裝 Python 嗎？

下載版不用，Python 和瀏覽器引擎都已經包在裡面。只有要從原始碼執行，或想參與開發，才需要 Python 3.11 以上，見 [docs/build.md](docs/build.md)（英文）。

### macOS 和 Linux 能用嗎？

能，但有一點要先說明。這個工具是在 Windows 上開發的，也在 Windows 上用真實帳號測過。macOS 版（是選單列項目，不是浮動小工具）和 Linux 版都有發布，自動化測試也會在三個系統上跑；不過用真實帳號重新整理用量，目前只在 Windows 11 上確認過，所以 macOS 和 Linux 請當成測試版。重置通知在各系統上的差異，見上面第一題。用起來有什麼不對勁，歡迎[開 issue](https://github.com/AIUsageClock/ai-usage-clock/issues) 回報。

### 免費嗎？

免費，以 MIT 授權開源。不過畫面上那些服務，本身還是要有帳號或訂閱。

## 延伸閱讀

[設定指南](docs/setup.zh-TW.md) · [日常使用](docs/usage.zh-TW.md) · [MCP 用量防護](docs/mcp.md)（英文） · [從原始碼建置](docs/build.md)（英文） · [參與貢獻](CONTRIBUTING.md) · [安全性](SECURITY.md) · [授權（MIT）](LICENSE)

目前版本：**1.0.0** · [更新紀錄](CHANGELOG.md)

AI Usage Clock 和 Anthropic、OpenAI、Google、GitHub、Microsoft、OpenCode、OpenRouter 或其他任何服務商都沒有隸屬關係。各產品名稱屬於各自的所有者。
