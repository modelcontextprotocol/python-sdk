---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# 補完 {#completions}

サーバーの上に UI を構築するクライアントは、ユーザーの入力に合わせて引数の値を自動補完したいと考えます。言語名、リポジトリ名、ファイルパスなどです。

**補完（completions）**は、サーバーがそうした候補を提供するための仕組みです。

## 補完する対象を用意する {#something-worth-completing}

補完が適用されるのはちょうど 2 つだけです。**プロンプト**の引数と、**リソーステンプレート**のパラメーターです。そこで、まずはその両方を 1 つずつ持つサーバーから始めます。

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

ここにはまだ補完に関するものは何もありません。

* `review_code` は `language` を受け取ります。どの綴りが受け付けられるかをユーザーに推測させるべきではありません。
* `github_repo` は `owner` と `repo` を受け取ります。両方とも自由入力のテキストボックスでは、使いにくいフォームになります。

## 補完ハンドラー {#the-completion-handler}

`@mcp.completion()` でデコレートした関数を **1 つ**追加します。

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* ハンドラーはサーバーごとに 1 つです。補完リクエストはすべてここに届くので、何が補完されているかに応じて分岐します。
* `async def` でなければなりません。SDK がこれを await します。
* 3 つの引数を受け取ります。
  * `ref`：「どの」プロンプトまたはリソーステンプレートかを表し、`PromptReference` か `ResourceTemplateReference` のどちらかです。見分けるには `isinstance` を使います。
  * `argument`：`argument.name` は補完対象の引数、`argument.value` はユーザーがこれまでに入力した文字列です。
  * `context`：すでに解決済みの引数です。今は無視してかまいません。
* 戻り値は `Completion(values=[...])`、または提示するものがないときは `None` です。

!!! tip
    `argument.value` はユーザーが入力したプレフィックスです。SDK はフィルタリングを**しません**。`values` に入れたものがそのまま UI に表示されます。`startswith` は自分で書きます。

### 試してみる {#try-it}

**[テスト](../get-started/testing.md)**で紹介したインメモリの `Client` で動かします。`ref=PromptReference(name="review_code")` と `argument={"name": "language", "value": "py"}` を指定して `client.complete()` を呼び出します。

```python
result.completion.values  # ['python']
```

* `ref` はハンドラーが受け取るのと同じ参照型です。
* `argument` は `name` と `value` のちょうど 2 つのキーを持つ、普通の dict です。

空の `value` を送ると、リスト全体が返ってきます。`lang.startswith("")` はどの言語に対しても真だからです。

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

`code`（ハンドラーが認識しない引数）について尋ねると `None` が返り、SDK はそれを空のリストに変換します。

```python
result.completion.values  # []
```

`None` は「候補なし」という意味であり、決してエラーではありません。UI は普通のテキストボックスにフォールバックします。

## 宣言した覚えのないケイパビリティ {#a-capability-you-never-declared}

ハンドラーを登録すること自体が宣言です。クライアントを接続して確認してみてください。

```python
client.server_capabilities.completions  # CompletionsCapability()
```

`completions` をどこにも列挙していません。SDK がハンドラーを見つけて、代わりにケイパビリティを宣言したのです。「オプション」のケイパビリティはすべてこの仕組みで動きます。ハンドラーが宣言そのものです。（3 つのプリミティブはオプションではありません。`MCPServer` はハンドラーの有無にかかわらず常にそれらを宣言します。）

!!! check
    最初の `server.py`（ハンドラーのないほう）に戻り、それでも問い合わせてみてください。呼び出しは JSON-RPC エラーで失敗します。

    ```text
    Method not found
    ```

    そして `client.server_capabilities.completions` は `None` です。これこそがケイパビリティの存在意義です。行儀のよいクライアントはこれを確認し、応答できないリクエストは最初から送りません。

## 依存する引数 {#dependent-arguments}

`github://repos/{owner}/{repo}` にはパラメーターが 2 つあり、`repo` として意味のある値は、先にどの `owner` が選ばれたかによって変わります。

そのためにあるのが `context` です。ユーザーが**すでに解決した**引数を運びます。

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* 新しい分岐は、テンプレートの `repo` パラメーターに対して実行されます。
* `context.arguments` は、これまでに選ばれた値（ここでは `owner`）を持つ `dict[str, str] | None` です。
* `owner` がまだなければ意味のある候補も出せないので、ハンドラーは `None` を返します。

クライアントは、解決済みの値を `context_arguments=` で送ります。今回の `ref` は `ResourceTemplateReference(uri="github://repos/{owner}/{repo}")` です。空の `value` で `repo` を要求し、`context_arguments={"owner": "modelcontextprotocol"}` を渡します。

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

`context_arguments=` を外すと、同じ呼び出しが `[]` を返します。ハンドラーは、オーナーがわかるまでどのリポジトリを提示すべきか知りようがありません。

!!! info
    `Completion` は `total=` と `has_more=` も受け取ります。`values` がより長いリストの一部であるときに設定すると、UI が「ほか 200 件」のように表示できます。ほとんどのハンドラーには必要ありません。

## まとめ {#recap}

* 補完は、**プロンプトの引数**と**リソーステンプレートのパラメーター**に対する候補です。それ以外にはありません。
* `@mcp.completion()` で唯一のハンドラーを登録します。シグネチャは `async def (ref, argument, context) -> Completion | None` です。
* `isinstance(ref, ...)` と `argument.name` で分岐します。`argument.value` によるフィルタリングは自分で行います。
* `None` は空のリストになります。決してエラーではありません。
* `context.arguments` は解決済みの値を保持し、クライアントはそれを `context_arguments=` として渡します。
* `completions` ケイパビリティは、ハンドラーを登録した瞬間に現れます。ハンドラーがなければ、リクエストは `Method not found` になります。

候補が役立つのは、ユーザーがまだプロンプトやテンプレートを「入力している」あいだです。ツール呼び出しの「途中」でユーザーに質問したいなら、必要なのは**[エリシテーション（elicitation）](../handlers/elicitation.md)**です。ツールがテキスト以外に返せるものはすべて**[画像、音声、アイコン](media.md)**にまとめてあります。
