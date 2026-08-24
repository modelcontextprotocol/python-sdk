---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# 非推奨の機能 {#deprecated-features}

2026-07-28 の仕様では、5 つのものが役目を終えます。SDK は今もその 5 つすべてを実装しており、そのすべてに**非推奨の警告**が付くようになりました。SDK のヘルパーが 1 つ、仕様とは別の理由で非推奨になっており、[ページの最後](#deprecated-sdk-helpers)に挙げています。

下の表は、非推奨になった機能それぞれについて、なくなる理由と、代わりに土台にすべきものを挙げています。

## 非推奨になるもの {#what-is-deprecated}

| 非推奨 | 理由 | 代わりにすること |
|---|---|---|
| **ルート（roots）**：`ctx.session.list_roots()`、`client.send_roots_list_changed()`、`Client(...)` に渡す `list_roots_callback=` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) がこのケイパビリティを非推奨にします。 | パスを通常のツール引数やリソース URI として受け取るか、`InputRequiredResult` に `ListRootsRequest` を埋め込みます（**[マルチラウンドトリップ（multi-round-trip）リクエスト](handlers/multi-round-trip.md)** を参照）。 |
| **サーバー起点のサンプリング**：`ctx.session.create_message()`、`Client(...)` に渡す `sampling_callback=` | SEP-2577 がこのケイパビリティを非推奨にします。 | `InputRequiredResult` を返し、クライアントに呼び出しを再試行させます（**[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)** を参照）。 |
| **プロトコルのロギング**：`ctx.log()`、`ctx.debug()`、`ctx.info()`、`ctx.warning()`、`ctx.error()`、`ctx.session.send_log_message()`、`client.set_logging_level()` | SEP-2577 がこのケイパビリティを非推奨にします。プロトコル内でこれに代わるものはありません。 | stderr へ出力する通常の `import logging`（**[ロギング](handlers/logging.md)** を参照）。 |
| **`ping`**：`client.send_ping()` | 単なる非推奨ではなく、プロトコルから**削除**されました。2026-07-28 には `ping` メソッドがありません。 | 何もありません。`mode="legacy"` の接続に対してしか動作しません。 |
| **クライアントからサーバーへの進捗**：`client.send_progress_notification()` | 2026-07-28 では、進捗はサーバーからクライアントへの方向だけになります。 | 送るものはありません。進捗はサーバー側が `ctx.report_progress()` で報告します（**[進捗](handlers/progress.md)** を参照）。 |

この表から 3 つのことがわかります。

* ルート、サンプリング、ロギングはひとまとまりです。**SEP-2577** という 1 つの提案が、3 つのケイパビリティを一度にすべて非推奨にしています。
* サンプリングとルートには、より根深い共通の問題があります。どちらも**サーバー**が**クライアント**に**リクエスト**を送る場面だという点です。2026-07-28 が **[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)** で置き換えるのは、まさにこの方向の通信全体です。なくなるのは単独の RPC メソッド（`sampling/createMessage`、`roots/list`、プッシュ型の `elicitation/create`）です。`CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` というペイロード型は `InputRequiredResult.input_requests` に埋め込まれる形で残り、クライアント側ではこれまでと同じコールバックに届きます。
* `ping` だけは毛色が違います。プロトコルはこれを非推奨にするのではなく、削除します。SDK のメソッドは依然として警告を出し（メッセージは「deprecated」ではなく「removed」と述べます）、現行仕様の接続で呼び出すと「Method not found」が返ります。

## 非推奨は勧告にすぎない {#deprecated-is-advisory}

今日の時点で壊れるものはありません。

上に挙げたメソッドはすべて、**2025-11-25 以前**で交渉されたセッションに対しては引き続き動作します。クライアントで `mode="legacy"` を固定すれば、2026 年より前とまったく同じ挙動になります。通信上の変更はなく、ケイパビリティの交渉も変わりません。

変わるのは、それぞれが最初に実行されたときに、目に見える警告が出る点です。

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` は `UserWarning` のサブクラスであり、`DeprecationWarning` のサブクラス**ではありません**。これは意図的なものです。Python のデフォルトのフィルターは、`__main__` として直接実行されるコードでしか `DeprecationWarning` を表示しません。ライブラリが何かを非推奨にしても 2 年間誰も気づかない、というのはこの仕組みのせいです。この警告は `-W` フラグなしで、どこでも表示されます。

!!! warning
    「勧告にすぎない」のは通信路の手前までです。サンプリングとルートはサーバーからクライアントへの「リクエスト」であり、2026-07-28 のセッションにはそれを運ぶチャネルがありません。現行仕様の接続のツール内で `ctx.session.create_message()` を呼び出すと、警告はやはり出ますが、そのあと送信がエラーで失敗します。

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    シグナルは 2 つ、この順番です。`MCPDeprecationWarning` は、どの接続でもメソッドを呼び出した瞬間に発生します。エラーは、そのあと SDK が送信を試みたときに返ってくるものです。この 2 つの機能がエンドツーエンドで動作するのは、対応するコールバックをクライアントが登録した `mode="legacy"` の接続だけです。

## レガシーセッションでの `ping` {#ping-on-a-legacy-session}

**ping** は、相手がまだ応答しているかを確かめるために、どちらの側からでも送れる空のリクエストです。2026-07-28 の仕様はこれを削除します（[SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)）。現行仕様のクライアントが送るリクエストはどれも、それ自体がサーバーの存在を証明していますし、現行仕様のサーバーには ping を送るチャネルがありません。SDK の 2 つのメソッドはどちらも、ハンドシェイク世代のセッションでは引き続き動作します。クライアント側からは次のように書きます。

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

サーバー側からは、任意のハンドラーの中で次のように書きます。

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` は呼び出しのたびに `MCPDeprecationWarning` で警告します。デフォルト（`2026-07-28`）の接続では、サーバーは代わりに `MCPError: Method not found` と応答します。
* `ctx.session.send_ping()` には警告がありません。現行仕様の接続では、ほかのサーバー起点のリクエストと同じく、バックチャネル（back-channel）がないというエラーを送出します。
* どちらの側も、ping に応答するために何かを登録する必要はありません。

## ルートの変更通知 {#roots-change-notifications}

ルートのケイパビリティを宣言した 2025 年世代のクライアントは、`notifications/roots/list_changed` を送ることで、ワークスペースのフォルダーが変わったことをサーバーに伝えられます。サーバーはそれを受けて `roots/list` をもう一度リクエストします。2026-07-28 の仕様は、プッシュ型のルートのフローの残りとともに、この通知を削除します。クライアント側では、`list_roots_callback=` を渡すこと（**[クライアントのコールバック](client/callbacks.md)**）が `"roots": {"listChanged": true}` の宣言にあたり、1 回の呼び出しでその約束を果たします。

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

サーバー側では、低レベルの `Server` が受信側のハンドラーを受け取ります。

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` は `list_roots_callback` が返すリストです。`client.send_roots_list_changed()` は警告を出し、`mode="legacy"` のクライアントが必要です。現行仕様の接続では、通知は黙って捨てられます。サーバーからの後続の `roots/list` は同じセッションに届くので、呼び出したあともセッションは開いたままにしてください。
* `MCPServer` にはこの通知のフックがありません。低レベルの `Server` では `on_roots_list_changed=` がハンドラーを登録します（これも非推奨で、構築時に警告を出します）。通知はペイロードを運ばないので、ハンドラーは `ctx.session.list_roots()` を呼んで新しいリストを取得します。

## 警告を抑止する {#silencing-the-warning}

新しいコードでは、しないでください。

ただし、保守しているサーバーが実際に 2026 年より前のクライアントを相手にしているなら、ログを静かに保つ正当な理由があります。最初の非推奨の呼び出しが実行される前に、このカテゴリをフィルターしてください。

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

API はこれだけです。メソッドごとのスイッチはありませんし、必要もありません。カテゴリが 1 つである利点は、1 行で黙らせ、1 行で元に戻せることです。

!!! check
    フィルターを逆向きにかければ、無料で回帰テストが手に入ります。pytest の設定の `filterwarnings` に `"error::mcp.MCPDeprecationWarning"` を追加すると、非推奨の呼び出しは警告ではなく**例外を送出**します。まだ `ctx.info()` を呼んでいる `old_log` という名前のツールは通らなくなります。呼び出しは `is_error=True` と `Error executing tool old_log` を伴って返り、キャプチャされたサーバーのログが原因を名指しします。

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    pytest の設定を 1 行足すだけで、非推奨の呼び出しがテストを失敗させずにコードベースへ紛れ込むことは二度とありません。

## 非推奨の SDK ヘルパー {#deprecated-sdk-helpers}

これらは仕様の変更ではなく、よりよい代替がある SDK の内部実装にすぎません。同じ `MCPDeprecationWarning` で警告し、3.0 で削除されます。

| 非推奨 | 代わりにすること |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` を呼んでから `FuncMetadata.call_fn()` を呼びます。これを呼んでいたのは、`FuncMetadata` を直接扱うコード（たとえば独自の `Tool` サブクラス）だけです。 |

## まとめ {#recap}

* 2026-07-28 の仕様は、**ルート**、サーバー起点の**サンプリング**、プロトコルの**ロギング**を非推奨にし（いずれも [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)）、**進捗**をサーバーからクライアントへの方向に限定し、**`ping`** を削除します。
* 「代わりにすること」の列が次の行き先を示しています。サンプリングとルートには **[マルチラウンドトリップリクエスト](handlers/multi-round-trip.md)**、ロギングには **[ロギング](handlers/logging.md)**、進捗には **[進捗](handlers/progress.md)** です。`ping` には何も必要ありません。
* 非推奨は勧告にすぎません。通信上の変更はなく、2026 年より前のセッションに対してはすべてが引き続き動作します。そして目に見える `MCPDeprecationWarning` が出ます（`UserWarning` なので、デフォルトで有効です）。
* サンプリングとルートにはさらに、2026-07-28 のセッションにはないバックチャネルが必要です。現行仕様の接続では警告を出し、そのあと例外を送出します。
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` でカテゴリ全体を黙らせます。pytest で `"error::mcp.MCPDeprecationWarning"` を指定すれば、テストの失敗に変わります。
* SDK のヘルパー `FuncMetadata.call_fn_with_arg_validation()` は、これとは別に非推奨になっており、3.0 で削除されます。
* 新しいコードは、これらのどれの上にも築くべきではありません。

このドキュメントのほかのページはすべて、現行の API を扱っています。
