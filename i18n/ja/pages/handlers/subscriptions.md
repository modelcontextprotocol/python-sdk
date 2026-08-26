---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# サブスクリプション {#subscriptions}

サーバーのカタログは固定ではありません。ツールは実行時に現れますし、リソース URI の背後にある内容も変わります。

クライアントがそれを知る手段が**サブスクリプション**です。クライアントは `subscriptions/listen` リクエストを 1 つ送り、そのリクエストへのレスポンス自体がストリームになります。開いたままになり、クライアントが求めた変更通知を運びます。

## ツールから発行する {#publish-it-from-the-tool}

サーバー側でやることは 1 行だけです。変更を発行します。

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` は、その URI をサブスクライブした開いているストリームすべてに届きます。それ以外には届きません。
* `await ctx.notify_tools_changed()` は、ツール一覧の変更を求めたストリームすべてに届きます。これを受け取ったクライアントは `tools/list` をもう一度呼び出し、今度は `sprint_report` が見えます。
* 兄弟にあたるのが `notify_prompts_changed()` と `notify_resources_changed()` です。
* サブスクライバーがいなければ、何も起こりません。アイドル状態のサーバーへの発行は no-op なので、誰かが聞いているかどうかを確認することはありません。何が変わったかを述べるだけです。

`MCPServer` は `subscriptions/listen` を代わりに処理します。通信上の義務（最初のフレームとしての確認応答、ストリームごとのフィルタリング、全フレームへのサブスクリプション ID の付与）は SDK の仕事です。

!!! check
    実際の通信では、フィルターに `board://sprint` を指定したストリームは、`complete_task` の実行後に次のようになります。

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    更新が運んでいないものに注目してください。ボードそのものです。どのフレームも `_meta` の下に listen リクエストの JSON-RPC id を持ち、その id がサブスクリプション ID です。これを発番するのはクライアントです。Python の `Client` は `"listen-1"` のような文字列を使いますが、他のクライアントは整数を使うこともあります。

## 求められたものだけ {#only-what-was-asked-for}

フィルターは契約です。ツール一覧の変更と 1 つのリソース URI を要求したストリームは、その 2 種類だけを受け取り、他は何も受け取りません。プロンプトの変更を発行しても、そのストリームは沈黙したままです。

`MCPServer` はリソース URI を文字列として完全一致で照合するので、`board://sprint` を指定したストリームには `board://sprint/tasks/1` のことは何も届きません。仕様では、サブスクライブされた URI のサブリソースの変更をサーバーが報告することを認めています。`MCPServer` がそうすることはありませんが、クライアントはそれを想定して作られています。

このストリームには、当てはまらないことが 2 つあります。

* **リプレイログではありません。** 切断されたストリームは失われ、誰も接続していない間に発行されたイベントはキューに入りません。クライアントは listen し直して再取得します。
* **2025 年世代の経路ではありません。** `resources/subscribe` を呼び出したクライアントには `ctx.session.send_resource_updated(uri)` で届けます。`notify_*` メソッドが届くのは `subscriptions/listen` のストリームだけです。

## 誰が監視できるかを決める {#deciding-who-may-watch}

デフォルトでは、要求された種類と URI はすべて受け入れられます。つまり、どの呼び出し側も、発行されるどの URI でも監視できます。読み取りハンドラーが参照されることはありません。誰も読み取っていないからです。`files://{name}` ハンドラーなら拒否するはずの呼び出し側でも、`files://payroll.csv` のストリームを開き、それが変わったこと、そしていつ変わったかを知ることができます。内容を知ることは決してありませんし、何が存在するかを探ることもできません。未知の URI も受け入れられ、単に一度も発火しないだけだからです。狭いとはいえ現実に存在する隙なので、マルチテナントのサーバーからユーザーごとの URI を発行する前にゲートを設けてください。

ゲートはミドルウェアです。SDK が確認応答する前に `subscriptions/listen` リクエストを見て、呼び出し側が読み取れないものを求めたときに拒否します。

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` は生のリクエストなので、ミドルウェアは自分でそれを `SubscriptionsListenRequestParams` として検証し、クライアントが求めたフィルターを読み取ります。
* 拒否は `call_next(ctx)` の前に `MCPError` を送出することで行います。クライアントはそのエラーを受け取り、ストリームは得られず、接続はそのまま続きます。メッセージは URI を挙げない一様なものにして、拒否によってどの URI が保護されているかが確認されることのないようにしてください。
* 1 つの `can_access(user, uri)` が両方の問いに答えます。リソースハンドラーは `resources/read` でそれを問い合わせ、ミドルウェアは `subscriptions/listen` で問い合わせます。テーブルをデータベースや RBAC システムに置き換えても、両者の足並みはそろったままです。
* 判定はストリームの寿命のあいだ有効です。イベントごとの再チェックはないので、呼び出し側のアクセス権がストリームの途中で失効しうる場合（期限切れになるトークンなど）は、失効した時点でその呼び出し側の接続を終了してください。

ミドルウェアの契約の全体は、他に何をラップするか、なぜ暫定扱いなのかも含めて、**[ミドルウェア](../advanced/middleware.md)** にあります。

## クライアント側 {#the-client-end}

そのストリームの反対側で、ボードを追いかけるクライアントがこちらです。

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

`client.listen(...)` に入るとリクエストが送られ、サーバーの確認応答を待つので、ブロックが始まる時点でストリームは生きています。型付きのイベントはどれも再取得の合図であって、ペイロードではありません。契約の全体が 1 画面に収まっています。クライアント側のそれ以外のことは専用のページにあります。メインのフローと並行しての監視、ストリームの終了、listen のやり直しです。「クライアント」の下の **[サブスクリプション](../client/subscriptions.md)** を参照してください。

## 1 プロセスを超えてスケールする {#scaling-past-one-process}

発行はハンドラーから開いているストリームへ、`SubscriptionBus` を経由して伝わります。デフォルトはインメモリで、1 つのプロセスとその中のすべてのストリームです。ロードバランサーの背後でレプリカを動かすまでは、これが正解です。レプリカを動かすと、クライアントのストリームは 1 つのレプリカに固定され、別のレプリカでの発行がそこに届かなければならないからです。

その継ぎ目は自分で実装します。pub/sub バックエンドの上に 2 つのメソッドを載せるだけです。

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` は自分で用意します。各レプリカで到着したメッセージをデコードし、登録されたすべてのリスナーを呼び出すリーダータスクも同様です。リスナーは同期的で、例外を送出してはならず、サーバーのイベントループ上で動きます。

バスが運ぶのは型付きの `ServerEvent` 値（小さなデータクラスが 4 つ）であって、JSON-RPC ではありません。ID の付与、フィルタリング、ストリームのライフサイクルは SDK に残るので、バスの実装がプロトコルを壊すことはできません。できるのはプロセス間でイベントを移動させることだけです。

リクエストの外から発行するには、参照を手元に持てるようにバスを自分で組み立てます。何も渡さないと `MCPServer` は内部で 1 つ作りますが、それを公開しません。

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## 低レベルでの組み立て {#the-low-level-composition}

低レベルの `Server` には、あらかじめ配線されたものは何もありません。同じ部品を 3 行で組み立てます。

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* バスは自分のものなので、直接そこへ発行します。`await bus.publish(ResourceUpdated(uri=...))` です。ハンドラーから届く場所に置いてください。ここではモジュールスコープ、大きなアプリではライフスパンです。
* `ListenHandler(bus)` は `MCPServer` が登録するのと同じハンドラーで、`on_subscriptions_listen=` は普通のハンドラースロットです。別のセマンティクスが欲しければそのスロットに独自の callable を入れてください。その場合、仕様上の義務は自分に移ります。まず確認応答し、すべてのフレームにサブスクリプション ID を付与し、フィルター外のものは何も配信しないことです。
* `ListenHandler.close()` は開いているすべてのストリームを正常に終了させます。各ストリームは最後のフレームとして listen リクエストの result を受け取ります。これは、サーバーが意図的にサブスクリプションを終了したことを示す仕様上の方法です。ストリームのフラッシュが終わる前に戻るので、トランスポートを破棄する前に少し待ってください。これを呼ばなければ、ストリームはクライアントが切断したときに終わります。

## まとめ {#recap}

* クライアントは `subscriptions/listen` リクエスト 1 つでオプトインし、そのレスポンスがストリームです。それを処理する機能は組み込まれています。
* 発行は `ctx.notify_*` で行い、ID の付与、フィルタリング、ライフサイクルの処理は SDK が担当します。
* イベントは合図であって、ペイロードではありません。両端とも再取得します。
* クライアント側は `async with client.listen(...)` です。詳しくは「クライアント」の下の **[サブスクリプション](../client/subscriptions.md)** を参照してください。
* 低レベルの `Server` では同じ部品を自分で組み立てます。バス、`ListenHandler(bus)`、`on_subscriptions_listen` スロットです。
* スケールアウトとは、`SubscriptionBus`（メソッド 2 つ）を実装し、`MCPServer(subscriptions=...)` として渡すことです。

これらすべてを処理するサーバーを、レプリカ 1 つでも 20 でも動かす方法は、**[デプロイとスケール](../run/deploy.md)** にあります。
