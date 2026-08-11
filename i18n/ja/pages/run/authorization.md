---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# 認可 {#authorization}

Streamable HTTP を使うと、MCP サーバーはごく普通の Web サービスになります。保護の仕方もほかの Web サービスと同じで、OAuth 2.1 のベアラートークンを使います。

OAuth の用語でいえば、サーバーは**リソースサーバー**です。誰かをサインインさせることはなく、トークンを発行することもありません。やることは 1 つだけです。各リクエストの `Authorization` ヘッダーを見て、そこに入っているトークンが有効かどうかを判断します。

このページはサーバー側の話です。認可サーバーを見つけてトークンを取得するクライアントについては、**[OAuth クライアント](../client/oauth-clients.md)**を参照してください。

## 3 つの当事者 {#the-three-parties}

* **認可サーバー**はユーザーをサインインさせ、アクセストークンを発行します。これを自分で書くことはありません。ID プロバイダー（Auth0、Keycloak、Entra、自前のもの）がこれにあたります。
* **リソースサーバー**は MCP サーバーです。リクエストごとにトークンを検証します。
* **クライアント**は、サーバーがどの認可サーバーを信頼しているかを見つけ、そこからトークンを取得し、`Authorization: Bearer <token>` として送り返してきます。

三角形はこれで全部です。このページで扱うのはすべて真ん中の項目です。

## トークンベリファイアー {#a-token-verifier}

有効なトークンがどんな形をしているかについて、SDK は何の前提も持ちません。**`TokenVerifier`** を実装して、こちらから伝えます。

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` は非同期メソッドを 1 つだけ持つプロトコルです。`verify_token` は `Authorization` ヘッダーから取り出した生のトークンを受け取り、有効なら **`AccessToken`** を、無効なら `None` を返します。実装するものはほかにありません。
* この例ではトークンをテーブルから引いています。実際のものは JWT の署名を検証するか、認可サーバーのトークンイントロスペクションエンドポイントを呼び出します。そのコードは自分で書きます。SDK はそれを呼び出すだけです。
* `token_verifier=` と `auth=` は必ずセットで渡します。片方だけ渡すと、`MCPServer(...)` はリクエストを 1 つも処理しないうちに `ValueError` を送出します。

`AuthSettings` はリソースサーバーの表向きの顔です。

* `issuer_url`：トークンを発行する認可サーバー。
* `resource_server_url`：この MCP エンドポイントの公開 URL。トークンが「どの」リソース向けかを示す名前であり、ディスカバリードキュメントが置かれる場所でもあります。
* `required_scopes`：すべてのトークンがこれらをすべて持っている必要があります。

!!! tip
    SDK リポジトリの `examples/servers/simple-auth/` には、実際の認可サーバーの [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) エンドポイントを呼び出す `IntrospectionTokenVerifier` があります。本番用のベリファイアーの多くはこの形になります。

## HTTP で得られるもの {#what-you-get-over-http}

認可は HTTP ヘッダーに乗るので、HTTP トランスポートにしか存在しません。デプロイするトランスポートで実行してください。`mcp.run(transport="streamable-http")` とすると `http://127.0.0.1:8000/mcp` で動きます。そのほかについては**[サーバーの実行](index.md)**を参照してください。これでアプリには 2 つのルートができます。

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

登録したのはツール 1 つです。2 つ目のルートは SDK が用意したものです。

### ディスカバリー {#discovery}

この well-known パスに `GET` すると、`AuthSettings` からそのまま組み立てられた **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata** が返ります。

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

このサーバーのことを何も知らないクライアントは、このドキュメントを手がかりに入口を見つけます。`authorization_servers` を読み、そこへトークンを取りに行きます。このドキュメントは 1 行も自分では書いていません。

!!! check
    トークンなしで（あるいはベリファイアーが `None` を返したトークンで）`/mcp` を呼び出すと、リクエストは入口で止められます。

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    何もパースされず、ツールも実行されていません。そして `WWW-Authenticate` にある `resource_metadata` のポインターこそが、ディスカバリーを自動化する仕掛けです。401 -> メタデータドキュメント -> 認可サーバー -> トークン -> 再試行、という流れです。

!!! warning
    これらはどれも `stdio` を保護しません。パイプには `Authorization` ヘッダーがないので、そこで `token_verifier` が参照されることはありません。`stdio` サーバーのセキュリティ境界は、それを起動したプロセスです。テストで使うインメモリの `Client(mcp)` も同じです。サーバーオブジェクトに直接接続し、認可を含む HTTP レイヤーを丸ごと飛ばします。

## 呼び出し側の ID {#the-callers-identity}

どのハンドラーの中でも、**`get_access_token()`** は現在のリクエストに対してベリファイアーが返した `AccessToken` です。

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* ツール、リソース、プロンプトのどれでも動き、持ち回る必要のあるものはありません。認証ミドルウェアがリクエストごとにコンテキスト変数へ保存しています。
* 返ってくるのは**ベリファイアーが組み立てたのと同じオブジェクト**です。`client_id`、`scopes`、`subject`、`expires_at`、そして追加で付けた `claims` が入っています。ツールごとのルールはここに掛けます。スコープを読んで、拒否するだけです。
* 認証済みの HTTP リクエストの外では `None` を返します。インメモリと `stdio` では常に `None` です。

`Authorization: Bearer alice-token` を付けて `whoami` を呼び出すと、モデルは次のテキストを読みます。

```text
alice (scopes: notes:read)
```

## SDK がやらない半分 {#the-half-the-sdk-doesnt-do}

SDK が提供するのはリソースサーバーの半分、つまり検証、告知、拒否です。ログインページも、同意画面も、トークンも提供しません。

3 つの当事者すべてが動く様子を見るには、SDK リポジトリの `examples/servers/simple-auth/`（小さな認可サーバーと、このページとまったく同じように構成されたリソースサーバー）を実行し、そこへ `examples/clients/simple-auth-client/` を向けてください。ディスカバリーからトークン取得までの一連の流れを追えます。

!!! info
    コンストラクターにはもう 1 つ、`auth_server_provider=` という引数があり、完全な認可サーバーを MCP サーバーの中に埋め込みます。これは MCP の認可仕様が土台にしている AS/RS 分離より前からあるものです。新しく作るサーバーでは使うべきではありません。

認可サーバーは、ユーザーが同意画面をクリックして進む代わりに、企業の ID プロバイダーが署名したアサーションを受け付けることもできます。SDK はこのやり取りの両側をサポートしています。このグラントと、それを提示するクライアントについては、**[ID アサーション](../client/identity-assertion.md)**を参照してください。

## まとめ {#recap}

* Streamable HTTP では、サーバーは OAuth 2.1 の**リソースサーバー**です。トークンを検証しますが、発行することはありません。
* 統合の接点は `TokenVerifier` がすべてです。非同期メソッドが 1 つ、トークンを受け取り、`AccessToken | None` を返します。
* `token_verifier=` と `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` は必ずセットで渡します。
* SDK は [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata を `/.well-known/oauth-protected-resource/...` で公開し、未認証のリクエストには、そこを指す `WWW-Authenticate` ヘッダー付きの 401 で応答します。ディスカバリーの仕組みはこれだけです。
* どのハンドラーでも、`get_access_token()` を呼べば誰が呼び出しているかがわかります。
* 認可は HTTP の関心事です。`stdio` とインメモリクライアントがそれを目にすることはありません。

クライアント側の半分（認可サーバーを見つけてトークンを取得してくれる部分）については、**[OAuth クライアント](../client/oauth-clients.md)**を参照してください。そして、ユーザーに尋ねる代わりに ID を「アサート」するクライアントについては、**[ID アサーション](../client/identity-assertion.md)**を参照してください。
