---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# 授權 {#authorization}

透過 Streamable HTTP，MCP 伺服器就是一個普通的 Web 服務，保護它的方式也和保護任何 Web 服務一樣：用 OAuth 2.1 bearer 權杖。

以 OAuth 的術語來說，你的伺服器是**資源伺服器（resource server）**。它從不讓任何人登入，也從不發出權杖。它只做一件事：查看每個請求上的 `Authorization` 標頭，判斷裡面的權杖是否有效。

這一頁講的是伺服器端。會探索授權伺服器並取得權杖的用戶端，請見 **[OAuth 用戶端](../client/oauth-clients.md)**。

## 三方角色 {#the-three-parties}

* **授權伺服器**負責讓人登入並發出存取權杖。這個不用你寫，它就是你的身分提供者（Auth0、Keycloak、Entra，或你自己的）。
* **資源伺服器**就是你的 MCP 伺服器。它在每個請求上驗證權杖。
* **用戶端**會探索你信任哪個授權伺服器，從那裡取得權杖，再以 `Authorization: Bearer <token>` 的形式送回來給你。

整個三角關係就這樣。這一頁的所有內容都是中間那一項。

## 權杖驗證器 {#a-token-verifier}

有效的權杖長什麼樣子，SDK 沒有任何預設立場。由你來告訴它，方法是實作 **`TokenVerifier`**：

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` 是只有一個非同步方法的 protocol。`verify_token` 會拿到 `Authorization` 標頭裡的原始權杖，有效就回傳 **`AccessToken`**，無效就回傳 `None`。沒有別的需要實作。
* 這個範例是在一張表裡查權杖。真實的實作會驗證 JWT 簽章，或呼叫授權伺服器的權杖內省（token introspection）端點。那段程式碼是你的，SDK 只負責呼叫它。
* `token_verifier=` 和 `auth=` 永遠成對出現。只傳其中一個，`MCPServer(...)` 在服務任何請求之前就會引發 `ValueError`。

`AuthSettings` 是資源伺服器對外的門面：

* `issuer_url`：發出權杖的授權伺服器。
* `resource_server_url`：這個 MCP 端點的公開 URL。它指明權杖是給**哪一個**資源用的，也是探索文件所在的位置。
* `required_scopes`：每個權杖都必須帶有全部這些 scope。

!!! tip
    SDK 儲存庫裡的 `examples/servers/simple-auth/` 有一個 `IntrospectionTokenVerifier`，會呼叫真實授權伺服器的 [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) 端點。大多數正式環境的驗證器都是這個樣子。

## 透過 HTTP 會得到什麼 {#what-you-get-over-http}

授權存在於 HTTP 標頭裡，所以只存在於 HTTP 傳輸方式上。在你要部署的那一種上執行它：`mcp.run(transport="streamable-http")` 會把它放在 `http://127.0.0.1:8000/mcp`，其餘內容請見 **[執行伺服器](index.md)**。應用程式現在有兩個路由：

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

你註冊了一個工具。第二個路由是 SDK 的。

### 探索 {#discovery}

對那個 well-known 路徑發 `GET`，會得到 **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata**，直接從你的 `AuthSettings` 產生：

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

從沒聽過你伺服器的用戶端，就是靠這份文件找到門路的：它讀取 `authorization_servers`，再去那裡拿權杖。這些你一行都沒寫。

!!! check
    不帶權杖呼叫 `/mcp`（或帶一個驗證器回傳 `None` 的權杖），請求會被擋在門口：

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    什麼都沒被解析，也沒有工具執行。而 `WWW-Authenticate` 裡那個 `resource_metadata` 指標，正是讓探索自動化的關鍵：401 -> 中繼資料文件 -> 授權伺服器 -> 權杖 -> 重試。

!!! warning
    這些都不會保護 `stdio`。管道沒有 `Authorization` 標頭，所以在那裡永遠不會詢問 `token_verifier`。`stdio` 伺服器的安全邊界是啟動它的那個處理程序。測試裡用的記憶體內 `Client(mcp)` 也一樣：它直接連到伺服器物件，跳過了 HTTP 層，授權也一併跳過。

## 呼叫端的身分 {#the-callers-identity}

在任何處理函式內，**`get_access_token()`** 就是驗證器為目前請求回傳的那個 `AccessToken`：

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* 在工具、資源和提示詞裡都能用，也不需要傳來傳去：驗證中介軟體會依請求把它存在一個上下文變數裡。
* 拿回來的是**驗證器建立的同一個物件**：`client_id`、`scopes`、`subject`、`expires_at`，以及你附加的任何額外 `claims`。這就是逐工具規則的著力點：讀取 scope，然後拒絕。
* 在已驗證的 HTTP 請求之外，它回傳 `None`。記憶體內和透過 `stdio` 時，它永遠是 `None`。

用 `Authorization: Bearer alice-token` 呼叫 `whoami`，模型會讀到：

```text
alice (scopes: notes:read)
```

## SDK 不做的那一半 {#the-half-the-sdk-doesnt-do}

SDK 給你的是資源伺服器這一半：驗證、公告、拒絕。它不提供登入頁面、同意畫面，也不提供權杖。

想看三方實際互動，可以執行 SDK 儲存庫裡的 `examples/servers/simple-auth/`（一個小型授權伺服器，加上一個設定方式和這一頁完全相同的資源伺服器），再把 `examples/clients/simple-auth-client/` 指向它，跑一遍完整的探索與取得權杖流程。

!!! info
    還有第二個建構子引數 `auth_server_provider=`，會把完整的授權伺服器嵌進你的 MCP 伺服器裡。它出現的時間早於 MCP 授權規範所依據的 AS/RS 分離設計。新的伺服器不應該使用它。

授權伺服器也可以接受企業身分提供者簽署的斷言，取代使用者點選同意畫面的步驟，而 SDK 支援這種交換的兩端。這種授權方式，以及提出它的用戶端，請見 **[身分斷言](../client/identity-assertion.md)**。

## 重點回顧 {#recap}

* 透過 Streamable HTTP，你的伺服器是 OAuth 2.1 的**資源伺服器**：它驗證權杖，從不發出權杖。
* `TokenVerifier` 就是整個整合介面：一個非同步方法，權杖進去，`AccessToken | None` 出來。
* `token_verifier=` 和 `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` 永遠成對出現。
* SDK 會在 `/.well-known/oauth-protected-resource/...` 發布 [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata，並以 401 回應未驗證的請求，其 `WWW-Authenticate` 標頭會指向這份文件。整個探索機制就這樣。
* 在任何處理函式裡，`get_access_token()` 就是誰在呼叫。
* 授權是 HTTP 層的事。`stdio` 和記憶體內用戶端永遠看不到它。

用戶端那一半（探索你的授權伺服器並替你取得權杖）請見 **[OAuth 用戶端](../client/oauth-clients.md)**。至於不問使用者、而是直接**斷言**身分的用戶端，請見 **[身分斷言](../client/identity-assertion.md)**。
