---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# v2 の新機能 {#whats-new-in-v2}

v2 では 2 つのことが同時に起こりました。1 つは **SDK の再構築**です。クライアントとサーバーの両方の下に新しいエンジンが入り、第一級の `Client` が加わり、v1 のコードベースが最初のインポートでぶつかる一連の名前変更があります。もう 1 つは**プロトコルの移行**です。v2 が話すのは MCP の 2026-07-28 リビジョンで、このリビジョンは接続のハンドシェイク、セッション、そしてサーバー起点のリクエストをすべて取り除きます。それでも、すでに使われているクライアントを置き去りにはしません。

このページはその両方を巡るツアーです。見出しごとに 1 つのセクションを設け、それぞれの最後にそのトピックを扱うページを示します。移植の手順書ではありません。それは**[移行ガイド](migration.md)**の役目で、すべての破壊的変更を変更前と変更後のコード付きで載せています。

!!! note "v2 が安定版の系列"
    `pip install mcp` は 2.x をインストールします。コピーしてそのまま貼り付けられるインストールコマンドは**[インストール](get-started/installation.md)**にあります。v2 で何かが壊れたり、意外な動きをしたり、作業の妨げになったりしたら、[知らせてください](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

## SDK：v1 から v2 へ {#the-sdk-v1-to-v2}

### `FastMCP` は `MCPServer` になった {#fastmcp-is-now-mcpserver}

高レベルのサーバークラスは名前が変わり、モジュールも一緒に変わりました。古いインポートパスは非推奨になったのではなく削除されたので、どの v1 サーバーも最初にここでつまずきます。

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

デコレーターで組み立てたサーバーなら、移植作業の大半もこれで終わりです。`@mcp.tool()`、`@mcp.resource()`、`@mcp.prompt()` は v1 で受け付けていたものをそのまま受け付け（`@mcp.resource()` には省略可能な `security=` キーワードが 1 つ加わりました）、入力スキーマも引き続き型ヒントから作られます。周辺の変更は次のとおりです。`mcp.server.fastmcp.*` の下にあったものはすべて `mcp.server.mcpserver.*` の下に移りました。`ctx.fastmcp` は `ctx.mcp_server` になり、`get_context()` は削除されました（代わりに `ctx: Context` パラメーターを宣言してください）。例外の基底クラス `FastMCPError` は `MCPServerError` です。インポートの対応表は**[移行ガイド](migration.md#fastmcp-renamed-to-mcpserver)**にあります。

### `Resolve`：ユーザーに入力を求める新しい方法 {#resolve-the-new-way-to-ask-the-user-for-input}

ツールが必要とするものを、すべてモデルから受け取るべきとは限りません。v2 の新機能として、`Resolve(fn)` で注釈したツールのパラメーターは、代わりに自分で書いた関数によってモデルからは見えない形で埋められます。その関数は `Elicit(...)` を返して、ユーザーに質問を提示できます。呼び出しの途中でクライアントから何かを得るには、これが推奨の方法です。SDK は接続が対応している仕組みに乗せて質問を運びます。レガシークライアントにはその場で送るエリシテーション（elicitation）リクエスト、2026-07-28 ではマルチラウンドトリップ（multi-round-trip）です。そのため、1 つのツール本体で両方の世代に対応できます。詳しくは**[依存関係](handlers/dependencies.md)**を参照してください。

!!! note
    必要なときのために、ほかの 2 つの形も残っています。`ctx.elicit()` はレガシー接続のクライアントに対して引き続き動作します（**[エリシテーション](handlers/elicitation.md)**）。また、ハンドラーが自分で `InputRequiredResult` を返してラウンドを手動で進めることもでき、2026-07-28 でサンプリングやルート（roots）のリクエストが運ばれるのもこの方法です（**[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)**）。

### 第一級の `Client` {#a-first-class-client}

v1 では 3 つの層が入れ子になっていました。生のストリームを返すトランスポートのコンテキストマネージャー、それを包む `ClientSession`、そして手で呼び出す `await session.initialize()` です。v2 にあるのはオブジェクト 1 つです。

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` が受け取るのは、サーバーオブジェクト（インメモリでトランスポートなし。テストで使う形です）、URL（Streamable HTTP）、または `stdio_client(...)` のような任意のトランスポートのコンテキストマネージャーです。`async with` に入ると接続し、サーバーがどの世代を話すかにかかわらずプロトコルバージョンをネゴシエートします。その後は `client.server_capabilities` と `client.protocol_version` がそのまま使え、サーバーが自身を名乗る場合は `client.server_info` も使えます（2026 年世代では識別情報が省略可能なので、`Implementation | None` になりました）。v1 で登録したサンプリングとエリシテーションのコールバックは引き続き動作します（コールバックの本体には、このページのほかの項目と同じ snake_case への属性名の変更が及びます）。加えて 2026 形式の「結果に埋め込まれたリクエスト」（後述）にも応答するようになり、1 つずつではなく並行して実行されます。低レベルのインターフェースが必要な人のために `ClientSession` は今も下にあり、`client.session` で取り出せます。ただしこちらも変わっています（新しいディスパッチャーエンジンの上で動き、自身のシグネチャも一部変わりました）。下りていく前に**[移行ガイド](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)**を読んでください。

**[Client](client/index.md)** で紹介し、**[クライアントのトランスポート](client/transports.md)**で 3 つの接続形態を、**[クライアントのコールバック](client/callbacks.md)**でコールバックそのものを扱います。**[テスト](get-started/testing.md)**では、v1 の `create_connected_server_and_client_session()` ヘルパーに代わるインメモリのパターンを示します。

### 低レベルの `Server` は改名ではなく再構築 {#the-low-level-server-was-rebuilt-not-renamed}

JSON-RPC の層で作業しているなら、ここが v2 の「すべてが違う」部分です。ツールが 1 つの同じサーバーを両方の書き方で示します。何が移ったかは、マーカーをクリックして確認してください。

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. ハンドラーはデコレーター（括弧を付けて呼び出す形）で登録します。サーバーができた後ならいつでもかまいません。
2. 素の `list[Tool]` を返すと、SDK が `ListToolsResult` に包みます。
3. フィールドは Python でも camelCase で、スキーマは**強制されます**。関数が動く前に、SDK が `call_tool` の引数をこのスキーマに対して jsonschema で検証します。下の `arguments["query"]` が安全なのはそのためです。
4. 1 つの `call_tool` ハンドラーがすべてのツールを受け持ち、ツール名と検証済みの引数を受け取ります。引数は展開済みで、`None` になることはありません。
5. v1 のツールは例外の送出で失敗を伝えます。どんな例外も捕捉され、`str(e)` をテキストにした `CallToolResult(isError=True)` として返されるので、呼び出し側のモデルはこのメッセージを読んで再試行できます。
6. コンテキストは暗黙の ContextVar から来ており、リクエストの途中でサーバーオブジェクトを通じて取り出します。
7. 素のコンテンツブロックは自動で `CallToolResult` に包まれます。

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. フィールドは snake_case になり、スキーマは**公開されるだけで適用はされません**。ハンドラーが動く前に引数を検査するものは何もありません。
2. どのハンドラーも `async (ctx, params) -> result` という同じ形です。コンテキストは第 1 引数で（`ctx.session`、`ctx.request_id`、`ctx.protocol_version` はここにあります）、`server.request_context` の行き先はここです。
3. 完全な `ListToolsResult` を自分で組み立てます。素のリストを返しても SDK は包んでくれず、サーバー側の `TypeError` になります。
4. 型付きの params が入り（`params.name`、`params.arguments`）、完全な結果が出ていきます。展開も、包みも、変換も自動では行われません。
5. 検査は同じで、手段が違います。ここで `ValueError` を送出すると、モデルには中身の見えない `-32603` として届きます（後述）。そのため、意図した通信上のエラーは `MCPError` として送出します。コードとメッセージはそのまま通り抜け、このテキストを添えた `-32602` は未知のツールに対する仕様自身の答えです。
6. `params.arguments` は `None` のことがあります。v1 では、コードに届く前に既定値の `{}` が入っていました。ハンドラーの前に検証がないので、この行は欠かせません。
7. ここで送出された予期しない例外は、**無害化された**プロトコルエラー `-32603` `"Internal server error"` になり、モデルがメッセージを見ることはありません。モデルに読ませて対応させたい失敗には、`CallToolResult(is_error=True, ...)` を返してください。
8. ハンドラーはコンストラクターの引数なので、サーバーのインターフェースはできた瞬間に完成しています。`add_request_handler()` は構築後に使える抜け道であり、カスタムメソッドへの入り口でもあります。

この例がそのままパターンです。より一般的に言うと、次のとおりです。どのハンドラーも同じ形で、型付きの params が入り、完全な結果型が出ていきます。ツール引数に対する以前の jsonschema 検査はなくなりました。例外はプロトコルエラーであり、`is_error=True` のツール結果になることはありません。暗黙の `server.request_context` ContextVar もなくなりました。ベンダーの名前空間を持つカスタムメソッドは `add_request_handler(method, params_type, handler)` によって第一級の扱いになり、ハンドラーが動く前に、受信した params が渡したモデルに照らして検証されます。そして `middleware` リスト（意図的に暫定扱いとしています）がすべての受信メッセージを包み、これまで上書きの対象になっていた非公開の `_handle_*` メソッドを置き換えます。

その下では、v1 の `BaseSession` の受信ループが、クライアントとサーバーが共有するディスパッチャーエンジンに置き換わりました。このページのいくつかの事柄が同時に成り立つのは、このエンジンのおかげです。1 つの `Server` オブジェクトが両方のプロトコル世代を受け持ちます。`Client(server)` は JSON-RPC のフレーミングなしにプロセス内でディスパッチします。そしてタイムアウトしたクライアントのリクエストは、サーバー側のハンドラーを実際にキャンセルするようになりました。

詳しくは**[低レベルの Server](advanced/low-level-server.md)** を参照してください。削除されたフックは**[移行ガイド](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)**が 1 つずつたどります。`MCPServer` より下に下りたことがなければ、どれも影響しません。

### 通信用の型は `mcp-types` に移り、フィールドはすべて snake_case に {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

プロトコルの型は、独立したディストリビューション `mcp-types` に置かれるようになりました。依存するのは pydantic と typing-extensions だけなので、ゲートウェイやプロキシ、コードジェネレーターは HTTP スタックをインストールせずに MCP の通信上の形を扱えます。そうしたプロジェクトは `mcp-types` をインストールして `mcp_types` をインポートします。`mcp` 自体はそのパッケージに厳密に一致するバージョンで依存し、再公開しています。そのため SDK に依存するコードは、これまでどおり `import mcp.types as types` や `from mcp.types import Tool` と書き（恒久的なエイリアスで、どの名前も同じオブジェクトです）、本当の依存先である `mcp` だけを宣言します。目安は、実際に依存しているパッケージを通じてインポートすることです。

これらの型では、Python の属性がすべて snake_case になりました。`result.is_error`、`tool.input_schema`、`listing.next_cursor` のような形です。実際に送受信される JSON はこれまでとまったく同じ camelCase で、変わったのは属性のつづりだけです。より厳格なデフォルトも 2 つ付いてきます。未知のフィールドはそのまま往復させずに無視されます（追加の情報は `_meta` に入れてください）。そして両側とも、ネゴシエートしたプロトコルバージョンに照らして通信を検証します。名前変更の対応表は**[移行ガイド](migration.md#field-names-changed-from-camelcase-to-snake_case)**を参照してください。

### トランスポートの設定は `run()` へ {#transport-configuration-moved-to-run}

`MCPServer(...)` が扱うのは、サーバーが「何であるか」です。名前、インストラクション、ライフスパン、認証がそうです。「どう配信するか」は `run()` とアプリビルダーの役目になりました。`host`、`port`、`stateless_http`、`json_response`、エンドポイントのパス、`transport_security` の移った先がそこです（`MCPServer("x", port=9000)` は `TypeError` です）。オーバーロードはトランスポートごとに型付けされているので、`stdio` が取るオプションと `streamable-http` が取るオプションはエディターが教えてくれます。知っておきたい削除が 1 つあります。`mount_path` はなくなりました。プレフィックスの下で配信するには、ASGI アプリをマウントするのがサポートされた方法です。

オプションは**[サーバーの実行](run/index.md)**、マウントは**[既存のアプリに追加する](run/asgi.md)**で扱います。

### インポートエラーなしに変わる動作 {#behavior-that-changes-without-an-import-error}

名前の変更は自分から存在を知らせてくれます。次のものは知らせてくれません。

* **同期関数はワーカースレッドで動きます。** `def` のツール（リソース、プロンプト、リゾルバーも同様）はイベントループをブロックしなくなりました。その代わり、本体はイベントループのスレッド上では動かなくなったので、特定のスレッドに縛られたコードには影響します。`async def` のハンドラーはそのままです。詳しくは**[移行ガイド](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**を参照してください。
* **ツールの中で送出した `MCPError`（v1 の `McpError`）はプロトコルエラーになりました。** モデルがそれを見ることはありません。ほかの例外はすべて、これまでどおりモデルが読んで対応できる `is_error=True` の結果になります。この切り分けは**[エラーの処理](servers/handling-errors.md)**で説明しています。
* **結果は送り出す前に検証されます。** `input_schema` が `{}` の手組みの `Tool` は、`tools/list` で失敗するようになりました（仕様は `"type": "object"` を要求します）。`@mcp.tool()` で作ったサーバーがこれに出会うことはありません。スキーマは SDK が書くからです。
* **クライアントは受け取ったものを検証します。** `list_tools()` と `call_tool()` は、ネゴシエートしたプロトコルバージョンに照らしてサーバーの応答を検査します。そのため、v1 の寛容なパースが見逃していた「少しだけ不正な」サーバーは `pydantic.ValidationError` を送出するようになりました。自分で管理していないサーバーに接続するなら、そうしたサーバーを見つけるのは自分だと思っておいてください。詳しくは**[移行ガイド](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)**を参照してください。
* **URI テンプレートは本物の RFC 6570 になりました。** `{+path}`、`{?query}` などが使え、マッチングは正規表現的な緩さではなく厳密になり、取り出した値に含まれるパストラバーサルはデフォルトで拒否されます。厳格になったテンプレートは、最初のリクエストではなくデコレーターの適用時に失敗します。詳しくは **[URI テンプレート](servers/uri-templates.md)**を参照してください。
* **Streamable HTTP のライフスパンは 1 回だけ**、起動時に実行され、その状態はすべてのセッションとリクエストで共有されます。v1 ではセッションごとに 1 回、`stateless_http=True` ではリクエストごとに 1 回実行されていました。ライフスパンで作るプールやキャッシュは劇的に安くなります。そこで接続ごとのリソースを取得していたものは、ハンドラー本体に移してください。詳しくは**[ライフスパン](handlers/lifespan.md)**を参照してください。
* **`mcp dev` と `mcp install` は、起動する環境を**インストール済みの SDK バージョンに固定します。どちらのコマンドもサーバーを新しい `uv run --with ...` 環境で実行しますが、以前はその環境で `mcp` が開発対象のバージョンではなく最新の安定リリースに解決されていました。詳しくは**[移行ガイド](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**を参照してください。
* **HTTP クライアントは `httpx` ではなく `httpx2` になりました。** 依存関係の入れ替えによって、コードが捕捉したり渡したりするもの（`httpx2.AsyncClient`、`httpx2.ConnectError`）が変わり、TLS 証明書の検証方法も変わります。`httpx2` は certifi 同梱の CA リストではなく、`truststore` を通じてオペレーティングシステムのトラストストアに照らして検証します。ほとんどの環境では気づくこともありません。システムの CA ストアを持たない最小構成のコンテナや、certifi のバンドルだけが知っていたプライベート CA では、TLS ハンドシェイクが失敗し始めます。`SSL_CERT_FILE`/`SSL_CERT_DIR` を設定するか、クライアントに `verify=ssl_context` を渡してください。詳しくは**[移行ガイド](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**を参照してください。

### 完全に削除されたもの {#removed-outright}

次の項目には、それぞれ**[移行ガイド](migration.md)**のセクションがあります。

* **WebSocket トランスポート**（クライアント側とサーバー側の両方）と `mcp[ws]` extra です。MCP 仕様の一部だったことは一度もありません。
* **実験的な Tasks** API（`mcp.*.experimental`）です。2026-07-28 はタスクをコアプロトコルの外に出して公式の拡張（[SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)）に移しており、この SDK はまだそれを実装していません。
* インポートパスとしての `mcp.shared.version`、`mcp.shared.progress`、`mcp.shared.session`（v1 の `message_handler` の注釈がインポートしていた `RequestResponder` スタブを含む）です。（`mcp.types` は削除されていません。独立した `mcp_types` パッケージの恒久的なエイリアスとして残っています。）
* 非推奨だった `streamablehttp_client` というつづりと、`streamable_http_client` の `get_session_id` コールバックです（この関数が返すストリームはちょうど 2 つになりました）。
* `McpError` です。**`MCPError`** に改名され、`(code, message, data)` を直接受け取るコンストラクターになりました。
* `MCPServer.get_context()`、`mount_path=`、そして低レベル `Server` のデコレーターメソッド、ContextVar、ハンドラーの辞書です。

## プロトコル：2025-11-25 から 2026-07-28 へ {#the-protocol-2025-11-25-to-2026-07-28}

v2 は 2026-07-28 リビジョンを実装し、しかも**両方の**リビジョンを同時に扱います。同じ `streamable_http_app()`（と同じ stdio サーバー）が、2025 年世代のクライアントの `initialize` にも 2026 年世代のクライアントのリクエストにも応答します。設定するものも、切り替えるフラグも、別のデプロイも要りません。新しいリビジョンに対応しても、古いリビジョンのクライアントが置き去りになることはありません。ここから先は、新しいリビジョン自体が何を変えるのかを説明します。

### ハンドシェイクもセッションもない {#no-handshake-no-session}

2026-07-28 のクライアントは、接続を開いてネゴシエートしてから話し始める、ということをしません。どのリクエストもプロトコルバージョン、クライアント情報、クライアントのケイパビリティを `_meta` に載せて運びます。唯一のディスカバリー呼び出しである `server/discover` も、ほかと変わらない普通のリクエストです。`Client` はデフォルトで正しく振る舞います。`server/discover` を一度試し、サーバーが古ければ `initialize` のハンドシェイクにフォールバックします。

Streamable HTTP では、2026 の経路に `Mcp-Session-Id` がありません。運用面での目玉はこれです。**新世代のリクエストをワーカーに結び付けるものが何もない**ので、単純なラウンドロビンのロードバランサーの後ろにあるどのレプリカでも応答できます。正直に言っておくべき但し書きが 2 つあります。2025 年世代のクライアント（今日ではほとんどのクライアントがそうです）は引き続きセッションを開き、v1 で必要だったのと同じスティッキネスを引き続き必要とします。それらについては何も変わりません。そして、マルチラウンドトリップの再試行がワーカーをまたいで運ばなければならない唯一のものは封印された `request_state` で、そのデフォルトの鍵はプロセスごとに生成されます。そのため、スケールアウトしたデプロイでは `RequestStateSecurity(keys=[...])` を渡します。（`stateless_http=True` は無関係です。2025 年世代のクライアントの扱い方にだけ影響し、2026 の通信がそれを読むことはありません。v1 ですでに設定しているなら、何も変わりません。）

クライアント側の話は**[プロトコルバージョン](protocol-versions.md)**、運用者向けのチェックリスト（Host の許可リスト、`request_state` の鍵、レプリカをまたぐ通知）は**[デプロイとスケール](run/deploy.md)**、両方の世代を同時に扱う話は**[レガシークライアントへの対応](run/legacy-clients.md)**にあります。

### サーバーはクライアントを呼び出せない：マルチラウンドトリップリクエスト {#the-server-cannot-call-the-client-multi-round-trip-requests}

2026-07-28 では、サーバー起点のリクエストはすべてなくなりました。プッシュ型のエリシテーション、サンプリング、`roots/list` です。2026 の接続にはそれらのためのチャネルがないので、`ctx.elicit()` と `ctx.session.create_message()` はそこでは `NoBackChannelError` で失敗します（レガシークライアントに対しては引き続き動作します）。

代わりの仕組みは呼び出しの向きを逆にします。ユーザーから何かを必要とするツールは質問を「返し」（`InputRequiredResult`）、クライアントはこれまでと同じコールバックでそれに答え、答えを添えて呼び出しが再試行されます。そのループは `Client` が回します。サーバー側で結果を自分で組み立てることはめったにありません。**[依存関係](handlers/dependencies.md)**がやってくれるからです。パラメーターを `Resolve(ask_quantity)` で注釈します（`ask_quantity` は自分で書く普通の関数です）。すると SDK は接続が対応している仕組み、つまりレガシーセッションならその場で送るエリシテーションリクエスト、2026 ならマルチラウンドトリップで質問します。ツール本体は 1 つ、世代は両方です。

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

このファイル 1 つに要点が詰まっています。1 つのサーバー、`Resolve` に支えられた 1 つのツール、そしてレガシークライアントと新世代のクライアントの両方がインメモリで答えを受け取ります。仕組み（SDK が封印と検証を行う `request_state` を含む）は**[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)**が説明し、質問のしかたは**[エリシテーション](handlers/elicitation.md)**が扱います。

!!! warning "移植した v1 サーバーの動作が変わる唯一の場所"
    最初にぶつかるのは自分のテストです。`Client(mcp)` はデフォルトで v2 サーバーに対して 2026-07-28 をネゴシエートするので、`ctx.elicit()` を呼ぶツールは v1 で通っていたテストで失敗します。質問を `Resolve(...)` パラメーターに移す（世代をまたいで使えます）か、本当にプッシュ型の動作が欲しいならテストクライアントを `mode="legacy"` に固定してください。

### ルート、サンプリング、プロトコルのロギングは非推奨、`ping` は削除 {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) は、すべてのプロトコルバージョンで 3 つの「ケイパビリティ」をまるごと非推奨にします。ルート、サンプリング、MCP レベルのロギング（`ctx.info()` など）です。これは上で述べたバックチャネル（back-channel）の欠如とは別の軸です。非推奨は勧告にすぎず、2025 年世代のセッションに対してはすべてが動き続け、通信上は何も変わりません。気づくのは `MCPDeprecationWarning` です。これは `UserWarning` なのでデフォルトで表示されます。アップグレード後の最初の `ctx.info(...)` がそう告げると思っておいてください。

`ping` はもっと厳しく、非推奨ではなくプロトコルから削除されました。非推奨になった機能の単独メソッドのうち 2 つ、`logging/setLevel` とクライアントの `notifications/roots/list_changed` も、2026-07-28 で同じように削除されています。また、進捗通知はサーバーからクライアントへの方向だけになりました。

完全な表、それぞれの代替、そしてレガシークライアントに対応しつつログを静かにしたい場合の 1 行のフィルターは**[非推奨の機能](deprecated.md)**にあります。

### 変更通知は 1 本のストリームに {#change-notifications-become-one-stream}

2026-07-28 では、単独の HTTP GET ストリームと `resources/subscribe` が `subscriptions/listen` に置き換わります。クライアントは長寿命のストリームを 1 本開き、欲しい通知の種類を指定します。`MCPServer` は追加の設定なしでこれに対応します。発行には `await ctx.notify_resource_updated(uri)`（や `notify_tools_changed()` など）を使い、ミドルウェアは呼び出し側ごとに listen リクエストを拒否でき、複数レプリカのデプロイでは共有の `SubscriptionBus` を差し込みます。クライアントでは `async with client.listen(...)` がストリームを開きます。フィルターはキーワード引数として渡し、型付きの変更イベントが返り、`sub.honored` はサーバーが配信に同意した部分集合です。

発行と配信は**[サブスクリプション](handlers/subscriptions.md)**、監視する側は**[クライアント編の対になるページ](client/subscriptions.md)**、バスは**[デプロイとスケール](run/deploy.md)**で扱います。

### そのほかを手短に {#the-rest-quickly}

* **識別情報は省略可能な、メッセージごとのメタデータです。** リクエスト側の `clientInfo` `_meta` キーは省略可能で（必須の組は `protocolVersion` と `clientCapabilities` です）、`serverInfo` は `server/discover` の結果本体の外に出ました。サーバーは代わりに、2026 年世代のすべての結果の `_meta` にそれを書き込みます（[spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)）。SDK は常に書き込みます。サーバーが自身を名乗らない場合（たとえばミドルウェアがキーを取り除いた場合）、`client.server_info` は `None` です。通信路上での書き込みの様子は**[低レベルの Server](advanced/low-level-server.md)** が示します。
* **リクエストは本体をパースしなくてもルーティングできます。** 新世代の HTTP リクエストは `Mcp-Method`（と、ツール系の 3 つの呼び出しでは `Mcp-Name`）を運びます。`x-mcp-header` で注釈したツールの入力スキーマのプロパティは `Mcp-Param-*` ヘッダーに写され、サーバーが本体と突き合わせて検査します（[SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)）。ゲートウェイやレートリミッターはヘッダーだけでルーティングできます。ルールは**[移行ガイド](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)**にあります。
* **結果はキャッシュのヒントを運びます。** 一覧と読み取りの結果は `ttlMs` と `cacheScope` を宣言します（[SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)）。メソッドごとに `cache_hints=` で設定し、`Client` は組み込みのレスポンスキャッシュでそれに従います。ヒントを送らないサーバー（2026 より前のサーバーはすべてそうです）には、これまでと同じキャッシュされない通信が届きます。詳しくは**[キャッシュのヒント](client/caching.md)**を参照してください。
* **拡張は第一級です。** サーバーとクライアントは、逆引き DNS 形式の識別子の下に省略可能なケイパビリティの束を宣言します（[SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)）。組み込みの `Apps` 拡張（MCP Apps）がそのリファレンスです。詳しくは**[拡張](advanced/extensions.md)**と **[MCP Apps](advanced/apps.md)** を参照してください。
* **エラーコードが標準化されました。** 存在しないリソースは `-32602` で、URI が `error.data` に入ります。仕様で新たに予約されたコードは `-32020`（ヘッダーの不一致）、`-32021`（必須のケイパビリティの欠如）、`-32022`（未対応のプロトコルバージョン）として現れます。**[トラブルシューティング](troubleshooting.md)**は正確なメッセージで引けるようになっています。
* **認可は誤った使い方をしにくくなりました。** クライアントは認可コードとともに返される `iss` を検証し（[RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207)。`callback_handler` は `AuthorizationCodeResult` を返すようになりました）、登録時に `application_type` を送り、別の認可サーバーに対して資格情報を使い回すことはありません。エンタープライズ方面の新機能は [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) の ID アサーションフローです。OAuth の変更は**[移行ガイド](migration.md)**にすべて載っています。該当するページは**[クライアント向けの OAuth](client/oauth-clients.md)** と **[ID アサーション](client/identity-assertion.md)**です。
* **どのサーバーもトレースできます。** OpenTelemetry はミドルウェアとして、デフォルトで有効な状態で同梱されます。どのリクエストにもサーバースパンが付き、プロセスがエクスポーターを設定するまでコストはかかりません。両端が SDK を使っていれば、クライアントは W3C のトレースコンテキストも `_meta` で伝播するので、トレースがつながります。詳しくは **[OpenTelemetry](run/opentelemetry.md)** を参照してください。

## v1 からアップグレードする場合 {#upgrading-from-v1}

* 何を変えるかの完全で正確な一覧は**[移行ガイド](migration.md)**です。このページはその「なぜ」を説明しました。
* **v1.x はなくなりません。** メンテナンス段階に移り、重大な修正とセキュリティパッチを受け続けます。2026-07-28 の仕様リリースによって壊れることもありません。ドキュメントは [/v1/](https://py.sdk.modelcontextprotocol.io/v1/) にあります。`mcp` に依存するライブラリを公開していて、まだ移行の準備ができていないなら、固定していない依存解決が 1.x にとどまるように上限を付けてください（たとえば `mcp>=1.28,<2`）。
* 荒削りなところ、わかりにくいところ、壊れているところがあれば、**[v2 のフィードバックを送ってください](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**。すべて目を通しています。
