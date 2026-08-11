---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# クライアントのコールバック {#client-callbacks}

MCP のリクエストは、ほぼすべてが一方向です。クライアントからサーバーへ送られます。

サーバーのほうから**クライアント**に何かを頼むこともできます。ユーザーに質問する、ユーザーのモデルでサンプリングする、ユーザーのワークスペースフォルダーを一覧する、といったことです。こうしたリクエストには、`Client(...)` に**コールバック**を渡して応答します。

## 問い合わせをするサーバー {#a-server-that-asks}

次のサーバーのツールは、単独では処理を終えられません。

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` は `elicitation/create` リクエストを**クライアントに**送り、待機します。
* 誰か（フォームに入力する人か、こちらのコード）が `name` を渡すまで、ツールは戻りません。

これはサーバー側の話で、**[エリシテーション（elicitation）](../handlers/elicitation.md)** のページが扱います。このページは通信路の反対側の話です。

## エリシテーションのコールバック {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* エリシテーションのコールバックは `async (context, params) -> ElicitResult` です。
* `params.message` が質問です。`params.requested_schema` は、サーバーが求める答えの JSON Schema です。実際のクライアントはこれをもとにフォームを描画しますが、ここでは自動で埋めています。
* 戻り値は `ElicitResult(action="accept", content={...})`、`action="decline"`、`action="cancel"` のいずれかです。それ以外の選択肢は `ErrorData(...)` だけで、これはリクエストを拒否し、呼び出し全体を失敗させます。
* `context` は `ClientRequestContext` です。使用中の `session`、サーバーの `request_id`、サーバーが付けた `meta` を持ちます。

!!! tip
    `params` は 2 つのエリシテーションモードのユニオンです。ここでは `params.mode` は `"form"` です。`"url"` のリクエストはスキーマの代わりに `params.url` を持ちます。1 つのコールバックで両方を扱い、`params.mode` で分岐してください。パターンの全体は **[エリシテーション](../handlers/elicitation.md)** にあります。

### 試してみる {#try-it}

`issue_card` を呼び出し、両側の様子を見てみましょう。

コールバックは、サーバーからの質問をパース済みの状態で受け取ります。

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

コールバックが答えると、ツールの中で `ctx.elicit(...)` が再開し、ツールが完了します。

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

こちらから `tools/call` が 1 回、サーバーからの折り返しの `elicitation/create` が 1 回、それに答えるのがこちらの関数です。すべてが 1 回のツール呼び出しの中で完結します。

!!! info
    `Client(...)` の呼び出しにある `mode="legacy"` は、実際に働いています。デフォルトでは `Client(...)` は新しいプロトコルの経路をネゴシエートしますが、その経路にはサーバーからクライアントへのリクエストのためのバックチャネル（back-channel）がありません。コールバックが動く前に `ctx.elicit` が失敗します。これを決めるのはトランスポートではなく、ネゴシエートされたプロトコルです。インメモリでも URL 越しでも同じです。クライアントがこうしたリクエストに答える必要があるときは、必ず `mode="legacy"` を指定してください。このページの裏にあるテストはすべてそうしています。詳しくは **[プロトコルバージョン](../protocol-versions.md)** を参照してください。

    2026-07-28 のセッションでもコールバックが使われなくなるわけではなく、呼ばれ方が変わります。ツールが `ElicitRequest` を含む `InputRequiredResult` を返すと、`Client` はそのエントリを同じ `elicitation_callback` に振り分け、呼び出しを再試行してくれます。この流れは **[マルチラウンドトリップ（multi-round-trip）リクエスト](../handlers/multi-round-trip.md)** で説明しています。

## コールバックはケイパビリティ {#a-callback-is-a-capability}

クライアントがエリシテーションのリクエストに答えられることを、サーバーに伝えた覚えはないはずです。伝えたのは SDK です。

クライアントは接続時に自分の `capabilities` を宣言します。サーバー側の宣言と鏡写しの関係です。このオブジェクトを自分で書くことはありません。**コールバックを登録すること自体が宣言です。**

| 渡すもの | クライアントが宣言するもの |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| どれも渡さない | `{}` |

細かい指定が 1 つだけあります。サンプリングのサブケイパビリティです。サンプラーが `tools` / `tool_choice` パラメーターを扱える場合は、`sampling_callback` と一緒に `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` を渡してください。サーバーは `sampling.tools` が宣言されているのを確認してからでないと、これらを送れません。

`logging_callback` と `message_handler` は表にありません。これらは通知を扱うもので、通知にケイパビリティは要りません。

サーバーは `ctx.session.check_client_capability(...)` で宣言を読み取ります。これを行うツールを追加します。

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

`elicitation_callback` だけを渡して接続し、呼び出します。

```python
result.structured_content  # {'result': ['elicitation']}
```

3 つのコールバックをすべて渡すと結果は `['elicitation', 'sampling', 'roots']`、どれも渡さなければ `[]` です。

!!! check
    今度はわざと間違えてみましょう。`elicitation_callback` **なしで**接続し、それでも `issue_card` を呼び出します。

    サーバーの `elicitation/create` リクエストはそれでもクライアントに届きます。そして、扱えると宣言していないので、SDK が代わりにエラーで答えます。そのエラーが呼び出し全体を失敗させます。`call_tool` は `is_error` の結果を返すのではなく、例外を送出します。

    ```text
    MCPError: Elicitation not supported
    ```

    これはツールのエラーではなくプロトコルエラー（`-32600`、*invalid request*）です。モデルが読んで再試行できるものは何もありません。`client_features` を用意する価値があるのはこのためです。行儀のよいサーバーは、頼む前に確認します。

## 非推奨の 2 つ {#the-deprecated-pair}

`sampling_callback` は `sampling/createMessage` に答えます。サーバーがクライアント側のモデルに何かを補完させるリクエストです。`list_roots_callback` は `roots/list` に答えます。サーバーが、作業してよいディレクトリを尋ねるリクエストです。

どちらも動作します。どちらも上のルールに従います。そしてどちらも、**2026-07-28 の仕様で削除される** RPC に応えるものです。新しいサーバーはリクエストの途中でクライアントを呼び返すことはせず、リクエストをツール結果の一部として返してきます（**[マルチラウンドトリップリクエスト](../handlers/multi-round-trip.md)**）。コールバック自体が使われなくなるわけではありません。`InputRequiredResult` が `CreateMessageRequest` や `ListRootsRequest` を含んでいると、`Client` の自動ループが、ここで登録したのと同じ `sampling_callback` または `list_roots_callback` にそれを振り分けます。一覧は **[非推奨の機能](../deprecated.md)** にあります。

まだ移行していないサーバーとやり取りするには、引き続きこれらのコールバックが必要です。シグネチャは次のとおりです。

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* サンプリングのコールバックは `CreateMessageRequestParams` の全体（`messages`、`model_preferences`、`max_tokens`）を受け取り、`CreateMessageResult` を返します。モデルを動かすのはこちら側で、やり方は自由です。SDK はリクエストを運ぶだけです。
* ルート（roots）のコールバックはパラメーターを一切取らず、`ListRootsResult` を返します。
* どちらも、拒否するときは代わりに `ErrorData(...)` を返せます。

`elicitation_callback` とまったく同じように `Client(...)` に渡します。

## 通知のコールバック {#the-notification-callbacks}

あと 2 つあります。どちらも何も宣言しません。

`logging_callback` は、サーバーが送る `notifications/message` を `LoggingMessageNotificationParams`（`level`、`logger`、`data`）として受け取ります。プロトコルのロギング自体が 2026-07-28 の仕様で非推奨になっています（代わりにどうするかは **[ロギング](../handlers/logging.md)** にあります）。そのため、このコールバックはまだ通知を出すサーバーのために存在します。2026 年世代の接続では、コールバックだけでは何も届きません。2026 年のサーバーは、オプトインしたリクエストにしかログメッセージを送らないからです。`Client(...)` に `log_level="info"`（または別のレベル）を渡すと、すべてのリクエストにそのオプトインが付き、そのレベル以上を受け取れます。2026 年より前のサーバーはこれを無視し、従来どおり `logging/setLevel` の挙動を保ちます。

`message_handler` は何でも受け取る窓口です。セッションが表に出すサーバー通知はすべて（それぞれ専用のコールバックに加えて）ここに届きます。ストリームを使うトランスポートでは、トランスポートレベルの `Exception` もすべて届きます。届かないものが 2 つあります。`notifications/cancelled` は表に出されず SDK が適用します。動作中の `listen()` ストリームに対する購読の確認応答は、そのストリームが消費します。パラメーターには `IncomingMessage`（`ServerNotification | Exception`、`mcp.client` からエクスポート）で注釈を付けてください。覚えておく価値のあるパターンは `if isinstance(message, Exception): raise message` の 1 つです。これで、接続が壊れたときに黙って消えるのではなく、はっきり失敗します。

## まとめ {#recap}

* サーバーはクライアントにリクエストを送れます。`Client(...)` に渡したコールバックで応答します。
* 現行のものはエリシテーションのコールバックです。`async (context, params) -> ElicitResult` で、フォームモードと URL モードの両方を 1 つの関数で扱います。
* **コールバックの登録がケイパビリティの宣言です。** 登録がなければ、SDK が代わりにサーバーのリクエストを拒否し、呼び出し全体が `MCPError` で失敗します。
* サーバーは、頼む前に `ctx.session.check_client_capability(...)` で確認します。
* `sampling_callback` と `list_roots_callback` も同じように動きますが、非推奨の機能のためのものです。新しいサーバーは代わりにマルチラウンドトリップリクエストを使います。
* `logging_callback` と `message_handler` は通知を受け取ります。何も宣言しません。

`Client(...)` の第 1 引数はトランスポートのオブジェクトです。すべての種類は **[クライアントのトランスポート](transports.md)** で扱っています。
