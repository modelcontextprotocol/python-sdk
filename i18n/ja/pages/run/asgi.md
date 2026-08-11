---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# 既存のアプリに組み込む {#add-to-an-existing-app}

`mcp.run("streamable-http")` は Web サーバーを起動してくれます。ただ、そうしたくない場合もあります。MCP サーバーがより大きな Web アプリケーションの一部である場合や、すでに ASGI のデプロイ環境がある場合です。

そのために、`mcp.streamable_http_app()` は **Starlette アプリケーション**を返します。

Starlette アプリは ASGI アプリなので、ASGI をホストできるもの（uvicorn、Hypercorn、別の Starlette、FastAPI）なら何でも MCP サーバーをホストできます。

## アプリ {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` は普通の ASGI アプリケーションです。任意の ASGI サーバーに渡せます。

```console
uvicorn server:app
```

MCP エンドポイントは `/mcp` にあるので、クライアントは `http://127.0.0.1:8000/mcp` に接続します。

このアプリには最初から 2 つのものが備わっています。

* ルートが 1 つ（`/mcp`）。Streamable HTTP のエンドポイントです。
* **ライフスパン**。`mcp.session_manager` を起動します。これは、稼働中のすべてのセッションのバックグラウンド処理を管理するオブジェクトです。

アプリを単体で動かす（`uvicorn server:app`）なら、どちらも意識することはありません。

!!! tip
    `streamable_http_app()` は `mcp.run("streamable-http", ...)` と同じキーワード引数を受け取ります。ただし `port` は除きます。ポートはアプリを配信する側のものだからです。`host` は引き続き受け付けますが、ここでは何もバインドしません。実際に何を制御するのかは **[デプロイとスケール](deploy.md)** で説明しています。オプションそのものは **[サーバーの実行](index.md)** で扱っています。

`mcp.sse_app()` は、すでに置き換えられた SSE トランスポート向けに同じものを提供します。

## 指定しない限り localhost のみ {#localhost-only-until-you-say-otherwise}

デフォルトでは、このアプリは localhost 宛てのリクエストに**だけ**応答します。`streamable_http_app()` は自分がどのホスト名の背後で配信されるのか知りようがないため、もっとも安全な許可リストで DNS リバインディング保護を有効にします。手元のマシンではまさにそれが正解です。実際のホスト名の背後にデプロイすると、`transport_security=` に実際に配信するホストの許可リストを渡すまで、**すべてのリクエストが `421 Misdirected Request` で拒否されます**。作成したものは何ひとつ参照すらされません。その許可リストをはじめ、動くアプリと実際のホスト名との間にあるものすべてについては、**[デプロイとスケール](deploy.md)** を参照してください。

## マウントする {#mounting-it}

MCP サーバーがより大きなアプリケーションの「一部」になった瞬間、このアプリは `Mount` の中に置くことになります。そしてそうした瞬間、ライフスパンは自分で面倒を見るべきものになります。

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` とデフォルトの `/mcp` パスの組み合わせで、エンドポイントは `/mcp` のままです。Starlette はルートを順に試し、`Mount("/")` は**すべての**パスにマッチします。そのため、自前のルートはリストの中でこれより「前」に置きます。後ろにあるものには到達できません。
* `lifespan` 関数は、**ホスト**アプリが生きている間ずっと `mcp.session_manager.run()` に入った状態を保ちます。これは誰もが忘れる 1 行です。
* `mcp.session_manager` は `streamable_http_app()` が呼ばれた「後」でしか存在しません。ルートをモジュールレベルで組み立て、マネージャーにはライフスパンの中でだけ触れているのはそのためです。

Starlette の `Host` ルートも同じように動きます。`Mount("/", ...)` を `Host("mcp.example.com", ...)` に差し替えれば、パスではなくホスト名でルーティングできます。ライフスパンのルールは変わりませんし、トランスポートセキュリティのルールも変わりません。`Host("mcp.example.com", ...)` ルートはそのホスト名宛てのリクエストしか受け取りませんが、トランスポート自身の Host 許可リスト（**[デプロイとスケール](deploy.md)**）は依然として先に実行されます。そこに `"mcp.example.com"` がなければ、このルートはすべてのリクエストに `421` で応答します。

!!! warning "ライフスパンはホストアプリのもの"
    `streamable_http_app()` は、返す Starlette のライフスパンに `session_manager.run()` を組み込みますが、**マウントされたサブアプリケーションのライフスパンは決して実行されません**。アプリをマウントすると、その組み込みのライフスパンはデッドコードになります。ASGI スタックの最上位にあるアプリが、自身のライフスパンで `mcp.session_manager.run()` に入らなければなりません。

!!! check
    `lifespan=lifespan` の行を削除してサーバーを起動してみてください。起動します。ルートも解決されます。そして `/mcp` への最初のリクエストが次のエラーで失敗します。

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    セッションマネージャーを起動するのは、その `run()` だけです。

## 2 つのサーバー、1 つのアプリ {#two-servers-one-app}

各 `MCPServer` は、それぞれ独自のセッションマネージャーを持つ独立したアプリです。好きなだけマウントし、すべてのマネージャーに 1 つのホストのライフスパンから入ってください。

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` が両方のマネージャーに入ります。2 つは一緒に起動し、逆順でシャットダウンします。
* エンドポイントは `/notes/mcp` と `/tasks/mcp` です。マウントのプレフィックスにデフォルトのパスを足したものです。

## パスを変える {#changing-the-path}

末尾の `/mcp` は `streamable_http_path` です。これを `"/"` にすると、マウントのプレフィックスがそのまま公開パス全体になります。

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

これでクライアントは `/notes/mcp` ではなく `/notes` に接続します。

## ブラウザークライアント向けの CORS {#cors-for-browser-clients}

ブラウザーベースのクライアントには 2 つの許可が必要です。MCP のリクエストヘッダーを**送る**許可と、MCP が返すヘッダーを**読む**許可です。どちらもホストアプリ側の CORS 設定であり、上で触れたトランスポートセキュリティの許可リストもそれと一致している必要があります。

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` は誰もが忘れるほうの半分です。ブラウザーは MCP リクエストのたびに**プリフライト**を行います。`Content-Type: application/json` と `Mcp-*` リクエストヘッダーは CORS のセーフリストに載っていないためです。そして、プリフライトで許可されなかったヘッダーがあれば、ブラウザーはそのリクエストを決して送りません。（`allow_headers=["*"]` でも動きます。Starlette はプリフライトに対して、要求されたものをそのまま返すからです。）
* `expose_headers=["Mcp-Session-Id"]` は読む側の半分です。Streamable HTTP はセッション ID をこのレスポンスヘッダーで返しますが、ブラウザーは CORS で名前を指定して公開しない限り、レスポンスヘッダーを JavaScript から隠します。これがないと、クライアントは 2 回目のリクエストを決して送れません。
* `allow_origins` は MCP ではなく自分で決めることです。厳密に指定し、上の `allowed_origins=` にも同じ内容を反映してください。CORS を強制するのはブラウザーですが、サーバー自身も `Origin` を検査します。トランスポートが信頼しないオリジンは、プリフライトが問題なく通った後でも `403` になります。
* `allow_methods` には Streamable HTTP が使う 3 つのメソッドを列挙します。メッセージを送る `POST`、サーバーからクライアントへのストリームを開く `GET`、セッションを終える `DELETE` です。

## カスタムルート {#custom-routes}

`@mcp.custom_route()` は、同じアプリ上に素の HTTP エンドポイントを登録します。デプロイされたサービスなら必ず必要になるものの、MCP とは何の関係もないもの、たとえばヘルスチェックや OAuth コールバックのためのものです。

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* ハンドラーは素の Starlette です。`Request` を受け取って `Response` を返す `async` 関数です。
* `streamable_http_app()` はすべてのカスタムルートを拾います。`app.routes` は今や `/mcp` と `/health` です。
* `GET /health` は `{"status": "ok"}` を返し、MCP はどこにも出てきません。

!!! warning
    カスタムルートは**決して認証されません**。サーバーのほかの部分が認証されている場合でもです。これは意図的なものです。ヘルスチェックや OAuth コールバックは、トークンが 1 つも存在しない段階で到達できなければならないからです。非公開のものをカスタムルートの背後に置かないでください。

## まとめ {#recap}

* `mcp.streamable_http_app()` は、`/mcp` というルートを 1 つ持つ Starlette アプリを返します。どの ASGI サーバーでも実行できます。
* デフォルトでは、このアプリは localhost 宛てのリクエストにだけ応答し、実際のホスト名の背後では `transport_security=` に許可リストを渡すまですべてを `421` で拒否します。そこは **[デプロイとスケール](deploy.md)** の担当で、本番環境までの残りの道のりも同様です。
* `Mount`（または `Host`）で、より大きな Starlette や FastAPI のアプリの中に置けます。
* **マウントすると組み込みのライフスパンは無効になります。** ホストアプリのライフスパンで `mcp.session_manager.run()` に入らなければ、最初のリクエストが失敗します。
* 1 つのアプリに複数のサーバーを載せるなら、マウントを複数用意し、すべてのセッションマネージャーに入るライフスパンを 1 つ用意します。
* `streamable_http_path="/"` で、エンドポイントはマウントのプレフィックスそのものに移ります。
* ブラウザークライアントには CORS が必要です。`Mcp-*` リクエストヘッダーのための `allow_headers` と、レスポンスのための `expose_headers=["Mcp-Session-Id"]` です。
* `@mcp.custom_route()` は、認証なしの素の HTTP エンドポイントを `/mcp` の隣に追加します。

サーバーに実際の URL で到達できるようになったら、**[クライアント](../client/index.md)** はサーバーオブジェクトの代わりにその URL を使って接続します。
