# エリシテーション {#elicitation}

処理の途中まで進んだのに答えが 1 つ足りない。そんなツールも、失敗する必要はありません。

**エリシテーション（elicitation）**を使えば、その場で尋ねられます。ツール呼び出しの途中でユーザーに質問が届き、その答えが同じ関数呼び出しの中に返ってきます。

モードは 2 つあります。

* **フォームモード**：値が必要な場合（確認、日付、数量など）。フィールドを記述すると、クライアントがフォームを描画します。
* **URL モード**：ユーザーに別の場所へ移動してもらう必要がある場合（OAuth の同意画面、決済ページなど）。そこでの操作はプロトコルを一切通りません。

尋ね方も 2 つあります。まず選ぶべきなのは**リゾルバー**です。質問をパラメーターに結び付けておけば、SDK が代わりに尋ねます。どんな接続でも、クライアントが話すプロトコルの世代が何であっても動きます。もう一方の直接的な方法である `await ctx.elicit(...)` は、サーバーからクライアントへのリクエストであり、このチャネルはレガシー接続（仕様バージョン 2025-11-25 以前）のクライアントにしか存在しません。このページではどちらも扱いますが、まずはリゾルバーから始めます。

## リゾルバーで尋ねる {#ask-with-a-resolver}

ツール全体の実行可否を決める質問（「本当に実行しますか？」「一致した 3 つのアカウントのどれですか？」）は、ツール本体から**リゾルバー**に切り出せます。あとはフレームワークが代わりに尋ねてくれます。

`Annotated[T, Resolve(fn)]` を付けたパラメーターは、ツール本体の前に `fn` を実行して埋められます。リゾルバーは値がすでに分かっていればそのまま返し、フレームワークに尋ねてほしいときは `Elicit(...)` を返します。

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` はツール自身の `path` 引数を名前で受け取り、フォルダーの中身を一覧して、**必要なときだけエリシテーションを行います**。空のフォルダーなら、クライアントとのラウンドトリップなしに `Confirm(ok=True)` へ解決します。
* `delete_folder` は `ElicitationResult[Confirm]` を注釈しているので、フレームワークは結果全体を注入し、ツールは `match` ですべてのケースを処理します。承諾して確定、承諾したが保持（`ok=False`）、辞退、キャンセルです。
* `confirm` パラメーターはツールの入力スキーマには一切現れません。`path` はクライアントが、`confirm` はリゾルバーが供給します。

ツール側で分岐する必要がなければ、ラップしていないモデル（`Annotated[Confirm, Resolve(confirm_delete)]`）を注釈してください。承諾時にはモデルを受け取り、辞退やキャンセルのときは呼び出しがエラーで中断します。

リゾルバーは**すべての**接続で動きます。レガシー接続のクライアントには、SDK が質問を直接送ります。**2026-07-28** の接続では、SDK は呼び出しの戻り値として質問を返し、クライアントの次の試行が答えを運んできます。リゾルバー側がその違いを意識することはありません。内部で何が起きているかは**[マルチラウンドトリップ（multi-round-trip）リクエスト](multi-round-trip.md)**を参照してください。

尋ねることは、リゾルバーができることの 1 つにすぎません。より一般的な仕組み（尋ねずに計算する依存関係、依存関係の依存関係、モデルが供給できるものとできないもの）については、**[依存関係](dependencies.md)**のページを参照してください。

## ツールの中から尋ねる {#ask-from-inside-the-tool}

ツールは、自分の本体の途中で処理を止めて尋ねることもできます。

!!! warning
    `ctx.elicit()` と `ctx.elicit_url()` はサーバーからクライアントへのリクエストであり、
    このチャネルはレガシー接続（仕様バージョン **2025-11-25** 以前）のクライアントにしか
    存在しません。**2026-07-28** の接続にはサーバー発のリクエストがないため、これらの
    呼び出しは失敗します。リゾルバーはどちらでも動作します。詳しくは
    **[プロトコルバージョン](../protocol-versions.md)**を参照してください。

`await ctx.elicit()` はメッセージと Pydantic モデルを受け取ります。

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** パラメーターがあるからこそ `ctx.elicit` が使えます。どのツールでも受け取れます。このオブジェクトには専用のページがあります：**[Context](context.md)**。
* `AlternativeDate` は、受け取りたい答えの**スキーマ**です。
* このツールは `async def` です。途中で止まって人の入力を待つのですから、そうでなければなりません。
* それ以外の日付なら、ツールはすぐに結果を返します。尋ねるのは必要なときだけです。
* ユーザーが承諾した日付は `book_table` 自身に戻ってきます。答えも他と同じ入力です。代替日もまた満席であれば、確認なしに予約するのではなく、もう一度尋ねます。

### クライアントが受け取るもの {#what-the-client-receives}

クライアントは、こちらのメッセージと、その隣にモデルから生成された JSON Schema を受け取ります。

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

このスキーマがフォームそのものです。`Field(description=...)` がラベルになり、デフォルト値は入力欄にあらかじめ埋まって、そのフィールドを省略可能にします。これは**[ツール](../servers/tools.md)**がツールの引数について説明しているのと同じ、Pydantic から JSON Schema への変換機構です。

!!! warning
    エリシテーションのスキーマは、ツールの入力スキーマほど表現力がありません。使えるのは
    フラットなプリミティブ型のフィールドだけです：`str`、`int`、`float`、`bool`、または
    文字列の `Literal`（`enum` になります）。モデルの中にモデルを入れると、クライアントへ
    何かを送る前に `ctx.elicit` が例外を送出します。

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    相手は作業中の人です。答えにネストが必要なら、それはツールの引数であるべきだった
    ということです。

### 3 つの答え {#the-three-answers}

`result.action` には、ユーザーが何をしたかが入ります。可能性はちょうど 3 つです。

* `"accept"`：フォームを送信しました。`result.data` は検証済みの `AlternativeDate` インスタンスです。
* `"decline"`：断られました。
* `"cancel"`：選ばずに質問を閉じました。

`result.data` が存在するのは `"accept"` のときだけです。だからこの例では、まず `result.action` を確認しています。型チェッカーもこの順序を強制します。`result.action == "accept"` の後では `result.data` は `AlternativeDate` ですが、その前には `.data` 自体がありません。

拒否はエラーではありません。辞退が何を意味するか（ここでは予約しないこと）はツールが決め、モデルには通常どおり応答します。

!!! tip
    答えは、コードが見る前に定義したモデルで検証されます。`bool` に対して `"maybe"` を
    送ってくるクライアントがいても、予約が壊れることはありません。呼び出しはスキーマ
    不一致のエラーで失敗し、`if` は実行されません。

## ユーザーを URL へ送る {#send-the-user-to-a-url}

モデルやクライアントを通してはいけないものもあります。認証情報、カード番号、OAuth の同意などです。そうしたものではデータを尋ねるのではなく、ユーザーにどこかへ移動してもらいます。

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` はメッセージ、訪問先の **URL**、そして自分で決める `elicitation_id` を受け取ります。`elicitation_id` は、サーバー内でこのエリシテーションを識別する任意の文字列です。
* 結果にはアクションしか入りません。`"accept"` はユーザーが URL を開くことに同意したという意味であり、その先の手続きを完了したという意味では**ありません**。
* 決済は帯域外で、ユーザーのブラウザーと決済プロバイダーの間で行われます。コンテンツが MCP を通って戻ってくることはありません。

2 つ目のツールを見てください。帯域外のフローが完了したことをサーバーが知ったとき（Webhook やポーリングなど。ここでは 2 つ目のツールとして表現しています）、`ctx.session.send_elicit_complete(...)` が同じ `elicitation_id` を付けて `notifications/elicitation/complete` を送ります。クライアントは、これによって「支払いを待っています...」の表示をやめてよいと分かります。これがなければ、クライアントは推測するしかありません。

## クライアント側 {#the-client-side}

尋ねるのはサーバーです。クライアントは `Client(...)` に **`elicitation_callback`** を渡して答えます。

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 1 つのコールバックで両方のモードを処理します。`params` は `ElicitRequestFormParams` と `ElicitRequestURLParams` のユニオンで、`isinstance` で分岐します。
* URL の場合は `params.url` をユーザーに表示し、選ばれたアクションを返します。`content` は決して返しません。
* フォームの場合、実際のアプリケーションは `params.requested_schema` を描画し、ユーザーの入力を `content` として返します。ここでは常に決め打ちの答えで承諾していますが、テストではまさにこういうコールバックが欲しくなります。
* コールバックを渡すことは**ケイパビリティの宣言**でもあります。これによってサーバーは、このクライアントに尋ねられると知ります。クライアントがサーバーのために答えられる他の事柄は**[クライアントコールバック](../client/callbacks.md)**にまとめてあります。

!!! info
    エリシテーションはサーバーからクライアントへのリクエストであり、それが存在するのは
    従来のハンドシェイクで確立したセッションだけです。だからこのクライアントは
    `mode="legacy"` を渡しています。**2026-07-28** の接続では、ツールは呼び出しの戻り値
    として質問を返す形で尋ねます。その流れは**[マルチラウンドトリップリクエスト](multi-round-trip.md)**です。

### 試してみる {#try-it}

`ctx.elicit` を使うフォームモードの `server.py`（`book_table` のほう）を Streamable HTTP で起動し（ワンライナーは**[サーバーの実行](../run/index.md)**にあります）、クライアントの `main()` を実行して `book_table` にクリスマス当日を尋ねてみてください。

コールバックは、送られてきた質問を表示します。

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

コールバックは `{"accept_alternative": True, "date": "2025-12-27"}` と答え、その間ずっと `await ctx.elicit(...)` の中で待っていたツールが予約を完了します。

```text
Booked a table for 2 on 2025-12-27.
```

次に URL モードの `server.py` に差し替えて、同じ `main()` を `pay_deposit` に向けてみてください。同じコールバックがもう一方の分岐に入り、決済リンクを表示し、ツールは「Complete the payment in your browser.」を返してきます。呼び出しの途中での、双方向の 1 往復です。

!!! check
    次に `Client` から `elicitation_callback=` を外して、もう一度クリスマス当日で
    `book_table` を呼んでみてください。呼び出し全体がプロトコルエラーで失敗します。

    ```text
    Elicitation not supported
    ```

    コールバックを登録していないクライアントは `elicitation` ケイパビリティを宣言していないので、
    尋ねる相手がいません。ツールが受け取ったのは `"decline"` ではなく例外です。これを前提に
    設計してください。どのエリシテーションにも「尋ねられなかったらどうするか」への妥当な答えが必要です。

## まとめ {#recap}

* `Annotated[T, Resolve(fn)]` を付けたパラメーターはリゾルバーが埋め、リゾルバーは尋ねる必要があるときに `Elicit(...)` を返します。これはすべての接続で動きます。
* スキーマはフラットな Pydantic モデルです。プリミティブなフィールドだけで、戻ってくるときに検証されます。
* `result.action` は `"accept"`、`"decline"`、`"cancel"` のいずれかです。`result.data` は accept のときだけ存在します。
* `await ctx.elicit(message, schema=Model)` はツール本体の中から尋ねます。`await ctx.elicit_url(message, url, elicitation_id)` は、モデルを通してはいけないすべてのもののためにあります（`ctx.session.send_elicit_complete(elicitation_id)` が帯域外の処理の完了を伝えます）。どちらもサーバーからクライアントへのリクエストなので、クライアントがレガシー接続であることが必要です。
* クライアントは 1 つの `elicitation_callback` で答え、params の型で分岐します。これを登録することがケイパビリティの宣言になります。
* 2026-07-28 の接続では、サーバーは質問を押し出すのではなく返します。同じコールバックには**[マルチラウンドトリップリクエスト](multi-round-trip.md)**から値が渡されます。

その戻り値の下で起きていること（リトライループ、`requestState` の保護、自分で駆動する方法）はすべて**[マルチラウンドトリップリクエスト](multi-round-trip.md)**にあります。
