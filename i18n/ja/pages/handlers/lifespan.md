---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# ライフスパン {#lifespan}

実際のサーバーの多くは、動いている間ずっと何かを保持しています。データベースのプール、HTTP クライアント、読み込んだモデルなどです。

それを呼び出しのたびに組み立てたくはありませんし、終了時にはきれいに閉じたいはずです。そのためにあるのが**ライフスパン**です。

## 型付きのライフスパン {#a-typed-lifespan}

ライフスパンは、サーバーを受け取って**オブジェクトを 1 つ** `yield` する `@asynccontextmanager` です。yield したものは、サーバーが動いている限りすべてのハンドラーから利用できます。

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

下から順に読んでいきます。

* `app_lifespan` は `yield` の**前**で `Database` に接続し、その**後**、`finally` の中で切断します。これが起動と終了の処理です。
* yield するのは `AppContext` です。セットアップしたものを保持するだけの素朴な dataclass です。今日はフィールドが 1 つでも、明日は 10 個になるかもしれません。
* つなぎ込みは `MCPServer("Bookshop", lifespan=app_lifespan)` だけで完了します。
* ツールの中では、yield したオブジェクトは `ctx.request_context.lifespan_context` として取り出せます。

ライフスパンは **1 回だけ**実行されます。サーバーの起動時（最初のリクエストより前）に入り、サーバーの停止時に抜けます。その間のすべてのリクエストが同じ `AppContext` を共有します。

!!! info
    FastAPI の `lifespan` を書いたことがあれば、すでに知っている内容です。同じデコレーター、同じ `yield`、同じ `finally` です。

### モデルから見えるもの {#what-the-model-sees}

新しいものは何もありません。`ctx` は **Context** パラメーターなので、SDK が注入し、入力スキーマには決して現れません。

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

モデルが渡せる引数は `genre` だけです。ライフスパンはサーバー側の内部事情です。

`@mcp.resource()` と `@mcp.prompt()` の関数も `ctx` パラメーターを受け取れます。ただし型は裸の `Context` と書きます。理由は次の節で説明します。`ctx` が持っているものはすべて **[Context](context.md)** にまとめてあります。

### 本当に型が付いている {#it-really-is-typed}

もう一度アノテーションを見てください。`ctx: Context[AppContext]` です。

この型パラメーター 1 つがあるからこそ、型チェッカーにとって `ctx.request_context.lifespan_context` は `AppContext` **そのもの**になります。`.db` は自動補完され、`.dbb` はサーバーを動かす前からエラーになります。

代わりに裸の `Context` と書くと、`lifespan_context` の型は `dict[str, Any]` になります。ライフスパンが何を yield したのか、型チェッカーには知りようがないからです。実行時にはオブジェクトはそこにありますが、型による補助は失われます。

!!! warning
    `Context[AppContext]` は**ツール専用**の書き方です。`@mcp.resource()` や `@mcp.prompt()` の関数に付けると、そのハンドラーの呼び出しはすべて失敗します。クライアントにはエラーが返り、サーバーのログには理由が記録されます。

    ```text
    Context is not available outside of a request
    ```

    リソースとプロンプトでは、裸の `ctx: Context` と書いてください。ライフスパンが yield したオブジェクトは、実行時には引き続き `ctx.request_context.lifespan_context` にあります。手放すのは型パラメーターであって、オブジェクトではありません。

!!! tip
    ライフスパンは必ず存在します。渡さなければ SDK のデフォルトが空の `dict` を yield するので、`ctx.request_context.lifespan_context` は `{}` であり、`None` になることはありません。裸の `Context` で型が `dict[str, Any]` になるのも、このデフォルトがあるためです。

## 実際に動かして確かめる {#watch-it-happen}

「起動処理は最初のリクエストより前に走る」というのは、言われたまま信じるべき類の話ではありません。

サーバーをライフサイクルだけに絞り込みましょう。`Database` に `connected` フラグを持たせ、`connect()` と `disconnect()` でそれを切り替え、その状態を報告するツールを追加します。

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` をモジュールレベルに置いている理由は 1 つだけです。サーバーの「外側」から覗けるようにするためです。

!!! check
    3 つの時点で、3 つの値になります。

    * サーバーの起動前、`database.connected` は `False` です。モジュールをインポートしただけでは何も接続されていません。
    * 動いている間に `database_status` を呼び出すと、結果は `"connected"` です。
    * サーバーを止めると `finally` ブロックが走り、`database.connected` は再び `False` になります。

    処理は置いた場所でちょうど実行されました。`yield` の前後であって、インポート時でもリクエストごとでもありません。

## まとめ {#recap}

* `lifespan=` には、サーバーを受け取ってオブジェクトを 1 つ `yield` する `@asynccontextmanager` を渡します。
* `yield` の前のコードが起動処理です。その後の `finally` が終了処理です。
* 実行は 1 回だけで、サーバーの一生全体を囲みます。リクエストごとではありません。
* `yield` したものは、すべてのツール、リソース、プロンプトで `ctx.request_context.lifespan_context` として使えます。
* `ctx: Context[AppContext]` と書けば、ツールではそのアクセスに完全に型が付きます。リソースとプロンプトでは裸の `Context` を使います。
* `lifespan=` を渡さなければ空の `dict` です。`None` になることはありません。

呼び出しの途中で止まり、本人にしかわからないことをユーザーに尋ねるハンドラーについては、**[エリシテーション（elicitation）](elicitation.md)** を参照してください。
