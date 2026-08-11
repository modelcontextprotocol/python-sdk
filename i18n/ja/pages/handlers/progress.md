---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# 進捗 {#progress}

30 秒かかるツールが 30 秒間なにも言わなければ、壊れているように見えます。

**進捗通知**はそれを解決します。ツールはどこまで進んだかを報告し、クライアントはそれを使って何を描くかを決めます。プログレスバー、スピナー、ログの 1 行などです。

## ツールから報告する {#report-it-from-the-tool}

**`Context`** パラメーターを受け取り、`report_progress` を呼び出してください。

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

引数は 3 つで、その意味は自分で決めます。

* `progress`：どこまで進んだか。仕様では、報告のたびに**増加する**ことが必須です。同じ値を繰り返したり、減らしたりしないでください。
* `total`：全体でどれだけあるか（わかっている場合）。省略可能です。
* `message`：「この」ステップについての、人が読める 1 行。省略可能です。

`ctx` は型ヒントによって注入され、モデルからは決して見えません。`import_catalog` の入力スキーマにあるプロパティは `urls` の 1 つだけです。**[Context](context.md)** のページはこのオブジェクトについて詳しく扱っています。進捗はそれが提供するものの 1 つです。

## クライアントで受け取る {#listen-for-it-from-the-client}

クライアントは、`call_tool` に `progress_callback=` を渡すことで、**呼び出しごとに**オプトインします。

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

コールバックは `async` 関数で、サーバーが報告したものをそのまま受け取ります。`progress`、`total`、`message` です。

!!! info
    `Client(mcp)` はサーバーオブジェクトにメモリ内で直接接続します。**[テスト](../get-started/testing.md)** のページの土台になっているのと同じクライアントです。`progress_callback` は、`Client` がどのトランスポートを使っていても同じパラメーターです。これから目にする「タイミング」はメモリ内接続のものです。メモリ内接続はコールバックをインラインで実行するため、すべての報告が `call_tool` が返る前に届きます。実際のトランスポートでは通知と結果の到着順は保証されず、遅いコールバックは `call_tool` が返ったあともまだ実行中のことがあります。

### 試してみる {#try-it}

`client.py` を `server.py` の隣に置いて、実行してください。

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

サーバー側の `await ctx.report_progress(...)` はそれぞれ、クライアント側で順番どおりに `show` の 1 回の呼び出しになり、2 行とも `call_tool` が返る**前に**出力されました。進捗は結果にまとめられるのではなく、ツールがまだ動いている間にストリーミングされます。

!!! warning
    `progress_callback` は `Client` ではなく、**呼び出し**に属します。そのためのコンストラクター引数はありません。呼び出しごとに必要なコールバックが違うからです。ある呼び出しはダウンロードバーを動かし、次の呼び出しはログの 1 行を出します。

!!! check
    今度は `progress_callback=show` を削除して、もう一度実行してください。

    ```text
    {'result': 'Imported 2 records.'}
    ```

    エラーも警告もなく、結果は同じです。`report_progress` は、**呼び出し側が進捗を要求しなかったときは何もしません**。ですから無条件に報告すればよく、誰かが聞いているかどうかを気にする必要はありません。

## 全体量がわからないとき {#when-you-dont-know-the-total}

`total` は分母がわかっているときのためのものです。わからないことも多いでしょう。フィードを読み尽くしているとき、カーソルをたどっているとき、長さヘッダーのないものをダウンロードしているときなどです。

その場合は省略してください。

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

コールバックは `total=None` を受け取ります。クライアントはそれでも「活動中」であることは表示できます（「3 imported so far...」など）が、パーセンテージは表示できません。見栄えのよいバーのために全体量をでっち上げないでください。

!!! tip
    `progress` は特定の何かを数える必要はありません。バイト、行、ページ。ユーザーにとってわかりやすい単位を選び、守れる `total` だけを約束してください。

## まとめ {#recap}

* `Context` を受け取るツールならどこからでも `await ctx.report_progress(progress, total=None, message=None)` を呼べます。
* クライアントは `call_tool` に `progress_callback=` を渡します。呼び出しごとであり、`Client` には渡しません。
* コールバックは `async (progress, total, message) -> None` で、ツールがまだ実行中の間に呼ばれます。
* 呼び出しにコールバックがなければ、`report_progress` は何もしません。無条件に報告してください。
* わからないときは `total` を省略します。コールバックは `None` を受け取ります。

進捗は、実行中のツールが「ユーザー」に見せるものです。サーバーを運用する「自分」のために記録する行は、別のチャネルです。**[ロギング](logging.md)** を参照してください。
