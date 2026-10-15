# 設定指南

[English](setup.md) · **繁體中文** · [简体中文](setup.zh-CN.md)

[回到 README](../README.zh-TW.md)

本頁說明各項服務的首次設定。日常使用方式請見[使用 AI Usage Clock](usage.zh-TW.md)。

首次啟動時，小工具會顯示已啟用的服務方塊。Claude、Codex 與 GitHub Copilot 預設啟用；OpenCode Go、OpenRouter、Antigravity 與兩個重置追蹤站則預設關閉，需要在 **Settings → General** 中開啟。Claude 與 Codex 使用 **Sign in**（登入）或 **Paste cookie**（貼上 Cookie）流程；OpenCode Go、GitHub Copilot 與 OpenRouter 則須在 Settings 中以 API 憑證進行設定。你可以開啟 Settings 停用不使用的服務，或新增更多 Claude、Codex 或 OpenCode Go 帳號。

## 各服務的首次設定

### Claude.ai

**Sign in（建議）：** 會詢問要使用哪一個已安裝的 Chrome 系列瀏覽器並記住你的選擇，支援 Google 與密碼金鑰（passkey），並自動連接所取得的 Claude 工作階段，無須複製 Cookie。**Paste cookie：** 仍保留作為復原用的備援方式。如需新增其他 Claude 訂閱，請至 **Settings → Claude**。

### ChatGPT Codex

與 Claude 相同。**Sign in** 會使用你選擇的已安裝瀏覽器，並自動連接 ChatGPT 工作階段，包括綁定 Google 與使用密碼金鑰的帳號。**Paste cookie** 僅作為備援。如需新增其他 Codex 訂閱，請至 **Settings → Codex**。

### OpenCode Go

前往 <https://opencode.ai/auth> 登入並複製 API 金鑰。在 **Settings → OpenCode** 中，將金鑰貼在訂閱名稱旁。每個訂閱都有獨立的金鑰與方塊。AI Usage Clock 會將金鑰存放於系統憑證儲存區，並透過已驗證的 Go API 讀取 Rolling、Weekly 與 Monthly 用量。應用程式內使用較短的名稱 **OpenCode**。

### GitHub Copilot

至 <https://github.com/settings/personal-access-tokens/new> 建立 **fine-grained PAT**（細粒度個人存取權杖）。個人方案請加上 **Account permissions → Plan → Read**。將其貼入 Settings，並設定你每月的 AI 點數額度（Pro=1,500、Pro+=7,000、Max=20,000）。若 Copilot 是透過組織計費，請填入計費組織，並使用具備組織計費存取權的權杖／帳號，以及 **Organization permissions → Administration → Read**。

### OpenRouter

至 <https://openrouter.ai/keys> 建立推論用（inference）API 金鑰，並貼入 Settings。若要顯示帳戶餘額與模型活動，另請至 <https://openrouter.ai/settings/provisioning-keys> 建立管理金鑰（management key）。管理金鑰無法用於推論；AI Usage Clock 會將其另外儲存，且僅用於 OpenRouter 的管理端點。每日花費預算為選填。

### Antigravity

在 **Settings → General** 中啟用 **Antigravity**。AI Usage Clock 會執行本機 `agy` CLI 的 `/quota` 指令；無須在 AI Usage Clock 中輸入帳號或 API 金鑰。**agy CLI** 欄位留空即可自動偵測（先找 `PATH` 中的 `agy`，Windows 上再找 `%LOCALAPPDATA%\agy\bin\agy.exe`），你也可以自行選擇執行檔。若檔案不存在，或檔名不是 `agy`，系統會回報錯誤且不會執行。方塊可顯示 Gemini 與 Claude+GPT 的用量，各有 5 小時與每週上限；請在 Antigravity 分頁選擇要顯示的群組。AI Usage Clock 在自行呼叫 `agy` 時會停用其背景更新並隱藏其主控台視窗；這不會影響你自行執行 `agy` 時的更新。若回應顯示有 token 消耗，或結果無法確認未消耗，輪詢會停止，直到重新啟動 AI Usage Clock。

## 多個 Claude / Codex / OpenCode Go 帳號

Claude、Codex 與 OpenCode Go 都可以同時追蹤多個訂閱。開啟該服務的 Settings 分頁，點選 **Add another**（新增其他帳號），並為帳號取一個簡短的名稱。每個 Claude 或 Codex 項目請使用 **Sign in** 或 **Paste cookie**；每個 OpenCode 項目則貼上對應的 API 金鑰。預設帳號顯示為 `Claude`、`Codex` 或 `OpenCode`；具名帳號則顯示為 `Claude (Work)`、`Codex (Account 2)`、`OpenCode (Team)` 等。Claude 與 Codex 帳號各自保有獨立的瀏覽器工作階段，OpenCode 帳號則各自使用獨立的系統鑰匙圈項目。

**General**（一般）分頁負責控制服務群組。啟用 Claude、Codex 或 OpenCode 後，會顯示該系列中所有已設定的帳號。任何帳號（包括最初的帳號）都可以從其分頁中移除；當尚未設定任何帳號時，**Add another** 按鈕仍然可用。每個帳號都有各自獨立的憑證、小工具方塊狀態與歷史紀錄。

使用帳號旁的 **Clear sign-in**（清除登入）可從 AI Usage Clock 移除該帳號的工作階段。這會同時清除受作業系統保護的已儲存 Cookie，以及該帳號內嵌瀏覽器中的即時 Cookie。它不會撤銷其他瀏覽器或裝置上的工作階段；若需要在所有地方登出，請使用服務供應商的安全性設定。

## 選用：本機用量與費用

啟用 **Settings → Local usage**（本機用量），即可估算本機上 Claude Code 與 Codex 的活動若以 API 價格計算會花費多少。AI Usage Clock 會將 token 數量、模型名稱、時間戳記與記錄檔的基本資訊（訊息與工作階段 ID、Claude Code 版本、記錄檔路徑，以及 Codex 記錄中的用量上限讀數）儲存在本機；不會上傳任何資料，且這些估算值並非實際收費。

開啟 **Usage details**（用量詳情），即可比較額度使用量與估算費用，並可依模型、日期與趨勢檢視。瀏覽器聊天、雲端任務、其他電腦，以及在 AI Usage Clock 匯入前已刪除的記錄，皆不包含在內。

## 選用：重置公告

兩個重置方塊預設皆為關閉。請在 **Settings → General** 中啟用 **Codex Resets** 或 **Claude Resets**。這些第三方追蹤站獨立於 OpenAI 與 Anthropic，其 AI 分類可能會將意思不明確的貼文誤判為已完成的重置；請開啟所附的原始貼文加以確認。

- AI Usage Clock 執行期間，對每個追蹤站最多每 15 分鐘連線一次（請求失敗後亦同）；若追蹤站要求更長的等待時間，AI Usage Clock 會遵從。重新啟動後會立刻再查一次。
- 這些網站會收到你的 IP 位址，以及 `ai-usage-clock/<version> (+https://github.com/AIUsageClock/ai-usage-clock)` 這個 User-Agent。請求會送往 `https://codex-resets.com/api/v1/status` 與 `https://claude-resets.com/api/resets`。
- 每個方塊會顯示最新事件與發生至今的時間，並標明類型：**Announced**（預告，重置事先宣布；只有 Codex 有這一類）、**Reset**（已重置，額度已補滿）或 **Banked**（重置額度，可自行兌換）。點 ↗ 可開啟原始貼文；點 ✕ 會隱藏該方塊，直到出現新的項目。
- Codex 另外會顯示一列由 AI 預測的 **Watch**（預測等級、選填的重置機率與時間範圍）。它不是官方公告，也不會觸發通知；預測期限一過就會消失。
- Claude 的暫定事件會在提示文字中標示；未標記為 `reset` 的 Claude 項目（包括政策公告）會被省略。
- AI Usage Clock 僅會開啟追蹤站所提供且使用 `http` 或 `https` 的連結。
- 請在 **Settings → Reset alerts**（重置提醒）中選擇重置通知類型：Codex 提供預告、已重置與重置額度提醒；Claude 提供已重置與重置額度提醒。程式第一次從某個追蹤站找到的事件只會被記錄，不會發出通知。若你把追蹤站關閉一陣子再開啟，程式會拿最新事件與上次記錄的比對，所以關閉期間發布的事件可能會觸發通知。

[資料來源：Codex Resets](https://codex-resets.com) · [資料來源：Claude Resets](https://claude-resets.com)

各系統如何送出這些通知，請見[使用 AI Usage Clock](usage.zh-TW.md#重置通知)。

## 瀏覽器登入的運作方式

Google 不允許在內嵌瀏覽器控制項內進行 OAuth 登入，因此 AI Usage Clock 會改為開啟 Chrome、Edge、Brave 或 Chromium。首次使用時會詢問你要用哪一個並記住選擇；之後可在 **Settings → General → Sign-in browser**（登入用瀏覽器）中變更。整個流程皆在本機進行：

1. AI Usage Clock 會建立一個全新的暫時性瀏覽器設定檔，其中不含你平常使用的瀏覽器的任何瀏覽紀錄、擴充功能、Cookie 或已儲存的帳號。
2. 你在該瀏覽器視窗中照常登入，包括使用 Google 或密碼金鑰。
3. AI Usage Clock 透過隨機產生、僅限本機回送（loopback）的偵錯連接埠監看該暫時性瀏覽器，並且只接受所選服務的 Cookie：`claude.ai` 或 `chatgpt.com`。
4. 該服務的工作階段會被複製到該 AI Usage Clock 帳號的持久性瀏覽器設定檔與受作業系統保護的機密儲存區。Google 的 Cookie 與不相關網站的 Cookie 皆會被忽略。
5. AI Usage Clock 會關閉暫時性瀏覽器、刪除其暫時性設定檔，並驗證該服務的用量頁面已處於登入狀態。

與外部瀏覽器並列顯示的小型 AI Usage Clock 視窗，是狀態與復原用的對話方塊，而不是第二個作用中的瀏覽器。內嵌 WebView 僅在你選擇時才會載入。若外部瀏覽器在驗證完成前被關閉，AI Usage Clock 會回到瀏覽器選擇畫面，而不會自行開啟備援方式。在內嵌模式下，系統會自動驗證已辨識的工作階段；**I'm signed in**（我已登入）仍可作為手動備援。

你日常使用的 Chrome／Edge 設定檔絕不會被開啟或檢視。匯入的工作階段在 AI Usage Clock 重新啟動後仍然有效，因此只有在服務讓其過期或撤銷時，才需要重新登入。內嵌瀏覽器與手動的 **Paste cookie** 選項仍可作為復原途徑。

## 資料存放位置

工作階段與設定會在多次執行之間保留，存放於各作業系統的應用程式資料目錄：

| 作業系統 | 應用程式資料                                    | 機密儲存後端                              |
| ------- | ----------------------------------------------- | ----------------------------------------- |
| Windows | `%APPDATA%/ai-usage-clock/`                     | 認證管理員（GitHub PAT、OpenRouter 金鑰與 OpenCode Go 金鑰）＋以 DPAPI 加密的 `secrets.dat`（用於 Cookie，因為認證管理員的資料大小上限對 ChatGPT 的 JWT 而言太小） |
| macOS   | `~/Library/Application Support/ai-usage-clock/` | 登入鑰匙圈                                |
| Linux   | `~/.config/ai-usage-clock/`                     | Secret Service（GNOME Keyring / KWallet） |

AI Usage Clock 不含遙測功能，也沒有後端服務。對各服務的請求皆由本機應用程式直接向所設定的服務發出。安全性與隱私權相關說明，請參閱 [SECURITY.md](../SECURITY.md)（英文）。

## Paste cookie（備援方式）

若自動瀏覽器登入無法啟動，或無法匯入該服務的工作階段，你仍可手動將現有的 Claude 或 Codex 工作階段 Cookie 複製到應用程式中。這是一種復原途徑；綁定 Google 與使用密碼金鑰的帳號應可使用一般的 **Sign in** 按鈕完成登入。

1. 照常在 **Chrome / Edge / Firefox** 中登入該服務。
2. 對於 ChatGPT，按下 **F12** → **Network**（網路），重新載入頁面，點選任一 `chatgpt.com` 請求，並複製完整的 **Request Headers → Cookie:** 值。其中包含分段的工作階段 Cookie，以及 `__Secure-oai-is` 等附屬驗證 Cookie。
3. 對於 Claude，按下 **F12** → **Network**，重新載入 `https://claude.ai/new#settings/usage`，點選任一 `claude.ai` 請求，並複製完整的 **Request Headers → Cookie:** 值。其中必須包含 `sessionKey`。
4. 在應用程式中，開啟 Settings 內對應的分頁，點選 **Paste cookie**，貼上標頭內容後儲存。
