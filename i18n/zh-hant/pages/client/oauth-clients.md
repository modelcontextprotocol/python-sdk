---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth 用戶端 {#oauth-clients}

有些 MCP 伺服器是受保護的。不帶權杖送請求過去，得到的回應是 `401 Unauthorized`。

**`OAuthClientProvider`** 就是取得權杖的方式。它根本不是 MCP 物件，而是一個 `httpx2.Auth`，也就是 httpx2 用來「對每個請求做點什麼」的標準掛鉤。把它掛在 `httpx2.AsyncClient` 上，再把那個用戶端交給 Streamable HTTP 傳輸，之後就不用再管它了。

這一頁講的是用戶端這一側。要讓自己的伺服器要求權杖，請見 **[授權](../run/authorization.md)**。

## Provider {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

要給它四樣東西：

* `server_url`：要連線的 MCP 端點。其餘的一切 provider 都會從這裡自行探索出來。
* `client_metadata`：就是你會在授權伺服器的「註冊應用程式」表單裡填的內容。
* `storage`：權杖在兩次執行之間存放的地方。
* `redirect_handler` 和 `callback_handler`：需要人介入的兩個時刻。

檔案裡其他地方都沒有提到 OAuth。`main()` 從頭到尾都看不到權杖。

### 用戶端中繼資料 {#client-metadata}

`OAuthClientMetadata` 就是貨真價實的 [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) 註冊文件，以 Pydantic 模型的形式呈現。

你設定三個欄位，其餘由預設值補上：`grant_types` 已經是 `["authorization_code", "refresh_token"]`，`response_types` 已經是 `["code"]`，正好就是這個 provider 執行的流程。

!!! check
    因為它是 Pydantic 模型，所以**在任何一個位元組送上網路之前**就會先驗證。漏掉 `redirect_uris`，建構當場就會失敗，引發一個指名該欄位的 `ValidationError`：

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    不會開啟瀏覽器，也不會在授權伺服器上留下做到一半的註冊。

### 權杖儲存 {#token-storage}

**`TokenStorage`** 是一個有四個非同步方法的 `Protocol`。不需要繼承任何東西；把這些方法寫出來，任何類別都能當權杖儲存庫：

* `get_tokens` / `set_tokens` 保存 `OAuthToken`：存取權杖、重新整理權杖、到期時間、範圍。
* `get_client_info` / `set_client_info` 保存授權伺服器在 provider 幫你註冊時發給你的 `OAuthClientInformationFull`，其中包含你的 `client_id`。

上面那個存在記憶體內的版本可以用。但處理程序結束時它就什麼都忘了，所以下次執行又得整套流程重來一遍。把它持久化到檔案或平台的鑰匙圈裡，下次執行就會安安靜靜。

!!! tip
    要存 `client_info`，不要只存權杖。provider 第一次找不到已儲存的 `client_info` 時會動態註冊。把它丟掉，每次執行就會產生一筆全新的註冊。

### 兩個處理函式 {#the-two-handlers}

授權碼流程只需要人介入一次：得有人登入並按下「允許」。

* **`redirect_handler`** 會帶著組裝完整的授權 URL 被 await。`client_id`、`redirect_uri`、`state` 和 PKCE challenge 都已經在裡面。你唯一的工作是讓瀏覽器開到那裡。桌面應用程式會呼叫 `webbrowser.open`；這個檔案則把它印出來。
* **`callback_handler`** 接著被 await。它會等到使用者回到你的 `redirect_uri`，再把那次重新導向的查詢參數以 `AuthorizationCodeResult` 回傳。

真正的用戶端會在重新導向 URI 上跑一個小型本機 HTTP 伺服器，而不是呼叫 `input()`。形狀完全一樣：接收重新導向，交回 `code`、`state` 和 `iss`。

!!! warning
    `state` 和 `iss` 要原封不動地傳回去。provider 會拿 `state` 與自己產生的那個比對，拿 `iss` 與探索到的 issuer 比對，不一致就拒絕。它們分別是 CSRF 與伺服器混淆攻擊的防線。

### 放進 `Client` {#into-the-client}

看看 `main()`。provider 掛在 **httpx2 用戶端**上，httpx2 用戶端放進 `streamable_http_client(url, http_client=...)`，那個傳輸再放進 `Client`。

`streamable_http_client` 沒有 `auth=` 關鍵字引數。凡是 HTTP 層級的東西（驗證、標頭、逾時、代理）都屬於你自備的 `httpx2.AsyncClient`。這種分層的說明請見 **[用戶端傳輸方式](transports.md)**。

## Provider 幫你做的事 {#what-the-provider-does-for-you}

`Client` 第一次送出請求時，伺服器回應 `401`。provider 接手：

1. **探索。** 讀取 `WWW-Authenticate` 標頭，從 `/.well-known/oauth-protected-resource` 抓取伺服器的 Protected Resource Metadata，得知是哪個授權伺服器在保護這個資源，再去抓取**那個**伺服器的中繼資料。
2. **註冊。** 儲存庫裡什麼都沒有？它會用你的 `OAuthClientMetadata` 動態註冊，並把結果存起來。
3. **授權。** 產生 PKCE 配對和一個 `state`，組出授權 URL，await 你的 `redirect_handler`，接著 await 你的 `callback_handler` 取得授權碼。
4. **交換。** 拿授權碼換得 `OAuthToken`，存起來，然後帶著 `Authorization: Bearer ...` 重送你原本的請求。

之後它就很安靜。權杖從儲存庫拿出來用，過期的存取權杖用重新整理權杖更新，只有這些都行不通時才會重跑整個流程。

這些你一行都沒寫。還剩兩個關鍵字引數（`client_metadata_url` 和 `validate_resource_url`），這個檔案兩個都用不到。值得認識的是 `client_metadata_url`，下面有它專屬的一節。

### 試試看 {#try-it}

這份文件裡的大多數範例都能用記憶體內的 `Client(server)` 檢驗。這個不行：整個流程的重點就是一個 HTTP `401`，而記憶體內的用戶端和它的伺服器之間根本沒有 HTTP。

儲存庫裡附有實際運作的版本。`examples/servers/simple-auth/` 會執行一個獨立的授權伺服器和一個受保護的 MCP 伺服器；`examples/clients/simple-auth-client/` 則是這一頁的用戶端長成的一個小型 CLI。它的 README 有那兩個指令：啟動伺服器、對著它們執行用戶端，就能看著上面四個步驟依序發生。

## Client ID Metadata Documents {#client-id-metadata-documents}

規格的 2026-07-28 修訂版已棄用動態用戶端註冊，改用 **Client ID Metadata Documents**（CIMD）。用戶端不再對遇到的每個授權伺服器 POST 一筆新的註冊，而是在一個穩定的 HTTPS URL 上發布一份描述自己的 JSON 文件，而那個 URL **就是**它的 `client_id`。文件由授權伺服器去抓取；provider 完全不碰它。

SDK 已經支援：建構 provider 時把那個 URL 以 `client_metadata_url=` 傳入即可。當授權伺服器的中繼資料宣告 `client_id_metadata_document_supported: true` 時，provider 會完全跳過 `/register` 請求：URL 以 `client_id` 的身分進入流程，而且沒有 `client_secret`。當伺服器沒有宣告（目前多數都還沒有），或者你根本沒傳 URL，provider 會**默默地**退回動態註冊，上面的一切照原樣運作。已儲存的 `client_info` 仍然優先於這兩者。

URL 必須是 HTTPS 且路徑不能是根路徑；否則在建構時就會引發 `ValueError`，不會發生任何網路動作。隨附的 `examples/clients/simple-auth-client/` 透過 `MCP_CLIENT_METADATA_URL` 環境變數接收它。

## 機器對機器 {#machine-to-machine}

夜間排程、CI 步驟、另一個服務。沒有瀏覽器，也沒有人可以按「允許」。這就是 **client credentials** 授權類型：你手上已經有 `client_id` 和 `client_secret`，權杖端點就是整個流程。

`ClientCredentialsOAuthProvider` 是同一個 `httpx2.Auth`，只是少了人：

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

改變的地方：

* 沒有 `OAuthClientMetadata`，沒有處理函式。傳入 `client_id` 和 `client_secret`；provider 會圍繞它們建出一筆最精簡的 `client_credentials` 註冊，並完全跳過動態註冊。
* `scope` 是以空格分隔的字串，也就是 OAuth 的線路格式。
* 下游的一切完全相同：同樣的 `TokenStorage`、同樣的 `httpx2.AsyncClient(auth=...)`、同樣的 `streamable_http_client`。

預設情況下，secret 在權杖請求中以 HTTP Basic 驗證傳送（`client_secret_basic`）。傳入 `token_endpoint_auth_method="client_secret_post"` 可改放進表單主體。有些授權伺服器只接受兩者其中之一。

!!! tip
    `client_secret` 要從環境變數或祕密管理工具讀取，絕對不要放進版本控制。

!!! info
    `mcp.client.auth.extensions.client_credentials` 裡還有一個 provider：**`PrivateKeyJWTOAuthProvider`**，給用 JWT 而非共用 secret 來驗證的用戶端使用（`private_key_jwt`，也就是金鑰對與工作負載身分那一類）。它遵循同樣的模式：建構一個，放到 `auth=` 上。同一個模組還附了 `SignedJWTParameters` 和 `static_assertion_provider`，兩個用來建出其 assertion 的輔助工具。

還有一種無人介入的情境：用戶端屬於某個企業，由企業的身分提供者（而非使用者）決定它可以連到哪些 MCP 伺服器。那是另一種授權類型，有自己的信任模型，也有自己的頁面：**[身分斷言](identity-assertion.md)**。

## 失敗的時候 {#when-it-fails}

OAuth 流程出錯時，provider 會引發來自 `mcp.client.auth` 的 `OAuthFlowError`。它有兩個子類別。`OAuthRegistrationError` 表示註冊沒有產生可用的用戶端：授權伺服器拒絕替你註冊，或者有註冊，但給的憑證是這個流程用不了的（例如它沒有實作的驗證方法）。`OAuthTokenError` 表示無法取得權杖：權杖端點拒絕了，或者已儲存的用戶端紀錄帶著這個用戶端無法套用的驗證方法——這會在組裝權杖請求時就回報，而不是送出之後。一個 `except OAuthFlowError:` 就能涵蓋探索、註冊、授權與交換。

不是所有問題都是流程錯誤。網路還是可能出錯；那些是一般的 `httpx2` 例外，會原封不動地往外傳遞。

## 重點回顧 {#recap}

* `OAuthClientProvider` 是一個 `httpx2.Auth`。放到 `httpx2.AsyncClient` 上，再把它傳給 `streamable_http_client(url, http_client=...)`，`Client` 永遠不會知道發生過 OAuth。
* 你提供四樣東西：伺服器 URL、一個 `OAuthClientMetadata`、一個 `TokenStorage`，以及 redirect/callback 這一對處理函式。
* `TokenStorage` 是一個 `Protocol`：四個非同步方法，沒有基底類別。除了權杖，也要持久化 `client_info`。
* 探索、註冊（動態的，或透過 **Client ID Metadata Document**）、PKCE、`state` 與 `iss` 檢查，以及權杖重新整理，都是 provider 的工作，不是你的。
* `ClientCredentialsOAuthProvider` 是無人介入的版本：`client_id` + `client_secret`，沒有處理函式，沒有瀏覽器。
* 每一種 OAuth 失敗都是 `OAuthFlowError`；`OAuthRegistrationError` 和 `OAuthTokenError` 是它的子類別。

這次交握的另一半，也就是讓你的**伺服器**要求權杖，請見 **[授權](../run/authorization.md)**。
