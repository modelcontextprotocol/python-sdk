---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# 進階 {#advanced}

一般的伺服器或用戶端需要的東西，在前面的章節裡都有對應的主題可循。這一節是當 `MCPServer` 的便利層反而礙事時，可以拿來用的逃生門：

* **[低階 Server](low-level-server.md)**：`MCPServer` 建構於其上的類別。手寫的 schema、`on_*` 處理函式、沒有任何東西會幫你檢查，還可以加上自訂的 JSON-RPC 方法。
* **[分頁](pagination.md)** 和 **[中介軟體](middleware.md)**：兩件**只**能在低階 `Server` 上做的事。
* **[擴充功能](extensions.md)** 和 **[MCP Apps](apps.md)**：協定的擴充介面。把擴充功能套件組合進伺服器，或自己寫一個。

有幾樣東西你可能理所當然會來這裡找，但它們其實放在實際會用到的地方：

* **授權** 放在 **[執行伺服器](../run/index.md)** 底下，因為伺服器部署在哪裡，就在哪裡保護它。
* **OAuth**、**身分斷言**、連接 **多個伺服器**，以及回應 **快取**，都在 **[用戶端](../client/index.md)** 底下。
* **多輪往返（multi-round-trip）請求** 和 **訂閱** 放在 **[在處理函式內部](../handlers/index.md)** 底下，因為兩者都是處理函式 **會做** 的事。
* **URI 範本** 放在 **[伺服器](../servers/index.md)** 底下，就在資源旁邊。
* **[協定版本](../protocol-versions.md)** 和 **[已棄用的功能](../deprecated.md)** 則各有自己的頂層頁面。

如果不確定自己需不需要這一節，那就是不需要。
