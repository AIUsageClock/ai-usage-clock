# 使用 AI Usage Clock

[English](usage.md) · **繁體中文** · [简体中文](usage.zh-CN.md)

[回到 README](../README.zh-TW.md)

本頁說明日常使用方式與已知限制。若還沒連接帳號，請先看[設定指南](setup.zh-TW.md)。

## 日常使用

- **Windows / Linux：** 拖曳浮動小工具即可移動，並使用右下角的握把調整大小。可將其收合為精簡的膠囊，或隱藏到系統匣。在小工具或系統匣圖示上按右鍵可開啟完整選單。在沒有系統匣的桌面環境中，請改在小工具上按右鍵。
- **macOS：** 選單列項目會顯示每個已啟用服務或帳號的最高用量。點選即可開啟彈出視窗。
- Settings 可控制服務、帳號、顏色、視窗行為、介面縮放、重新整理時機與登入時自動啟動。
- 當用量有變動時，每 5 分鐘自動重新整理一次，之後預設會逐步退避，最長間隔為 60 分鐘。
- 重新整理發生錯誤時，區塊會顯示簡短的原因；保留的數值會標示為 `<cause> · stale`（例如 `offline · stale` 或 `timeout · stale`），而沒有保留數值的錯誤則顯示 `error · <cause>`。

## 重置通知

重置提醒來自選用的 Codex Resets 與 Claude Resets 追蹤站（見[選用：重置公告](setup.zh-TW.md#選用重置公告)）。

- 在 Windows 上，提醒會使用通知中心的原生通知；點選通知會在瀏覽器中開啟原始貼文，即使 AI Usage Clock 已結束也一樣。同時到達的提醒會同時顯示。
- 若原生通知失敗，或在非 Windows 系統上，且有可用的 Qt 系統匣時，會改用系統匣氣泡通知。氣泡通知之間至少間隔 8 秒；點選氣泡會開啟最後一則氣泡的貼文。
- macOS 選單列模式，以及沒有系統匣的 Linux 上，不會顯示重置通知。重置區塊仍會在 macOS 彈出視窗與沒有系統匣的 Linux 浮動小工具中更新。
- 若 Windows 中已關閉氣泡提示，則不會顯示備援氣泡通知。
- AI Usage Clock 會在 `HKCU\Software\Classes\AppUserModelId\AIUsageClock.AIUsageClock` 下註冊其通知名稱與內建圖示（`DisplayName` = `AI Usage Clock`，`IconUri` = 內建圖示的路徑）；解除安裝後，你可以刪除此機碼。

## 注意事項與限制

- 重置公告區塊沒有百分比，且不會出現在 macOS 選單列摘要中。
- Antigravity 用量、重置區塊與原生通知僅在 Windows 11 上測試過；macOS 與 Linux 尚未測試。
- **為什麼 Sign in 會開啟另一個 Chrome 系列視窗？** Google 會封鎖內嵌 user-agent 中的 OAuth，而 Chrome 的應用程式繫結加密（App-Bound Encryption）又使 AI Usage Clock 無法讀取你日常使用的瀏覽器設定檔。因此 AI Usage Clock 會開啟一個全新的暫時性瀏覽器設定檔，透過 Chrome 的本機回送偵錯介面僅接收所選服務的 Cookie，將其匯入應用程式，然後刪除該暫時性設定檔。
- **Claude／Codex 的頁面版面可能會改變。** 若某個以瀏覽器為基礎的服務區塊在服務更新 UI 後顯示「error」，可能需要調整 `src/aiusageclock/providers/` 下的頁面擷取 JS — 應用程式的其餘部分仍可正常運作。
- **遠端桌面與沒有 GPU 的工作階段需要注意一點。** 這個小工具本身是純 Qt Widgets，可在任何環境執行，包括透過 RDP/XRDP，以及沒有 GPU 的機器。Claude 與 Codex 是透過驅動內嵌的 Chromium 來讀取的，這需要 OpenGL 環境；若工作階段既不提供 GLX 也不提供 EGL，就無法提供此環境。在這種情況下，這些區塊會回報需要瀏覽器，而 OpenCode Go、GitHub Copilot 與 OpenRouter 使用 API 憑證，可正常運作。大多數 Linux 桌面環境會透過 Mesa 提供軟體 GL，因此這只會發生在單純的 X 伺服器與部分遠端工作階段上。若 AI Usage Clock 誤判你的工作階段，請設定 `AIUSAGECLOCK_FORCE_WEBENGINE=1` 以略過檢查。
- Copilot REST 端點回傳的是帳單用量的目前日曆月資料。小工具追蹤的是已消耗的 AI 點數總額相對於內含額度的使用情形；淨數量／金額僅為需付費的超額部分。重置時間以下個月 1 日計算。GitHub 目前並未提供可靠的個人方案額度欄位，因此 Settings 使用方案下拉選單，並提供「自訂」作為備援。年繳／以請求次數計費的帳號，則以舊版 premium request 機制作為備援處理。
- **Copilot 用量會有延遲。** Copilot REST 端點的更新速度明顯比 Claude 或 Codex 慢 — 點數統計可能需要數小時才會反映最近的活動。小工具顯示的是 GitHub 回傳的最新數值；請將 Copilot 區塊視為落後指標，而非即時資料。
- **Copilot AI 點數。** GitHub 已將 Copilot 從依請求次數計算的額度，改為以 token 為基礎的 AI 點數。付費方案仍包含程式碼補全與下一步編輯建議，而 Chat、CLI、雲端代理、Spaces、Spark 與第三方程式碼代理則會消耗 AI 點數。應用程式顯示的是 GitHub 回傳的點數用量；若你的帳號由組織計費，請填入計費組織，讓 AI Usage Clock 讀取該組織的計費點數池。
- **OpenRouter 使用兩種金鑰類型。** 推論金鑰用於取得 `/key` 的花費資料。管理金鑰則是取得 `/credits` 帳戶餘額與 `/activity` 模型歷史所必需。沒有管理金鑰時，AI Usage Clock 仍會顯示金鑰層級的花費，但無法顯示餘額或模型活動。
- **OpenRouter 的時間區間以 UTC 為準。** 今日／本月花費取自 OpenRouter 目前的 UTC 日與月欄位。模型活動取自 OpenRouter 預設的 `/activity` 歷史區間：最近 30 個已完成的 UTC 日，不含目前的 UTC 日。
- **閒置的額度。** 用量為 0% 且計時區間尚未開始的額度會顯示 `idle`，而不是剩餘時間；等你下次使用它時才開始計時。
