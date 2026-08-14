---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# 拡張機能 {#extensions}

**拡張機能**とは、1 つの識別子の下にまとめられた、オプトイン式の MCP の振る舞い一式です。

サーバー側では、ツール、リソース、新しいリクエストメソッドを提供でき、`tools/call` をラップすることもできます。クライアント側では、追加の `tools/call` の結果形状を引き受け（claim）、ベンダー通知を監視できます。それぞれの側が自分の `capabilities.extensions` でアドバタイズし、求めなかった人にとっては何も変わりません。これが契約です（[SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)）。そして黄金律が 1 つあります。**拡張機能はデフォルトでオフです**。

## 拡張機能を使う {#using-an-extension}

構築時にインスタンスを渡します。

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

これで完了です。サーバーは `capabilities.extensions` の下で `io.modelcontextprotocol/ui` をアドバタイズし、拡張機能が提供するものをすべて配信するようになります。

`Apps` は組み込みのリファレンス拡張機能で、専用のページがあります。**[MCP Apps](apps.md)** を参照してください。

!!! note
    拡張機能は構築時に固定されます。後から呼び出す `add_extension` はありません。クライアントが接続している間、サーバーのケイパビリティマップは変わるべきではないからです。

ケイパビリティマップは `server/discover` に載って運ばれます。これは **2026-07-28** の経路です。レガシーの `initialize` ハンドシェイクにはこれを載せる場所がないため、レガシークライアントには拡張機能がそもそも見えません。それを前提に設計してください。拡張機能はサーバーを「補強する」ものであり、サーバーを使う唯一の手段になってはいけません。

## 独自の拡張機能を書く {#writing-your-own}

`Extension` をサブクラス化し、必要なものだけをオーバーライドします。どのメソッドにもデフォルトがあります。

### 識別子 {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

識別子は、仕様の `_meta` キーの文法に従った `vendor-prefix/name` 形式の文字列です。ドット区切りのラベル（それぞれ英字で始まり、英字または数字で終わる）、スラッシュ、そして名前が続きます。**クラスが定義された時点で**検証されるため、タイプミスがサーバーの起動まで放置されることはありません。

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

プレフィックスには自分が管理するドメインを使ってください。`io.modelcontextprotocol/*` は MCP プロジェクト自身が仕様化する拡張機能用です。

### ツールの提供 {#contributing-tools}

役に立つ最小の拡張機能は、ツール 1 つと設定マップ 1 つです。

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` は `ToolBinding` を返します。サーバーはそれぞれを、自分で `mcp.add_tool(...)` を呼んだ場合とまったく同じように登録します。スキーマ生成も、`Context` の注入も、何もかも同じです。
* `settings()` は `capabilities.extensions["com.example/stamps"]` にアドバタイズされる値です。設定なしで拡張機能をアドバタイズするには `{}`（デフォルト）を返してください。
* 拡張機能がサーバーを受け取ることはありません。提供するものをデータとして宣言し、`MCPServer` がそれを消費します。書き換えられる `self.server` はありません。

そして `main()` がその証明です。`mcp` に直接つなぐインメモリのクライアントです。

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### 独自メソッドの提供 {#serving-your-own-methods}

拡張機能は**新しいリクエストメソッド**を登録できます。仕様のメソッドと並んで配信される、独自の動詞（verb）です。

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` は `RequestParams` をサブクラス化しているため、2026 の `_meta` エンベロープが一様にパースされ、ハンドラーが受け取るのは検証済みのパラメーターであって、生の dict ではありません。クライアントが制御できる値には上限を設けてください。`Field(ge=1, le=100)` は、コードが何かを割り当てる前に、ばかげた `limit` を拒否します。
* `require_client_extension(ctx, EXTENSION_ID)` がゲートです。拡張機能を宣言しなかったクライアントには `-32021`（必須のクライアントケイパビリティの欠如）エラーが返り、仕様が求める機械可読な `requiredCapabilities` ペイロードが付きます。
* `protocol_versions=frozenset({"2026-07-28"})` はメソッドを通信路上の 1 つのバージョンに固定します。他のバージョンではクライアントは `METHOD_NOT_FOUND` を受け取ります。そのバージョンにメソッドが存在しないのとまったく同じです。そのクライアントにとっては、実際に存在しません。

メソッドは**厳密に追加のみ**です。SDK はこれを実行時ではなく構築時に強制します。

* 仕様で定義されたメソッド（`tools/list`、`completion/complete` など）に対する `MethodBinding` は、バインディングの構築時に `ValueError` を送出します。コアの動詞はサーバーのものです。
* 2 つの拡張機能が同じメソッドをバインドすると、2 つ目の登録時に送出されます。後勝ちはプラグイン同士が互いを壊す原因です。SDK はそうしません。
* 空の `protocol_versions` セットも送出します。決して配信できないメソッドはバグであって、設定ではありません。

### クライアント側 {#the-client-side}

同じファイルの `main()` に、クライアント側の話がすべて、その両半分とも入っています。

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` が拡張機能を宣言します。宣言は `ClientCapabilities.extensions` になります。2026-07-28 接続では、このマップはリクエストごとの `_meta` エンベロープで運ばれるため、サーバーは**すべての**リクエストでそれを見ます。レガシー接続では `initialize` ハンドシェイクに載ります。サーバーのコードはどちらでも気にしません。`require_client_extension(ctx, ...)` と `ctx.session.check_client_capability(...)` は、どちらの経路でも正しい情報源を読みます。
* ベンダーメソッドは 1 層下がって `client.session.send_request(...)` を使います。`Client` がファーストクラスのメソッドを増やすのは仕様の動詞に対してだけです。`send_request` はどんな `Request` サブクラスも受け付けるため、ベンダーリクエストはそのまま渡せます。

### `tools/call` のインターセプト {#intercepting-toolscall}

唯一の介入型フックです。ツール呼び出しを監視、短絡、または拒否するには `intercept_tool_call` をオーバーライドします。

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` は検証済みの `CallToolRequestParams` です。生の JSON に触れずに `params.name` と `params.arguments` が手に入ります。どのツール呼び出しが実行されるかを決めるのもこれです。書き換えたコンテキストを `call_next` に渡して変わるのは、ハンドラーが `ctx` 上で観測するものであり、ツールの呼び出しではありません。通信路レベルのリクエスト書き換えは[ミドルウェア](middleware.md)の仕事です。
* `call_next(ctx)` はチェーンの残りを実行し、ハンドラーの結果を返します。そのまま返す（監視）、別のものを返す（置換）、または `MCPError` を送出する（拒否）のいずれかです。何を返しても、2026 年世代の `serverInfo` アイデンティティスタンプを含め、ハンドラーの結果と同様にシリアライズされるため、短絡するインターセプターが匿名またはスキーマ外のレスポンスを生み出すことはありません。
* 複数の拡張機能がある場合、インターセプターは登録順にネストします。`extensions=[...]` の最初の拡張機能が最も外側です。
* デフォルトの実装は素通しで、拡張機能がこのフックを一切オーバーライドしないサーバーでは、素の `tools/call` ハンドラーがそのまま保たれます。使わないもののコストを払うことはありません。

このフックがラップするのは `tools/call` だけです。すべてのメッセージに関わる処理には[ミドルウェア](middleware.md)を使ってください。それがミドルウェアの役目です。

## クライアント拡張機能を使う {#using-a-client-extension}

**クライアント拡張機能**は、同じ契約を利用する側から見たものです。1 つの識別子の下にまとめられたクライアント側の振る舞い一式です。インスタンスを `Client(extensions=[...])` に渡し、通常どおりツールを呼び出します。

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` は、他のすべての呼び出しと同様にプレーンな `CallToolResult` を返します。拡張機能が変えたのは次の点です。サーバーは `buy` に対して、最終結果の代わりに `receipt` という**結果の形状**で答えられるようになり、`call_tool` が戻る前に `Receipts` がそれを完了させます（ここでは後続の呼び出しでレシートを引き換えます）。呼び出し側のコードは何も変わりません。

拡張機能を外せば、このどれも存在しません。サーバーのゲートは宣言しなかったクライアントを拒否し（エラー -32021）、ゲートを省いたサーバーから届いた引き受け対象の形状は検証に失敗します。認識できない `resultType` に対して仕様が求めるとおりです。通信路の両端で、デフォルトはオフです。

クライアント側の振る舞いを**一切持たない**識別子をアドバタイズするには（サーバーがケイパビリティでゲートし、クライアントは何もしない、上の検索クライアントのような場合）、`advertise()` を使います。

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## クライアント拡張機能を書く {#writing-a-client-extension}

`ClientExtension` をサブクラス化し、必要なものだけをオーバーライドします。提供できるものは 3 種類で、それぞれにデフォルトがあります。`settings()`、`claims()`、`notifications()` です。

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* 識別子はサーバー側と同じ文法に従い、クラスの定義時に検証されます。
* `claims()` は `ResultClaim` を返します。通信上のタグ、それをパースするモデル、それを完了させるリゾルバーの組です。モデルは `result_type: Literal["receipt"]` でタグを固定しなければならず、その動詞のコア結果型をサブクラス化してはいけません。どちらも引き受けの構築時に強制されます。`receipt_token` のようなベンダーフィールドはそのまま通信路を流れます。差し替えられた形状はそのままの形でクライアントに届きます。
* リゾルバーはパース済みのモデルと `ClaimContext` を受け取ります。`ctx.session` は `client.session` と同じ公開ハンドルなので、後続の処理は通常のセッション呼び出しです。戻り値はその動詞の通常の `CallToolResult` です。
* `settings()` は `ClientCapabilities.extensions[identifier]` にアドバタイズされる値で、`Client` の構築時に一度だけ読み取られます。

`notifications()` は、監視するベンダーのサーバー通知を宣言します。

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

ハンドラーは検証済みのパラメーターをディスパッチ順に 1 つずつ受け取ります。監視するだけで、拒否も返信もできません。

目立たないルールが 2 つあります。引き受けが有効なのは 2026-07-28 接続だけで、ケイパビリティのアドバタイズもそれに従います。レガシー接続では引き受けは消え、識別子も一緒にアドバタイズから外れるため、自分が拒否してしまう形状を持つ拡張機能をクライアントがアドバタイズすることはありません。また、リゾルバーではなく自分で引き受け対象の形状を受け取りたいときは、`client.session.call_tool(..., allow_claimed=True)` を呼び出してください。このフラグがないと、セッション層の呼び出し側に届いた引き受け対象の形状は `UnexpectedClaimedResult` を送出します。

### 拡張機能の動詞 {#extension-verbs}

拡張機能独自のリクエストメソッドには、クライアント側の登録は不要です。ベンダーリクエスト型は `mcp.types.Request` をサブクラス化し、[独自メソッドの提供](#serving-your-own-methods)と同様に `client.session.send_request` を通ります。追加が 1 つあります。パラメーターのキーを `Mcp-Name` ヘッダーに載せなければならない場合（tasks のような拡張機能の仕様では、その動詞にこれが必要です）、リクエスト型は `name_param` を宣言します。

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

セッションはどの送信経路でも `params["jobId"]` を `Mcp-Name` に反映し、値が欠けている場合は必須ヘッダーを黙って省くのではなく、はっきりとエラーになります。

## 拡張機能にできないこと {#what-an-extension-cannot-do}

提供できる範囲は意図的に**閉じて**います。サーバー側では、設定、ツール、リソース、メソッド、`tools/call` のインターセプター 1 つ。クライアント側では、設定、結果の引き受け、通知のバインディング。拡張機能には次のことができません。

* **ホストの内部に手を伸ばすこと。** データを宣言するだけで、サーバーやクライアントへの参照は持ちません。
* **コアの振る舞いを置き換えること。** 仕様のメソッドとコアの結果タグは構築時に拒否されます（`initialize` はランナーが完全に予約しています）。コアの語彙に隠れた通知バインディングは、代わりに警告を出して沈黙します。
* **後から登録すること。** `MCPServer(...)` や `Client(...)` が戻った後は、拡張機能の集合はそのまま確定です。

これらの壁と戦っているなら、書いているのは拡張機能ではありません。フォークです。壁こそが機能です。`extensions=[Apps(), Stamps()]` を読んだユーザーは、この 2 つが触れた可能性のあるものを「すべて」把握できます。
