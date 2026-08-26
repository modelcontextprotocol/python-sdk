---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

**MCP App** とは、見た目を持つツールのことです。データと並んで、ツールがホストに対話型の画面として描画させる HTML ドキュメントを指し示します。

構成要素は 2 つで、常にこの 2 つです。

1. **ツール**。ほかのツールと同じように、処理を行ってデータを返します。
2. **`ui://` リソース**。ホストがそのツールのために表示する HTML を収めます。

ツールは `_meta.ui.resourceUri` でリソースを参照します。ホストはそれを `resources/read` で取得し、**サンドボックス化された iframe** に描画し、ツールの結果を `postMessage` 経由でその iframe に送り込みます。サーバーが `ui/*` メッセージを送受信することは一切ありません。そのやり取りはホストと iframe の間のものです。サーバーが提供するのはツールと HTML ドキュメントだけで、演出はホストが担当します。

SDK はこれを組み込みの `Apps` 拡張（`io.modelcontextprotocol/ui`）として提供しています。[拡張](extensions.md)になじみがなければ、先にそのページにざっと目を通してください。1 分で済みます。それから戻ってきてください。

## 見た目のある時計 {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

やることは 4 つです。

* `Apps()`：1 つのインスタンスが、UI に紐づくツールとそのリソースをまとめて保持します。
* `@apps.tool(resource_uri="ui://clock/app.html")`：通常のツールに `_meta.ui.resourceUri` の印を加えたものです。`@mcp.tool()` が受け付けるもの（name、title、description など）はすべてそのまま渡せます。
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`：対応するリソースで、`text/html;profile=mcp-app` として提供されます。この MIME タイプこそが、ホストに「これはアプリなので描画せよ」と伝える目印です。
* `MCPServer("clock", extensions=[apps])`：オプトインします。これでサーバーは `capabilities.extensions` の下で `io.modelcontextprotocol/ui` を公開します。

HTML 自体はホストの `postMessage` を待ち受けて結果を表示します。本格的なアプリでは、HTML の中で公式の [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps) ブラウザー SDK を使ってください。生のメッセージイベントの代わりに `ontoolresult`、`callServerTool`、`getHostContext`、`onhostcontextchanged` が使えます。

## グレースフルデグラデーション {#graceful-degradation}

すべてのクライアントがアプリを描画するわけではありません。それが何を意味するかについて、仕様は率直です。

> ツールは、UI が利用できる場合でも、意味のある `content` 配列を返さ**なければなりません**。

モデルが読むのは `content` で、iframe は人間のためのものです。UI に対応したホストでもテキストの結果はモデルに渡されますし、テキスト専用のクライアントはそれ「だけ」を受け取ります。ですから定番のパターンは「1 つのツール、2 つの答え」です。もう一度 `get_time` を見てください。

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` が `True` になるのは、クライアントが `io.modelcontextprotocol/ui` 拡張を宣言し、**かつ** `mimeTypes` 設定に `text/html;profile=mcp-app` を含めている場合だけです。このフィールドは必須なので、省略したクライアントは該当しません。同じファイルの `main()` が宣言しているのはまさにこれです。ネゴシエーションのクライアント側であり、その結果リッチな答えが返ってきます。

!!! warning
    `"[Rendered UI]"` のようなプレースホルダーを唯一のコンテンツとして返さないでください。フォールバックのテキストが役に立たなければ、そのツールはテキスト専用のすべてのクライアントにとっても、モデル自身にとっても役に立ちません。きちんと文を書いてください。

## iframe を厳しく制限する {#locking-the-iframe-down}

セキュリティのメタデータはリソース側が持ちます。iframe が何を読み込めるか、どのブラウザー権限を要求するか、どのようにフレーム内に表示されたいか、です。

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` と `permissions` は**ホストへの要望**であって、サーバーの振る舞いではありません。ホストはそれらをもとに iframe の Content-Security-Policy と Permissions-Policy を組み立てますが、拒否することもあります。許可されたと決めつけず、JS 側で機能検出してください。

`ResourceCsp` をフィールドごとに示します（Python の名前、通信上のキー、ホストがそれで何をするか）。

| Python | 通信上のキー（`_meta.ui.csp`） | 制御対象 |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`：`fetch` や XHR の接続先 |
| `resource_domains` | `resourceDomains` | `img-src`、`style-src` など：静的アセット |
| `frame_domains` | `frameDomains` | `frame-src`：入れ子の iframe |
| `base_uri_domains` | `baseUriDomains` | `base-uri`：`<base>` が指せる先 |

`ResourcePermissions`：各フィールドが iframe 用のブラウザー権限を要求します。

| Python | 通信上のキー（`_meta.ui.permissions`） |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP と権限は**リソース**に置くもので、ツールには決して置きません。仕様のツールメタデータにはそれらの入る場所がなく、そこに置いてもホストは無視します。SDK ではこの間違いをそもそも表現できないようにしています。`@apps.tool()` には `csp` パラメーターが存在しません。

### 可視性 {#visibility}

ツールに `visibility=["app"]` を付けると、「これはモデルのためではなく iframe のために存在する」という意味になります。

* `"model"`：モデルが呼び出せます。
* `"app"`：iframe が（`callServerTool` 経由で）呼び出せます。
* 省略：両方。これがデフォルトです。

フィルタリングは**ホスト**の仕事です。サーバーはアプリ専用のツールもほかのツールと同じように `tools/list` に載せ、ホストがそれをモデルから隠します。サーバー側でフィルタリングしないでください。

## SDK が強制するルール {#the-rules-the-sdk-enforces}

これらはすべて、本番ではなく起動時に失敗します。

* `resource_uri` やリソース URI が `ui://...` でない場合、デコレート時または登録時に `ValueError` になります。
* **対応する登録済みリソースのない** URI に紐づけられたツールは、`MCPServer(extensions=[apps])` が拡張を取り込む時点で `ValueError` になります。`resources/read` で 404 になる HTML を公開するツールは設定ミスなので、構築を拒否します。
* `@apps.tool()` に `meta={"ui": ...}` を渡すと `ValueError` になります。`_meta["ui"]` はデコレーターの管轄です。`resource_uri=` と `visibility=` で指定してください。ほかの `meta=` キーは問題なく一緒にマージされます。

現時点では、TypeScript の ext-apps SDK も FastMCP もこれらをどれも検出しません。ホストより先に自分で気づけるほうがよいと考えています。

## インライン HTML の先へ {#beyond-inline-html}

`add_html_resource` はよくあるケース、つまり HTML の文字列を扱います。それ以外、たとえばディスク上の HTML や生成されたコンテンツでは、リソースを自分で組み立てて渡してください。

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource` は、リソースに MIME タイプが明示されていなければ `text/html;profile=mcp-app` を補い、明示的な不一致は拒否します。ほかの MIME タイプの `ui://` リソースは、どのホストも描画しないリソースだからです。

!!! tip
    非推奨のフラットな `_meta["ui/resourceUri"]` キーをまだ読んでいる GA 前のホストを対象にしていますか？ 自分でマージしてください。`@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})` と書きます。入れ子の `ui` オブジェクトが仕様の形で、フラットなキーはいずれなくなります。

## 動かしてみる {#see-it-run}

`examples/stories/` の `apps` ストーリーは、このページを実行可能なペアにしたものです。UI に紐づく時計ツールを持つサーバーと、Apps をネゴシエートしてツールの `_meta.ui.resourceUri` を読み、HTML を取得してツールを呼び出すクライアントです。

```bash
uv run python -m stories.apps.client
```
