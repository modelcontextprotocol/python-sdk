---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# 身分斷言 {#identity-assertion}

一般的 OAuth provider（**[OAuth 用戶端](oauth-clients.md)**）一開始會先問 MCP 伺服器一個問題：「你信任哪一個授權伺服器？」答案指向哪裡它就跟到哪裡，接著要嘛有人登入，要嘛用預先共享的密鑰代替。

企業兩者都不想交給每台伺服器各自決定。它早就有一個身分提供者（Okta、Microsoft Entra ID，或你自己的）；使用者今天早上就已經登入過了；而且安全團隊希望只在這一個地方決定誰能存取什麼。[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)，也就是 **Enterprise-Managed Authorization** 擴充功能，把決定權移到那裡。IdP 會簽署一個短效的 JWT，**Identity Assertion JWT Authorization Grant**，簡稱 **ID-JAG**：宣告**這位使用者**透過**這個用戶端**可以存取**這台 MCP 伺服器**。用戶端拿它換一個普通的存取權杖。沒有瀏覽器、沒有同意畫面、沒有動態註冊。

這一頁講的是這筆交換的兩端。MCP 伺服器本身完全不變：它仍然是 **[授權](../run/authorization.md)** 裡的資源伺服器，檢查送上門的任何權杖。

## 兩個權杖請求 {#two-token-requests}

這裡有兩個不同的權威機構在運作，把它們分開命名，幾乎就等於讀懂這一頁。**企業 IdP** 是你所屬組織的身分提供者：它知道員工是誰，政策放在它那裡，ID-JAG 也由它簽發。SDK 從不跟它對話。**MCP 授權伺服器**和 **[授權](../run/authorization.md)** 裡是同一個角色：MCP 伺服器中繼資料裡指名的簽發者，負責簽發該 MCP 伺服器接受的權杖。在一般的 OAuth 流程裡，這兩個角色通常是同一台機器。這裡它們是兩台，而整個授權流程就是後者同意信任前者。

用戶端對兩者各發一個權杖請求。

1. **對企業 IdP。** 用戶端拿使用者的登入結果（他們的 OpenID Connect ID 權杖）換 ID-JAG。這是一次 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 權杖交換，完全是你 IdP 的 API，而且 **SDK 不會發這個請求**。由你在一個非同步回呼裡完成。政策決定也發生在這裡：IdP 如果拒絕，就根本不會簽發 ID-JAG，也就沒有東西可以出示。
2. **對 MCP 授權伺服器。** 用戶端以 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) 的 `jwt-bearer` 授權類型出示 ID-JAG（`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`，ID-JAG 放在 `assertion`），然後收到存取權杖。**這是 SDK 會發的請求**，而接受它，就是這一頁替授權伺服器加上的唯一一件事。

以下全部都是第二個請求：送出它的用戶端，以及回應它的授權伺服器。

## 用戶端 {#the-client}

**`IdentityAssertionOAuthProvider`** 位於 `mcp.client.auth.extensions.identity_assertion`。和 **[OAuth 用戶端](oauth-clients.md)** 裡的每個 provider 一樣，它是一個 `httpx2.Auth`：建立一個，放到 `auth=`，再把 `httpx2.AsyncClient` 交給傳輸。

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

從下往上讀。

* `main()` 就是標準 OAuth 用戶端的 `main()`（**[OAuth 用戶端](oauth-clients.md)**），一行都沒改。重點正是這個：一旦 provider 存在，下游沒有任何東西知道權杖是哪一種授權類型產生的。
* 這個 provider 接收其他 provider 無法自行探索到的東西：有人事先向授權伺服器**預先註冊**好的 `client_id` 和 `client_secret`、該授權伺服器的 `issuer`，以及 `assertion_provider`，一個依需求回傳全新 ID-JAG 的非同步回呼。
* `storage` 是同一個 `TokenStorage` 協定。只會呼叫那兩個權杖方法；這裡沒有動態註冊，所以沒有 `client_info` 需要記住。

### 斷言提供者 {#the-assertion-provider}

`fetch_id_jag(audience, resource)` 是你唯一要寫的程式碼。每次權杖交換會 await 它一次，建立時從不呼叫，而且只在授權伺服器的中繼資料已取回並驗證**之後**才呼叫，所以設定錯誤的 issuer 永遠不會洩漏斷言。它的兩個引數是簽發 ID-JAG 時必須帶有的其中兩個 claim：`audience` 是授權伺服器的簽發者（ID-JAG 的 `aud`），`resource` 是 MCP 伺服器的正規識別碼（ID-JAG 的 `resource`）。第三個你手上已經有了：ID-JAG 的 `client_id` claim 必須指名你交給 provider 的那個 `client_id`，否則授權伺服器會拒絕交換。

上面的 `idp_issue_id_jag` **不是你的程式碼**。它代替身分提供者，在處理程序內簽署斷言，讓這個檔案能完整執行，你也能讀到 ID-JAG 帶有的每一個 claim。真正的 `fetch_id_jag` 會改發上一節的第一個權杖請求：對你的 IdP 做一次 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 權杖交換，定義在 Identity Assertion JWT Authorization Grant 草案裡，[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 則是該草案的 profile。已登入使用者的 ID 權杖作為 `subject_token` 送進去，`requested_token_type` 是 ID-JAG 自己的 URN（`urn:ietf:params:oauth:token-type:id-jag`），`audience` 和 `resource` 原樣傳過去，回應裡就帶著 ID-JAG。到你 IdP 的說明文件裡要找的，就是這些名稱底下的這個交換。

!!! tip
    每次交換都會請求一個全新的 ID-JAG，而這正是重點：它是單次使用、只活幾分鐘的授權，而且這一頁的授權伺服器拒絕接受同一個兩次。不要快取它。會被重複使用的，是它幫你換來的存取權杖。

### issuer 是設定值 {#the-issuer-is-configuration}

反轉的地方在這裡。`OAuthClientProvider` 會問資源伺服器該用哪一個授權伺服器，答案指向哪裡就跟到哪裡。這個 provider 拒絕這麼做：`issuer` 是必填，[RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) 中繼資料從該 issuer 自己的 well-known 路徑取回，權杖端點必須位於該 issuer 的 origin 上，而且從不向資源伺服器詢問任何事。

擴充功能並沒有要求這樣做；這是刻意更嚴格的選擇。這個用戶端帶著兩樣值得偷的東西，一個預先註冊的密鑰和一個綁定 audience 的斷言，而如果用戶端任由遭入侵的 MCP 伺服器把它導向攻擊者的授權伺服器，這兩樣都會 POST 過去。在建立時就釘死 issuer，等於把這段對話整個刪掉。

!!! warning
    設定的 `issuer` 會依 RFC 8414 §3.3 的簡單字串比對，和中繼資料文件的 `issuer` 欄位比較：逐字元比對，結尾斜線也算，沒有任何正規化。不要用猜的。從你的授權伺服器抓 `/.well-known/oauth-authorization-server`，把它回傳的 `issuer` 值複製過來。以這一頁的授權伺服器來說是 `https://auth.example.com/`，帶斜線，因為它的 issuer 是從 pydantic 的 URL 物件建出來的。不相符的話，流程會在送出任何一個憑證或斷言之前，就停在 `OAuthFlowError: Authorization server metadata issuer
    mismatch`。

### 機密用戶端 {#a-confidential-client}

`client_secret` 是必填；沒有它，建構子會引發 `ValueError`。[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 底下的 IETF profile 把這種授權類型保留給機密用戶端，SEP-990 要求用戶端必須驗證身分，而這個 SDK 以堅持要有共享密鑰的方式同時強制這兩點。`token_endpoint_auth_method` 決定它走哪裡：`client_secret_post`（預設，放在表單主體）或 `client_secret_basic`（HTTP Basic 標頭）。profile 也允許 `private_key_jwt`；這個 provider 不支援。

!!! tip
    從環境變數或密鑰管理服務讀取 `client_secret`，永遠不要從版本控制裡讀。

### provider 替你做的事 {#what-the-provider-does-for-you}

第一個請求不帶驗證就送出，伺服器的 `401` 啟動整個流程。

1. **探索。** 從設定的 issuer 的 [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known 路徑取回授權伺服器中繼資料，檢查文件的 `issuer` 相符，並檢查權杖端點位於 issuer 的 origin 上。
2. **斷言。** await 你的 `assertion_provider`。
3. **交換。** 把 `jwt-bearer` 授權 POST 到權杖端點，儲存 `OAuthToken`，然後帶著 `Authorization: Bearer ...` 重送你原本的請求。

`WWW-Authenticate` 指名 `insufficient_scope` 的 `403`，會用你的 `scope` 和被質疑的 scope 的聯集，再跑一次步驟 2 和 3。（`scope` 永遠只是請求；這一頁的授權伺服器只核發 ID-JAG 上寫的，其他一概不給。）整個過程裡沒有任何更新權杖：存取權杖過期時，下一個 `401` 會簽發一個全新的 ID-JAG 再交換一次，而**那**正是 IdP 握在手上的控制桿。失敗和 **[OAuth 用戶端](oauth-clients.md)** 其他部分一樣是那兩個例外：探索和驗證用 `OAuthFlowError`，權杖端點拒絕時則是它的子類別 `OAuthTokenError`。

## 授權伺服器 {#the-authorization-server}

大多數時候你到這裡就停了。MCP 授權伺服器是別人的產品，接受 ID-JAG 是它要開啟的設定，而 SDK 在 [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 裡負責的那一半，就是上面的用戶端。

SDK 也可以自己**當**授權伺服器：`create_auth_routes` 以任何 Starlette 應用程式都能掛載的清單形式回傳授權伺服器的路由，儲存庫裡的 `examples/servers/simple-auth/` 就是這樣跑起一個的。SEP-990 在這個介面上加了一個旗標和一個方法：

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` 管控一切。關閉時（這是預設），即使你實作了 hook，`/token` 也會以 `unsupported_grant_type` 回應這種授權類型，中繼資料也不會提到它。開啟時，中繼資料會多出 `jwt-bearer` 授權類型，並在 `authorization_grant_profiles_supported` 裡列出 `urn:ietf:params:oauth:grant-profile:id-jag`，也就是擴充功能用來宣傳支援的欄位。（這個 SDK 的用戶端從不讀它：它只為一個 issuer 佈建，直接開口問就是了。）
* **`exchange_identity_assertion`** 就是那個 hook。在它執行之前，SDK 已經驗證了用戶端、拒絕了公開用戶端，也拒絕了註冊資料裡沒列出這種授權類型的用戶端。你會拿到一個 `IdentityAssertionParams`（原始的 `assertion`、請求的 `scopes` 和 `resource`），回傳一個普通的 `OAuthToken`。
* 動態用戶端註冊無條件拒絕這種授權類型，所以這裡的 `get_client` 提供的是手動佈建的用戶端。ID-JAG 用戶端沒辦法靠自己註冊而存在。
* 這個類別有一半是拒絕。`OAuthAuthorizationServerProvider` 是**整個**授權伺服器，所以它也要求授權碼流程；同時讓使用者登入的伺服器會真的實作那些，而這一台只有一扇門。

!!! warning
    SDK 從不解碼斷言：只有你的部署知道它信任哪一個 IdP、那個 IdP 發布哪些金鑰，所以 `exchange_identity_assertion` 裡的每一行都至關重要。依 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3，用 IdP 發布的金鑰（它的 JWKS；這裡的共享密鑰只是示範用）驗證簽章，以及 `iss` 和 `exp`。要求 JWT 標頭的 `typ` 是 `oauth-id-jag+jwt`，這是 profile 防止其他 JWT 被拿來重播成授權的防線。要求 `aud` 是你自己的 issuer。要求 ID-JAG 的 `client_id` claim 等於處理函式驗證過的用戶端，且它的 `resource` claim 指名的是你確實有提供的資源。追蹤 `jti` 直到斷言的 `exp`，讓它只被接受一次。還有，核發的 scope，以及最重要的、簽發權杖的 `resource`，都要從驗證過的 ID-JAG 取得，永遠不要從請求取得：`params.resource` 是用戶端隨便打的東西。完整的處理規則在 [Enterprise-Managed Authorization 規格](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization)裡。

用 `TokenError("invalid_grant", ...)` 拒絕不合格的斷言。這個流程裡另一個錯誤碼是 `invalid_target`：指名了你沒提供的資源的 ID-JAG 會用它拒絕，這正是阻止這台伺服器替別人的資源簽發權杖的機制。而核發的 scope 來自 ID-JAG 的 `scope` claim（沒有這個 claim 的斷言也會被拒絕）；你的實作也許會改成對應使用者的群組。

再注意回傳的 `OAuthToken` 沒有帶的東西：更新權杖。IdP 透過決定是否簽發下一個 ID-JAG，來決定這位使用者能保有存取權多久。在這裡簽發更新權杖，等於悄悄把這個決定權交回去。

!!! info
    仍以 `auth_server_provider=` 內嵌授權伺服器的伺服器，透過 `AuthSettings(identity_assertion_enabled=True)` 走到同一段程式碼。**[授權](../run/authorization.md)** 說明了為什麼新的伺服器不該從那裡開始。

!!! check
    把這一頁的兩個檔案接在一起，整個授權流程就是一個 `POST /token`：

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    沒有 `/authorize`、沒有 `/register`、沒有抓 protected-resource 中繼資料。線路上僅有的請求是引來 `401` 的那一個、well-known 的抓取、這次交換，然後就是帶著 bearer 的普通 MCP 流量。而你的驗證器從 ID-JAG 讀出的 `sub`，正是工具裡 `get_access_token().subject` 回報的值。

### 試試看 {#try-it}

SDK 儲存庫裡的 `examples/stories/identity_assertion/` 就是這一頁的實際執行版：同一個 `exchange_identity_assertion` 驗證器、一台以它的權杖把關的 MCP 伺服器、一個替身 IdP，和用戶端，全放在一個會自我檢查的程式裡。`uv run python -m stories.identity_assertion.client --http` 會跑完整個交換，並斷言 IdP 指名的使用者就是工具看到的使用者。

## 重點回顧 {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 讓企業身分提供者（而不是終端使用者）決定用戶端可以存取哪些 MCP 伺服器。IdP 把這個決定簽進一個 **ID-JAG** 裡。
* 取得 ID-JAG 是對**你的 IdP** 做的 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 權杖交換，SDK 不做這件事。把它出示給 MCP 授權伺服器是 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) 的 `jwt-bearer` 授權類型，SDK 兩端都做。
* `IdentityAssertionOAuthProvider` 是另一個 `httpx2.Auth`：一個預先註冊的機密用戶端、一個釘死的 `issuer`，和一個 `assertion_provider(audience, resource)` 回呼。沒有瀏覽器、沒有註冊、沒有更新權杖。
* 授權伺服器從不透過資源伺服器探索。把 `issuer` 設定成和它中繼資料文件提供的字串一模一樣；比對是逐字元的。
* 伺服器端是 `identity_assertion_enabled=True` 加上 `exchange_identity_assertion`。SDK 驗證用戶端並管控授權類型；驗證 ID-JAG 完全是你的事，而簽發的權杖綁定的是 ID-JAG 的 `resource`，不是請求的。

這一頁唯一沒碰過的角色是 MCP 伺服器。它拿你剛簽發的權杖做什麼，早在 **[授權](../run/authorization.md)** 裡就已經在做了。
