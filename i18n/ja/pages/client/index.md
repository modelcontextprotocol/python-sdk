---
translation:
  sections: [ebef1e7a0df854f4, 7e16449f66e7dfd6, eeb0682f7d2a1079, 5713f0196a34e6e7, 0e844597859e4248, 3a97d9195ddcc92e, 1da08c483e59c141, 84702cc6e0a1fd42, 8dee7a31c86ffc5c, 83a5bce168ef23d7]
  tool: 1
---
# Client {#the-client}

**`Client`** は、Python プログラムが MCP サーバーと対話するための手段です。

1 つのオブジェクトに 1 つのライフサイクルがあります。組み立てて、`async with` に入り、メソッドを呼び出します。プロトコルの動詞（ツールの一覧取得、ツールの呼び出し、リソースの読み取り、プロンプトのレンダリング）はどれも、このオブジェクトの `async` メソッドで、型付きの結果を返します。

## 最初のクライアント {#your-first-client}

クライアントには、対話する相手のサーバーが必要です。このページのすべてのスニペットが接続するのが、この Bookshop です。`server.py` として保存し、HTTP で起動したままにしてください。

```python title="server.py"
--8<-- "docs_src/client/tutorial001.py"
```

```console
uv run mcp run server.py --transport streamable-http
```

これでサーバーは `http://localhost:8000/mcp` で提供されます。クライアントは別のプログラムです。`client.py` として保存し、2 つ目のターミナルで `python client.py` を実行してください。

```python title="client.py" hl_lines="7-11"
--8<-- "docs_src/client/tutorial001_client.py"
```

* `Client("http://localhost:8000/mcp")` には **URL** を渡しているので、いま起動したサーバーに Streamable HTTP で接続します。
* `async with` が**ライフサイクル**です。入ると接続してネゴシエーションを行い、出ると切断します。`connect()` / `close()` のペアはなく、ブロックが終わった後の `Client` は再利用できません。
* ブロックの中では、接続に関する情報がすでに通常のプロパティとして揃っています。

### `Client` に渡せるもの {#what-you-can-pass-to-client}

`Client` は位置引数を 1 つ取り、その型からトランスポートを決定します。

* URL 文字列（`Client("http://localhost:8000/mcp")`）：Streamable HTTP。デプロイで使うトランスポートです。
* `StdioServerParameters`：ローカルの**サブプロセス**として起動するコマンドで、その stdin と stdout を通じて対話します。
* **トランスポート**：`async with ... as (read, write)` できるものなら何でも。たとえば、自分の HTTP クライアントをラップする `streamable_http_client(url, http_client=...)` です。
* `MCPServer`（または低レベルの `Server`）のインスタンス：**プロセス内**で接続します。サブプロセスもポートもありません。これはテスト向けで、**[テスト](../get-started/testing.md)** がこれを土台にしています。

このページの残りの内容は、4 つのどれでも同じです。ヘッダー、サブプロセス、タイムアウト、そして `Transport` プロトコルについては、専用のページ **[クライアントのトランスポート](transports.md)** があります。

### 接続済みクライアントが持つもの {#whats-on-a-connected-client}

読み取り専用のプロパティが 4 つあり、ブロックに入った瞬間に値が入ります。

* `client.server_info`：サーバーの識別情報。報告しない 2026 年世代のサーバーでは `None` です（python-sdk のサーバーはデフォルトで報告します）。ここでは `server_info.name` が `"Bookshop"` で、`server_info.version` はサーバーが報告する値です。
* `client.server_capabilities`：サーバーができること（`tools`、`resources`、`prompts`、`completions`、...）。サーバーが持たないケイパビリティは `None` です。
* `client.protocol_version`：両者が合意したプロトコルバージョン。ここでは `"2026-07-28"` です。
* `client.instructions`：サーバーの `instructions=` 文字列。設定されていなければ `None` です。

プロトコルバージョンを選んだ覚えはないはずです。デフォルトでは `Client` がサーバーを調べ、古いサーバーに対しては従来のハンドシェイクにフォールバックします。そのため、1 つのクライアントがどの世代のサーバーに対しても動作します。これを制御する必要がある場合、詳しくは **[プロトコルバージョン](../protocol-versions.md)** を参照してください。

!!! tip
    `client.session` は下層の `ClientSession` で、低レベルへの抜け道です。このページの内容では必要ありません。

## ツールの一覧取得 {#listing-tools}

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` は `ListToolsResult` を返し、ツールは `.tools` に入っています。それぞれが、ホストがモデルに渡す完全な定義です。最初のツールは次のとおりです。

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

そして `tool.input_schema` は、サーバーが関数の型ヒントから導き出した JSON Schema です。

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

このスキーマには、UI が引数フォームを描画するのに必要なものも、モデルが有効な引数を生成するのに必要なものも、すべて含まれています。

2 つ目のツール `lookup_book` は `title=` なしで登録されているので、その `tool.title` は `None` です。

!!! tip
    `title` は省略可能なので、人間にツールを見せる UI はどちらかを選ぶ必要があります。`title` があればそれを、なければ `name` を使います。`from mcp.shared.metadata_utils import get_display_name` がまさにそれを行い、ツール、リソース、リソーステンプレート、プロンプトに対応しています。

## ツールの呼び出し {#calling-a-tool}

`call_tool(name, arguments)` はツールを実行し、`CallToolResult` を返します。

```python title="client.py" hl_lines="9-16"
--8<-- "docs_src/client/tutorial003.py"
```

サーバーの `lookup_book` は Pydantic の `Book` を返します。クライアントから見えるのは次のとおりです。

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

戻り値は 1 つ、読むべきものは 3 つです。それぞれ読み手が異なります。

### `content`：モデルが読むもの {#content-what-the-model-reads}

`content` は**コンテンツブロック**の `list` で、コンテンツブロックはユニオン型です。`TextContent`、`ImageContent`、`AudioContent`、`ResourceLink`、`EmbeddedResource` のいずれかです。ツールは種類の異なるブロックを複数返せます。

`main` が `block.text` に触れる前に `isinstance(block, TextContent)` で絞り込んでいるのはそのためです。`isinstance` の外に `.text` がないことに注目してください。`ImageContent` が持つのは `.text` ではなく `.data` なので、型チェッカーが許しません。このユニオンは、ツールが送ってよいものを正直に表しています。コードもそうあるべきです。

### `structured_content`：アプリケーションが読むもの {#structured_content-what-your-application-reads}

`structured_content` はツールの戻り値を JSON にしたもので、ツールが宣言した `output_schema` に一致します。文字列の解析も推測も不要です。

両方があるときは、意図的に同じことを 2 回言っています。`content` はモデル向け、`structured_content` はコード向けです。構造化されたほうがどこから来るのか、どう制御するのかは、**[構造化出力](../servers/structured-output.md)** のページで説明しています。

### `is_error`：ツールが失敗したかどうか {#is_error-whether-the-tool-failed}

例外を送出するツールが、クライアント側で例外を送出することは**ありません**。`is_error=True` の付いた通常の結果として返ってきます。

!!! check
    `lookup_book` に `"Solaris"`（カタログにない書名）を問い合わせると、関数は `ToolError` を送出します。それでも呼び出しは正常に返ります。

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    `ToolError` のメッセージは `content` に入りました。そこなら**モデル**が読んで、やり直せます。これは意図的なものです。ツールのエラーはクラッシュではなく、会話の一部です。（仮にツールが別の例外でクラッシュしていたら、`content` には `Error executing tool lookup_book` とだけ入ります。）`structured_content` を信用する前に、必ず `is_error` を確認してください。

!!! warning
    `is_error=True` がカバーするのは、自分で書いた `raise` だけではありません。サーバーに存在すらしないツールを要求しても（`call_tool("does_not_exist", {})`）、何も送出されません。同じ形の結果が返り、`is_error=True` で `content` には `Unknown tool: does_not_exist` が入ります。`Client` のメソッドが `MCPError` を送出するのは、サーバーが結果ではなく JSON-RPC の**エラー**で応答したときだけです。サーバーがどんなときにどちらを返すかは **[エラーの処理](../servers/handling-errors.md)** で扱っています。

## リソース {#resources}

リソースの動詞は組になっています。一覧取得が 2 通り、読み取りが 1 通りです。

```python title="client.py" hl_lines="9-18"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` は**具体的な**リソース、つまり URI が固定のものを返します。ここでは `['catalog://genres']` です。
* `list_resource_templates()` は**パラメーター化された**ものを返します。ここでは `['catalog://genres/{genre}']` です。テンプレートは値を埋めるまで読み取れないため、2 つは別々のリストになっています。
* `read_resource(uri)` は通常の `str` の URI を受け取り、両方に対して動作します。`"catalog://genres/poetry"` を渡せば、サーバーがテンプレートに照合します。

`read_resource` は `contents` を返します。これは `TextResourceContents` または `BlobResourceContents` のリストです。考え方はツールのコンテンツと同じで、`isinstance` で絞り込んでから `.text`（または `.blob`）を読みます。

クライアントは、リソースが変更されたときに通知を受けることもできます。2025 年世代の接続では `subscribe_resource(uri)` / `unsubscribe_resource(uri)` がそれにあたります。このメソッドのペアは `MCPServer` が実装していないため、2026-07-28 の通信上（これらの動詞はもう存在しません）ではリクエストに `-32601`、*Method not found* が返ります。2026 年の代替は `subscriptions/listen` ストリームで、こちらは `MCPServer` が実際に提供しています（そこでは `server_capabilities.resources.subscribe` が `True` です）。これを `client.listen(...)` で消費する方法は、このセクションの **[サブスクリプション](subscriptions.md)** のページで説明しています。

## プロンプト {#prompts}

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` は、サーバーが何を提供していて、各プロンプトが何を必要とするかを教えてくれます。

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` でレンダリングします。引数の dict は `str -> str` で、プロンプトの引数は常に文字列です。結果は `messages`、つまり `PromptMessage` のリストで、それぞれが `role` と `content` ブロックを持ちます。

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

ホストはこれらのメッセージをそのままモデルに渡します。機能はこれだけです。

## 補完 {#completions}

補完ハンドラーを持つサーバーは、ユーザーの入力に合わせてプロンプトやリソーステンプレートの引数を自動補完できます。

```python title="client.py" hl_lines="9-13"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` は、「どの」プロンプトまたはテンプレートを埋めているかを示します。`PromptReference` または `ResourceTemplateReference` です。
* `argument` は `{"name": ..., "value": ...}` で、引数と、ユーザーがこれまでに入力した内容です。

答えは `result.completion.values` に入っています。`"p"` と入力すると、サーバーは `['poetry']` を返します。サーバー側の実装と、ハンドラーがすでに埋まっている「他の」引数を使って候補を絞り込む方法は、**[補完](../servers/completions.md)** のページで説明しています。

## ページネーション {#pagination}

`list_*` メソッドはどれも `cursor=` キーワードを取り、結果はどれも `next_cursor` を持ちます。`next_cursor` が `None` なら、すべて取得済みです。

```python title="client.py" hl_lines="7-15"
--8<-- "docs_src/client/tutorial007.py"
```

`list_all_tools` はどのサーバーに対しても正しく動きます。`MCPServer` はすべてを 1 ページで返すので、`next_cursor` は `None` になり、ループは 1 回だけ実行されます。ほとんどのコードがこのループを書かないのはそのためです。実際にページ分割するサーバーと、カーソルが従うルールについては **[ページネーション](../advanced/pagination.md)** を参照してください。

## テストでの利用 {#in-tests}

このページの `client.py` はどれも、HTTP 経由で `server.py` に到達していました。テストではネットワークを省き、`Client` にサーバーオブジェクトそのものを渡します。`from server import mcp` としてから `Client(mcp)` です。プロセスもポートも不要で、上記のメソッドはどれも同じように動きます。

そのために用意されたコンストラクターのフラグが 1 つあります。`Client(mcp, raise_exceptions=True)` です。効果があるのはプロセス内接続のときだけで、その説明と、それを中心にしたパターン全体の組み立ては **[テスト](../get-started/testing.md)** のページにあります。

## まとめ {#recap}

* `Client(x)` は、URL 文字列には Streamable HTTP で接続し、`StdioServerParameters` にはサブプロセスを起動し、トランスポートには直接入り、テストではサーバーオブジェクトそのものを受け取ります。
* `async with` がライフサイクルのすべてです。その中では `server_capabilities` と `protocol_version` にすでに値が入っており、サーバーが提供していれば `server_info` と `instructions` も同様です。
* `list_tools()` で各ツールの `name`、`title`、`description`、`input_schema` が得られます。
* `call_tool()` はモデル向けの `content`、コード向けの `structured_content`、そして `is_error` を返します。例外を送出するツールは、例外ではなく結果として返ってきます。
* `content` はブロック型のユニオンです。読む前に `isinstance` で絞り込みます。
* `list_resources` / `list_resource_templates` / `read_resource`、`list_prompts` / `get_prompt`、そして `complete` で動詞は一通り揃います。
* `list_*` はどれも `cursor=` を取ります。`next_cursor` が `None` になるまでループします。

サーバーのほうからクライアントに要求できることと、それにどう応えるかは、**[クライアントのコールバック](callbacks.md)** で扱います。
