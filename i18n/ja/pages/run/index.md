---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# サーバーの実行 {#running-your-server}

`mcp.run()` がサーバーを起動します。

決めることはただ 1 つ、**トランスポート**です。サーバーとクライアントの間でバイト列が実際にどうやり取りされるかを指します。

## トランスポートを選ぶ {#pick-a-transport}

| トランスポート | 概要 | 使う場面 |
|---|---|---|
| `stdio` | ホストがファイルをサブプロセスとして起動し、その stdin と stdout を介して通信します。 | ローカルサーバー。デフォルトです。 |
| `streamable-http` | ポートで待ち受ける本物の HTTP サーバーです。 | デプロイするものすべて。 |
| `sse` | 古い HTTP トランスポートです。 | 使いません。 |

!!! warning
    SSE は 2025-03-26 のプロトコル改訂で Streamable HTTP に置き換えられました。
    `mcp.run(transport="sse")` は今も動作し、専用の `sse_path=` と `message_path=` オプションもありますが、まだ移行していないクライアントのために残されているだけです。新しいものをこの上に作らないでください。

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` は同期的です。サーバーが動いている間ずっとブロックします。
* 引数がなければ、トランスポートは `stdio` です。
* `if __name__ == "__main__":` の下に置くのは、サーバーを読み込むものすべて（`mcp dev`、`mcp run`、`mcp install`、テスト）がこのファイルを **import** するからです。このガードにより、import しただけでサーバーが起動してしまうのを防ぎます。

### stdio {#stdio}

設定するものは何もありません。ホストがファイルを子プロセスとして起動し、その stdin にリクエストを書き込み、stdout からレスポンスを読み取ります。

自分で実行してみると、その結果がわかります。

```console
python server.py
```

何も表示されず、戻ってもきません。ホストが先に話しかけてくるのを stdin で待っているのです。

つまり stdout **が通信路そのもの**だということでもあります。サービス提供中、SDK は通信路をプライベートなディスクリプターに移し、stdout に「フラッシュされた」出力（継承した stdout に書き込むサブプロセスや、フラッシュされた `print()`）を stderr へ振り向けます。そこならストリームを壊すおそれがありません。サービス開始「前」に stdout にフラッシュされた出力（ラッパースクリプトの echo や、バッファリングなしの import 時の print）は、依然として通信路に流れ込みます。終了時にインタープリターが吐き出すまでバッファに溜まったままの `print()` も同様です。本当に必要な出力には `logging` モジュールが適切な手段です。そのハンドラーは各レコードを発生のたびに stderr へフラッシュします。詳しくは **[ロギング](../handlers/logging.md)** を参照してください。

### 試してみる {#try-it}

```console
uv run mcp dev server.py
```

Inspector は本物のホストとまったく同じことをします。`server.py` をサブプロセスとして起動し、stdio で接続します。

ポートは指定していません。そもそもポートがないのです。

## Streamable HTTP {#streamable-http}

同じサーバーを代わりにポートに載せるには、`run()` でトランスポート（とそのオプション）を指定します。

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

この 1 行で Starlette アプリが組み立てられ、uvicorn で配信されます。クライアントは `http://127.0.0.1:3001/mcp` に接続します。

トランスポートごとに固有のキーワード引数があり、すべて `run()` に渡します。

* `host` / `port`：待ち受ける場所です。デフォルトは `127.0.0.1` と `8000` です。
* `streamable_http_path`：MCP エンドポイントの場所です。デフォルトは `/mcp` です。
* `json_response=True`：各 POST に SSE ストリームではなく単一の JSON ボディで応答します。このボディにはレスポンスしか入る余地がありません。そのため、リクエストの途中でクライアントを呼び返すツール（`ctx.elicit()` やサンプリング）は、この区間で `NoBackChannelError` を送出します。進行中の呼び出しに紐づく通知（`ctx.report_progress()` による進捗や呼び出しごとのログメッセージ）は破棄されますが、独立した `GET` ストリームは無関係な通知を引き続き運びます。
* `stateless_http=True`：リクエストごとに新しいトランスポートを作り、セッションを追跡しません。
* `max_request_body_size`：受け付ける POST ボディの最大サイズ（バイト単位）です。デフォルトは 4 MiB で、これより大きいリクエストはパースやセッション作成の前に HTTP 413 を受け取ります。正当な MCP メッセージがこのサイズを超える場合にだけ引き上げてください。
* `event_store`、`retry_interval`、`transport_security`：再開可能性と DNS リバインディング保護です。localhost 以外の場所にデプロイするまでは後回しでかまいません。`transport_security` については **[デプロイとスケール](deploy.md)** で扱います。

!!! warning
    トランスポートのオプションは `run()` に渡します。`MCPServer(...)` には**渡しません**。コンストラクターはサーバーが「何であるか」、つまり名前、バージョン、instructions を記述します。`run()` はそれをどう配信するかを記述します。逆にすると、MCP が関わる前に Python が答えを返します。

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` は近道です。それ以上のことが必要になった瞬間（既存のアプリの中にサーバーをマウントする、1 つのプロセスで 2 つのサーバーを動かす、ブラウザークライアント向けの CORS）、ASGI アプリを自分で組み立てて任意の ASGI ホストに渡すことになります。それが **[既存のアプリに追加する](asgi.md)** です。

## サーバー設定 {#server-settings}

実行に関することのうち、いくつかはトランスポートとは無関係です。これらはコンストラクター引数です。

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`：`MCPServer(...)` が構築された瞬間に `logging.basicConfig()` に渡されます。これは**ルート**ロガーを設定するため、SDK のロガーだけでなく自分のロガーのレベルも決まります。デフォルトは `"INFO"` です。
* `debug`：HTTP トランスポートが組み立てる Starlette アプリに転送されます。デフォルトは `False` です。

どちらも `mcp.settings` に載り、実行時に読み出せます。

## `mcp` コマンド {#the-mcp-command}

`[cli]` エクストラをインストールすると、これらすべてを包む小さなコマンドラインツールが入ります。

`mcp dev` はサーバーを **MCP Inspector** の下で実行します。

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` は組み立てる環境にパッケージを追加し、`--with-editable` は自分のパッケージをそこにインストールします。`PATH` に `npx` が必要です。Inspector は Node.js アプリだからです。

`mcp run` はファイルを import し、サーバーオブジェクト（モジュールレベルの `mcp`、`server`、`app` のいずれか）を見つけて、その `run()` を呼び出します。

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

`:` の接尾辞は、オブジェクトが `mcp`、`server`、`app` 以外の名前のときにそのオブジェクトを指定します。

ここでは `if __name__ == "__main__":` ブロックは決して実行されません。`mcp run` が自分で `run()` を呼び出し、転送するオプションは `--transport` だけです。

`mcp install` はサーバーを **Claude Desktop** に登録し、アプリが代わりに起動してくれるようにします。

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` と `-f .env` はそのエントリに環境変数を記録します。Claude Desktop はサーバーを独自のプロセスで起動します。シェルの環境はそこにはありません。

`mcp install` が知っているホストは Claude Desktop だけです。他のホスト（Claude Code、Cursor、VS Code）はそれぞれの設定ファイルに同じ起動コマンドを書きます。それぞれについては **[本物のホストに接続する](../get-started/real-host.md)** に載っています。

`mcp version` はインストールされている SDK のバージョンを表示します。

!!! tip
    `mcp dev` と `mcp run` が理解するのは `MCPServer` だけです。低レベルの `Server` で組み立てる場合は、自分で実行します。**[低レベルの Server](../advanced/low-level-server.md)** を参照してください。

## まとめ {#recap}

* **トランスポート**とは、バイト列がサーバーに届く方法です。ローカルのサブプロセスなら `stdio`、ポートなら `streamable-http` です。SSE は置き換えられました。
* `mcp.run()` でトランスポートを選びます。引数がなければ `stdio` で、ブロックします。
* トランスポートのオプション（`host`、`port`、`streamable_http_path` など）はすべて `run()` の引数であり、`MCPServer(...)` の引数ではありません。
* `run()` は `if __name__ == "__main__":` の下に置いてください。サーバーを読み込むものはすべて、まずファイルを import します。
* `log_level=` と `debug=` はコンストラクター引数で、`mcp.settings` に載ります。
* Inspector には `mcp dev`、ファイルの実行には `mcp run`、Claude Desktop には `mcp install`、バージョンには `mcp version` です。
* トランスポートによってサーバーが「何であるか」が変わることはありません。このページの 3 つのファイルはすべて、まったく同じツールを公開しています。

`run()` そのものが限界になるとき（すでに存在するアプリの中にサーバーを置く場合）は **[既存のアプリに追加する](asgi.md)** です。本物のホスト名と複数のワーカーは **[デプロイとスケール](deploy.md)** です。そして、一部のクライアントがまだ仕様バージョン 2025-11-25 以前にとどまっているなら、**[レガシークライアントへの対応](legacy-clients.md)** が朗報です。
