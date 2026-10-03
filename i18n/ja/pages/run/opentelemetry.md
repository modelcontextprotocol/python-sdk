---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

サーバーはすでにトレースされています。何も追加する必要はありません。

作成するサーバーはどれも、処理するメッセージごとに [OpenTelemetry](https://opentelemetry.io/) のスパンを発行します。自分で書いたわけでも、インポートしたわけでもありません。`MCPServer(...)` を呼び出した瞬間から、そこにあります。

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

これで完全な、トレース済みのサーバーです。`search_books` を呼び出すと、そのためのスパンが作成されます。低レベルの `Server` でも同じです。トレースはどちらにも組み込まれています。

## 得られるもの {#what-you-get}

受信したメッセージはすべて、メソッドとその対象にちなんだ名前の `SERVER` スパンになります。`search_books` に対する `tools/call` は `tools/call search_books` というスパンになり、単なる `tools/list` はそのまま `tools/list` です。

各スパンはいくつかの属性を持ちます。

* `mcp.method.name` と `mcp.protocol.version`。すべてのスパンに付きます。
* `jsonrpc.request.id`。リクエストに付きます（通知には ID がありません）。
* ハンドラーが例外を送出すると、スパンのステータスがエラーになります。`is_error=True` のツール結果でも同様です。

そしてツール呼び出しのトレースは非常によくある要望なので、`tools/call` のスパンは OpenTelemetry の [GenAI セマンティック規約](https://opentelemetry.io/docs/specs/semconv/gen-ai/)に従います。

* `gen_ai.operation.name`。`"execute_tool"` が設定されます。
* `gen_ai.tool.name`。呼び出されるツールが設定されます。

同じ考え方で、`prompts/get` のスパンには `gen_ai.prompt.name` が付きます。一覧系のメソッドには名前を付ける対象がないため、`gen_ai.*` のキーは付きません。

!!! tip
    トレース UI がツール呼び出しを他のエージェントと同じようにグループ化してくれるのは、これらの GenAI 属性のおかげです。このグループ化は追加のコードなしで手に入ります。

## 必要になるまでコストはかからない {#it-costs-nothing-until-you-want-it}

「デフォルトで有効」が安心できるデフォルトである理由はここにあります。

SDK が依存しているのは、OpenTelemetry の軽量な半分である `opentelemetry-api` だけです。SDK もエクスポーターもインストールされていなければ、スパンの作成は何もしません。つまり、サーバーが今まさに発行しているスパンのコストはほぼゼロで、誰もそれを収集していません。

実際に「見たく」なった日には、残りの半分をインストールして、送り先を指定します。

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

通常の OpenTelemetry のやり方でエクスポーターを設定すれば、SDK が静かに作成してきたスパンがすべて見えるようになります。サーバーのコードは変わりません。1 行たりともです。

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) はそうしたバックエンドの 1 つで、設定まで代わりにやってくれます。`pip install logfire`、`logfire.configure()` とするだけで、MCP のスパンがライブビューに表示されます。OpenTelemetry の上に構築されているので、以下の内容もすべてそのまま当てはまります。

## 通信路をまたぐトレース {#traces-that-cross-the-wire}

トレースが最も役に立つのは、リクエストをクライアントからサーバーまで、1 つにつながった図として追えるときです。

クライアントとサーバーの両方が SDK を使っていれば、そのつながりは自動的に得られます。クライアントが [W3C トレースコンテキスト](https://www.w3.org/TR/trace-context/)をリクエストに注入し、サーバーがそれを読み取るので、サーバーのスパンは同じトレース内でクライアントのスパンの下にネストされます。これが [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414) で、特に何もしなくても使えます。

受信したメッセージにトレースコンテキストが含まれていない場合、たとえば SDK ではないクライアントからのリクエストでは、サーバーのスパンは孤立した新しいトレースを開始するのではなく、サーバー側ですでに現在のスパンになっているものを親にします。

## 無効にする {#turning-it-off}

トレースはミドルウェアであり、サーバーのリストの先頭にあります。スパンをまったく発行しないサーバーが本当に必要なら、取り除いてください。

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    このインポートには先頭にアンダースコアが付いていますが、これは意図的なものです。このクラスは、[`Server.middleware`](../advanced/middleware.md) が暫定的であるのと同じく暫定的なものなので、インポートパスは変わるものと考えてください。これが必要になることはほとんどありません。エクスポーターをインストールしていなければスパンはコストがかからないので、通常は有効のままにしてエクスポーターをインストールしない、というのが答えです。

## まとめ {#recap}

* すべての `MCPServer` とすべての低レベルの `Server` は、受信したメッセージごとに `SERVER` スパンを 1 つ、デフォルトで発行します。何も書く必要はありません。
* スパンには `mcp.method.name` と `mcp.protocol.version` が付きます。`tools/call` と `prompts/get` にはさらに GenAI 属性も付くので、ツール呼び出しは他のエージェントと同じようにグループ化されます。
* OpenTelemetry の SDK とエクスポーターをインストールするまでコストはかからず、インストールすればサーバーを変更することなく見えるようになります。
* 両側が SDK を使っていれば、クライアントからサーバーへのトレースコンテキストは自動的に伝播します。

そもそもリクエストを実行してよいかどうかを決めるのが、**[認可](authorization.md)**です。
