---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# 在處理函式內部 {#inside-your-handler}

處理函式的引數來自用戶端。除此之外它能讀到的**其他**一切，以及執行時能做的一切，都在這裡。

它能讀到什麼：

* **[Context](context.md)** 是任何處理函式都能額外要求的那一個參數：進行中的請求、它的標頭、它的工作階段（session），以及進度與變更通知的操作。
* **[相依性](dependencies.md)** 是模型永遠看不到的參數，由你自己的函式透過 `Resolve` 填入。
* **[生命週期](lifespan.md)** 說明伺服器在啟動時只建立一次的狀態，以及處理函式如何透過 `Context` 取得它。

它執行時能做什麼：

* 用 **[徵詢](elicitation.md)**（elicitation）向使用者要求更多輸入，以及承載它的 2026-07-28 模式 **[多輪往返請求](multi-round-trip.md)**（multi-round-trip）。
* 用 **[取樣與根目錄](sampling-and-roots.md)**（sampling 與 roots）向用戶端要求 LLM 生成結果或它的工作區資料夾，這兩者已棄用但仍然提供。
* 對耗時的工作回報 **[進度](progress.md)**。
* 用 **[記錄](logging.md)** 寫入記錄（寫到標準錯誤輸出，給負責維運伺服器的人看）。
* 用 **[訂閱](subscriptions.md)** 告訴已訂閱的用戶端有東西變了。

如果還沒有註冊處理函式，請從 **[工具](../servers/tools.md)** 開始。這裡的每一頁都假設你已經有一個。
