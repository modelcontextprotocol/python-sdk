---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# プロトコルバージョン {#protocol-versions}

MCP には 2 つの世代があります。

2026-07-28 より前にリリースされたサーバーは、すべての接続を **`initialize` ハンドシェイク**で始めます。クライアントがバージョンを提案し、サーバーが対案を返し、クライアントが了承します。これらがすべて、最初の実質的なリクエストより前に行われます。**2026-07-28** のサーバーはこのハンドシェイクをやめました。クライアントが **`server/discover`** のプローブを 1 回送り、サーバーは必要なものすべてを 1 つの結果にまとめて返します。

`Client` が代わりにネゴシエーションしてくれるので、気にする必要はほとんどありません。このページで扱うのは、それを制御するたった 1 つのコンストラクター引数 `mode=` と、それを変更する 3 つの場面です。

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

`mode` を渡していないので、デフォルトの `"auto"` が使われます。`async with` に入ると、この SDK が話せる最新のバージョンで `server/discover` プローブを 1 回だけ送ります。その後は次のどちらかです。

* **新世代のサーバー**はこれに応答します。クライアントはその結果を採用します。ラウンドトリップ 1 回で完了です。
* **古いサーバー**は `server/discover` を知らないので、エラーを返します。クライアントは従来の `initialize` ハンドシェイクにフォールバックし、そこでネゴシエートされた結果を受け入れます。

どちらの場合でも接続は確立され、どちらだったかは `client.protocol_version` でわかります。

```text
2026-07-28
```

機能としてはこれだけです。`Client` は 1 つ、サーバーはどの世代でもよく、コードに分岐は要りません。

!!! info
    `MCPServer` はインメモリ、stdio、Streamable HTTP のどのトランスポートでも `server/discover` に応答します。そのため、自分のサーバーが相手なら `auto` は必ず `2026-07-28` になります。フォールバックが発動するのは 2026 年より前の本物のサーバーが相手のときだけで、それはまさにフォールバックしてほしい場面です。

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` はプローブを一切送りません。`initialize` ハンドシェイクを実行します。2026 年より前のクライアントが開くのと同じ接続です。

```text
2025-11-25
```

同じサーバーです。このサーバーは `2026-07-28` を問題なく話せますが、尋ねないようクライアントに指示したのです。

これが必要になるのは、**プッシュ型**の機能を使うときです。

サーバー起点のリクエストとは、サーバーのほうから「呼び出し側」を呼ぶものです。`ctx.elicit(...)` がユーザーの前にフォームを出したり、サンプリングがツール呼び出しの途中でモデルに補完を求めたりします。このチャネルはハンドシェイク世代のセッションにしか存在しません。

2026-07-28 ではこのチャネルはなくなりました。サーバーは質問を結果として「返し」、クライアントは答えを添えて呼び出しをやり直します（**[マルチラウンドトリップ（multi-round-trip）リクエスト](handlers/multi-round-trip.md)**）。

`mode="auto"` でハンドシェイクになるのは、サーバーが古すぎてほかに手がないときだけです。`mode="legacy"` ならハンドシェイクが保証されます。`Client(...)` に `sampling_callback` を渡すとき、リクエストとして駆動させたい `elicitation_callback` を渡すとき、あるいは `message_handler` を渡すときは、いつでもこれを使ってください。それぞれについては **[クライアントのコールバック](client/callbacks.md)** で説明しています。

## バージョンのピン留め {#pinning-a-version}

`mode` には新世代のプロトコルバージョン文字列も指定できます。現時点でその集合はちょうど `["2026-07-28"]` です。

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

ピン留めすると**何も**送りません。プローブもハンドシェイクもありません。クライアントはローカルで `2026-07-28` を採用し、`async with` から戻った瞬間に接続は使える状態です。

ピン留めは「呼び出し側」がする約束です。サーバーがそのバージョンを話せるとすでに知っている、という約束です。クライアントは確認しません。

!!! check
    ピン留めはディスカバリーではありません。`client.server_info` を表示してみると、その代償がはっきり見えます。

    ```text
    None
    ```

    クライアントはサーバーに素性を尋ねていないので、`server_info` は `None` です。`client.server_capabilities` も同じで、どのケイパビリティも `None` です。ツール呼び出しは引き続き動きます（プロトコルはそのどれも必要としません）。しかし、`server_capabilities` を読んで何を提供するか決めるコードは動きません。

    次のセクションがその解決策です。

ピン留めできるのは新世代のバージョンだけです。ハンドシェイク世代の文字列は、I/O が発生する前の構築時点で拒否され、代わりに何を書くべきかはエラーが教えてくれます。

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## `prior_discover` を使った再接続 {#reconnecting-with-prior_discover}

プローブは安価ですが、それでも再接続のたびに支払うラウンドトリップであり、答えが変わることはほとんどありません。

なので取っておきましょう。`auto` で接続した後、`client.session.discover_result` にはサーバーが送った `DiscoverResult` がそのまま入っています。`supported_versions`、`capabilities`、`instructions`、そしてサーバーが結果の `_meta` に刻んだ識別情報です。次回はそれを `prior_discover=` として渡します。

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

2 回目の接続はネゴシエーションのラウンドトリップが**ゼロ**で、それでも相手が誰なのかを正確に把握しています。これがピン留めモードの正しい使い方です。`mode=` でバージョンを指定し、`prior_discover=` で識別情報を与えます。✨

`DiscoverResult` は Pydantic モデルです。`saved.model_dump_json()` をファイルやキャッシュに保存し、次のプロセスで `DiscoverResult.model_validate_json(...)` を使って復元します。

!!! tip
    `prior_discover=` が効くのは、`mode` がバージョンのピン留めのときだけです。`"auto"` ではクライアントはいずれにせよサーバーをプローブしますし、`"legacy"` では無視されます。

## 4 つのモード {#the-four-modes}

| 書くコード | ネゴシエーションの通信 | 得られるもの |
| --- | --- | --- |
| `Client(target)` | `server/discover` プローブ 1 回。失敗したら `initialize` ハンドシェイク | 世代を問わず、両者が話せる最新のバージョン |
| `Client(target, mode="legacy")` | `initialize` ハンドシェイク | ハンドシェイク世代のバージョン。サーバー起点のリクエストが使える |
| `Client(target, mode="2026-07-28")` | なし | そのバージョンに固定。`server_info` は `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | なし | そのバージョンに固定。さらに前回保存した識別情報も付く |

## まとめ {#recap}

* MCP にはハンドシェイク世代（`2025-11-25` まで、`initialize` ハンドシェイク）と新世代（`2026-07-28`、`server/discover`）があります。`Client` がその橋渡しをします。
* `mode="auto"` がデフォルトです。プローブし、だめならフォールバックします。ほかの 3 行のどれかに当てはまらない限り、そのままにしておいてください。
* 「何になったのか」の答えは、いつでも `client.protocol_version` です。
* `mode="legacy"` はハンドシェイクを強制します。サンプリング、プッシュ型のエリシテーション（elicitation）、`message_handler` といったサーバー起点のリクエストに必要なのはこれです。
* バージョンのピン留め（`mode="2026-07-28"`）はネゴシエーションの通信を一切送りません。その代償として `client.server_info` が `None` になります。
* `prior_discover=` がその代償を取り戻します。`client.session.discover_result` を保存し、それを使って再接続すれば、両方が手に入ります。

新世代の接続にはプッシュ用のチャネルがありません。では 2026 年世代のサーバーは、呼び出しの途中でどうやって質問するのでしょうか。結果として返すのです。詳しくは **[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)** を参照してください。
