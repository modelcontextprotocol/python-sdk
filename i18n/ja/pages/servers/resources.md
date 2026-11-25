---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# リソース {#resources}

**リソース**とは、アプリケーションが読めるように公開するデータです。

これが分かれ目です。ツールは**モデル**が呼び出すと決めるものです。リソースは**アプリケーション**が読み込むと決めるもの（設定ファイル、レコード、ドキュメントなど）で、コンテキストとしてモデルの前に置かれます。

宣言するには、普通の Python 関数に `@mcp.resource(uri)` を付けます。

## 最初のリソース {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

形はツールと同じで、1 つだけ加わるものがあります。**URI** です。リソースは名前ではなくアドレスで指定されます。クライアントが要求するのは `config://app` であって、`get_config` ではありません。

残りは、やはり SDK が関数から読み取ります。

* **名前**は関数名、つまり `get_config` です。
* クライアントに見える**説明**は docstring です。
* **内容**は関数が返すものです。

`resources/list` でクライアントが受け取るのは次のとおりです。

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

そして `config://app` を読むと関数が実行され、戻り値がテキストとして返ってきます。

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    一覧の取得は軽い処理です。関数は `resources/list` のときには**呼び出されません**。呼び出されるのは `resources/read` のときだけで、それも要求された URI についてだけです。リソースを 1000 個公開しても、コストがかかるのは誰かが開いたものだけです。

### 試してみる {#try-it}

MCP Inspector でサーバーを起動してください。

```console
uv run mcp dev server.py
```

表示された URL を開き、**Resources** タブに移動してください。一覧に `config://app` が説明付きで並んでいます。クリックすると Inspector がそれを読み込み、2 行の設定が表示されます。

## リソーステンプレート {#resource-templates}

レコードごとに URI を 1 つずつ用意するやり方はスケールしません。URI に**プレースホルダー**を置き、それに対応するパラメーターを関数に持たせます。

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

URI に `{user_id}`、関数に `user_id: str` と書きます。約束事はこれですべてです。

これで**リソーステンプレート**になり、居場所も変わります。`resources/list` からは外れ、代わりに `resources/templates/list` に、アドレスではなくパターンとして現れます。

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

クライアントはプレースホルダーを埋め、`users://42/profile` や `users://ada/profile` のような具体的な URI を読みます。そのすべてに 1 つの関数が応答し、マッチした値が `user_id` として渡されます。

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

結果の `uri` に注目してください。これはクライアントが要求した**具体的な** URI であって、テンプレートではありません。

!!! check
    プレースホルダーとパラメーターは一致している必要があります。URI が `{user_id}` のまま関数のパラメーターを `user` に改名すると、デコレーターは**インポート時に**、つまりどのクライアントも触れないうちに拒否します。

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    不一致はバグでしかありえないので、SDK は不一致を抱えたままではサーバーを起動できないようにしています。

プレースホルダーの構文は [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) です。複数セグメントにまたがる値には `{+path}`、省略可能なクエリパラメーターには `{?q,lang}` というように、ほかにも書き方があります。また、SDK は取り出した値に対して、デフォルトでパス安全性のチェックを行います。完全なリファレンスは **[URI テンプレートとパス安全性](uri-templates.md)** を参照してください。

`get_user_profile` は、`Context` と注釈を付けたパラメーターを受け取ることもできます。SDK はそれを URI パラメーターとして扱うことなく注入します。それで何が得られるかは **[Context](../handlers/context.md)** のページで説明しています。

## 何を返すか {#what-you-return}

返せるのは `str` だけではありません。リソースごとに `mime_type` を指定し、合うものを返してください。

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` は `str` を返すので、そのまま送られます。これがよくあるケースです。
* `catalog_stats` は `dict` を返すので、SDK が **JSON テキスト**にシリアライズしてくれます。

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` は `bytes` を返すので、クライアントは `TextResourceContents` ではなく `BlobResourceContents` を受け取ります。その `blob` フィールドに、バイト列が base64 エンコードされて入っています。

JSON にシリアライズできるほかのもの、つまりリスト、Pydantic モデル、dataclass にも同じルールが当てはまります。`str` でも `bytes` でもなければ、JSON になります。

`mime_type` は自分で宣言するもので、デフォルトは `text/plain` です。SDK が戻り値の中身を調べて推測することはありません。そのため、ラベルを付けていない `dict` のリソースは、相変わらずプレーンテキストとして案内されます。

!!! tip
    関数から導き出したくないときは、`@mcp.resource()` に `name=`、`title=`、`description=` も渡せます。また、書くべき関数がそもそもないときのために、`mcp.server.mcpserver.resources` には既製の `Resource` クラス（`TextResource`、`BinaryResource`、`FileResource`、`HttpResource`、`DirectoryResource`）が用意されており、`mcp.add_resource(...)` で登録します。

クライアントはリソースを**購読**して、変更があったときに通知を受け取ることもできます。これはクライアント側の話なので、**[クライアント](../client/index.md)** で説明しています。

## まとめ {#recap}

* 関数に `@mcp.resource(uri)` を付けるとリソースになります。URI がアドレス、戻り値が内容、docstring が説明です。
* URI に `{placeholder}` を入れると**テンプレート**になります。`resources/templates/list` に載り、マッチするすべての URI に 1 つの関数が応答します。
* プレースホルダーの名前は関数のパラメーター名と一致させなければなりません。間違えても、気づくのは本番ではなくインポート時です。
* 関数が実行されるのはリソースが**読まれた**ときで、一覧に載るときではありません。
* `str` はテキストに、`bytes` は base64 の blob に、それ以外は JSON テキストになります。ラベルを付けるには `mime_type=` を使います。
* ツールはモデルが行動するためのもので、リソースはアプリケーションが読むためのものです。

3 つ目のプリミティブ、つまり人がメニューから選ぶものが **[プロンプト](prompts.md)** です。
