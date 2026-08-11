---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# セッショングループ {#session-groups}

`Client` は 1 つのサーバーに接続します。実際のアプリケーションでは複数のサーバー（検索サーバー、データベースサーバー、社内 API など）を使いたいことが多く、結局それぞれの接続とツール一覧を個別に管理することになります。

**`ClientSessionGroup`** は、多数の接続を保持し、それらが公開するものすべてを 1 つのビューにまとめる単一のオブジェクトです。

## 2 つのサーバー {#two-servers}

まず、ごく普通のサーバーを 2 つ用意します。互いに何の関係もないので、どちらも自然とツールに `search` という名前を付けています。

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## 1 つのグループ {#one-group}

`ClientSessionGroup` を作成し、サーバーごとに **`connect_to_server`** を 1 回ずつ呼び出します。

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` はサーバーオブジェクトではなく、トランスポートのパラメーターを受け取ります。サブプロセスを起動するなら `StdioServerParameters`（`mcp` から）、すでに URL で待ち受けているサーバーなら `StreamableHttpParameters` または `SseServerParameters`（`mcp.client.session_group` から）です。
* `group.tools` は、接続しているすべてのサーバーのツールを集めた `dict[str, Tool]` です。`group.resources` と `group.prompts` も同じ形です。
* `group.call_tool(name, arguments)` は名前を引き、それを所有するセッションを見つけて呼び出しを転送します。どのサーバーかを指定する必要はありません。

!!! check
    `client.py` を 2 つのサーバーと同じ場所に置いて実行してください。2 回目の `connect_to_server` は拒否されます。

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    これは `MCPError` で、2 つ目のサーバーの何かが登録される前に送出されます。名前はグループ**全体**で一意でなければならず、自分で管理していない 2 つのサーバーはいずれ衝突します。

## `component_name_hook` {#component_name_hook}

これはサーバー側ではなく、グループ側で解決します。`(name, server_info)` を受け取る関数を渡すと、グループは登録するすべての名前に対してその関数を実行します。

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

もう一度実行してください。`print(sorted(group.tools))` には両方が表示されます。

```text
['Library.search', 'Web.search']
```

* **キー**は自分で決めたものです。`by_server` は `server_info.name`、つまり各 `MCPServer(...)` の構築時に渡された名前からキーを組み立てました。
* 中の `Tool` は変更されていません。`group.tools["Web.search"].name` は依然として `"search"` であり、`call_tool` が通信路に載せるのはこの名前です。プレフィックスがプロセスの外に出ることはありません。
* ツールだけではありません。ライブラリの `hours` リソースは `Library.hours` として登録されます。

!!! tip
    フックは衝突したものだけでなく、**すべて**のサーバーの**すべて**の名前に対して実行されます。衝突時だけプレフィックスを付けるモードはありません。1 つの方式を決めて、全体に適用してください。

## サーバーの追加と削除 {#adding-and-removing-servers}

`connect_to_server` は開いた `ClientSession` を返します。後でそのサーバーを外したくなる場合に備えて保持しておいてください。`await group.disconnect_from_server(session)` で、そのサーバーのツール、リソース、プロンプトがグループから削除されます。

すでに接続済みの `ClientSession` を持っている場合（`Client.session` がそうです）、新しいトランスポートを開く代わりに `await group.connect_with_session(server_info, session)` に渡してください。同じように集約されます。グループは、自分で開いていないセッションを閉じることはありません。`server_info` はコンポーネントのプレフィックスに使うサーバー名を指定します。2026 年世代の接続では `client.server_info` が `None` になることがある（識別情報は任意です）ため、その場合は自分で `Implementation(name=..., version=...)` を渡してください。

## 従来のハンドシェイク {#the-classic-handshake}

`ClientSessionGroup` は `Client` ではなく `ClientSession` の上に構築されています。`connect_to_server` を呼ぶたびに従来の `initialize` ハンドシェイクが実行されます。**[プロトコルバージョン](../protocol-versions.md)**で説明している `server/discover` プローブを送ることはありません。このハンドシェイクはすべての MCP サーバーが理解するので、互換性が失われることは一切ありません。ただ、もっと良い方法に対応しているサーバーに対しても、グループは古くて遅い経路を取るというだけです。

## まとめ {#recap}

* `ClientSessionGroup` は多数のサーバー接続を保持し、それらのツール、リソース、プロンプトをそれぞれ 1 つの `dict` にまとめます。
* サーバーごとに `connect_to_server(params)` を呼びます。受け取るのはトランスポートのパラメーターであり、`Client` が受け取るサーバーオブジェクトや URL ではありません。
* `group.call_tool(name, arguments)` は、所有するサーバーへのルーティングを代わりに行います。
* 名前はグループ全体で一意でなければなりません。`search` ツールを持つ 2 つのサーバーは、そのままでは共存できません。
* `component_name_hook=` は登録されるすべての名前を書き換えます。dict のキーは変わりますが、実際に送信される名前は変わりません。
* `connect_with_session` はすでに持っているセッションを追加し、`disconnect_from_server` はセッションを削除します。

グループが使うハンドシェイク（と、`Client` が優先するより高速なハンドシェイク）について詳しくは、**[プロトコルバージョン](../protocol-versions.md)**を参照してください。
