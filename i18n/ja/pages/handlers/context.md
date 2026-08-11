---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Context {#the-context}

ツールの引数はモデルから渡されます。それ以外のすべて（処理中のリクエスト、ツールが属するサーバー、クライアントに話しかける手段）は、1 つのオブジェクトから得られます。それが **`Context`** です。

自分で組み立てる必要も、設定する必要もありません。要求するだけです。

## 要求する {#ask-for-it}

任意のツールに、`Context` で注釈したパラメーターを追加してください。

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* SDK はリクエストごとに新しい `Context` を組み立てて渡します。
* パラメーターの**名前は関係ありません**。`ctx`、`context`、`c` のどれでもよく、SDK は注釈を見て見つけます。
* リソースやプロンプトでも、同じように宣言できます。
* `ctx.request_id` は、関数がいま処理しているリクエストの id です。

!!! info
    FastAPI を使ったことがあれば、この仕組みには見覚えがあるはずです。フレームワーク自身の型（あちらでは `Request`、こちらでは `Context`）でパラメーターを宣言すると、フレームワークがそれを供給します。登録するものも設定するものもありません。型注釈がこの仕組みのすべてです。

### モデルからは見えない {#invisible-to-the-model}

ここはしっかり身につけておきたい部分です。`tools/list` が `search_books` について報告する入力スキーマは次のとおりです。

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

プロパティは 1 つです。`ctx` は引数ではありません。スキーマには決して現れず、モデルに知らされることもなく、どのクライアントも値を入れられません。これは作成者と SDK の間の取り決めであり、通信上には現れません。

### 試してみる {#try-it}

MCP Inspector でサーバーを実行してください。

```console
uv run mcp dev server.py
```

`search_books` のフォームには `query` フィールドが 1 つだけあります。`dune` を指定して呼び出してください。

```text
[request 3] Found 3 books matching 'dune'.
```

この数字は、たまたまそのときのリクエストの番号です。もう一度ツールを呼び出すと変わります。リクエストごとに専用の `Context` が作られるからです。

## 何が得られるか {#what-it-gives-you}

注入されるオブジェクトは小さなものです。`request_id` のほかに次のものがあります。

* `await ctx.read_resource(uri)`：ツールの中からサーバー**自身の**リソースを 1 つ読みます。次のセクションで扱います。
* `await ctx.report_progress(progress, total, message)`：長い呼び出しの最中に、進捗を呼び出し側へ逐次送ります。詳しくは **[進捗](progress.md)** を参照してください。
* `await ctx.elicit(message, schema)` と `await ctx.elicit_url(...)`：ツールを一時停止してユーザーに質問します。これが **[エリシテーション（elicitation）](elicitation.md)** です。
* `ctx.session`：このクライアントとの会話のサーバー側です。クライアントに送る通知はここにあり、最後のセクションで使います。
* `ctx.headers`：トランスポートが運んだリクエストヘッダー、stdio では `None` です。カスタムヘッダーは `(ctx.headers or {}).get("x-...")` で読めます。ヘッダーはクライアントが与える入力です。ロケールや機能フラグには使えますが、身元の確認には決して使わないでください。
* `ctx.request_context`：リクエストごとの生のレコードです。実際に手を伸ばすフィールドは `lifespan_context`、つまり起動コードが yield したオブジェクトです（**[ライフスパン](lifespan.md)** を参照）。

ロギングは意図的にこの一覧に入れていません。サーバーは、ほかの Python プログラムと同じく Python の `logging` モジュールでログを記録します。その理由は短いページ **[ロギング](logging.md)** にまとめてあります。

!!! tip
    注入が行われるのは登録した関数だけです。ツールが呼び出すヘルパーに専用の `Context` は渡されないので、`ctx` を通常の引数として渡してください。どこか別の場所から取り出せる暗黙の「現在のコンテキスト」はありません。

## 自分のリソースを読む {#read-your-own-resources}

サーバーのリソースはクライアントだけのものではありません。ツールからも読めます。

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` は `resources/read` を処理するのと同じレジストリを通して URI を解決するので、ツールはクライアントが受け取るのと同じものを得ます。コンテンツブロックごとに 1 つの `ReadResourceContents` を持つイテラブルです。この URI の場合は 1 つです。

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` は `genres()` が返したものそのままです。情報源は 1 つです。クライアントはリソースを閲覧し、ツールはそれを消費し、誰も文字列をコピーしません。
* `describe_catalog` の唯一のパラメーターは `Context` なので、その入力スキーマには**プロパティが 1 つもありません**。モデルは `{}` で呼び出します。

## 一覧が変わったことをクライアントに伝える {#tell-the-client-the-list-changed}

サーバーが提供するものは、インポート時に固定されるわけではありません。実行時にツールを登録し、それをクライアントに伝えます。

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` は普通の関数をツールとして登録します。名前、説明、スキーマは `@mcp.tool()` を使った場合とまったく同じように導出されます。
* `await ctx.session.send_tool_list_changed()` は `notifications/tools/list_changed` を送ります。これを受け取ったクライアントは `tools/list` を再度呼び出し、`recommend_book` を目にします。

同種のメソッドには `send_resource_list_changed()`、`send_prompt_list_changed()`、そして特定の 1 つのリソースの変更を知らせる `send_resource_updated(uri)` があります。

2026-07-28 の接続では、クライアントは自分が開いた `subscriptions/listen` ストリーム上でしか変更通知を受け取らないため、上記の `send_*` メソッドはそれらのストリームに届きません。`Context` の公開メソッドは、購読中のすべてのストリームに一度に配信します。`await ctx.notify_tools_changed()`、`await ctx.notify_prompts_changed()`、`await ctx.notify_resources_changed()`、`await ctx.notify_resource_updated(uri)` です。レプリカをまたいだスケールアウトも含め、詳しくは **[サブスクリプション](subscriptions.md)** を参照してください。

!!! check
    誰かが `enable_recommendations` を実行するまで、約束しているツールは存在しません。それでも呼び出すと、結果はモデルが読めるエラーです。

    ```text
    Unknown tool: recommend_book
    ```

    `enable_recommendations` を実行すると、まったく同じ呼び出しが成功します。ツールの一覧は本当に動的です。`tools/list` は「いま」登録されているものをそのまま反映します。

## まとめ {#recap}

* パラメーターに `Context` を注釈すると（ツールでも、リソースでも、プロンプトでも）、SDK がそれを注入します。名前は自由です。
* モデルからは見えません。入力スキーマに含まれるのは、常に本物の引数だけです。
* `ctx.request_id` はリクエストを識別し、`ctx.request_context.lifespan_context` は起動時に yield したものです。
* `await ctx.read_resource(uri)` を使うと、ツールからサーバー自身のリソースを読めます。
* `ctx.session` はクライアントへ戻るチャネルです。`send_tool_list_changed()` とその同種のメソッドは、変更した一覧を取得し直すようクライアントに伝えます。
* 進捗の報告とエリシテーションも `Context` が出発点です。それぞれに専用のページがあります。

モデルが目にすることのない、自分の関数で埋めるパラメーターが **[依存関係](dependencies.md)** です。
