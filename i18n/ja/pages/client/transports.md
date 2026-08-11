---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# クライアントのトランスポート {#client-transports}

どの `Client` も、**トランスポート**を介してサーバーと対話します。トランスポートとは、実際にメッセージを運ぶもののことです。

トランスポートを別途設定することはありません。`Client` は位置引数を 1 つだけ受け取り、その型からトランスポートを判断します。

それぞれの「サーバー」側（`mcp.run()` が何をするのか、何をデプロイするのか）については、**[サーバーの実行](../run/index.md)** を参照してください。

## インメモリ {#in-memory}

サーバーオブジェクトそのものを渡します。

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

サブプロセスも、ポートも、通信路を流れるバイト列もありません。クライアントとサーバーは同じプロセス内の 2 つのオブジェクトですが、呼び出しは本物のプロトコル層を通ります。`search_books` は、HTTP 越しの場合とまったく同じように一覧に載り、検証され、呼び出されます。

そのため、これは同時に 2 つの役割を果たします。

* **テストハーネス。** このドキュメントの例はすべてこの方法で実行されており、**[テスト](../get-started/testing.md)** のページはこのパターンを中心に組み立てられています。
* **組み込み用の API。** サーバーを自分で構築するアプリケーションなら、そのツールを呼び出すのにネットワーク越しの経路は必要ありません。

## Streamable HTTP {#streamable-http}

URL の文字列を渡すと **Streamable HTTP** になります。デプロイ時に使うトランスポートです。

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

本番用のクライアントはこれですべてです。`Client` は URL を `streamable_http_client(...)` で包み、MCP に必要な設定を施した `httpx2.AsyncClient` の上に載せてくれます。具体的には `follow_redirects=True`、connect/write/pool のタイムアウトが 30 秒、そしてサーバーがレスポンスストリームを開いたままにすることがあるため read のタイムアウトが 300 秒です。

!!! check
    構築しただけの `Client` は接続されて**いません**。構築時に行われるのはトランスポートの選択だけで、実際に開くのは `async with` です。入る前に接続に手を伸ばすと、SDK がそのことを教えてくれます。

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    `Client("http://...")` と書いた時点では、何も解決も取得も起動もされていません。この行にコストはかかりません。

### 自前の `httpx2.AsyncClient` を使う {#bring-your-own-httpx2asyncclient}

`Authorization` ヘッダー、Cookie、プロキシ、mTLS、あるいは別のタイムアウトが必要になったら、`httpx2.AsyncClient` を自分で組み立てて `streamable_http_client` に渡します。

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

注目すべき点が 2 つあります。

* `httpx2.AsyncClient` の所有者は**自分**なので、入るのも出るのも自分で行います。SDK は自身が作成していないクライアントを決して閉じません。
* `streamable_http_client(url, http_client=...)` はトランスポートを返し、`Client(transport)` はそれを他のものと同じように受け取ります。

TLS について 1 点。`httpx2` は、同梱の CA リストではなく、オペレーティングシステムのトラストストアに対して証明書を検証します（[`truststore`](https://pypi.org/project/truststore/) を使用）。利用できるシステム CA ストアがない環境（一部の最小構成コンテナなど）では、標準の環境変数 `SSL_CERT_FILE`/`SSL_CERT_DIR` を設定するか、`httpx2.AsyncClient` に明示的に `verify=ssl_context` を渡してください（背景は [`httpx` と `httpx-sse` の `httpx2` への置き換え](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)を参照）。

!!! warning
    `streamable_http_client` は以前、`headers=` と `timeout=` を直接受け取っていました。今はもう受け取りません。パラメーターは `url`、`http_client`、`terminate_on_close` だけです。習慣で `headers=` を渡すと、次のようになります。

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    HTTP に関わるものはすべて、渡す 1 つの `httpx2.AsyncClient` に集約されています。

!!! info
    `httpx2` はおなじみの `httpx` の API をそのまま保っているので、`httpx` を知っていれば、認証、プロキシ、イベントフック、リトライ、接続数の制限のやり方はすでに知っていることになります。SDK はその上に何も足さず、何も引きません。OAuth が差し込まれるのもここです。`httpx2.AsyncClient(auth=OAuthClientProvider(...))` のように書きます。そのフロー全体については **[OAuth クライアント](oauth-clients.md)** を参照してください。

## stdio {#stdio}

**stdio** サーバーはサブプロセスです。クライアントがそれを起動し、stdin に JSON-RPC を書き込み、stdout から JSON-RPC を読み取ります。デスクトップのホストが手元のマシンでサーバーを動かす方法がこれです。ホストとは、このコードに UI を加えたもの「そのもの」です。**[本物のホストに接続する](../get-started/real-host.md)** は、同じ関係をホストの側から設定ファイルとして見たものです。

`StdioServerParameters` でプロセスを記述し、`stdio_client` でトランスポートに変換して、「それ」を `Client` に渡します。

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` はパラメーターオブジェクトをそのままでは受け取りません。`StdioServerParameters` は設定であり、`stdio_client(server)` はそこからプロセスを起動する方法を知っているトランスポートです。必ず包んでください。

`async with` ブロックを抜けると、サブプロセスも終了されます。stdin を閉じ、待機し、居残っていれば強制終了します。自分で後始末をすることはありません。

!!! warning
    子プロセスは環境変数を継承**しません**。最小限の許可リスト（POSIX では `HOME`、`LOGNAME`、`PATH`、`SHELL`、`TERM`、`USER`）だけを受け取るので、自分が書いたとは限らないプロセスに機密情報が漏れることはありません。

    API キーを必要とするサーバーは、そこでキーを見つけられません。`env=` で明示的に渡してください。それらの変数は許可リストの上にマージされます。上の例で `BOOKSHOP_API_KEY` がしているのがまさにそれです。

## SSE {#sse}

`mcp.client.sse` の `sse_client(url)` は、Streamable HTTP に取って代わられた HTTP トランスポートです。まだこれを話すサーバーと対話するには、同じように `Client(sse_client("http://localhost:8000/sse"))` と包みます。そして、新しいものをこの上に作らないでください。

## `Transport` プロトコル {#the-transport-protocol}

`Client` から見れば、上記はすべて同じものです。

**トランスポート**とは、`(read, write)` というメッセージストリームのペアを yield する非同期コンテキストマネージャーのことです。正式には `mcp.client` の `Transport` プロトコルです。`Client` は引数を型で解決します。サーバーオブジェクトならインプロセスで接続し、`str` なら `streamable_http_client(url)` になり、それ以外は直接トランスポートとして入ります。この最後の規則があるからこそ、`stdio_client(...)`、`streamable_http_client(...)`、`sse_client(...)` はすべて同じ場所に収まり、自分で独自のものを書くこともできます。

## まとめ {#recap}

* `Client(mcp)`（サーバーオブジェクト）はインメモリで接続します。テストと組み込みに使ってください。
* `Client("http://.../mcp")`（URL）は、本番用のトランスポートである Streamable HTTP で接続します。
* ヘッダー、認証、プロキシ、タイムアウトは、`streamable_http_client(url, http_client=...)` に渡す `httpx2.AsyncClient` に設定します。`headers=` キーワードはありません。
* stdio は `Client(stdio_client(StdioServerParameters(...)))` であり、パラメーターオブジェクト単体では決してありません。
* サブプロセスが受け取るのは自分の環境ではなく、許可リストに基づく環境です。`env=` でそこに追加します。
* トランスポートとは、`async with x as (read, write)` と書けるものすべてです。`Client` は、サーバーオブジェクトでも URL でもないものをそのままこのプロトコルに渡します。
* `Client` の構築でトランスポートが選ばれ、`async with` でそれが開かれます。

トランスポートが開いたら、両者はプロトコルバージョンについて合意する必要があります。普段は意識することはありません。意識することになったら、**[プロトコルバージョン](../protocol-versions.md)** のページを参照してください。
