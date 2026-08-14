---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# ツール {#tools}

**ツール**とは、モデルが呼び出せる関数のことです。

普通の Python 関数に `@mcp.tool()` を付ければ宣言できます。API はこれだけです。

## 最初のツール {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

書いたコードを見てください。スキーマも JSON もプロトコルもなく、あるのは関数だけです。SDK はこの関数から 3 つのことを読み取ります。

* ツールの**名前**は関数名、つまり `search_books` です。
* モデルが目にする**説明**は docstring、つまり `Search the catalog by title or author.` です。
* モデルが渡すことを許される**引数**は型ヒント、つまり `query: str` と `limit: int` から決まります。

### 入力スキーマ {#the-input-schema}

SDK はこれらの型ヒントから JSON Schema を生成し、`tools/list` のときにクライアントへ送ります。

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

どちらの引数にもデフォルト値がないため、両方とも `required` に入っています。これはすぐ後で直します。（`title` キーは Pydantic が生成した付随物です。契約にあたるのは、プロパティとその型、そして `required` です。）

!!! tip
    ここでの型ヒントはドキュメントではありません。**契約そのもの**です。クライアントが `"limit": "ten"` を送ってきても、関数が実行される前に SDK が拒否します。

### モデルが受け取るもの {#what-the-model-gets-back}

`{"query": "dune", "limit": 5}` でツールを呼び出すと、結果は 2 つの部分からなります。

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` は**モデル**が読むテキストです。`structured_content` は**クライアントアプリケーション**向けの型付きデータです。これが含まれているのは、戻り値の型を `-> str` と宣言したからです。

`structured_content` については、まだ気にしなくてかまいません。ツールから本物の Python オブジェクトを返せば、適切に処理されます。詳しくは **[構造化出力](structured-output.md)** のページを参照してください。

### 試してみる {#try-it}

MCP Inspector でサーバーを実行してください。

```console
uv run mcp dev server.py
```

表示される URL を開き、**Tools** タブに移動して `search_books` を呼び出してください。

Inspector は、必須の `query` テキストフィールドと必須の `limit` 数値フィールドを持つフォームを描画します。このフォームは型ヒントから組み立てられたものです。ほかの MCP クライアントもすべて同じようにします。

## 省略可能な引数 {#optional-arguments}

パラメーターにデフォルト値を与えると、必須ではなくなります。これだけです。ただの Python です。

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

スキーマは次のようになります。

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

`limit` は `required` から外れ、`"default": 10` が付きました。省略したクライアントには `10` が渡ります。Python とまったく同じです。

## `Field` を使った詳細なスキーマ {#richer-schemas-with-field}

型ヒントだけでもかなりのことができますが、引数に「説明」を付けたり、制約を課したりしたい場合もあります。

型を `Annotated` で包み、Pydantic の `Field` を加えます。

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

新しい点が 3 つあり、どれもパラメーターに付いています。

* `Field(description=...)`：引数ごとの説明です。モデルは docstring と合わせてこれを読みます。
* `Field(ge=1, le=50)`：数値の範囲です。スキーマには `"minimum": 1, "maximum": 50` として入ります。
* `Literal["fiction", "non-fiction", "poetry"]`：列挙型です。モデルはこの中の 1 つしか選べません。

!!! check
    制約は飾りではありません。`limit=999` でツールを呼び出すと、**関数が実行される前に** SDK がツールエラーを返します。

    ```text
    Input should be less than or equal to 50
    ```

    このエラーはツールの結果としてモデルに返され、モデルはそれを読んで有効な値でやり直します。`le=50` と一度書いただけで、自己修正するエージェントがただで手に入ったことになります。

!!! info
    FastAPI や Pydantic を使ったことがあれば、これはすべて既知の内容です。同じ `Field`、同じ `Annotated`、同じバリデーションです。MCP 固有の学ぶべきことはここにはありません。

## パラメーターとしてのモデル {#a-model-as-a-parameter}

ツールが取る引数が 2、3 個を超えるときは、Pydantic モデルにまとめます。

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

`Book` のスキーマはツールの入力スキーマの中に（`$defs` の参照として）ネストされます。モデルはこれを JSON オブジェクトとして埋め、関数はバリデーション済みの**本物の `Book` インスタンス**を受け取ります。`.title`、`.author`、`.year` の各属性が使えます。

自由に組み合わせられます。普通のパラメーターとモデルのパラメーターを並べても、モデルをネストしても、モデルのリストにしてもかまいません。どこまで行っても Pydantic です。

## `async def` {#async-def}

ツールが I/O を行う場合（API を呼ぶ、ファイルを読む、データベースに問い合わせるなど）は、`async def` で宣言し、その中で `await` してください。SDK 側がそれを await します。

普通の `def` のツールも使えます。SDK がスレッド内で実行するので、サーバーをブロックすることはありません。

ほかに設定することはありません。

## 名前、タイトル、アノテーション {#names-titles-and-annotations}

SDK が推論するものはすべて、デコレーターで上書きできます。

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` は UI 向けの、人が読むための名前です。クライアントは `search_books` の代わりに *"Search the catalog"* を表示します。
* `annotations` はクライアントに対する振る舞いの**ヒント**です。
  * `read_only_hint=True`：このツールは何も変更しません。
  * `open_world_hint=False`：開かれた Web ではなく、閉じた対象の集合（このカタログ）に対して働きます。
  * 残りの 2 つ、`destructive_hint` と `idempotent_hint` は「書き込む」ツールを説明するものです。何かを削除する可能性があるか、そして 2 回呼び出すのは 1 回呼び出すのと同じか、を表します。仕様はどちらも読み取り専用でないツールに対してだけ定義しているので、`search_books` に付けても何も伝わりません。

行儀のよいクライアントは、これらを使って「これを実行する前にユーザーに確認する必要があるか」といったことを判断します。これらはヒントであって、セキュリティではありません。クライアントがこれらを守ることを決して当てにしないでください。

!!! tip
    関数名と docstring から導きたくない場合は、`@mcp.tool()` に `name=` と `description=` を渡すこともできます。たいていは導くほうで十分です。

## まとめ {#recap}

* 関数に `@mcp.tool()` を付けるとツールになります。名前は関数から、説明は docstring から取られます。
* 型ヒントが**そのまま**入力スキーマです。デフォルト値を付けると引数は省略可能になります。
* `Annotated[..., Field(...)]` で説明と制約を、`Literal` で列挙型を加えられます。
* 構造化された「ボディ」を受け取るには、Pydantic モデルのパラメーターを使います。
* 不正な引数は自動的に拒否され、モデルが読んで立て直せるエラーが返ります。
* I/O には `async def` を、それ以外には普通の `def` を使います。

`return` した値がその後どうなるかは、**[構造化出力](structured-output.md)** で扱います。
