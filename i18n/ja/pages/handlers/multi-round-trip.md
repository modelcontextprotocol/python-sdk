---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# マルチラウンドトリップ（multi-round-trip）リクエスト {#multi-round-trip-requests}

ツールが 1 回のラウンドトリップでは完了できないことがあります。選択、確認、認証情報など、ユーザーだけが持っているものが必要になる場合です。

2026-07-28 より前は、サーバーは**呼び返す**ことでそれを手に入れていました。つまり、元のリクエストを処理している途中で、エリシテーション（elicitation）やサンプリング呼び出しといった自分のリクエストをクライアントに向けて開いていました。2026-07-28 の仕様は、このバックチャネル（back-channel）を廃止します。

代わりに、サーバーは**返します**。

## 呼び返さずに返す {#return-dont-call-back}

サーバーは `tools/call` に対して、`CallToolResult` の代わりに **`InputRequiredResult`** で応答します。仕事をするのはそのうち 2 つのフィールドです。

* **`input_requests`**：サーバーがまだ必要としているもの。サーバーが選んだ名前をキーとする dict です。各値は `ElicitRequest`、`CreateMessageRequest`、`ListRootsRequest` のいずれかです。
* **`request_state`**：不透明なトークン。クライアントはリトライ時にこれをそのまま送り返します。これを読むのはサーバーだけです。

クライアントはそれぞれのリクエストに応えたうえで、**同じツールをもう一度**呼び出します。このとき回答を `input_responses` に、トークンを `request_state` に載せます。サーバーは足りなかったものを手に入れ、通常の `CallToolResult` を返します。

プロトコルはこれだけです。どの区間もクライアントからサーバーへの普通のリクエストです。逆向きに流れるものは一切ありません。

## サーバー側 {#the-server-side}

`@mcp.tool()` では、これを手で組み立てることはめったにありません。ユーザーに尋ねる依存関係（`Elicit`）、クライアントの LLM をサンプリングする依存関係（`Sample`）、クライアントのルート（roots）を一覧する依存関係（`ListRoots`）のいずれかを宣言すれば、SDK が `InputRequiredResult` を返してくれます。その形式は **[依存関係](dependencies.md)** のページで扱います。2 つの形式は混在できません。1 回の呼び出しには `input_responses`/`request_state` のチャネルが 1 つしかないため、`Resolve(...)` パラメーターを使うツールは、本体から `InputRequiredResult` を返すこともできません。`InputRequiredResult` を戻り値として宣言すると登録時に拒否され（`InvalidSignature`）、宣言せずに返すと実行時に呼び出しが失敗します。手動の形式は**低レベル**の `Server` で、その `on_call_tool` ハンドラーはどちらの結果型を返してもかまいません。

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` の型は `-> CallToolResult | InputRequiredResult` です。2 つ目を返すこと、それがサーバー側の API のすべてです。
* 最初の呼び出しでは `params.input_responses` が `None` なので、ガードが働き、ハンドラーは答える代わりに尋ねます。
* リトライ時には、クライアントが送った `ElicitResult` が、サーバーが `input_requests` で使ったのと**同じキー**（`"region"`）の下に入っています。

そのファイルの残り（明示的な `input_schema`、手組みの `CallToolResult`）は普通の低レベル `Server` で、**[低レベル Server](../advanced/low-level-server.md)** で扱っています。このページが付け加えるのは 2 つ目の戻り値の型だけです。

## ツール以外 {#beyond-tools}

`tools/call` は特別ではありません。2026-07-28 では、サーバーは `prompts/get` と `resources/read` にも同じように応答できます。`MCPServer` では、`@mcp.prompt()` 関数、または `@mcp.resource()` の**テンプレート**関数が、自分で `InputRequiredResult` を返し、リトライ時の回答をコンテキストから読み取ります。

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* 1 回目は `InputRequiredResult` を返します。リトライ時には `ctx.input_responses` が同じキーの下に回答を保持しており、関数は通常の結果を返します。ここではプロンプトメッセージ、テンプレートリソースならリソースの内容です。
* 設定した `request_state` は、サーバー上の他のものと同じく、通信路に出る前に封印され、送り返されたときに検証されます。封印で何が得られるか、いつキーの設定が必要かは、下の **[`requestState` の保護](#protecting-requeststate)** で扱います。
* `@mcp.tool()` 関数も、依存関係の形式が合わない場合は、同じように結果を直接返せます。
* 静的な `@mcp.resource()` 関数は参加しません。`Context` を受け取らないので、リトライを読み取りようがないからです。尋ねられるのはテンプレートリソースだけです。
* 下の世代のルールはそのまま適用されます。2026 より前のセッションで `InputRequiredResult` を返すと、警告で説明しているのと同じ `-32603` になります。

## クライアント側 {#the-client-side}

`Client` がループを回してくれます。

サーバーが求める可能性のあるコールバック（`elicitation_callback`、`sampling_callback`、`list_roots_callback`）を登録し、ツールを呼び出します。`InputRequiredResult` が届くと、`Client` は `input_requests` の各エントリーを対応するコールバックに振り分け、回答とエコーバックした `request_state` を付けてリトライし、`CallToolResult` が返ってくるまで続けます。

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* この `elicitation_callback` は、2026 より前のサーバーのバックチャネル `elicitation/create` が呼び出していたはずのものと同じです。`sampling/createMessage` に対する `sampling_callback`、`roots/list` に対する `list_roots_callback` も同様です。2026-07-28 では単独のサーバー→クライアント RPC はなくなりましたが、まったく同じ `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` のペイロードが `input_requests` の中に載り、同じ 3 つのコールバックに振り分けられます。1 組のコールバックで両方の世代に対応できます。
* `call_tool` は素の `CallToolResult` を返します。途中のラウンドは呼び出し側からは見えません。
* `get_prompt` と `read_resource` も同じループを回します。

!!! check
    コールバックを付けないままにすると、ループは 1 回目で失敗します。SDK の代役のコールバックはすべてのエリシテーションにエラーで答え、`call_tool` は *"Elicitation not supported"* というメッセージの `MCPError` を送出します。

ループには上限があります。`Client(..., input_required_max_rounds=10)` がデフォルトの上限で、それを超えて `InputRequiredResult` を返し続けるサーバーに対しては `call_tool` が例外を送出します。あるラウンドが `request_state` だけを載せていて `input_requests` がない場合、`Client` はリトライの前に短くスリープします（50ms から倍々に増えて上限 250ms）。そのため、単に「まだ終わっていない」と言っているだけのサーバーをビジーポーリングすることはありません。

### ループを自分で回す {#driving-the-loop-yourself}

自動ループは単一プロセスのクライアントには十分です。次のような場合は、代わりに自分でループを握ってください。

* クライアントが**分散**している場合。ユーザーに質問を表示するプロセスが `call_tool` を呼んだプロセスではなく、別のワーカーがリトライを発行します。`request_state` はその境界を越えて自分のストレージ経由で持ち運べる永続化可能なトークンであり、`input_responses` は向こう側がそれと一緒に送り返すものです。
* 各ラウンドを**検査**したい場合。すべての `input_requests` エントリーを記録・監査する、特定の種類のリクエストを拒否する、区間の間に独自のバックオフを適用する、などです。
* ラウンド数ではなく**実時間**で上限をかけたい場合。`input_required_max_rounds` に頼る代わりに、自分のループを `anyio.fail_after(...)` で包みます。

下層のセッションに降りると、`allow_input_required=True` がユニオン型をそのまま渡してくれます。

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` は戻り値の型を `CallToolResult | InputRequiredResult` に広げます。それを絞り直すのが `isinstance` です。
* `request_state` はこれで自分の手の中にあります。区間の間で書き留めておけば、新しいプロセスから会話を再開できます。
* `input_requests` の各エントリーについて、`input_responses` の**同じキー**の下に `InputResponse` を置きます。`fulfil` が UI の入る場所です。この例では回答をハードコードしています。
* どの区間でも、ツール名も `arguments` も同じです。リトライは元の呼び出しをもう一度実行するものであり、新しいメソッドではありません。

## `requestState` の保護 {#protecting-requeststate}

ここまでは `request_state` をエコーとして扱ってきましたし、通信上はまさにそれだけのものです。しかしクライアントは区間の間それを保持します（プロセスをまたいで書き留めることは、まさに前のセクションが認めたことです）。そのため、戻ってくるものは**クライアントが供給する入力**です。改変されているかもしれず、期限切れかもしれず、まったく別の呼び出しから抜き取られたものかもしれません。仕様はサーバーに対し、この状態が認可、リソースアクセス、ビジネスロジックに影響しうる場合は常に、状態の完全性を保護し、検証に失敗したラウンドを拒否することを要求しています。

`MCPServer` はデフォルトでこれを保護します。どのサーバーも、送り出す `requestState` を封印し、すべてのエコーを検証します。リゾルバーの状態も手組みの状態も同様で、プロセス起動時に生成されたキーを使います。設定するものは何もなく、平文を書き、平文を読みます。通信路に載るのは不透明な暗号化トークンだけです。

デフォルトのキーはプロセスとともに生まれて消えます。単一プロセスを超えてデプロイする前に、これだけは知っておく必要があります。

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **デフォルト（設定なし）**は単一プロセスに向いています。stdio、または HTTP ワーカーがちょうど 1 つの場合です。別のワーカー、ロードバランサーの背後の別インスタンス、再起動後の同じサーバーに届いたリトライは、そのプロセスが持っていないキーで封印されています。クライアントは下記の固定の拒否を受け取り、フローを最初からやり直さなければなりません。
* **`keys=[...]`** は、リトライが**別のインスタンス**に届く可能性がある場合（マルチワーカーの `uvicorn`、ロードバランスされた HTTP）や、再起動をまたいで生き残る必要がある場合に必須です。どのインスタンスも、兄弟インスタンスが発行したものを検証できます。仕組みは同じで、生成されたものの代わりに自分のシークレットを使うだけです。
* KMS や既存のトークンサービスなど独自の暗号を使うなら、`keys` の代わりに `RequestStateSecurity(codec=...)` を渡します。その契約は下の **[独自の暗号を持ち込む](#bring-your-own-crypto)** で扱います。

### 封印が運ぶもの {#what-the-seal-carries}

デフォルトでも設定済みでも、通信路上の `requestState` は暗号化され認証されたトークンです。自分のコードがそれを目にすることはありません。ハンドラーとリゾルバーは平文を書き、平文を読みます（`ctx.request_state`）。SDK が送り出すときに封印し、受け取るときに検証します。完全性に加え、各トークンは次のものに束縛されます。

* **時間枠。** ラウンドごとに新しい有効期限で封印し直すため、`RequestStateSecurity(ttl=...)`（デフォルト 600 秒）が制限するのはフロー全体ではなく、ラウンドごとの考慮時間です。
* **認証されたプリンシパル。** SDK が検証した OAuth アクセストークンをリクエストが載せている場合、状態はトークンのクライアント、発行者、サブジェクトに束縛されます。あるユーザー向けに発行された状態は、両者が 1 つの OAuth クライアントを共有していても、別のユーザーの下では失敗します。サブジェクトを供給しないベリファイアーは、束縛をクライアントの識別情報だけに弱めます。URL ベースのクライアント ID の下では、それはそのクライアントソフトウェアのすべてのユーザーで共有されます。認証が SDK の外（前段のプロキシ）で終端されている場合や、トランスポートが認証なしの場合は、束縛するプリンシパルがないためこのチェックは働きません。`RequestStateSecurity(bind_principal=...)` で独自のアイデンティティシグナルから供給すれば別です。トークンベリファイアーがどの要素を供給するにせよ、一貫して供給しなければなりません。あるリクエストではサブジェクトを含め、別のリクエストでは省くベリファイアーは、フローの途中でプリンシパルを変えてしまい、進行中のラウンドは拒否されます。
* **元のリクエスト。** メソッド、ツール名またはプロンプト名（あるいはリソース URI）、そして引数のダイジェストです。別のツール、別の引数、別のメソッドに対してリプレイされたトークンは失敗します。
* **尋ねた質問そのもの。** リゾルバーの回答はすべて、クライアントに表示されたレンダリング済みの質問に固定されます。最初に届いたラウンドでも、記録済みの回答を後で再利用するときでも同じです。メッセージの文言を変えたりスキーマを変えたりして再デプロイすると、サーバーは古い回答を消費する代わりに尋ね直します。同じ固定は逆向きにも効きます。メッセージは呼び出しごとのデータではなく、ツールの引数から導出してください。タイムスタンプやライブのレートから組み立てたメッセージはラウンドごとにレンダリングが変わるため、記録済みの回答はどれも古く見え、クライアントのラウンド上限で呼び出しが終わるまでサーバーは尋ね直し続けます。

これらはすべて SDK の仕事であり、自分の仕事ではありません。独自のコーデックを持ち込んでも、コーデックの仕事ではありません。

### キーのローテーション {#rotating-keys}

`keys[0]` が新しい状態を封印し、リスト内のすべてのキーが検証に使われます。ダウンタイムなしのローテーションは 3 段階で、各段階を完全にロールアウトしてから次に進みます。

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

発行側を先に昇格させないでください。まだ検証できないインスタンスがあるキーで発行すると、ロールアウトの途中で進行中のラウンドが落ちます。

キーのスコープは 1 つのサービスです。封印されたエンベロープはサーバーの名前もオーディエンスクレームとして載せているため、たまたまシークレットを共有している別のサービスが発行したトークンは、いずれにせよ拒否されます。このクレームの識別力は名前次第なので、明示的なポリシーを与えられたサーバーは本物の名前を持つか、`RequestStateSecurity(audience=...)` を設定しなければなりません。名前のないサーバーは構築時に例外を送出します。`audience=` は、あるサービスが別のサービスの発行した状態を受け入れなければならない、意図的なマルチサービス構成にも使えます。（設定なしのデフォルトは対象外です。そのキーはプロセスの外に出ることがないので、オーディエンスクレームが付け加えるものはありません。）

### 独自の暗号を持ち込む {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` は、`seal(bytes) -> str` と `unseal(str) -> bytes` を持ち、自分が発行していないトークンに対しては `InvalidRequestState` を送出するものなら何でも受け取ります。典型的な形は KMS に対するエンベロープ暗号化で、起動時にデータキーを一度アンラップし、トークンごとの暗号処理はローカルに保ちます。

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL、プリンシパルの束縛、リクエストの束縛はコーデックの仕事**ではありません**。SDK はどのコーデックについても、`seal` の前にそれらをペイロードに刻み込み、`unseal` の後で再検証します。コーデックの義務は完全性（改ざんされていれば送出する）と、理想的には機密性だけです。

### 検証に失敗したとき {#when-verification-fails}

受信側の失敗はすべて、改ざん、期限切れ、別のリクエストやプリンシパルに対するリプレイ、このサーバーが知らないキーでの封印のいずれであっても、同じ答えを受け取ります。

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

どの原因にも固定のメッセージが 1 つなので、どのチェックが失敗したかが通信上に漏れることはありません。本当の理由はサーバーのログに出ます。`tools/call`、`prompts/get`、`resources/read` に届く `requestState` はすべてチェックされ、状態を発行しないハンドラー宛てに届いたものも含まれます。実際に最も多い拒否は攻撃者ではありません。デフォルトのプロセスローカルなキーが、再起動前や別インスタンスからのリトライと出会うケースです。クライアントはフローをやり直し、それが問題になる場合の対策が `keys=[...]` です。

### 手組みの状態 {#hand-built-state}

自分で設定する `request_state`（ツール、プロンプト、リソーステンプレートの関数から `InputRequiredResult` を返す場合）は、リゾルバーの状態と同じ仕組みで封印・検証され、コードの変更は一切不要です。平文を書き、平文を読むだけで、上記のすべての束縛が適用されます。

設定済みであっても SDK が代わりに固定できない唯一のものは、質問の同一性です。状態の中にある回答が、こちらで定義したどの質問に属するのかを SDK は知りません。質問をキーにして回答を保存するなら、独自の質問識別子を状態に含め、リトライ時にそれをチェックしてください。

低レベルの `Server` は何も付いてこない層です。`MCPServer` と違い、自分で境界を追加するまで何も封印されず、それまでは `request_state` が書いたとおりに通信路を渡ります。1 行のオプトインは **[低レベル Server](../advanced/low-level-server.md#the-other-handlers)** に示しています。

## 2026-07-28 の結果型 {#a-2026-07-28-result}

`InputRequiredResult` はプロトコルバージョン **2026-07-28** にしか存在しません。インメモリの `Client(server)` はそれを代わりにネゴシエートしてくれます。通信路越しでは `mode="auto"` がそれを検出します。接続後、`client.protocol_version` で何が得られたかが分かります。

!!! warning
    2026 より前のセッションには `InputRequiredResult` を入れる場所がありません。`mode="legacy"` の接続でハンドラーからこれを返すと、ランナーはネゴシエートされたバージョンにシリアライズできず、クライアントには `-32603` *"Handler returned an invalid result"* エラーが返ります。両方の世代に対応するサーバーは、これを使う前に `ctx.protocol_version` をチェックしなければなりません。

!!! info
    **URL モードのエリシテーション**は、2026 の接続ではまさにこの仕組みに載ります。`input_requests` のエントリーは、params が `ElicitRequestURLParams` である `ElicitRequest` です。ユーザーが帯域外のフローを終えると、クライアントが呼び出しをリトライします。同じループで、新しい API はありません。高レベルサーバー側の話は **[エリシテーション](elicitation.md)** にあります。

## まとめ {#recap}

* 2026-07-28 では、呼び出しの途中で入力が必要なサーバーは `InputRequiredResult` を**返します**。クライアントへのリクエストを開くことは決してありません。
* `input_requests` は必要としているものです。`request_state` はサーバーだけが読む不透明な再開トークンです。
* `Client` がリトライループを回してくれます。`elicitation_callback` / `sampling_callback` / `list_roots_callback` を登録すれば、`call_tool` は素の `CallToolResult` を返します。`input_required_max_rounds`（デフォルト 10）が上限をかけます。
* ラウンドを検査したり永続化したりするには、`client.session.call_tool(..., allow_input_required=True)` を使い、`while isinstance(result, InputRequiredResult)` ループを自分で握ります。
* `@mcp.tool()` では、ユーザーに尋ねる依存関係がこの結果を作ってくれます（**[依存関係](dependencies.md)**）。**低レベル**の `Server` が手動の形式です。
* プロンプトとリソースも参加します。`@mcp.prompt()` またはテンプレートの `@mcp.resource()` 関数は自分で `InputRequiredResult` を返し、リトライ時に `ctx.input_responses` を読みます。
* `requestState` はクライアントが供給する入力として戻ってくるため、`MCPServer` はデフォルトで、リゾルバーの状態も手組みの状態も同様に、プロセスローカルなキーで封印します。マルチインスタンスのデプロイでは `RequestStateSecurity(keys=[...])`（またはカスタムコーデック）を渡し、どのインスタンスも兄弟インスタンスが発行したものを検証できるようにします。封印はすべてのトークンを時間枠と元のリクエストに束縛します。さらに、SDK が検証した認証をリクエストが載せている場合や、`bind_principal=` で独自のアイデンティティシグナルを供給している場合は、認証されたプリンシパルにも束縛します（**[`requestState` の保護](#protecting-requeststate)**）。

これがサーバー起点のサンプリングや、プッシュ型のバックチャネルの残りを置き換える仕組みです。**[非推奨の機能](../deprecated.md)** を参照してください。
