---
translation:
  sections: [7be05607887e6853, e7375894888d9750, c36f73fc7e3af13b, 2fec2d7e129e62fe, 809b0e0a7c27295a, b4395a04d2a5d906, 1a436007f5f54779, c6b2078ed1e63ba5]
  tool: 1
---
# エラーの処理 {#handling-errors}

ツールの失敗には 3 通りあり、SDK はそれぞれを違う形で扱います。

`ToolError` を送出すると、**モデル**がメッセージを目にします。`MCPError` を送出すると、**プロトコル**がそれを目にします。それ以外を送出するとクラッシュです。モデルには呼び出しが失敗したことだけが伝わり、トレースバックはログに記録されます。

このページは、そのどれを選ぶかについてです。

## モデルが直せるエラー {#an-error-the-model-can-fix}

何かを検索するツールを用意し、その検索を空振りさせてみます。

```python title="server.py" hl_lines="2 12-13"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`mcp.server.mcpserver.exceptions` にある `ToolError` は、何かがうまくいかなかったことをツールがモデルに伝える手段です。

カタログにないタイトルで呼び出して、結果を見てみましょう。

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* リクエストは**成功**しています。結果が返っており、呼び出し側では何も送出されていません。
* `is_error` は `True` で、メッセージ（ツール名が前に付きます）が `content` に入っています。まさにモデルが読む場所です。
* `structured_content` は `None` です。失敗した呼び出しには、構造化すべき戻り値がありません。

これが**ツールエラー**で、ほとんどの場合これこそが望む挙動です。

ツールを呼び出しているのはモデルです。引数を選んだのもモデルです。つまりツールエラーは会話の 1 ターンになります。モデルは「No book titled 'Nothing' in the catalog.」を読み、タイトルを推測し損ねたことに気づき、もっと良いタイトルで呼び直します。`raise` を 1 つ書いただけで、自己修正するエージェントが手に入りました。

サーバー側では、`ToolError` はログに `INFO` が 1 行出るだけで、トレースバックはありません。想定していた失敗なので、調べることは何もありません。

!!! tip
    ツールからエラーメッセージを `return` しないでください。返された文字列は `is_error=False` なので、モデルにとっても（そしてあらゆるクライアント UI にとっても）ツールは正常に動作し、その文字列が答えだったように見えます。`raise` してください。シグナルはこのフラグです。

## モデルが直せないエラー {#an-error-the-model-cannot-fix}

今度は `ToolError` を `MCPError` に置き換えます。

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` は SDK の**プロトコルエラー**です。ツールのラッパーが捕捉**しない**唯一の例外で、そのまま伝播し、`tools/call` リクエスト全体が結果ではなく JSON-RPC エラーで失敗します。

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **結果がありません**。`content` も `is_error` もなく、モデルが読めるものは何もありません。
* 代わりに**ホスト**アプリケーションがエラーを受け取ります。ツールがそもそも存在しなかった場合と同じ扱いです。
* `code`、`message`、`data` はそのまま届きます。`INVALID_PARAMS` は `-32602` です。`mcp.types` はこれを含む JSON-RPC のエラーコード（`INVALID_REQUEST`、`INTERNAL_ERROR` など）を定数としてエクスポートしているので、マジックナンバーを手で打つ必要はありません。

!!! check
    同じ検索、同じ空振りですが、今度はクライアント側で呼び出しが結果を返す代わりに「送出」します。

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    最初のバージョンは、モデルが反応できる一文を渡しました。こちらは何も渡しません。`get_author` にとってこれは明らかに改悪であり、それが次のセクションの要点です。

## どちらを送出するか {#which-one-to-raise}

2 つの経路は、2 つの異なる問いに答えるものです。

* 「実行」の失敗、つまりツールがやろうとしたことがうまくいかなかった場合は、**`ToolError` を送出**します。呼び出しを選んだのはモデルなので、モデルがその結果を目にし、立て直す機会を得るべきです。綴りの間違ったタイトル、タイムアウトした上流の API、存在しない行。どれもツールエラーです。
* 「リクエストそのもの」を拒否すべきときは **`MCPError` を送出**します。ツールが依存するケイパビリティをクライアントが持っていない、サーバーが誰にも応答できる状態にない、呼び出し側が必要な手順を飛ばした。どれもモデルが再試行しても直らないので、メッセージを渡しても得るものはありません。

決め手になる問いは 1 つです。**もっと賢いモデルならこれを避けられたか**。はい → `ToolError`。いいえ → `MCPError`。

この基準で見ると、`get_author` の 2 番目のバージョンは選択を誤っています。より良いタイトルで直るのですから、モデルはメッセージを見るべきでした。あれは仕組みを見せるためのもので、推奨するためのものではありません。

!!! info
    `MCPError` は `from mcp import MCPError` でインポートでき、`code`、`message`、省略可能な `data` ペイロードを受け取ります。そこに入れた内容がそのままクライアントに届きます。SDK は送出された `MCPError` をサニタイズせず、そのまま転送します。

## その他の例外 {#any-other-exception}

今度はチェックを外し、辞書の検索がそれ自体で失敗するのに任せます。

```python title="server.py" hl_lines="11"
--8<-- "docs_src/handling_errors/tutorial004.py"
```

`CATALOG[title]` は `KeyError` を送出します。想定していなかった例外なので、SDK はクラッシュとして扱います。

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool get_author")]
```

呼び出しは依然として `is_error=True` を返すので、モデルは失敗したことを知り、先へ進めます。受け取らないのは例外のテキストです。コードから出た `KeyError` や、3 つ下の層のライブラリのドライバーが吐いた SQL の山は、サーバーの内部を説明してしまうかもしれません。そのため、サーバーの外には決して出ません。

それを受け取るのはサーバー側です。サーバーはクラッシュを `ERROR` レベルで完全なトレースバック付きで記録し、`Tool 'get_author' raised an unexpected exception` と出力します。したがって、`WARNING` レベルの本番ログはどの `ToolError` でも静かなままで、本当に何かが壊れた瞬間に声を上げます。

## 存在しないリソース {#a-resource-that-doesnt-exist}

リソースも同じ線引きをします。そして、よくあるケースのために名前付きの例外を 1 つ用意しています。

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` は**テンプレート**です。「あらゆる」タイトルにマッチするので、「URI が正しい形式か」と「その本が存在するか」は別の問いであり、2 番目に答えられるのはこの関数だけです。

答えられないときは `ResourceNotFoundError` を送出してください。SDK はこれを、仕様が存在しないリソースに割り当てているプロトコルエラーに変換します。`-32602` で、リクエストされた URI が `data` に入るので、クライアントは「どの」読み取りが失敗したのかがわかります。

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

ここには `is_error=True` のような中間的な結果がないことに注目してください。リソースの読み取りは、内容を返すか失敗するかのどちらかです。リソースにはプロトコルの経路しかありません。`ResourceError` は「見つからない」以外の失敗のための同じ仕組みで（`-32603` とメッセージ）、どちらもログには `INFO` が 1 行出るだけです。`MCPError` を除くその他の例外はクラッシュです。クライアントには URI だけを示す `-32603` が届き、トレースバックは `ERROR` レベルでログに記録されます。テンプレートをはじめ、リソースに関するその他すべては **[リソース](resources.md)** にあります。

## 送出する必要のないエラー {#errors-you-never-raise}

不正な引数が関数に届くことはありません。

`get_author` に文字列ではない `title` を送ると、SDK は関数を呼び出す**前に**入力スキーマと照合して拒否します。その結果は同じ種類の `is_error=True` のツールエラーなので、モデルが読んで修正できます。**[ツール](tools.md)** では、`Field(le=50)` 制約で同じ拒否の様子を示しています。

つまり、書かなくてよい `raise` 文がまるごと一群あるということです。自分の型ヒントを改めて検証しないでください。

!!! info
    このページで**クライアント**から見えるものはすべて、テストを書くときに使うインメモリの `Client` からも見えます。`raise_exceptions=True` でも、失敗したツールの例外が呼び出し側に返されることはありません。このフラグが作用できる時点では、例外はすでに `is_error=True` の結果になっています。結果に対してアサートしてください。クラッシュのトレースバックが必要なら、それはサーバーのログにあり、pytest の `caplog` で捕捉できます。このパターンは **[テスト](../get-started/testing.md)** で扱っています。

## まとめ {#recap}

* ツールの中で **`ToolError`** を送出する → 呼び出しは `is_error=True` を返し、メッセージが `content` に入ります。モデルはそれを読み、再試行できます。
* **`MCPError`** を送出する → 呼び出しそのものが JSON-RPC エラーで失敗します。モデルには何も見えず、ホストが対処します。`code`、`message`、`data` はそのまま残ります。
* 決め手の問い：「もっと賢いモデルならこれを避けられたか」。はい → `ToolError`。いいえ → `MCPError`。
* **その他の例外**はクラッシュ → モデルには `Error executing tool <name>` とだけ書かれた `is_error=True`、サーバー側にはトレースバック付きの `ERROR` レコードが残ります。
* リソースのハンドラーから `ResourceNotFoundError` を送出する → プロトコルの `-32602` になり、URI が `data` に入ります。
* 不正な引数は関数が実行される前にスキーマと照合して拒否されます。そのために `raise` する必要はありません。
* インポート：`from mcp import MCPError`、`from mcp.server.mcpserver.exceptions import ToolError, ResourceError, ResourceNotFoundError`、そしてエラーコードの定数は `mcp.types` から取得します。

エラーの処理はここまでです。サーバーが「公開する」ものはこれですべてです。すべてのハンドラーが実行中に読み取れるもの、そして実行中にクライアントに対して行えることは、次のセクション **[ハンドラーの中で](../handlers/index.md)** で扱います。

遭遇する可能性が最も高い SDK エラーの正確な文面、それぞれの意味、そしてそれぞれを一手で直す方法は **[トラブルシューティング](../troubleshooting.md)** にあります。
