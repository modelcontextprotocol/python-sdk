---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# 低レベルの Server {#the-low-level-server}

`@mcp.tool()` はひとつの層です。その下には 2 つ目のサーバークラス `Server` があり、生の MCP を話します。プロトコルオブジェクトを渡すと、それをそのまま通信路に載せます。

`MCPServer` はその上に作られています。便利な層が邪魔になるときは、下に降ります。

* Python のシグネチャから導出されたものではなく、**正確な**スキーマ（ファイルから読み込んだもの、データベースから生成したもの）を出力する必要がある。
* 結果を完全に制御する必要がある。`_meta`、`is_error`、`structured_content` のすべてのキー。
* MCP が定義していないメソッドを扱う必要がある。

それ以外はすべて、`MCPServer` のままで構いません。

## 同じツールを手書きする {#the-same-tool-by-hand}

これは **[ツール](../servers/tools.md)** が `@mcp.tool()` を使って 9 行で書いている `search_books` ツールから、糖衣構文を取り除いたものです。

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

変わったのは 3 つで、それが低レベル API のすべてです。

* **ハンドラーはコンストラクターのパラメーターです。** `on_list_tools=` と `on_call_tool=` を `Server(...)` に渡します。この層にデコレーターはなく、すべてのハンドラーが同じ形 `async (ctx, params) -> result` をしています。
* **入力スキーマは自分で書きます。** `Tool.input_schema` は素の JSON Schema の `dict` です。誰も型ヒントから導出してはくれません。導出元になる型ヒントがないからです。
* **結果は自分で組み立てます。** `CallToolResult(content=[TextContent(...)])` を手で書きます。ラップされるものも、変換されるものも、戻り値のアノテーションから推論されるものもありません。

`params` はパース済みのリクエストです。`CallToolRequestParams` からは `.name` と `.arguments` が取れます。`ctx` は `ServerRequestContext` です。クライアントに話しかけるための `ctx.session`、`ctx.lifespan_context`、`ctx.request_id`、そして受信したリクエストの `_meta` である `ctx.meta` があります。

!!! info
    FastAPI を使ったことがあれば、この関係はもう知っています。`MCPServer` はデコレーターと型ヒントの層で、`Server` はその下の Starlette です。両者は競合するものではありません。`MCPServer` は `Server` を構築し、まさにこのようなハンドラーをそこに登録します。

### 試してみる {#try-it}

これには Inspector がありません。`mcp dev` と `mcp run` は `MCPServer` しか受け付けないからです。インメモリの `Client` は気にしません。`MCPServer` を受け取るのとまったく同じように、低レベルの `Server` を受け取ります。

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

`@mcp.tool()` 版が出力したのと同じテキストです。正直に言うと、違いが 2 つあります。

* `result.structured_content` は `None` です。高レベルのサーバーは `-> str` を `{"result": ...}` にラップしてくれますが、ここでは自分で組み立てなかったものを誰も組み立ててくれません。
* `list_tools` は**自分で**打ち込んだスキーマを一字一句そのまま返します。高レベル版にはすべてのプロパティに `"title": "Query"` があり、ルートに `"title": "search_booksArguments"` がありました。Pydantic の産物です。この層では、通信上に現れるものはすべて自分が載せたものです。

## 何もチェックされない {#nothing-is-checked-for-you}

`MCPServer` は、生成したスキーマに照らして呼び出しを検証し、関数が実行される前に不正な引数を拒否します（**[ツール](../servers/tools.md)**）。

`Server` はそれをしません。`input_schema` はクライアントに「公開」されますが、`params.arguments` に「適用」されることは決してありません。

!!! check
    `limit` なしで `search_books` を呼び出すと、`args["limit"]` が `KeyError` を送出します。クライアントに見えるのは次のとおりです。

    ```text
    MCPError: Internal server error
    ```

    JSON-RPC エラー、コード `-32603`、メッセージは意図的に一般的なものです。SDK はトレースバックをリモートの呼び出し側に漏らしません。モデルは自分が何を間違えたのか知ることができないので、再試行もできません。（テストでは、`raise_exceptions=True` を指定すると代わりに本当の例外が表に出ます。**[テスト](../get-started/testing.md)** を参照してください。）

これは一般化できます。低レベルのハンドラーから送出された例外は**常に**プロトコルエラーであり、`is_error=True` のツール結果になることはありません。モデルに失敗を読ませて回復させたいなら、`params.arguments` を自分で検証し、`CallToolResult(content=[TextContent(...)], is_error=True)` を返してください。この 2 種類の失敗が **[エラーの処理](../servers/handling-errors.md)** の主題です。

## 2 つのツール、1 つのハンドラー {#two-tools-one-handler}

`on_call_tool` はサーバー上のすべてのツールの唯一の入り口です。`params.name` で振り分けます。

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` は両方を公開します。`call_tool` は名前でディスパッチします。
* `else` 分岐は重要です。`Server` は、一度もリストに載せていない名前への `tools/call` でも、そのままハンドラーに転送してしまいます。そこで例外を送出すると、呼び出しは上と同じ `-32603` になります。

## 構造化出力を手書きする {#structured-output-by-hand}

`Tool` に `output_schema` を宣言し、結果に `structured_content` を載せます。どちらも自分の責任です。

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

呼び出すと、結果は両方の表現を持ちます。

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

`_meta` ブロックはサーバーの識別スタンプです。SDK は 2026 年世代のすべての結果にこれを追加し、`version` はコンストラクターの値を使います（何も設定していないサーバーは空文字列を報告します）。自身を識別してはならないサーバーは、返す結果を所有するミドルウェアでこのキーを取り除けます。

サーバーは 2 つのフィールドを比較しません。この SDK の `Client` は比較します。宣言した `output_schema` を満たさない `structured_content` を返すと、`call_tool` は `Invalid structured content returned by tool search_books` で始まり、続けて `jsonschema` の失敗内容を引用する `RuntimeError` を送出します。スキーマを約束するのは簡単ですが、守るのは自分の仕事です。戻り値の型とスキーマの全段階については **[構造化出力](../servers/structured-output.md)** を参照してください。

## `_meta`：モデルではなくアプリケーションのために {#\_meta-for-the-application-not-the-model}

`content` は答えのうちモデルが読む部分です。`structured_content` は同じ答えを型付きデータにしたものです。`_meta` は 3 つ目のチャネルで、答えの一部ではまったくなく、**クライアントアプリケーション**のために結果に同乗するデータです。

レコード ID、トレース ID など、UI が必要としプロンプトが必要としないものに使います。

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* 構築するときは通信路上の名前である `_meta=` を使います。クライアントは `result.meta` として読み出します。
* キーには名前空間を付けてください（`bookshop/record_ids`）。`io.modelcontextprotocol/*` のキーはプロトコルが予約しています。

!!! warning
    `_meta` はサーバーとクライアントアプリケーションの間の取り決めであり、何がモデルに届くかについての保証ではありません。何を描画するかはホストが決めます。ツール結果のどの部分にも、決して秘密情報を入れないでください。

## ケイパビリティはハンドラーに従う {#capabilities-follow-your-handlers}

`Server` は、ハンドラーを渡したメソッド群だけを正確に公開します。上の `Bookshop` は `on_list_tools` と `on_call_tool` だけを渡しているので、接続したクライアントには次のように見えます。

```json
{"tools": {"listChanged": false}}
```

`resources` も `prompts` もありません。裏付けるものがないからです。`on_list_prompts` を渡せば `prompts` が現れ、`on_completion` を渡せば `completions` が現れます。

`MCPServer` は、何かを登録したかどうかにかかわらず、常にツール、リソース、プロンプトを公開します。そのマネージャーが常に存在するからです。この層では、宣言とはコンストラクター呼び出しそのものです。

## ライフスパンのジェネリック {#the-lifespan-generic}

`Server` は、そのライフスパンが yield する型についてジェネリックです。一度アノテーションを付ければ、そのオブジェクトは現れる場所すべてで型が付きます。

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* ライフスパンは `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]` です。`async` ジェネレーターに `@asynccontextmanager` を付けると、まさにそれが得られます。
* `yield` したものが `ctx.lifespan_context` になり、ハンドラーに `ServerRequestContext[Catalog]` とアノテーションが付いているので、`.search(...)` が補完され、型チェックされます。
* サーバーの起動時に一度入り、停止時に一度出ます。起動、後始末、そして同じ考え方の `MCPServer` 版については **[ライフスパン](../handlers/lifespan.md)** を参照してください。

`lifespan=` がなければ、`ctx.lifespan_context` は空の `dict` です。

## 独自のメソッド {#a-method-of-your-own}

コンストラクターは MCP が定義するメソッドを扱います。`add_request_handler` はそれ以外のすべてを扱います。

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* 最初の引数はメソッド文字列です。通知には対になる `add_notification_handler` があります。
* `params_type` は、受信した `params` をハンドラーの実行**前**に検証するためのモデルです。つまり、カスタムメソッドはツールが受けられない検証を受けられます。`_meta` フィールドがほかのメソッドと同じようにパースされるよう、`RequestParams` をサブクラス化してください。
* ハンドラーは `BaseModel`、`dict`、または `None` を返します。SDK がそれを JSON-RPC の結果にシリアライズします。

正直な注意点が 1 つあります。高レベルの `Client` には MCP が定義するメソッドの動詞しかないので、`client.reindex()` はありません。ベンダーメソッドは、その存在をすでに知っている相手のためのものです。一緒に配布するクライアントや、JSON-RPC を話す自前の別のサービスなどです。

自分のものにできないメソッドが 1 つあります。

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

ハンドシェイクはランナーのものです。`server/discover`、`ping`、その他すべての組み込みは自由に置き換えられます。

!!! tip
    このエラーで言及されている `Server.middleware` は、`initialize` を含む**すべての**受信メッセージをラップします。新しいメソッドに応答するのではなく、トラフィックを観察したり書き換えたりしたいなら、**[ミドルウェア](middleware.md)** から始めてください。

## その他のハンドラー {#the-other-handlers}

以下はどれも、ここまでで身につけた語彙で理解できる考え方です。それぞれに専用のページがあります。

* `on_call_tool`、`on_get_prompt`、`on_read_resource` は、通常の結果の代わりに `InputRequiredResult` を返して呼び出しを一時停止し、クライアントに入力を求めることができます。**[マルチラウンドトリップ（multi-round-trip）リクエスト](../handlers/multi-round-trip.md)** を参照してください。この層らしく、何も代わりにインストールされません。`MCPServer` はデフォルトで `requestState` を封印しますが、ここでは設定した `request_state` は書いたとおりに通信路を渡ります。`server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` でオプトインするまではそうです。この 1 行（どちらの名前も `mcp.server.request_state` からインポートします）で、`MCPServer` が行うのとまったく同じ封印と検証が得られます（**[`requestState` の保護](../handlers/multi-round-trip.md#protecting-requeststate)**）。
* `on_list_resources`、`on_read_resource`、`on_list_prompts`、`on_get_prompt`、`on_completion` は、ほかのプリミティブ向けの同じ `(ctx, params) -> result` の形です。
* `on_subscriptions_listen` は 2026-07-28 の `subscriptions/listen` ストリームを提供します。`SubscriptionBus` の上に構築した `ListenHandler` を渡し、ほかのハンドラーからバスにイベントを発行してください。全体の組み立て方については **[サブスクリプション](../handlers/subscriptions.md)** を参照してください。
* `server.streamable_http_app()` は `MCPServer` のものと同じ Starlette アプリを返します。**[サーバーの実行](../run/index.md)** がほかの ASGI アプリをデプロイするのと同じ方法でデプロイしてください。この層には `server.run(transport=...)` はありません。`server.run(read_stream, write_stream, server.create_initialization_options())` が 1 組のストリーム上で 1 つの接続を駆動し、その 1 行がすべてです。

## まとめ {#recap}

* 低レベルの `Server` はハンドラーを `on_*` の**コンストラクターパラメーター**として受け取ります。すべてのハンドラーは `async (ctx, params) -> result` です。
* `input_schema` の dict は自分で書き、`CallToolResult` は自分で組み立てます。導出も、ラップも、検証も、代わりにしてくれるものはありません。
* ハンドラー内の例外は `-32603` のプロトコルエラーです。モデルが読めるツールエラーは、`is_error=True` を付けて**自分で**返す `CallToolResult` です。
* 結果の `_meta` はモデルではなくクライアントアプリケーション宛てです。
* `Server[T]` はライフスパンが yield するものについてジェネリックで、`ctx.lifespan_context` は型付きの `T` です。
* `add_request_handler(method, params_type, handler)` は任意のメソッドを提供します。`initialize` は予約されています。
* `Server` が公開するケイパビリティは、どのハンドラーを登録したかから導出されます。

`Client(server)` が両方のサーバーを同じように扱ったのは、両者がまさに同じプロトコルだからであり、それこそが要点です。さらに下の層はクラスですらありません。**[ミドルウェア](middleware.md)** です。
