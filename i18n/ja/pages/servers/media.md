---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# メディア {#media}

ツールが返せるのはテキストだけではありません。

SDK には、バイナリの結果を扱うヘルパーが 2 つ（**`Image`** と **`Audio`**）と、サーバー、ツール、リソース、プロンプトにクライアントの UI 上での「顔」を与える **`Icon`** 型が用意されています。

## 画像を返す {#returning-an-image}

戻り値の型を `Image` と注釈し、ファイルを指定して返します。

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` は `path`（読み込むファイル）か `data`（生のバイト列）のどちらか一方だけを取ります。
* クライアントに見える MIME タイプは拡張子から推測されます。`logo.png` は `image/png` として通知されます。
* ロゴだからといって特別なことは何もありません。`server.py` の隣にある PNG なら何でも使えます。コードが描画したグラフでも、図でも、写真でもかまいません。

`Image` は SDK の便利機能であって、プロトコルの型ではありません。実際に送受信されるときには、戻り値は **`ImageContent`** ブロック（ファイルのバイト列を base64 エンコードしたものと MIME タイプ）になります。

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

注目すべき点が 2 つあります。

* `data` は base64 です。バイト列には一切触れていません。ファイルを読み込んでエンコードしたのは SDK です。
* `structured_content` は `None` です。`Image` はモデルが見るためのコンテンツであり、アプリケーションが解析するためのデータではありません。出力スキーマはありません。（戻り値の注釈そのものがスキーマになる **[構造化出力](structured-output.md)** と比べてみてください。）

!!! info
    `ImageContent` と `AudioContent` は `mcp.types` にあり、単純な `str` の結果が変換される `TextContent` のすぐ隣に並んでいます（**[ツール](tools.md)**）。ツールの結果はコンテンツブロックのリストです。`Image` と `Audio` は、2 種類のバイナリブロックを作る最短の方法です。

### 試してみる {#try-it}

任意の PNG を `server.py` の隣に置いて `logo.png` という名前にし、次を実行してください。

```console
uv run mcp dev server.py
```

**Tools** タブを開いて `logo` を呼び出します。結果は文字列ではありません。`image` コンテンツブロックであり、Inspector が画像を描画します。ディスク上のファイルから画面上のピクセルまでの間は、すべて SDK が処理しました。

## 音声を返す {#returning-audio}

`Audio` も同じ形です。`logo.png` はそのままにして、任意の WAV を `chime.wav` として隣に置いてください。

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

結果は **`AudioContent`** ブロックです。

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

仕組みは同じです。ディスク上のファイルが入力で、base64 と MIME タイプが出力、出力スキーマはありません。

## バイト列かファイルか {#bytes-or-a-file}

どちらのヘルパーも `path=` の代わりに `data=`（生のバイト列）を受け付けます。これは、そもそもファイルとして存在したことのないバイト列のためのモードです。データベースのカラム、HTTP のレスポンス、Pillow が描いたばかりの画像などです。

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

`path=` なら宣言するものは何もありません。ファイルは結果を組み立てるときに読み込まれ、MIME タイプは拡張子から推測されます。

* `Image`：`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`。
* `Audio`：`.wav`、`.mp3`、`.ogg`、`.flac`、`.aac`、`.m4a`。

認識できない拡張子は `application/octet-stream` にフォールバックします。

!!! check
    `data=` の場合はファイル名がないので、推測する材料がありません。`format=` を忘れると、SDK はデフォルトにフォールバックします。画像なら `image/png`、音声なら `audio/wav` です。この方法で MP3 のバイト列から `Audio` を作ると、クライアントには `mime_type="audio/wav"` と伝えられ、それを忠実に信じてデコードに失敗します。`data=` を渡すときは `format=` も渡してください。

## アイコン {#icons}

`Icon` はメタデータであって、コンテンツではありません。画像そのものは運ばず、URI で画像を指し示します。クライアントはそれを取得して、サーバーの名前やツール、リソース、プロンプトの横に表示することがあります。

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` はクライアントが解決できる URI です。`https:` か、追加の取得なしでアイコンを埋め込みたければ `data:` URI です。
* `mime_type` と `sizes`（`"48x48"`、スケーラブルな形式なら `"any"`）を指定すると、複数のアイコンを提供したときにクライアントが適切なものを選べます。
* `theme="light"` または `theme="dark"` で、アイコンを一方の配色向けとして印を付けます。

同じ `icons=[...]` キーワードは `MCPServer(...)`、`@mcp.tool()`、`@mcp.resource()`、`@mcp.prompt()` のいずれでも受け付けられます。

### クライアントからはどこに見えるか {#where-a-client-sees-them}

アイコンは、それが飾る対象と一緒に送られます。サーバーのアイコンはクライアントの接続時に `client.server_info` に届きます（2026 年世代の接続では省略可能なので、まず絞り込んでください）。

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

ツールのアイコンは `tools/list` の `Tool` オブジェクトに、リソースのアイコンは `resources/list` の `Resource` に、プロンプトのアイコンは `prompts/list` の `Prompt` にあります。フィールド名は常に `icons` です。

## まとめ {#recap}

* ツールから `Image` または `Audio` を返すと、クライアントは `ImageContent` / `AudioContent` ブロックを受け取ります。バイト列が base64 エンコードされ、MIME タイプが付きます。
* `path=` から作って拡張子に MIME タイプを決めさせるか、メモリ上の `data=` に明示的な `format=` を添えて作ります。
* メディアの結果には `structured_content` も出力スキーマもありません。
* `Icon` はポインターです。`src` URI に、省略可能な `mime_type`、`sizes`、`theme` を加えたものです。
* `icons=[...]` はサーバー、ツール、リソース、プロンプトのどれにも使え、クライアントは対応するオブジェクト上でそれらを見つけます。

ツールが結果に「入れられる」ものはこれですべてです。ツールが「失敗した」ときに何が起こるか（そして誰がそれを知るべきか）は **[エラーの処理](handling-errors.md)** で扱います。
