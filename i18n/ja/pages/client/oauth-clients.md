---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth クライアント {#oauth-clients}

一部の MCP サーバーは保護されています。トークンなしでリクエストを送ると、`401 Unauthorized` が返ってきます。

そのトークンを手に入れる手段が **`OAuthClientProvider`** です。これは MCP のオブジェクトではまったくありません。`httpx2.Auth`、つまり「すべてのリクエストに何かを施す」ための httpx2 標準のフックです。これを `httpx2.AsyncClient` に取り付け、そのクライアントを Streamable HTTP トランスポートに渡せば、あとは気にする必要がありません。

このページはクライアント側の話です。自分のサーバーにトークンを要求させる方法は **[認可](../run/authorization.md)** で扱います。

## プロバイダー {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

渡すものは 4 つです。

* `server_url`：接続先の MCP エンドポイント。プロバイダーはそれ以外のすべてをここから発見します。
* `client_metadata`：認可サーバーの「アプリケーションを登録する」フォームに入力するような内容。
* `storage`：実行と実行のあいだにトークンを保管しておく場所。
* `redirect_handler` と `callback_handler`：人間が関わる 2 つの場面。

ファイル内のほかの箇所には OAuth は一切登場しません。`main()` がトークンを目にすることはありません。

### クライアントメタデータ {#client-metadata}

`OAuthClientMetadata` は、本物の [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) 登録ドキュメントを Pydantic モデルにしたものです。

設定するフィールドは 3 つです。残りはデフォルト値が埋めてくれます。`grant_types` は最初から `["authorization_code", "refresh_token"]`、`response_types` は最初から `["code"]` で、これはまさにこのプロバイダーが実行するフローです。

!!! check
    Pydantic モデルなので、**ネットワークに 1 バイトも流れる前に**検証されます。
    `redirect_uris` を省くと、構築の時点でそのフィールド名を指した `ValidationError` で失敗します。

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    ブラウザーは開かず、認可サーバーに中途半端な登録が残ることもありません。

### トークンストレージ {#token-storage}

**`TokenStorage`** は 4 つの非同期メソッドを持つ `Protocol` です。何かを継承する必要はありません。メソッドを書けば、どんなクラスでもトークンストアになります。

* `get_tokens` / `set_tokens` は `OAuthToken`（アクセストークン、リフレッシュトークン、有効期限、スコープ）を保持します。
* `get_client_info` / `set_client_info` は、プロバイダーが登録したときに認可サーバーが発行した `OAuthClientInformationFull`（`client_id` を含む）を保持します。

上のインメモリ版はちゃんと動きます。ただしプロセスが終了するとすべてを忘れるので、次の実行では一連の手順を最初からやり直すことになります。ファイルやプラットフォームのキーリングに永続化すれば、次の実行は何も聞かれずに済みます。

!!! tip
    トークンだけでなく `client_info` も保存してください。プロバイダーは、保存済みの `client_info` が見つからない初回に動的登録を行います。これを捨ててしまうと、実行のたびに新しい登録を発行することになります。

### 2 つのハンドラー {#the-two-handlers}

認可コードフローで人間が必要になるのはちょうど一度だけです。誰かがサインインして「許可」をクリックしなければなりません。

* **`redirect_handler`** は、完全に組み立て済みの認可 URL を引数に await されます。`client_id`、`redirect_uri`、`state`、PKCE チャレンジはすでにその中に入っています。やるべきことはブラウザーをそこへ向かわせることだけです。デスクトップアプリなら `webbrowser.open` を呼び、このファイルでは表示するだけです。
* 次に **`callback_handler`** が await されます。ユーザーが `redirect_uri` に戻ってくるまで待ち、そのリダイレクトのクエリパラメーターを `AuthorizationCodeResult` として返します。

実際のクライアントは、`input()` を呼ぶ代わりにリダイレクト URI 上で小さなローカル HTTP サーバーを動かします。形はまったく同じです。リダイレクトを受け取り、`code`、`state`、`iss` を返します。

!!! warning
    `state` と `iss` は届いたとおりそのまま渡してください。プロバイダーは `state` を自分が生成したものと、`iss` を発見した発行者と照合し、一致しなければ拒否します。これらは CSRF とサーバー取り違えに対する防御です。

### `Client` へ {#into-the-client}

`main()` を見てください。プロバイダーは **httpx2 クライアント**に載り、httpx2 クライアントは `streamable_http_client(url, http_client=...)` に入り、そのトランスポートが `Client` に入ります。

`streamable_http_client` には `auth=` キーワードがありません。HTTP レベルのもの（認証、ヘッダー、タイムアウト、プロキシ）はすべて、持ち込む `httpx2.AsyncClient` に設定します。このレイヤー構成については **[クライアントのトランスポート](transports.md)** を参照してください。

## プロバイダーがやってくれること {#what-the-provider-does-for-you}

`Client` が初めてリクエストを送ると、サーバーは `401` を返します。そこからプロバイダーが引き継ぎます。

1. **発見。** `WWW-Authenticate` ヘッダーを読み、サーバーの Protected Resource Metadata を `/.well-known/oauth-protected-resource` から取得します。そこからこのリソースを保護している認可サーバーを知り、「その」サーバーのメタデータを取得します。
2. **登録。** ストレージに何もなければ、`OAuthClientMetadata` を使って動的に登録し、結果を保存します。
3. **認可。** PKCE のペアと `state` を生成し、認可 URL を組み立て、`redirect_handler` を await します。続いて、コードを受け取るために `callback_handler` を await します。
4. **交換。** コードを `OAuthToken` と引き換えて保存し、元のリクエストを `Authorization: Bearer ...` 付きで再送します。

それ以降は静かになります。トークンはストレージから取り出され、期限切れのアクセストークンはリフレッシュトークンで更新されます。そのどれもうまくいかないときだけ、フローをもう一度実行します。

これらを自分で書く必要はまったくありませんでした。残るキーワード引数は 2 つ（`client_metadata_url` と `validate_resource_url`）で、このファイルではどちらも不要です。知っておく価値があるのは `client_metadata_url` のほうで、下に専用のセクションがあります。

### 試してみる {#try-it}

このドキュメントの例のほとんどは、インメモリの `Client(server)` で確認できます。これは違います。このフローの要点は HTTP の `401` であり、インメモリのクライアントとサーバーのあいだには HTTP がありません。

リポジトリには実際に動くバージョンが同梱されています。`examples/servers/simple-auth/` はスタンドアロンの認可サーバーと保護された MCP サーバーを動かし、`examples/clients/simple-auth-client/` はこのページのクライアントを小さな CLI に育てたものです。その README に 2 つのコマンドが載っています。サーバーを起動し、それに対してクライアントを実行すれば、4 つのステップが進んでいくのを見られます。

## Client ID Metadata Documents {#client-id-metadata-documents}

仕様の 2026-07-28 改訂では、動的クライアント登録が非推奨になり、代わりに **Client ID Metadata Documents**（CIMD）が推奨されます。出会う認可サーバーごとに新しい登録を POST する代わりに、クライアントは自分自身についての JSON ドキュメントを 1 つ、安定した HTTPS URL で公開します。そしてその URL がそのまま `client_id` になります。ドキュメントを取得するのは認可サーバーで、プロバイダーはそれに一切触れません。

SDK はすでにこれに対応しています。プロバイダーを構築するときに URL を `client_metadata_url=` として渡してください。認可サーバーのメタデータが `client_id_metadata_document_supported: true` を公表していれば、プロバイダーは `/register` リクエストを完全に省きます。URL が `client_id` としてフローに入り、`client_secret` はありません。サーバーがそれを公表していない場合（まだ大半がそうです）、または URL を渡さなかった場合、プロバイダーは**何も言わずに**動的登録にフォールバックし、上の説明どおりにすべてが動きます。保存済みの `client_info` は、依然としてそのどちらよりも優先されます。

URL は HTTPS で、ルート以外のパスを持っている必要があります。それ以外は、ネットワーク通信が起こる前の構築時点で `ValueError` になります。同梱の `examples/clients/simple-auth-client/` は、これを `MCP_CLIENT_METADATA_URL` 環境変数として受け取ります。

## マシン間通信 {#machine-to-machine}

夜間ジョブ、CI のステップ、別のサービス。ブラウザーはなく、「許可」をクリックする人もいません。これが **クライアントクレデンシャル** グラントです。`client_id` と `client_secret` はすでに手元にあり、トークンエンドポイントがフローのすべてです。

`ClientCredentialsOAuthProvider` は同じ `httpx2.Auth` で、人間がいないだけです。

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

変わった点は次のとおりです。

* `OAuthClientMetadata` もハンドラーもありません。`client_id` と `client_secret` を渡すと、プロバイダーはそれらを中心に最小限の `client_credentials` 登録を組み立て、動的登録を完全に省きます。
* `scope` はスペース区切りの文字列で、OAuth の通信上の形式です。
* その先はすべて同じです。同じ `TokenStorage`、同じ `httpx2.AsyncClient(auth=...)`、同じ `streamable_http_client` です。

デフォルトでは、シークレットはトークンリクエストの HTTP Basic 認証として送られます（`client_secret_basic`）。代わりにフォームボディに入れるには、`token_endpoint_auth_method="client_secret_post"` を渡してください。認可サーバーによっては、2 つのうち片方しか受け付けません。

!!! tip
    `client_secret` は環境変数かシークレットマネージャーから読み込んでください。ソース管理からは決して読み込まないでください。

!!! info
    `mcp.client.auth.extensions.client_credentials` にはもう 1 つプロバイダーがあります。
    **`PrivateKeyJWTOAuthProvider`** は、共有シークレットの代わりに JWT で認証するクライアント向けです（`private_key_jwt`、つまり鍵ペアやワークロードアイデンティティの方式）。パターンは同じで、1 つ構築して `auth=` に載せます。同じモジュールには、そのアサーションを組み立てる 2 つのヘルパー、`SignedJWTParameters` と `static_assertion_provider` も含まれています。

人間がいない状況はもう 1 つあります。クライアントが企業に属していて、どの MCP サーバーに到達してよいかをユーザーではなくその企業のアイデンティティプロバイダーが決める場合です。これは独自の信頼モデルを持つ別のグラントで、専用のページ **[アイデンティティアサーション](identity-assertion.md)** があります。

## 失敗したとき {#when-it-fails}

OAuth フローがうまくいかないと、プロバイダーは `mcp.client.auth` の `OAuthFlowError` を送出します。これには 2 つのサブクラスがあります。`OAuthRegistrationError` は、登録の結果として使えるクライアントが得られなかったことを意味します。認可サーバーが登録を拒否したか、登録はされたもののこのフローでは使えないクレデンシャル（たとえば実装していない認証方式）だった場合です。`OAuthTokenError` は、トークンを取得できなかったことを意味します。トークンエンドポイントに拒否されたか、保存済みのクライアントレコードにこのクライアントが適用できない認証方式が含まれていた場合で、後者は送信されずにトークンリクエストの組み立て中に報告されます。`except OAuthFlowError:` 1 つで、発見、登録、認可、交換のすべてをカバーできます。

すべてがフローエラーというわけではありません。ネットワークが失敗することもあります。それらは通常の `httpx2` の例外で、手を加えられずにそのまま通り抜けます。

## まとめ {#recap}

* `OAuthClientProvider` は `httpx2.Auth` です。`httpx2.AsyncClient` に載せ、それを `streamable_http_client(url, http_client=...)` に渡せば、`Client` は OAuth が行われたことを知ることすらありません。
* 渡すものは 4 つです。サーバーの URL、`OAuthClientMetadata`、`TokenStorage`、そしてリダイレクト／コールバックのハンドラーのペアです。
* `TokenStorage` は `Protocol` です。非同期メソッドが 4 つで、基底クラスはありません。トークンだけでなく `client_info` も永続化してください。
* 発見、登録（動的、または **Client ID Metadata Document** 経由）、PKCE、`state` と `iss` のチェック、トークンの更新はプロバイダーの仕事であり、呼び出し側の仕事ではありません。
* `ClientCredentialsOAuthProvider` は人間がいない版です。`client_id` と `client_secret` だけで、ハンドラーもブラウザーも要りません。
* OAuth の失敗はすべて `OAuthFlowError` です。`OAuthRegistrationError` と `OAuthTokenError` がそのサブクラスです。

このハンドシェイクのもう半分、つまり「サーバー」にトークンを要求させる方法は **[認可](../run/authorization.md)** で扱います。
