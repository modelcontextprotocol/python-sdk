---
translation:
  sections: [9cac816674181eb0, 7c157764133fea1f, 40b4916d82eaf1d4, 10d151f2cc75317f, 3d0832f39b0d7059, 92742ba36533633d, 0aeca6145e7bd302]
  tool: 1
---
# クライアントのトランスポート {#client-transports}

どの `Client` も、**トランスポート**を介してサーバーと対話します。トランスポートとは、実際にメッセージを運ぶもののことです。

トランスポートを別途設定することはありません。`Client` は位置引数を 1 つだけ受け取り、その型からトランスポートを判断します。

それぞれの「サーバー」側（`mcp.run()` が何をするのか、何をデプロイするのか）については、**[サーバーの実行](../run/index.md)** を参照してください。

## Streamable HTTP {#streamable-http}

URL の文字列を渡すと **Streamable HTTP** になります。デプロイ時に使うトランスポートであり、最初に選ぶべきトランスポートです。

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

本番用のクライアントはこれですべてです。`Client` は URL を `streamable_http_client(...)` で包み、MCP に必要な設定を施した `httpx2.AsyncClient` の上に載せてくれます。具体的には、connect/write/pool のタイムアウトが 30 秒、そしてサーバーがレスポンスストリームを開いたままにすることがあるため read のタイムアウトが 300 秒です。

!!! check
    構築しただけの `Client` は接続されて**いません**。構築時に行われるのはトランスポートの選択だけで、実際に開くのは `async with` です。入る前に接続に手を伸ばすと、SDK がそのことを教えてくれます。

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    `Client("http://...")` と書いた時点では、何も解決も取得も起動もされていません。この行にコストはかかりません。

### 自前の `httpx2.AsyncClient` を使う {#bring-your-own-httpx2asyncclient}

`Authorization` ヘッダー、Cookie、プロキシ、mTLS、あるいは別のタイムアウトが必要になったら、`httpx2.AsyncClient` を自分で組み立てて `streamable_http_client` に渡します。

```python title="client.py" hl_lines="8-13"
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
    `httpx2` はおなじみの `httpx` の API をそのまま保っているので、`httpx` を知っていれば、認証、プロキシ、イベントフック、リトライ、接続数の制限のやり方はすでに知っていることになります。SDK はその上に何も足さず、何も引きません。唯一の例外が[リダイレクトの扱い](#redirects)です。OAuth が差し込まれるのもここです。`httpx2.AsyncClient(auth=OAuthClientProvider(...))` のように書きます。そのフロー全体については **[OAuth クライアント](oauth-clients.md)** を参照してください。

### リダイレクト {#redirects}

トランスポートは渡された URL に接続し、そのオリジンにだけ接続します。

* 同じスキーム、ホスト、ポートにとどまる `307`/`308` のリダイレクトには従います。同じホスト上での `http://` → `https://` も同様です。よくある `/mcp` → `/mcp/` という末尾スラッシュのリダイレクトはこれでカバーされます。
* それ以外の場所へのリダイレクトには従い**ません**。呼び出しは次のエラーで失敗します。

    ```text
    MCPError: Redirect to https://other.example.com/mcp not followed; use that URL as the endpoint if it is the intended server
    ```

    その URL が意図したサーバーなら、設定にその URL を書いてください。そうでなければ、サーバーか、その前段にあるプロキシの設定が誤っています。

これは、渡すどの `httpx2.AsyncClient` にも当てはまります。その `follow_redirects` の設定は、MCP のリクエストについてはどちらの方向にも参照されません。SDK の OAuth プロバイダーも、自身のリクエストに同じ規則を適用します。

!!! tip
    `Redirect to http://… not followed: it would downgrade this HTTPS endpoint to plain HTTP` は、サーバーが自身の知らない TLS 終端プロキシの背後にあり、`http://` のリダイレクトを発行していることを意味します。これはサーバー側で直すか（**[デプロイとスケール](../run/deploy.md#behind-a-tls-terminating-proxy)**）、メッセージが示すとおりの正確な `https://…/` の URL を使うことで解決します。

## stdio {#stdio}

**stdio** サーバーはサブプロセスです。クライアントがそれを起動し、stdin に JSON-RPC を書き込み、stdout から JSON-RPC を読み取ります。デスクトップのホストが手元のマシンでサーバーを動かす方法がこれです。ホストとは、まさにこのコードに UI を加えたものです。**[本物のホストに接続する](../get-started/real-host.md)** は、同じ関係をホストの側から設定ファイルとして見たものです。

`StdioServerParameters` でプロセスを記述し、それを `Client` に渡します。

```python title="client.py" hl_lines="3-7 11"
--8<-- "docs_src/client_transports/tutorial004.py"
```

ブロックに入るとプロセスが起動します。抜けるとサブプロセスは終了されます。stdin を閉じ、待機し、居残っていれば強制終了します。自分で後始末をすることはありません。

子プロセスの stderr は自分の stderr に流れます。別の場所に送るには、`stdio_client`（`mcp` にあります）でトランスポートを自分で組み立て、代わりにそれを渡してください。`Client(stdio_client(server, errlog=log_file))` のように書きます。

!!! warning
    子プロセスは環境変数を継承**しません**。最小限の許可リスト（POSIX では `HOME`、`LOGNAME`、`PATH`、`SHELL`、`TERM`、`USER`）だけを受け取るので、自分が書いたとは限らないプロセスに機密情報が漏れることはありません。

    API キーを必要とするサーバーは、そこでキーを見つけられません。`env=` で明示的に渡してください。それらの変数は許可リストの上にマージされます。上の例で `BOOKSHOP_API_KEY` がしているのがまさにそれです。

## インメモリ {#in-memory}

テストでは、デプロイするものも起動するものもありません。サーバーオブジェクトそのものを渡します。

```python hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

サブプロセスも、ポートも、通信路を流れるバイト列もありません。クライアントとサーバーは同じプロセス内の 2 つのオブジェクトですが、呼び出しは本物のプロトコル層を通ります。`search_books` は、HTTP 越しの場合とまったく同じように一覧に載り、検証され、呼び出されます。**[テスト](../get-started/testing.md)** のページは、このパターンを中心に組み立てられています。

同じ形は組み込み用の API としても使えます。サーバーを自分で構築するアプリケーションなら、ネットワーク越しの経路なしにそのツールを呼び出せます。

## SSE {#sse}

`mcp.client.sse` の `sse_client(url)` は、Streamable HTTP に取って代わられた HTTP トランスポートです。まだこれを話すサーバーと対話するには、同じように `Client(sse_client("http://localhost:8000/sse"))` と包みます。そして、新しいものをこの上に作らないでください。

## `Transport` プロトコル {#the-transport-protocol}

`Client` から見れば、上記はすべて同じものです。

**トランスポート**とは、`(read, write)` というメッセージストリームのペアを yield する非同期コンテキストマネージャーのことです。正式には `mcp.client` の `Transport` プロトコルです。`Client` は引数を型で解決します。`str` なら `streamable_http_client(url)` になり、`StdioServerParameters` なら `stdio_client(params)` になり、サーバーオブジェクトならインプロセスで接続し、それ以外は直接トランスポートとして入ります。この最後の規則があるからこそ、`stdio_client(...)`、`streamable_http_client(...)`、`sse_client(...)` はすべて同じ場所に収まり、自分で独自のものを書くこともできます。

## まとめ {#recap}

* `Client("http://.../mcp")`（URL）は、本番用のトランスポートである Streamable HTTP で接続します。
* ヘッダー、認証、プロキシ、タイムアウトは、`streamable_http_client(url, http_client=...)` に渡す `httpx2.AsyncClient` に設定します。`headers=` キーワードはありません。
* リダイレクトに従うのは、URL 自身のオリジン内（末尾スラッシュの `307`/`308`）と、同じホスト上の `http`→`https` だけです。それ以外は `Redirect to … not followed` で失敗します。最終的な URL を設定してください。
* stdio は `Client(StdioServerParameters(...))` です。自分で `stdio_client(...)` に包むのは、子プロセスの stderr をリダイレクトしたいときだけです。
* サブプロセスが受け取るのは自分の環境ではなく、許可リストに基づく環境です。`env=` でそこに追加します。
* `Client(mcp)`（サーバーオブジェクト）はインメモリで接続します。テストで使うか、サーバーを構築したアプリケーションにそのサーバーを組み込むために使ってください。
* トランスポートとは、`async with x as (read, write)` と書けるものすべてです。`Client` は、サーバーオブジェクトでも URL でも `StdioServerParameters` でもないものを、そのままこのプロトコルに渡します。
* `Client` の構築でトランスポートが選ばれ、`async with` でそれが開かれます。

トランスポートが開いたら、両者はプロトコルバージョンについて合意する必要があります。普段は意識することはありません。意識することになったら、**[プロトコルバージョン](../protocol-versions.md)** のページを参照してください。
