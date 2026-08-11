---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# アイデンティティアサーション {#identity-assertion}

通常の OAuth プロバイダー（**[OAuth クライアント](oauth-clients.md)**）は、まず MCP サーバーに「どの認可サーバーを信頼しているか」を尋ねるところから始まります。返ってきた答えが指す先へどこまでも従い、そのうえで人がサインインするか、事前共有したシークレットがその代わりを務めます。

企業は、そのどちらもサーバーごとに決めたくはありません。企業はすでに ID プロバイダー（Okta、Microsoft Entra ID、自社製のもの）を運用しています。ユーザーは今朝すでにそこへサインイン済みです。そしてそこは、セキュリティチームが「誰が何に到達してよいか」を一か所で決めたい場所でもあります。**Enterprise-Managed Authorization** 拡張である [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) は、その判断をそこへ移します。IdP は有効期間の短い JWT、すなわち **Identity Assertion JWT Authorization Grant**（**ID-JAG**）に署名します。これは「このユーザーが、このクライアントを通じて、この MCP サーバーに到達してよい」という表明です。クライアントはそれを通常のアクセストークンと交換します。ブラウザーも、同意画面も、動的登録もありません。

このページでは、その交換の両端を扱います。MCP サーバー自体は何も変わりません。**[認可](../run/authorization.md)** で説明したリソースサーバーのまま、届いたトークンを何であれ検査します。

## 2 つのトークンリクエスト {#two-token-requests}

ここには 2 つの別々の権限主体が関わっています。両者を区別して呼び分けられれば、このページの大半は理解できたも同然です。**エンタープライズ IdP** は組織の ID プロバイダーです。従業員が誰であるかを知っており、ポリシーが置かれる場所であり、ID-JAG を発行します。SDK がこれと通信することはありません。**MCP 認可サーバー** は **[認可](../run/authorization.md)** のときと同じ当事者です。MCP サーバーのメタデータに名前が載っている発行者（issuer）であり、その MCP サーバーが受け入れるトークンを発行する存在です。通常の OAuth フローでは、この 2 つの役割はたいてい 1 つの箱に収まっています。ここでは 2 つに分かれており、このグラント全体は、後者が前者を信頼すると同意することにほかなりません。

クライアントは、それぞれに 1 回ずつトークンリクエストを送ります。

1. **エンタープライズ IdP へ。** クライアントはユーザーのサインイン（OpenID Connect の ID トークン）を ID-JAG と交換します。これは [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) のトークン交換であり、完全に IdP 側の API であって、**SDK はこのリクエストを行いません**。行うのは呼び出し側で、1 つの非同期コールバックの中で実装します。ポリシーの判断が下されるのもここです。IdP が拒否すれば ID-JAG は発行されず、提示するものは何もありません。
2. **MCP 認可サーバーへ。** クライアントは [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) の `jwt-bearer` グラント（`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`、ID-JAG を `assertion` として）で ID-JAG を提示し、アクセストークンを受け取ります。**SDK が行うのはこちらのリクエストです**。そしてこれを受け入れることが、このページが認可サーバーに追加する唯一の事柄です。

以降はすべて 2 番目のリクエストの話です。それを送るクライアントと、それに応答する認可サーバーを扱います。

## クライアント {#the-client}

**`IdentityAssertionOAuthProvider`** は `mcp.client.auth.extensions.identity_assertion` にあります。**[OAuth クライアント](oauth-clients.md)** のどのプロバイダーとも同じく `httpx2.Auth` です。インスタンスを作り、`auth=` に載せ、その `httpx2.AsyncClient` をトランスポートに渡します。

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

下から順に読んでいきます。

* `main()` は標準的な OAuth クライアントの `main()`（**[OAuth クライアント](oauth-clients.md)**）そのもので、1 行も変わっていません。そこが肝心です。プロバイダーさえできてしまえば、下流のどこも、どのグラントがトークンを生んだのかを知りません。
* プロバイダーが受け取るのは、ほかのプロバイダーには発見できないものです。誰かが認可サーバーに**事前登録**した `client_id` と `client_secret`、その認可サーバーの `issuer`、そして要求に応じて新しい ID-JAG を返す非同期コールバック `assertion_provider` です。
* `storage` は同じ `TokenStorage` プロトコルです。呼ばれるのは 2 つのトークンメソッドだけです。ここには動的登録がないので、覚えておくべき `client_info` もありません。

### アサーションプロバイダー {#the-assertion-provider}

自分で書くコードは `fetch_id_jag(audience, resource)` だけです。トークン交換のたびに 1 回 await され、構築時に呼ばれることはありません。しかも認可サーバーのメタデータを取得して検証した「後」でしか呼ばれないため、issuer の設定ミスでアサーションが漏れることはありません。2 つの引数は、ID-JAG の発行時に含めなければならないクレームのうちの 2 つです。`audience` は認可サーバーの issuer（ID-JAG の `aud`）、`resource` は MCP サーバーの正規識別子（ID-JAG の `resource`）です。3 つ目はすでに手元にあります。ID-JAG の `client_id` クレームは、プロバイダーに渡した `client_id` を指していなければならず、そうでなければ認可サーバーは交換を拒否します。

その上にある `idp_issue_id_jag` は**自分で書くコードではありません**。これは ID プロバイダーの代役で、ファイルが単体で完結し、ID-JAG が運ぶクレームをすべて読めるように、同一プロセス内でアサーションに署名しています。実際の `fetch_id_jag` は、代わりに前節の 1 番目のトークンリクエストを行います。すなわち IdP に対する [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) のトークン交換で、[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) がプロファイル化している Identity Assertion JWT Authorization Grant ドラフトで定義されています。サインイン済みユーザーの ID トークンが `subject_token` として入り、`requested_token_type` は ID-JAG 自身の URN（`urn:ietf:params:oauth:token-type:id-jag`）です。`audience` と `resource` はそのまま渡され、レスポンスが ID-JAG を運んできます。IdP のドキュメントで探すべきは、これらの名前を使ったこの交換です。

!!! tip
    交換のたびに新しい ID-JAG が要求されますが、それこそが狙いです。ID-JAG は使い切りで数分しか生きないグラントであり、このページの認可サーバーは同じものを 2 度受け入れることを拒否します。キャッシュしないでください。再利用されるのは、それで手に入れたアクセストークンのほうです。

### issuer は設定値 {#the-issuer-is-configuration}

ここに逆転があります。`OAuthClientProvider` は、どの認可サーバーを使うかをリソースサーバーに尋ね、返ってきた答えが指す先へどこまでも従います。このプロバイダーはそれを拒みます。`issuer` は必須で、[RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) のメタデータはその issuer 自身の well-known パスから取得されます。トークンエンドポイントはその issuer のオリジン上になければならず、リソースサーバーには何も尋ねません。

拡張仕様がこれを要求しているわけではありません。意図的に、より厳しくした選択です。このクライアントは盗む価値のあるものを 2 つ持っています。事前登録されたシークレットと、audience に束縛されたアサーションです。侵害された MCP サーバーに攻撃者の認可サーバーへ誘導されるのを許すクライアントなら、その両方をそこへ POST してしまうでしょう。構築時に issuer を固定すれば、そのやり取り自体がなくなります。

!!! warning
    設定した `issuer` は、メタデータ文書の `issuer` フィールドと RFC 8414 §3.3 の単純な文字列比較で照合されます。1 文字ずつ、末尾のスラッシュも含め、正規化なしです。推測しないでください。認可サーバーから `/.well-known/oauth-authorization-server` を取得し、返ってきた `issuer` の値をコピーしてください。このページの認可サーバーでは、それはスラッシュ付きの `https://auth.example.com/` です。issuer が pydantic の URL オブジェクトから組み立てられているためです。一致しない場合、クレデンシャルやアサーションが 1 つも送られる前に、`OAuthFlowError: Authorization server metadata issuer
    mismatch` でフローが止まります。

### コンフィデンシャルクライアント {#a-confidential-client}

`client_secret` は必須で、ないとコンストラクターが `ValueError` を送出します。[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) の下敷きになっている IETF プロファイルはこのグラントをコンフィデンシャルクライアント専用としており、SEP-990 はクライアントの認証を要求しています。この SDK は、共有シークレットを必須とすることでその両方を強制しています。`token_endpoint_auth_method` で、シークレットをどこに載せて送るかを選びます。`client_secret_post`（デフォルト、フォーム本体の中）か `client_secret_basic`（HTTP Basic ヘッダー）です。プロファイルは `private_key_jwt` も許可していますが、このプロバイダーはサポートしていません。

!!! tip
    `client_secret` は環境変数かシークレットマネージャーから読み込んでください。ソース管理には決して入れないでください。

### プロバイダーがしてくれること {#what-the-provider-does-for-you}

最初のリクエストは認証なしで送られ、サーバーの `401` がフローを開始します。

1. **ディスカバリー。** 設定した issuer の [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known パスから認可サーバーのメタデータを取得し、文書の `issuer` が一致することと、トークンエンドポイントが issuer のオリジン上にあることを確認します。
2. **アサーション。** `assertion_provider` を await します。
3. **交換。** `jwt-bearer` グラントをトークンエンドポイントに POST し、`OAuthToken` を保存し、元のリクエストを `Authorization: Bearer ...` 付きで再送します。

`WWW-Authenticate` に `insufficient_scope` が示された `403` では、指定した `scope` とチャレンジされたスコープの和集合で手順 2 と 3 をもう一度実行します。（`scope` はあくまで要求にすぎません。このページの認可サーバーは ID-JAG に書かれたものを付与し、それ以外は付与しません。）ここにはリフレッシュトークンはどこにもありません。アクセストークンが期限切れになると、次の `401` で新しい ID-JAG が発行されて再び交換が行われます。IdP が握っているレバーはまさに「そこ」です。失敗は **[OAuth クライアント](oauth-clients.md)** のほかの部分と同じ 2 つの例外です。ディスカバリーと検証には `OAuthFlowError`、トークンエンドポイントが拒否したときはそのサブクラスの `OAuthTokenError` です。

## 認可サーバー {#the-authorization-server}

たいていの場合、ここで終わりです。MCP 認可サーバーは誰か別の人の製品であり、ID-JAG の受け入れはその製品側で有効にする設定です。[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) のうち SDK が担う半分は、上のクライアントです。

SDK が認可サーバー「そのもの」になることもできます。`create_auth_routes` は認可サーバーのルートを、どんな Starlette アプリでもマウントできるリストとして返します。リポジトリの `examples/servers/simple-auth/` はそうやって認可サーバーを動かしています。SEP-990 は、そのインターフェースにフラグを 1 つとメソッドを 1 つ追加します。

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` がすべての門番です。オフ（これがデフォルト）のときは、フックを実装していても `/token` はこのグラントに `unsupported_grant_type` で応答し、メタデータにも載りません。オンにすると、メタデータに `jwt-bearer` グラントタイプが加わり、`authorization_grant_profiles_supported` に `urn:ietf:params:oauth:grant-profile:id-jag` が列挙されます。これは拡張仕様がサポートを告知するために使うフィールドです。（この SDK のクライアントはそれを読みません。1 つの issuer 向けにプロビジョニングされており、単に要求するだけです。）
* **`exchange_identity_assertion`** がフックです。これが実行される前に、SDK はクライアントを認証し、パブリッククライアントを拒否し、登録内容にこのグラントが含まれていないクライアントを拒否しています。受け取るのは `IdentityAssertionParams`（生の `assertion`、要求された `scopes` と `resource`）で、返すのは素の `OAuthToken` です。
* 動的クライアント登録はこのグラントを無条件に拒否するので、ここでの `get_client` は手作業でプロビジョニングしたクライアントを返します。ID-JAG クライアントが自分で自分を登録して存在するようになることはできません。
* クラスの半分は拒否です。`OAuthAuthorizationServerProvider` は認可サーバー「全体」なので、認可コードフローも求められます。ユーザーのサインインも行うサーバーならそれらを本当に実装しますが、このサーバーには入口がちょうど 1 つしかありません。

!!! warning
    SDK がアサーションをデコードすることは決してありません。どの IdP を信頼し、その IdP がどの鍵を公開しているかを知っているのはデプロイメントだけなので、`exchange_identity_assertion` の中身はすべてが安全性を支える要です。[RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3 に従い、IdP が公開している鍵（JWKS。ここでの共有シークレットはデモ用です）で署名を検証し、`iss` と `exp` も検証してください。JWT ヘッダーの `typ` が `oauth-id-jag+jwt` であることを要求してください。これは、別の JWT がグラントとして再利用されるのを防ぐプロファイルの防護策です。`aud` が自分自身の issuer であることを要求してください。ID-JAG の `client_id` クレームがハンドラーの認証したクライアントと一致すること、`resource` クレームが実際に提供しているリソースを指していることを要求してください。`jti` をアサーションの `exp` まで追跡し、一度しか受け入れないようにしてください。そして付与するスコープ、とりわけ発行するトークンの `resource` は、検証済みの ID-JAG から取り、リクエストからは決して取らないでください。`params.resource` はクライアントが入力したものにすぎません。処理ルールの全体は [Enterprise-Managed Authorization 仕様](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization) にあります。

不正なアサーションは `TokenError("invalid_grant", ...)` で拒否してください。このフローのもう 1 つのエラーコードは `invalid_target` です。提供していないリソースを指す ID-JAG はこれで拒否され、それによってこのサーバーが他人のリソース向けのトークンを発行するのを防ぎます。そして付与するスコープは ID-JAG の `scope` クレームから取ります（これを持たないアサーションも拒否されます）。実際のサーバーでは、代わりにユーザーのグループをマッピングするかもしれません。

返される `OAuthToken` が持っていないものにも注目してください。リフレッシュトークンです。IdP は、次の ID-JAG を発行するかどうかを決めることで、このユーザーがいつまでアクセスを保てるかを決めます。ここでリフレッシュトークンを発行してしまうと、その決定権をこっそり手放すことになります。

!!! info
    今も `auth_server_provider=` で認可サーバーを組み込んでいるサーバーは、`AuthSettings(identity_assertion_enabled=True)` を通じて同じコードに到達します。新しいサーバーがそこから始めるべきでない理由は **[認可](../run/authorization.md)** で説明しています。

!!! check
    このページの 2 つのファイルをつなぎ合わせると、グラント全体は 1 回の `POST /token` です。

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

    `/authorize` も、`/register` も、protected resource metadata の取得もありません。通信路に流れるリクエストは、`401` を引き出したもの、well-known の取得、この交換、そしてベアラートークンを付けた通常の MCP トラフィックだけです。そして、バリデーターが ID-JAG から読み取った `sub` は、ツールの中で `get_access_token().subject` が報告する値とまったく同じです。

### 試してみる {#try-it}

SDK リポジトリの `examples/stories/identity_assertion/` は、このページを実際に動かしたものです。同じ `exchange_identity_assertion` バリデーター、そのトークンで保護された MCP サーバー、代役の IdP、そしてクライアントが、1 つの自己検証プログラムにまとまっています。`uv run python -m stories.identity_assertion.client --http` で交換全体を実行し、IdP が名指ししたユーザーがツールから見えるユーザーであることを assert します。

## まとめ {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) により、クライアントがどの MCP サーバーに到達してよいかを、エンドユーザーではなく企業の ID プロバイダーが決められます。IdP はその決定を **ID-JAG** に署名して封じ込めます。
* ID-JAG の取得は「自分の IdP」に対する [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) のトークン交換であり、SDK は行いません。それを MCP 認可サーバーに提示するのが [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) の `jwt-bearer` グラントで、SDK はその両側を担います。
* `IdentityAssertionOAuthProvider` もまた `httpx2.Auth` の 1 つです。事前登録済みのコンフィデンシャルクライアント、固定した `issuer`、そして 1 つの `assertion_provider(audience, resource)` コールバックから成ります。ブラウザーも、登録も、リフレッシュトークンもありません。
* 認可サーバーがリソースサーバーから発見されることはありません。`issuer` には、そのメタデータ文書が返す文字列と完全に同じものを設定してください。比較は 1 文字ずつです。
* サーバー側は `identity_assertion_enabled=True` と `exchange_identity_assertion` です。SDK はクライアントを認証し、グラントの可否を判定します。ID-JAG の検証は完全に自分の責任で、発行されるトークンはリクエストのものではなく ID-JAG の `resource` に束縛されます。

このページが一度も触れなかった当事者が 1 つあります。MCP サーバーです。たった今発行したトークンで MCP サーバーが何をするかは、**[認可](../run/authorization.md)** ですでに行っていたことです。
