---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
  tool: 1
---
# プロンプト {#prompts}

**プロンプト**は、ユーザーが選ぶメッセージテンプレートです。

ツールはモデルのためのものです。プロンプトはその逆です。ユーザーがクライアントのメニュー（スラッシュコマンドやボタン）から 1 つを選んで引数を入力すると、レンダリングされたメッセージが、ユーザー自身が入力したかのように会話に入ります。

プロンプトを宣言するには、テキストを返す関数に `@mcp.prompt()` を付けます。

## 最初のプロンプト {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK が読み取るのは、ツールの場合と同じ 3 つです。

* **名前**は関数名、つまり `review_code` です。
* クライアントが表示する**説明**は docstring、つまり `Review a piece of code.` です。
* **引数**はパラメーターから決まります。`code` にはデフォルト値がないので必須です。

クライアントが `prompts/list` で受け取るのは次のとおりです。

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

ここには JSON Schema がありません。プロンプトの引数は、**名前付きの文字列値**が並んだフラットなリストです。モデルが組み立てるペイロードではなく、人が記入するフォームです。

### レンダリングする {#rendering-it}

クライアントは `prompts/get` に引数を渡してテンプレートをレンダリングします。関数が実行され、返した `str` が **1 つのユーザーメッセージ**になります。

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

プロンプトの一生はこれがすべてです。名前で一覧に載り、必要なときにレンダリングされ、チャットに差し込まれます。

!!! check
    `required` のチェックは関数が実行される前に行われます。`code` なしで `review_code` をレンダリングすると、リクエスト自体が JSON-RPC エラー（コード `-32603`）で失敗します。

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    モデルに返すためのツール形式のエラー結果はありません。そもそもモデルが関与していないからです。呼び出しは例外を送出します。理由（`Missing required arguments: {'code'}`）はサーバーのログに記録されます。

### 試してみる {#try-it}

MCP Inspector でサーバーを実行してください。

```console
uv run mcp dev server.py
```

**Prompts** タブを開いて `review_code` を選択してください。Inspector は、必須の `code` フィールドが 1 つあるフォームを表示します。入力してレンダリングすると、上のユーザーメッセージがそのまま返ってきます。

## 複数のメッセージ {#more-than-one-message}

コードレビューは 1 つのメッセージです。デバッグセッションは会話であり、プロンプトはその会話全体の出発点を用意できます。

`str` の代わりに、メッセージのリストを返します。

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` と `AssistantMessage` は `mcp.server.mcpserver.prompts.base` にあります。`str` を渡すと、`TextContent` にラップしてくれます。ロールはクラス名で決まります。
* `Message` は両者に共通の基底クラスです。戻り値のアノテーションにはこれを使ってください。

`debug_error` をレンダリングすると、3 つのメッセージがこの順番で生成されるようになります。

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

最後のメッセージに注目してください。`assistant` のターンをあらかじめ埋めておくのは、誘導の文言をユーザー自身に入力させることなく、モデルの「次の」返答を方向づけるための方法です。

## タイトルと引数の説明 {#titles-and-argument-descriptions}

`review_code` は関数名であって、ラベルではありません。ボタンに載せるのにもっとふさわしいものをクライアントに渡し、フォームを見ただけで意味がわかるように各引数に説明を付けます。

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` は人が読むための名前で、ツールの `title` とまったく同じです。
* `Annotated[str, Field(description=...)]` は、**[ツール](tools.md)** でツールのパラメーターを説明するのに使うのと同じパターンです。ここでは、説明はスキーマの中ではなく引数に付きます。
* `language` にはデフォルト値があるので、必須ではなくなります。

これで `prompts/list` のエントリには、クライアントがよいフォームを描くのに必要なものがすべてそろいます。

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    **[ツール](tools.md)** を読んでいれば、このページの内容はもうすべて知っています。同じデコレーター、同じく docstring が説明になる仕組み、同じ `Annotated`/`Field` です。変わるのは、誰が起動するか（ユーザー）と、結果がどこへ行くか（会話の中）だけです。

## まとめ {#recap}

* 関数に `@mcp.prompt()` を付けるとプロンプトになります。名前は関数から、説明は docstring から取られます。
* プロンプトは**ユーザーが制御する**ものです。クライアントが一覧を出し、ユーザーが 1 つ選んで引数を入力します。
* 引数は名前付き文字列のフラットなリストです（スキーマなし）。デフォルト値のあるパラメーターは省略可能です。
* `str` を返すと 1 つのユーザーメッセージになります。`UserMessage` / `AssistantMessage` のリストを返すと、複数ターンの会話の出発点を用意できます。
* `title=` と `Field(description=...)` は、クライアントが UI に表示するものです。
* 必須の引数が欠けていると、リクエスト全体が失敗します。プロンプト単位のエラー結果はありません。

プロンプト（やリソーステンプレート）の引数をサーバー側でオートコンプリートする機能については、**[補完](completions.md)** を参照してください。
