---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# 加到現有的應用程式中 {#add-to-an-existing-app}

`mcp.run("streamable-http")` 會幫你啟動一個網頁伺服器。有時候你不想要這樣：MCP 伺服器只是較大網頁應用程式的其中一塊，或者你早就有 ASGI 部署了。

這種情況下，`mcp.streamable_http_app()` 會回傳一個 **Starlette 應用程式**。

Starlette 應用程式就是 ASGI 應用程式，所以任何能承載 ASGI 的東西（uvicorn、Hypercorn、另一個 Starlette、FastAPI）都能承載你的 MCP 伺服器。

## 應用程式 {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` 是普通的 ASGI 應用程式。交給任何 ASGI 伺服器即可：

```console
uvicorn server:app
```

MCP 端點在 `/mcp`，所以用戶端要連到 `http://127.0.0.1:8000/mcp`。

這個應用程式已經自帶兩樣東西：

* 一條路由 `/mcp`：Streamable HTTP 端點。
* 一個**生命週期**（lifespan），負責啟動 `mcp.session_manager`，也就是掌管每個進行中工作階段（session）背景工作的那個物件。

單獨執行這個應用程式（`uvicorn server:app`），這兩件事你完全不用操心。

!!! tip
    `streamable_http_app()` 接受的關鍵字引數和 `mcp.run("streamable-http", ...)` 一樣，只是少了 `port`：連接埠屬於負責提供這個應用程式的那一層。`host` 仍然接受，但在這裡不會綁定任何東西；它實際控制什麼，**[部署與擴展](deploy.md)** 有說明。選項本身則請見 **[執行伺服器](index.md)**。

`mcp.sse_app()` 對已被取代的 SSE 傳輸做同樣的事。

## 只限 localhost，除非你另有指定 {#localhost-only-until-you-say-otherwise}

預設情況下，這個應用程式**只**回應送往 localhost 的請求。`streamable_http_app()` 無從得知自己會在哪個主機名稱後面提供服務，所以它用最保險的允許清單啟用 DNS 重新綁定防護；在你自己的機器上，這正好合適。部署到真正的主機名稱後面，就代表**每個請求都會以 `421 Misdirected Request` 被拒絕**，直到你透過 `transport_security=` 傳入一份你實際提供服務的主機允許清單為止。在那之前，請求根本到不了你寫的任何東西。這份允許清單，以及從一個能動的應用程式到真正主機名稱之間的其他一切，都在 **[部署與擴展](deploy.md)**。

## 掛載 {#mounting-it}

當 MCP 伺服器成為更大應用程式的**一部分**時，就要把這個應用程式放進 `Mount` 裡。而一旦這麼做，生命週期就成了你的責任：

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` 加上預設的 `/mcp` 路徑，端點仍然在 `/mcp`。Starlette 依序嘗試路由，而 `Mount("/")` 會比對到**每一個**路徑，所以你自己的路由要放在清單中它的**前面**。放在它後面的都到不了。
* `lifespan` 函式會在**外層**應用程式的整個存活期間進入 `mcp.session_manager.run()`。這就是大家都會忘記的那一行。
* `mcp.session_manager` 要在呼叫過 `streamable_http_app()` **之後**才存在。這就是為什麼路由在模組層級建立，而管理器只在生命週期裡才會碰到。

Starlette 的 `Host` 路由用法相同：把 `Mount("/", ...)` 換成 `Host("mcp.example.com", ...)`，就改成依主機名稱而非路徑來路由。生命週期的規則不變，傳輸安全的規則也不變。`Host("mcp.example.com", ...)` 路由只會收到送往該主機名稱的請求，但傳輸本身的 Host 允許清單（**[部署與擴展](deploy.md)**）仍然會先執行。清單裡沒有 `"mcp.example.com"` 的話，那條路由對每一個請求的回應都是 `421`。

!!! warning "生命週期歸外層應用程式管"
    `streamable_http_app()` 把 `session_manager.run()` 接進它回傳的那個 Starlette 的生命週期裡，但**被掛載的子應用程式，其生命週期永遠不會執行**。一旦掛載，內建的生命週期就成了死程式碼。位於 ASGI 堆疊最頂端的那個應用程式，必須在自己的生命週期裡進入 `mcp.session_manager.run()`。

!!! check
    刪掉 `lifespan=lifespan` 那一行再啟動伺服器。能啟動，路由也能解析。然後第一個送往 `/mcp` 的請求會失敗：

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    除了它自己的 `run()`，沒有任何東西會啟動工作階段管理器。

## 兩個伺服器，一個應用程式 {#two-servers-one-app}

每個 `MCPServer` 都是各自獨立的應用程式，有自己的工作階段管理器。想掛載幾個都可以；在外層那一個生命週期裡進入每一個管理器：

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` 會進入兩個管理器；它們一起啟動，並以相反順序關閉。
* 端點是 `/notes/mcp` 和 `/tasks/mcp`：掛載前綴加上預設路徑。

## 更改路徑 {#changing-the-path}

結尾那個 `/mcp` 就是 `streamable_http_path`。把它設成 `"/"`，掛載前綴就成了完整的對外路徑：

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

現在用戶端連到 `/notes`，而不是 `/notes/mcp`。

## 給瀏覽器用戶端的 CORS {#cors-for-browser-clients}

以瀏覽器為基礎的用戶端需要你給兩項許可：**送出**它的 MCP 請求標頭，以及**讀取** MCP 回傳的那一個標頭。兩者都是外層應用程式上的 CORS 設定，而上面的傳輸安全允許清單必須和它一致：

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` 是大家都會忘的那一半。瀏覽器對每個 MCP 請求都會做**預檢**，因為 `Content-Type: application/json` 和 `Mcp-*` 請求標頭不在 CORS 安全清單上，而預檢沒放行的標頭，就等於瀏覽器永遠不會送出的請求。（`allow_headers=["*"]` 也行：預檢要求什麼，Starlette 就回什麼。）
* `expose_headers=["Mcp-Session-Id"]` 是讀取那一半。Streamable HTTP 在那個回應標頭中回傳工作階段 ID，而除非 CORS 指名公開，瀏覽器會對 JavaScript 隱藏回應標頭。少了它，用戶端永遠發不出第二個請求。
* `allow_origins` 是你的決定，不是 MCP 的。要精確，並在上面的 `allowed_origins=` 中照樣設定：CORS 由瀏覽器強制執行，但伺服器自己也會檢查 `Origin`，傳輸不信任的來源即使預檢順利通過，仍會收到 `403`。
* `allow_methods` 列出 Streamable HTTP 用到的三個方法：`POST` 送出訊息、`GET` 開啟伺服器到用戶端的串流、`DELETE` 結束工作階段。

## 自訂路由 {#custom-routes}

`@mcp.custom_route()` 在同一個應用程式上註冊一個普通的 HTTP 端點，給每個部署的服務都需要、但和 MCP 毫無關係的東西用：健康檢查、OAuth 回呼。

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* 處理函式就是普通的 Starlette：一個從 `Request` 到 `Response` 的 `async` 函式。
* `streamable_http_app()` 會收進每一條自訂路由。`app.routes` 現在是 `/mcp` 和 `/health`。
* `GET /health` 回應 `{"status": "ok"}`，完全看不到 MCP 的影子。

!!! warning
    自訂路由**永遠不會經過驗證**，即使伺服器的其他部分有。這是刻意的：健康檢查和 OAuth 回呼必須在任何權杖存在之前就能連到。不要把任何私密的東西放在它後面。

## 重點回顧 {#recap}

* `mcp.streamable_http_app()` 回傳一個只有一條路由 `/mcp` 的 Starlette 應用程式。任何 ASGI 伺服器都能執行它。
* 預設情況下，這個應用程式只回應送往 localhost 的請求；放在真正的主機名稱後面時，在你透過 `transport_security=` 傳入允許清單之前，它會以 `421` 拒絕一切。這件事，以及通往正式環境的其餘路程，都歸 **[部署與擴展](deploy.md)** 管。
* `Mount`（或 `Host`）把它放進更大的 Starlette 或 FastAPI 應用程式裡。
* **掛載會停用內建的生命週期。**外層應用程式的生命週期必須進入 `mcp.session_manager.run()`，否則第一個請求就會失敗。
* 一個應用程式裡放多個伺服器，代表多個掛載，加上一個會進入每個工作階段管理器的生命週期。
* `streamable_http_path="/"` 把端點移到掛載前綴本身。
* 瀏覽器用戶端需要 CORS：`allow_headers` 給 `Mcp-*` 請求標頭用，`expose_headers=["Mcp-Session-Id"]` 給回應用。
* `@mcp.custom_route()` 在 `/mcp` 旁邊加上普通、不經驗證的 HTTP 端點。

一旦伺服器能透過真正的 URL 連到，**[用戶端](../client/index.md)** 就會用那個 URL 而不是伺服器物件來連線。
