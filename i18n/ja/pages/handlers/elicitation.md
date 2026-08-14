---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# エリシテーション {#elicitation}

処理の途中で答えがひとつ足りないだけのツールは、失敗する必要はありません。

**エリシテーション（elicitation）**を使えば、質問できます。ツール呼び出しの途中でユーザーに質問が届き、その答えが同じ関数呼び出しの中に戻ってきます。

モードは 2 つあります。

* **フォームモード**：値（確認、日付、数量）が必要な場合です。フィールドを記述すると、クライアントがフォームを描画します。
* **URL モード**：ユーザーに別の場所（OAuth の同意画面、決済ページ）へ行ってもらう必要がある場合です。そこでユーザーが行うことは、何ひとつプロトコルを通りません。

そして、質問の仕方も 2 通りあります。まず選ぶべきなのは**リゾルバー**です。質問をパラメーターに結び付けておけば、SDK が質問します。どんな接続でも、クライアントがどのプロトコルの世代を話していても動きます。直接的な方法である `await ctx.elicit(...)` は、サーバーからクライアントへのリクエストです。この経路は、レガシー接続（仕様バージョン 2025-11-25 以前）のクライアントにしか存在しません。このページでは両方を扱いますが、まずはリゾルバーから始めてください。

## リゾルバーで質問する {#ask-with-a-resolver}

ツール全体の実行を左右する質問（「本当によろしいですか」「一致した 3 つのアカウントのうちどれですか」など）は、ツール本体から取り出して**リゾルバー**に移せます。そうすれば、フレームワークが代わりに質問してくれます。

`Annotated[T, Resolve(fn)]` と注釈したパラメーターには、ツール本体の前に `fn` を実行した結果が入ります。リゾルバーは、値がすでに分かっていればそのまま返し、フレームワークに質問させたいときは `Elicit(...)` を返します。

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` はツール自身の `path` 引数を名前で読み取り、フォルダーの中身を一覧し、**必要なときにだけ質問します**。空のフォルダーなら、クライアントとの往復なしで `Confirm(ok=True)` に解決されます。
* `delete_folder` は `ElicitationResult[Confirm]` と注釈しているので、フレームワークは結果全体を注入し、ツールはすべての場合を `match` で分岐します。承諾して確認、承諾したが削除しない（`ok=False`）、拒否、キャンセルです。
* `confirm` パラメーターはツールの入力スキーマには決して現れません。クライアントが `path` を渡し、リゾルバーが `confirm` を渡します。

ツールが分岐する必要がないなら、代わりにラップしていないモデル（`Annotated[Confirm, Resolve(confirm_delete)]`）で注釈してください。承諾ならツールはモデルを受け取り、拒否やキャンセルなら呼び出しはエラーで中断されます。

リゾルバーは**すべての**接続で動きます。レガシー接続のクライアントには、SDK が質問を直接送ります。**2026-07-28** の接続では、SDK が呼び出しから質問を「返し」、クライアントの次の試行が答えを運んできます。リゾルバーがその違いを知ることはありません。その裏で何が起きているかは **[マルチラウンドトリップリクエスト（multi-round-trip requests）](multi-round-trip.md)** で説明しています。

質問は、リゾルバーにできることのひとつにすぎません。質問せずに計算する依存関係、依存関係の依存関係、モデルが渡せるものと渡せないものといった仕組み全般は、**[依存関係](dependencies.md)** のページで説明しています。

## ツールの中から質問する {#ask-from-inside-the-tool}

ツールは、自分の本体の途中で止まって質問することもできます。

!!! warning
    `ctx.elicit()` と `ctx.elicit_url()` はサーバーからクライアントへのリクエストです。この経路は、レガシー接続（仕様バージョン **2025-11-25** 以前）のクライアントにしか存在しません。**2026-07-28** の接続にはサーバー起点のリクエストがないため、これらの呼び出しは失敗します。リゾルバーはどちらでも動きます。詳しくは **[プロトコルバージョン](../protocol-versions.md)** を参照してください。

`await ctx.elicit()` はメッセージと Pydantic モデルを受け取ります。

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** パラメーターがあるからこそ `ctx.elicit` が使えます。どのツールでも受け取れます。このオブジェクトについては専用のページ **[Context](context.md)** があります。
* `AlternativeDate` は、欲しい答えの**スキーマ**です。
* ツールは `async def` です。そうでなければなりません。途中で止まって人を待つからです。
* ほかの日付なら、ツールはすぐに返ります。質問するのは必要なときだけです。
* ユーザーが承諾した日付は、`book_table` 自身をもう一度通ります。答えも、ほかの入力と同じ入力です。代わりの日付も満席なら、やみくもに確定するのではなく、もう一度質問します。

### クライアントが受け取るもの {#what-the-client-receives}

クライアントは、メッセージと一緒に、モデルから生成された JSON Schema を受け取ります。

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

このスキーマがフォームです。`Field(description=...)` がラベルになり、デフォルト値は入力欄にあらかじめ入って、そのフィールドを省略可能にします。これは、**[ツール](../servers/tools.md)** のページがツールの引数について説明しているのと同じ、Pydantic から JSON Schema への変換の仕組みです。

!!! warning
    エリシテーションのスキーマは、ツールの入力スキーマほど表現力がありません。フラットなプリミティブ型のフィールドだけです。`str`、`int`、`float`、`bool`、または文字列の `Literal`（`enum` になります）。モデルの中にモデルを入れると、クライアントに何かを送る前に `ctx.elicit` が例外を送出します。

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    人の作業を中断して質問しているのです。答えに入れ子が必要なら、それはツールの引数にすべきでした。

### 3 つの答え {#the-three-answers}

`result.action` を見れば、ユーザーが何をしたかが分かります。可能性はちょうど 3 つです。

* `"accept"`：フォームを送信しました。`result.data` は検証済みの `AlternativeDate` インスタンスです。
* `"decline"`：断りました。
* `"cancel"`：選ばずに質問を閉じました。

`result.data` は `"accept"` のときにしか存在しません。だからこそ、この例では先に `result.action` を確認しています。この順序は型チェッカーが強制します。`result.action == "accept"` の後では `result.data` は `AlternativeDate` ですが、その前には `.data` 自体がありません。

断られてもエラーではありません。断られたことが何を意味するか（ここでは、予約しないこと）はツールが決め、モデルには普通に答えます。

!!! tip
    答えは、コードに届く前にモデルに照らして検証されます。`bool` に `"maybe"` を送ってくるクライアントがいても、予約が壊れることはありません。呼び出しはスキーマ不一致のエラーで失敗し、`if` は実行されません。

## ユーザーを URL へ誘導する {#send-the-user-to-a-url}

認証情報、カード番号、OAuth の同意など、モデルやクライアントを通してはならないものがあります。そうしたものについては、データを求めるのではなく、ユーザーにどこかへ行ってもらうよう頼みます。

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` は、メッセージ、開いてもらう **URL**、そして自分で決める `elicitation_id` を受け取ります。これは、サーバー内でこのエリシテーションを識別できる任意の文字列です。
* 結果にあるのはアクションだけです。`"accept"` はユーザーが URL を開くことに同意したという意味で、向こう側でやるべきことを終えたという意味**ではありません**。
* 決済は、ユーザーのブラウザーと決済プロバイダーの間で、帯域外で行われます。MCP を通って戻ってくる内容は一切ありません。

2 つ目のツールを見てください。帯域外のフローが終わったことをサーバーが知ったとき（webhook やポーリング。ここでは 2 つ目のツールとしてモデル化しています）、`ctx.session.send_elicit_complete(...)` が同じ `elicitation_id` を付けて `notifications/elicitation/complete` を送ります。これによってクライアントは、「waiting for payment...」の表示をやめてよいと分かります。これがなければ、クライアントは推測するしかありません。

## クライアント側 {#the-client-side}

質問するのはサーバーです。クライアントは、`Client(...)` に **`elicitation_callback`** を渡すことで答えます。

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 1 つのコールバックで両方のモードを扱います。`params` は `ElicitRequestFormParams` と `ElicitRequestURLParams` のユニオンで、`isinstance` で分岐します。
* URL の場合は、`params.url` をユーザーに見せ、ユーザーが選んだアクションを返します。`content` は決して返しません。
* フォームの場合、本物のアプリケーションなら `params.requested_schema` を描画し、ユーザーの入力を `content` として返します。このコールバックは決まった答えで常に「はい」と答えます。これはまさに、テストで欲しいコールバックです。
* コールバックを渡すことは、**ケイパビリティの宣言**でもあります。これによってサーバーは、このクライアントに質問できることを知ります。クライアントがサーバーの代わりに答えられるほかのことは、**[クライアントのコールバック](../client/callbacks.md)** にまとまっています。

!!! info
    エリシテーションはサーバーからクライアントへのリクエストであり、それは従来のハンドシェイクによるセッションにしか存在しません。このクライアントが `mode="legacy"` を渡しているのはそのためです。**2026-07-28** の接続では、ツールは代わりに呼び出しから質問を「返す」ことで質問します。その流れは **[マルチラウンドトリップリクエスト](multi-round-trip.md)** で説明しています。

### 試してみる {#try-it}

`ctx.elicit` を使うフォームモードの `server.py`（`book_table` のほう）を Streamable HTTP で起動し（1 行で起動するコマンドは **[サーバーの実行](../run/index.md)** にあります）、クライアントの `main()` を実行して、`book_table` にクリスマス当日の予約を頼んでください。

コールバックは、送られてきた質問を表示します。

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

コールバックは `{"accept_alternative": True, "date": "2025-12-27"}` と答え、その間ずっと `await ctx.elicit(...)` の中で待っていたツールが予約を完了します。

```text
Booked a table for 2 on 2025-12-27.
```

今度は URL モードの `server.py` に差し替え、同じ `main()` を `pay_deposit` に向けてください。同じコールバックがもう一方の分岐を通り、決済リンクを表示し、ツールは「Complete the payment in your browser.」と返してきます。呼び出しの途中で、双方向に 1 往復です。

!!! check
    今度は `Client` から `elicitation_callback=` を取り除き、もう一度クリスマス当日で `book_table` を呼び出してください。呼び出し全体がプロトコルエラーで失敗します。

    ```text
    Elicitation not supported
    ```

    コールバックを登録しなかったクライアントは `elicitation` ケイパビリティを宣言していないので、質問する相手がいません。ツールが受け取ったのは `"decline"` ではなく、例外です。これに備えて設計してください。どのエリシテーションにも、「質問できなかったらどうするか」に対する妥当な答えが必要です。

## まとめ {#recap}

* `Annotated[T, Resolve(fn)]` と注釈したパラメーターはリゾルバーが埋め、リゾルバーは質問が必要なときに `Elicit(...)` を返します。すべての接続で動きます。
* スキーマはフラットな Pydantic モデルです。プリミティブ型のフィールドだけで、戻ってくるときに検証されます。
* `result.action` は `"accept"`、`"decline"`、`"cancel"` のいずれかで、`result.data` は承諾のときにだけ存在します。
* `await ctx.elicit(message, schema=Model)` はツール本体の中から質問し、`await ctx.elicit_url(message, url, elicitation_id)` はモデルを通してはならないもののためにあります（帯域外の部分が終わったことは `ctx.session.send_elicit_complete(elicitation_id)` で伝えます）。どちらもサーバーからクライアントへのリクエストなので、クライアントがレガシー接続である必要があります。
* クライアントは 1 つの `elicitation_callback` で答え、params の型で分岐します。これを登録することがケイパビリティの宣言になります。
* 2026-07-28 の接続では、サーバーは質問をプッシュする代わりに返します。同じコールバックに質問を届けるのは **[マルチラウンドトリップリクエスト](multi-round-trip.md)** です。

その「返す」仕組みの裏側（再試行ループ、`requestState` の保護、自分で駆動する方法）は、すべて **[マルチラウンドトリップリクエスト](multi-round-trip.md)** で説明しています。
