---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# トラブルシューティング {#troubleshooting}

このページの見出しはすべて、SDK が出すエラーの文字列そのままです。その下に、エラーの意味と一手で済む直し方を書いてあります。トレースバックの最後の行（またはサーバーログ）をブラウザーのページ内検索で探し、該当する項目だけを読んでください。

いくつかの項目は、次の 1 つのサーバーを相手に動かしています。ツールが 1 つとテンプレート付きリソースが 1 つあり、どちらも知らない都市を渡されると例外を送出します。

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

このページで引用しているエラーは本物です。SDK 自身のテストスイートが、そのすべてを再現しています。

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

これは MCP のエラーではありません。anyio のノイズであり、本当のエラーは貼り付けたトレースバックの**最後の行**にあります。

`Client.__aenter__` はタスクグループを開始します。anyio はタスクグループから抜けていくものをすべて `ExceptionGroup` に包むので、`async with Client(...)` ブロックから抜け出した例外は、種類を問わず「すべて」この形で届きます。

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

これに対してやることは 2 つです。

1. **一番下を読む。** 失敗の正体は `MCPError: No forecast for 'Atlantis'.` です。「その」文字列をこのページで探してください。
2. **ブロックの内側で捕まえる。** `ExceptionGroup` が現れるのは、例外が `async with` から「抜け出した」ときだけです。内側で捕まえれば、同じ失敗は素の `MCPError` であり、グループはどこにもありません。

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    「接続」中の失敗（間違った URL、起動していないサーバー、このページの後ろに出てくる `421`）は `async with` そのものから抜け出すので、捕まえるための「内側」がありません。その場合は、グループの一番下を読んでください。

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` はオブジェクトを組み立てるだけです。`async with` に入るまで何も接続しないので、どのメソッドも拒否します。

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

中に入ってください。`__aenter__` が接続です。

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` が切断です。だからこそ、呼び忘れる `client.close()` というものが存在しません。**[テスト](get-started/testing.md)** は、まさにこのパターンの上に組み立てられています。

## `Error executing tool <name>: <message>` と `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

読んでいるのは**結果**であって、例外ではありません。`call_tool` は例外を送出しておらず、ツールが失敗しても送出することは決してありません。

サーバーが知らない都市で `forecast` を呼ぶと、ツールが送出した例外は、リクエストが「成功」と記された形で返ってきます。

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` は、サーバーが登録したことのない名前に対する同じ形の結果です。不正な引数も同じように、関数が実行される前にツールの入力スキーマと照合されて拒否されます。

直すのはクライアント側です。**`result.is_error` を確認してください**。`call_tool` を `try/except` で囲んでも、これらはどれも捕まりません。捕まえるものがないからです。これは意図した設計であり、このページで身につけておくと一番役に立つ点です。呼び出しを選んだのは「モデル」なので、メッセージを受け取ってやり直す機会を得るのもモデルです。詳しくは **[エラーの処理](servers/handling-errors.md)** を参照してください。例外を「送出する」側の `MCPError` の経路も含めて説明しています。

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

`@mcp.tool()` ではなく `@mcp.tool` と書いています。`tool()` はデコレーターの「ファクトリー」です。括弧がないと、Python は関数をその `name=` パラメーターに渡してしまいます。

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

括弧を付けてください。`@mcp.resource(...)` と `@mcp.prompt()` も、同じ書き間違いに対して同じことを言います。

!!! note
    これはモジュールが**インポート**された時点で送出されます。どのクライアントが接続するよりも前です。そのため、ホストがサーバーを「接続済みでツール 0 個」ではなく「起動失敗」（または「切断」）と表示している場合は、この形を疑ってください。自分で `python server.py` を実行し、トレースバックを読んでください。型チェッカーでも検出できます。関数は有効な `name=` ではないからです。

## `Tool already exists: <name>` {#tool-already-exists-name}

2 つの登録が同じツール名を使いました。勝つのは**最初の**登録で、2 つ目は黙って捨てられます。「サーバーログ」に出るこの警告が唯一の合図です。

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` が報告する `forecast` は 1 つで、それは `forecast_today` のほうです。どちらかの名前を変えてください。`MCPServer(..., warn_on_duplicate_tools=False)` は結果を変えずに警告だけを黙らせるので、有効のままにしておいてください。リソースとプロンプトにも同じ規則と同じログ行があります（`Resource already exists:`、`Prompt already exists:`）。

## ホストに表示されるツールが 0 個 {#my-host-lists-zero-tools}

これにはエラー文字列がありません。だからこそ検索しにくいのです。SDK が登録済みのツールを `tools/list` から落とすことはないので、外側に向かって確認していきます。

* **サーバーはそもそも起動したか。** 括弧のない `@mcp.tool` はインポート時に例外を送出しますし、クラッシュしたサーバーは一部のホストでは空のサーバーによく似て見えます。自分で `python server.py` を実行してください。
* **ツールは、ホストが動かしている `mcp` に載っているか。** 別のモジュールにある 2 つ目の `MCPServer(...)` は、別の空のサーバーです。ホストのコマンドが実際にどのオブジェクトをインポートしているか確認してください。
* **2 つのツールが名前を共有していないか。** していれば、片方は消えています。サーバーログで `Tool already exists:` を探してください。
* **ホスト側の一覧が古くないか。** 起動後に追加したツールは、`notifications/tools/list_changed` を処理するクライアントにしか届きません。ホストの再起動が手っ取り早い直し方です。
* **退避される区間の外で、何かが `stdout` に書き込んでいないか。** 提供中、SDK は「フラッシュされた」迷子の stdout 出力を stderr に退避します（ベストエフォートです。標準ストリームを差し替える環境はそのまま提供されます）。しかし、それより前に stdout にフラッシュされた出力（エコーするラッパースクリプト、バッファリングなしのプロセスでのインポート時の `print()`）や、インタープリター終了時に吐き出されるバッファリング済みの `print()` は、プロトコルのストリームに載ってしまいます。ゴミが 1 行混じるだけでホストが接続を切ることがあり、一部のホストはそれを中身のないサーバーとして表示します。代わりに `logging` モジュールでログを出してください。ホスト側のチェックリストの残りは **[実際のホストに接続する](get-started/real-host.md)** にあります。

「無効な」ツール名は、このリストには「入りません」。規約に沿わない名前は警告をログに出しますが、ツールはそれでも登録され、一覧に載ります。

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

サーバーが HTTP リクエストを門前払いし、そのボディが JSON-RPC ではなかったため、python の `Client` にはこの代用メッセージよりましなものを見せる手段がありません。

群を抜いて多い原因は、デプロイしたばかりの Streamable HTTP サーバーです。`transport_security=` なしの `streamable_http_app()`（および `mcp.run("streamable-http")`）は、デフォルトで **DNS リバインディング保護** が有効です。`Host` ヘッダーが localhost のリクエストだけを受け付けます。手元のノート PC では正しいデフォルトですが、実際のホスト名の裏では間違ったデフォルトです。

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

これをデプロイしてクライアントを向けると、接続はハンドシェイクで失敗します。

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

サーバーが実際に送った言葉、`421` と `Invalid Host header` は、手元には届きません。421 のボディには `Content-Type: application/json` がないので、クライアントはそれをパースできないのです。それらは**サーバーのログ**にあります。次に見るべき場所はそこです。

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

直し方は `transport_security=` です。実際に提供するホスト名を許可リストに入れてください。

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    変更はこれだけです。まったく同じクライアントが今度は接続し、`2026-07-28` をネゴシエートして、`forecast` を呼び出します。

各フィールドの意味、リバースプロキシの場合、その他デプロイ時に変わることはすべて **[デプロイとスケール](run/deploy.md)** で扱っています。そして、すぐ下の `421 Misdirected Request` / `Invalid Host header` は、同じ失敗を反対側から見たものです。

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

これは `Server returned an error response` を、python の `Client` 「以外」のもの、つまり curl、ブラウザーのネットワークタブ、リバースプロキシのアクセスログ、あるいは別の SDK から見たものです。

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` は、このステータスに対する HTTP 自体の理由句です。`Invalid Host header` は SDK のレスポンスボディです。そして python の `Client` は、同じ出来事を `Server returned an error response` として表示します。3 つとも 1 つの拒否です。チェックはサーバーがバインドしたアドレスではなく、**リクエストが運ぶ `Host` ヘッダー**に対して行われます。そのため、公開ホスト名を転送するリバースプロキシは、直接接続するクライアントとまったく同じようにこれに引っかかります。

直し方は `Server returned an error response` で示したのと同じ `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` です。境界的な挙動を 2 つ挙げておきます。

* `allowed_hosts` の項目は完全一致の文字列です。`"mcp.example.com"` はポートなしの `Host` ヘッダーに一致し、`"mcp.example.com:*"` は明示的なポートが付いたものすべてに一致します。両方を列挙してください。
* ボディが `Invalid Origin header` の `403` は、`Origin` ヘッダーに対する兄弟分のチェックです。発動するのはブラウザーに対してだけで（`Origin` を送るものは他にありません）、その許可リストが `allowed_origins=` です。

チェックを無効にするのが正直な設定になるのはいつか、という点も含め、詳しくは **[デプロイとスケール](run/deploy.md)** を参照してください。

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

MCP アプリが別の ASGI アプリの中にマウントされていて、その**セッションマネージャー**を起動するものが何もありません。

`mcp.streamable_http_app()` は、自身のライフスパンでマネージャーを起動する Starlette アプリを返します。`uvicorn server:app` はそのライフスパンを実行してくれます。しかし Starlette は**マウントされたサブアプリケーションのライフスパンを決して実行しません**。そのため、アプリを `Mount` の中に入れた瞬間にマネージャーは起動されなくなり、最初のリクエストで爆発します。

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

サーバーは起動します。ルートも解決します。そのうえで、`uvicorn` はリクエストごとにこれを出力します。

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

クライアントには 500 が見えます。直し方は、**ホスト**側のアプリに `mcp.session_manager.run()` に入るライフスパンを付けることです。

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

これを扱うページは **[既存のアプリに追加する](run/asgi.md)** です。1 つのアプリに複数のサーバーを入れる場合や FastAPI の場合も含みます。同じクラスから出る隣接した文字列を 2 つ挙げます。

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` マネージャーは使い切りです。同じアプリのライフスパンに 2 回入ると、これに当たります。
* `mcp.session_manager` が存在するのは `streamable_http_app()` が呼ばれた**後**だけです。先にルートを組み立て、マネージャーにはライフスパンの中でだけ触れてください。

## `MCPError: Session not found` {#mcperror-session-not-found}

クライアントが送った `Mcp-Session-Id` をサーバーが認識していません。ほぼ確実に、サーバーが**再起動した**（または別のインスタンスにルーティングされた）のが原因です。セッションは、その 1 つのプロセスのメモリの中にあります。

探すべきサーバーのバグはありません。HTTP レスポンスは `404` で、そのボディは JSON-RPC「です」。そのため上の `421` とは違い、python の `Client` はこれをそのまま見せてくれます。

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

直し方は再接続です。`async with Client(...)` ブロックを抜けて新しいブロックに入れば、新しいセッションがネゴシエートされます。長く生きるクライアントであれば、呼び出しの周りで `MCPError` を捕まえ、死んだセッションの中でリトライするのではなく、このメッセージを見たら再接続することになります。

再起動「なしで」これが起きるなら、スティッキーセッションなしで複数のワーカーを動かしています。ワーカーごとに独自のセッションテーブルを持つので、間違ったワーカーにルーティングされたリクエストはここに行き着きます。この話とその 2 つの直し方（スティッキールーティング、または `stateless_http=True`）は、**[デプロイとスケール](run/deploy.md)** と **[レガシークライアントへの提供](run/legacy-clients.md)** が担当しています。

サーバー運用者向けには、対応するログ行は `Rejected request with unknown or expired session ID: <id>` です。`INFO` で記録されるので、通常の `WARNING` のしきい値では見えません。デプロイ直後にまとまって出るのは正常です。接続中のクライアントがすべて再接続しているのです。

## `MCPError: Method not found` {#mcperror-method-not-found}

片側が、もう片側にハンドラーのない JSON-RPC リクエストを送りました。`e.error.data` にメソッド名が入っています。よくある原因は**世代の不一致**です。あるプロトコルリビジョンには存在して別のリビジョンには存在しないメソッドを、違う世代のピアに送った場合です。たとえば `2025` 年世代の `resources/subscribe` が `2026-07-28` の接続に届いたり、`2026` 専用の `subscriptions/listen` が `mode="legacy"` に固定されたクライアントから送られたりした場合です。どちら側が何を話すかの地図は **[プロトコルバージョン](protocol-versions.md)** にあります。もう 1 つの正当な原因（ハンドラーを登録しなかったオプションのケイパビリティ）は **[補完](servers/completions.md)** にあります。

モダンなプロトコルが削除したリクエストであるにもかかわらず、このエラーに**ならない**ものが 1 つあります。`2026-07-28` の接続でツールが `ctx.elicit()` を呼ぶ場合です。サーバーはそのリクエストを「送る」こと自体を拒否するので、代わりに得られるのは、このページの後ろに出てくる `Cannot send 'elicitation/create': ...` です。

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

サーバーはユーザーに何かを尋ねたいのに、このクライアントは尋ねられることができると一度も言っていません。

エリシテーション（elicitation）のリゾルバーは、接続中のクライアントがフォームのエリシテーションを宣言していない場合、最初の時点で拒否します。`e.error.data` には、足りないものが正確に書かれています。

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

`Client(...)` に `elicitation_callback=` を渡してください。コールバックの登録「が」ケイパビリティの宣言です。2 つ目のスイッチはありません。

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

他のコールバック（`sampling_callback`、`list_roots_callback`）は **[クライアントのコールバック](client/callbacks.md)** に一覧があります。どれも同じように宣言を兼ねています。

!!! info
    `-32021` は `MISSING_REQUIRED_CLIENT_CAPABILITY` で、2026-07-28 の仕様が追加した 3 つのエラーコードのうちの 1 つです。どれも例外クラスではありません。すべて `MCPError` として届き、見るべき場所は `e.error.code` です。定数は `mcp.types` がエクスポートしています。残りの 2 つは `-32020` `HEADER_MISMATCH`（HTTP ヘッダーが、それに伴うリクエストボディと食い違っている）と `-32022` `UNSUPPORTED_PROTOCOL_VERSION`（リクエストが、このサーバーの話さないバージョンを指定した）です。仕様に準拠した SDK クライアントはどちらも起こせないので、見かけたら、クライアントとサーバーの間でリクエストを書き換えている何かを調べてください。

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

`Client did not declare the form elicitation capability ...` と同じ欠落を、最初の時点でチェックしない経路が綴ったものです。サーバーはエリシテーションへの回答を必要としたのに、接続中のクライアントは `elicitation_callback` を登録していませんでした。

これを目にするのは、レガシー接続での `ctx.elicit()` からです。また、どの接続であっても、返されたマルチラウンドトリップ（multi-round-trip）の質問（**[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)**）が、それに答えるコールバックのないクライアントに届いた場合にも目にします。直し方はまったく同じで、`Client(...)` に `elicitation_callback=` を渡してください。「ユーザーに尋ねなかった」ことをツールが `decline` として受け取る形はありません。尋ねられないクライアントは失敗した呼び出しなので、それを前提にツールを設計してください。

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

ハンドラーがリクエストの途中でクライアントに連絡を取ろうとしましたが、その接続の呼び出しには、サーバーからのリクエストを運べるチャネルがありません。呼び出しをそこに置くサーバー設定は 3 つあります。

**`2026-07-28` の接続。どのトランスポートでも、常に。** モダンなプロトコルにはサーバー起点のリクエストがそもそも存在しないので、サーバーは何かを送る前に拒否します。ツールの中の `ctx.elicit()` が、これに出会う典型的な経路です（`Client(server)` は頼まれなくても `2026-07-28` をネゴシエートするので、最初のインメモリテストで出会います）。`elicitation_callback=` を渡しても何も変わりません。答えるべきリクエストがクライアントに届くことがないからです。

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**`stateless_http=True` のサーバーでのレガシー接続。** ステートレスとは、すべてのリクエストがそれぞれ独立した世界だということです。セッションもサーバーからクライアントへのストリームもなく、したがって、それらを持つ世代であっても `elicitation/create`（または `sampling/createMessage`、または `roots/list`）を送る先がどこにもありません。

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**`json_response=True` のサーバーでのレガシー接続。** `POST` には 1 つの JSON ボディで応答します。1 つのボディが運ぶのはレスポンスだけなので、リクエスト途中の `ctx.elicit()` が必要とするリクエストスコープのストリームは、ここにも存在しません。セッション、その `Mcp-Session-Id`、そしてスタンドアロンのストリームはすべて残っています。なくなったのはリクエストスコープのチャネルだけです。

メッセージには、送れなかったメソッド名が入っています。サーバーが送出するクラスは `NoBackChannelError` ですが、通信路が運ぶのは基底の `MCPError` だけなので、トレースバックの最後の行はクラス名ではなく上の文章です。

`2026-07-28` のクライアントに対しては、直し方は 3 つとも同じです。呼び出しの途中で連絡を取り返さないことです。質問を**リゾルバー**に移す（または自分で `InputRequiredResult` を返す）と、質問は「レスポンス」の一部になり、どの接続でも運べます。

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

同じ質問、クライアント側も同じ `elicitation_callback` です。違いは内部にあります。リゾルバーを使うと、サーバーは質問を押し込むのではなく呼び出しから「返す」ことができるので、サーバーからクライアントへ流れるものは何もなくなります。これで、サーバーが 3 つの設定のどれであっても、すべての `2026-07-28` クライアントが救われます。「レガシー」クライアントは、書き換えだけでは救われません。`2025-11-25` には質問を返す手段がないので、レガシー接続ではリゾルバーは依然として `elicitation/create` をリクエストスコープのチャネルに送ります。そのため、そのチャネルを保持するサーバー、つまり `stateless_http=True` でも `json_response=True` でもないサーバーが依然として必要です。リゾルバーについては **[エリシテーション](handlers/elicitation.md)**、通信路上で何が起きるかについては **[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)** を参照してください。

!!! check
    `ctx.elicit()` を使うツールは間違っているのではなく、「2026 年より前」のものです。`mode="legacy"`（従来の `initialize` ハンドシェイク、仕様 `2025-11-25` 以前）で、`stateless_http=True` でも `json_response=True` でもないサーバーに接続すれば動きます。そこにはサーバーからクライアントへのチャネルが存在するからです。各バージョンが何を持つかについては **[プロトコルバージョン](protocol-versions.md)** を参照してください。

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

クライアントがエコーバックした `requestState` トークンをサーバーが検証できなかったため、そのラウンドを拒否しました。

`requestState` は、**[マルチラウンドトリップ](handlers/multi-round-trip.md)**の呼び出しが区間と区間の間で運ぶ、不透明な再開トークンです。`MCPServer` は送り出すときにこれを封印し、すべてのエコーを検証します。さらに、トークンを発行しないハンドラーに対してであっても、`tools/call`、`prompts/get`、`resources/read` に届く「すべての」`request_state` を検証します。そのため、このプロセスが封印していないトークンは、どこに届いても拒否されます。

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

メッセージは意図的に固定されています。どのチェックが失敗したかは、通信上には決して現れません。理由は**サーバーログ**に行くので、それを読むことが診断のすべてです。

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

実際に目にする理由は次のとおりです。

* **`unknown key`** が重要です。デフォルトの封印キーはプロセス起動時に生成されるので、**別のワーカー**、ロードバランサーの裏の別のインスタンス、あるいは**再起動後の**同じサーバーに届いたリトライは、このプロセスが一度も持ったことのないキーで封印されています。これは攻撃者ではなく、デフォルトが複数のプロセスに出会っただけです。
* **`audience`**：トークンは「別のサーバー名」を持つインスタンスによって封印されました。名前は封印のデフォルトの audience クレームなので、フリートはキーだけでなく名前も共有する（または明示的な `RequestStateSecurity(audience=...)` を設定する）必要があります。
* **`expired`**：ラウンドが封印の `ttl` より長くかかりました。これは 600 秒で、呼び出しごとではなくラウンドごとです。
* **`malformed`** / **`codec error`**：トークンが転送中に改変されたか、そもそも封印されたトークンではありませんでした。
* **`request binding`**：トークンが、別のツール、別の引数、または別のメソッドとともに戻ってきました。

マルチプロセスの直し方は、引数 1 つ（すべてのインスタンスで「同じ」`keys`）に加えて、引数ですらないものが 1 つです。同じサーバー「名」（または明示的に共有した `audience=`）です。

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

封印するのは `keys[0]` で、リスト内のすべてのキーが検証します。これがダウンタイムなしのローテーションを可能にしています。封印が何を守るのかとローテーションの手順は **[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md#protecting-requeststate)** で説明しています。2 ワーカーでの失敗の一部始終とその 2 段構えの直し方は **[デプロイとスケール](run/deploy.md)** でたどっています。

!!! tip
    `keys=[...]` は弱いキーを即座に拒否し、珍しく親切なメッセージを出します。

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    書いてあるとおりにしてください。

## まだ解決しない場合 {#still-stuck}

* SDK が出したメッセージがこのページにないなら、それ自体が報告する価値のあるドキュメントのバグです。
* [イシュートラッカー](https://github.com/modelcontextprotocol/python-sdk/issues)を検索してください。そこに出てくるエラー文字列の大半は、すでに誰かがまとめています。
* 何も見つからない場合は、完全なトレースバックを添えて[イシューを開く](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)か、[MCP Contributors Discord の #python-sdk-dev](https://discord.gg/6CSzBmMkjX) で尋ねてください。

## まとめ {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` がエラーであることは決してありません。**最後の行**を読んでください。`async with Client(...)` ブロックの「内側」で `MCPError` を捕まえれば、包まれること自体を完全に避けられます。
* `call_tool` は、ツールが失敗しても例外を送出しません。`Error executing tool ...` と `Unknown tool: ...` は結果です。`result.is_error` を確認してください。
* `Client must be used within an async context manager` -> `async with` を使ってください。`Use @tool() instead of @tool` -> 括弧を付けてください。
* サーバーログの `Tool already exists:` は、同名の 2 つのツールが 1 つに潰れた唯一の合図です。
* 1 つの 421、3 つの綴り：`Server returned an error response`（python の `Client`）、`421 Misdirected Request` / `Invalid Host header`（それ以外すべて）、`Invalid Host header: <host>`（サーバーログ）。直し方：`transport_security=TransportSecuritySettings(allowed_hosts=[...])`。
* `Task group is not initialized` -> マウントされたアプリで、ホストのライフスパンが `mcp.session_manager.run()` に入っていません。
* `Session not found` -> サーバーが再起動しました。再接続してください。
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` にはサーバーからクライアントへのチャネルが必要です。`2026-07-28` の接続にはそれが決してなく、`stateless_http=True` はレガシーのチャネルを奪い、`json_response=True` はリクエストスコープのチャネルを奪います。リゾルバーを使ってください（レガシークライアントには、チャネルを保持するサーバーも必要です）。隣の `Method not found` は、相手側のプロトコルリビジョンにないメソッドへのリクエストです。
* `Client did not declare the form elicitation capability ...` と `Elicitation not supported` -> クライアントに `elicitation_callback=` が足りません。
* `Invalid or expired requestState` は、通信上では決して理由を言いません。サーバーログが言います。`unknown key` は、ワーカー間で `RequestStateSecurity(keys=[...])` を共有せよという意味です。
