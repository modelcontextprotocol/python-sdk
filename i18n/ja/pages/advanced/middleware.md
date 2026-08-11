---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# ミドルウェア {#middleware}

**ミドルウェア**とは、サーバーが受け取るすべてのメッセージを包み込む 1 つの非同期関数です。

`async (ctx, call_next)` の形で書き、`server.middleware` に追加します。API はこれだけです。

!!! warning
    ミドルウェアのリストは、ソース上で**暫定（provisional）**とマークされています。シグネチャやセマンティクスは 2.x のマイナーリリースで変わる可能性があります。メッセージを「観察」する（計時、ログ、トレース）ため、あるいは「拒否」するために使ってください。サーバーの土台にはしないでください。

`MCPServer` は構築時にこのリストを受け取り（`MCPServer(name, middleware=[...])`）、`mcp.middleware` として公開します。低レベルの `Server` も同じリストを `server.middleware` として公開します。以下の例では低レベルの `Server` を使います。`Server(name, on_call_tool=...)` に馴染みがなければ、先に**[低レベルの Server](low-level-server.md)** を読んでください。

## 計時ミドルウェア {#a-timing-middleware}

サーバー 1 つ、ツール 1 つ、そして各メッセージにかかった時間をログに出すミドルウェア 1 つです。

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` はハンドラーが受け取るのと同じ `ServerRequestContext` です。`ctx.method` は生のメソッド文字列、`ctx.params` はバリデーション**前**の生のパラメーターです。
* `call_next(ctx)` はチェーンの残り、つまりバリデーション、ハンドラーの検索、ハンドラー本体を実行します。返ってきたものをそのまま返せば、レスポンスには手が加わりません。
* `try`/`finally` は意図的なものです。ハンドラーが例外を送出しても計時されます。失敗は `call_next` から出てくる例外としてミドルウェアに届くからです。
* `server.middleware.append(...)` で登録します。リストは外側から順に実行されるので、`middleware[0]` が通信路に最も近いミドルウェアです。

### 試してみる {#try-it}

クライアントを接続し、ツールを一覧し、1 つ呼び出してください。ログには **3 行**出ます。

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

呼び出しは 2 回なのに、行は 3 つです。最初の行は `server/discover`、つまり何かを要求する前に、クライアントが接続をセットアップするために送ったリクエストです。

ここがポイントです。ミドルウェアは受信する**すべての**メッセージを包みます。

* 接続のセットアップ。`server/discover`、あるいはレガシーセッションでは `initialize` と `notifications/initialized` です。
* すべてのリクエストとすべての通知。通知の場合は `ctx.request_id is None` であり、`call_next(ctx)` は `None` を返し、何を返しても破棄されます。
* サーバーにハンドラーがないメソッドでさえ対象です。`call_next` は `MCPError(-32601, "Method not found")` を送出し、それがミドルウェアを「通り抜けて」クライアントへ向かいます。

## ミドルウェアの中でできること {#what-you-can-do-inside-one}

ためらうべき度合いが小さいものから順に並べます。

* **観察する。** 時間を計る、数える、ログに出す。上の例がこれです。
* **拒否する。** `call_next(ctx)` を呼ぶ「代わりに」`MCPError` を送出すると、そのメッセージ 1 つに JSON-RPC エラーで応答します。接続は維持され、次のメッセージは通ります。サーバーが呼び出し側ごとに `subscriptions/listen` を制御するのはこの方法です。サブスクリプションのページの**[誰が監視できるかを決める](../handlers/subscriptions.md#deciding-who-may-watch)**で順を追って説明しています。
* **書き換える。** `ctx` はデータクラスです。`await call_next(dataclasses.replace(ctx, params=...))` とすると、クライアントが送ったものとは異なるパラメーターをチェーンの残りに渡せます。`initialize` に対しては決して行わないでください。クライアントが受け取る結果は書き換えたパラメーターから組み立てられますが、サーバーは元の通信路上のパラメーターから接続状態を確定します。両者が、ネゴシエートした内容について食い違ったままハンドシェイクを終える可能性があります。
* **応答する。** `call_next(ctx)` を呼ばずに結果を返すと、それがレスポンスとしてクライアントへ送られます。`call_next` が渡してくるのは完成した送信形式であり、パイプラインは返したものに一切手を加えないので、エンベロープ全体が自分の責任になります。2026 年世代の接続ではこれに `serverInfo` の `_meta` スタンプが含まれます。SDK はハンドラーの結果にはこれを付けますが、ミドルウェアが返すものには付けません。

!!! check
    `initialize` もミドルウェアが包むものの 1 つであり、ミドルウェアはそのための「唯一の」フックです。`add_request_handler` で乗っ取ろうとすると、SDK は拒否します。

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` はインラインで処理されます。ミドルウェアチェーンが返るまで、サーバーはそれ以上の受信メッセージを読みません。そのため、`initialize` の処理中にサーバーからクライアントへのリクエスト（`ctx.session.send_request(...)` やエリシテーション（elicitation））を await すると、**接続がデッドロックします**。待っているレスポンスは決して読まれないからです。送りっぱなしの通知は問題ありません。

## デフォルトで有効な唯一のミドルウェア {#the-one-middleware-that-ships-on-by-default}

SDK が同梱するミドルウェアはちょうど 1 つで、すでにサーバーのリストに載っています。すべてのメッセージに対して OpenTelemetry のスパンを発行するミドルウェアです。自分で追加する必要はなく、ほとんどの場合は意識することもありません。エクスポーターをインストールするまでは何もしません。専用のページがあります。**[OpenTelemetry](../run/opentelemetry.md)** を参照してください。

!!! info
    ASGI ミドルウェアを書いたことがあれば、この形はもう知っています。Starlette の `(scope, receive, send)` が `(ctx, call_next)` になり、トランスポートの「後」で、生の HTTP リクエストではなくデコード済みのメッセージに対して動きます。2 つは組み合わせられます。`streamable_http_app()` 上の Starlette ミドルウェアは HTTP を見て、こちらは MCP を見ます。

## まとめ {#recap}

* ミドルウェアは `async (ctx, call_next) -> result` です。`MCPServer(middleware=[...])` として渡すか（または `mcp.middleware` に追加し）、低レベルの `Server` では `server.middleware` に追加します。
* 受信する**すべての**メッセージ（`server/discover`、`initialize`、リクエスト、通知、未知のメソッド）を包み、外側から順に実行されます。
* `ctx.request_id is None` で、通知とリクエストを見分けます。
* `call_next` を呼ぶ代わりに例外を送出すると、メッセージを 1 つ拒否できます。接続は維持されます。
* SDK 自身の OpenTelemetry トレースもミドルウェアであり、すでにリストに載っています。**[OpenTelemetry](../run/opentelemetry.md)** を参照してください。
* この仕組み全体が暫定です。観察には使っても、その上に何かを築かないでください。

リクエストを包むものはこれですべてです。**[認可](../run/authorization.md)**は、そもそもそのリクエストを実行させるかどうかを決めるものです。
