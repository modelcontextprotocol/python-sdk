---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# ヘッダーパラメーター {#header-parameters}

ほとんどのサーバーでは、この機能は必要ありません。

サーバーの前段にあるゲートウェイやロードバランサーは、ボディを解析せずに読み取れる情報でしかルーティングできません。ツールの引数を `x-mcp-header` でマークすると、`2026-07-28` の **[プロトコルバージョン](../protocol-versions.md)** を使うクライアントは、その値を HTTP ヘッダーとしても送信します。

## 引数をマークする {#mark-an-argument}

マークは、引数の JSON Schema に追加するキー 1 つです。`MCPServer` では、`Field` がそのキーを追加します。

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* `2026-07-28` の Streamable HTTP では、クライアントはボディに加えて `Mcp-Param-Region` を送信し、サーバーは両者が食い違う呼び出しを拒否します。
* ツールを一覧取得していないクライアントは、マークを見たことがありません。そのためヘッダーを送信せず、呼び出しは拒否されます。この SDK の `Client` は、その場合にツールを一覧取得して呼び出しを 1 回だけ再送するので、先に一覧取得しておいても節約できるのはラウンドトリップ 1 回分だけです。
* それ以外の接続では、このアノテーションは無視されます。

関数は変わりません。`region` はこれまでどおり引数として渡されます。

## マークできるもの {#what-can-be-marked}

`str`、`int`、`bool` の引数です。それ以外は、ツールの登録時に `InvalidSignature` で拒否されます。

単一の型を持たない `str | None` も同様に拒否されます。省略可能な引数では、Pydantic の `WithJsonSchema` を使ってスキーマを明示する必要があります。

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## 低レベルの `Server` の場合 {#on-the-low-level-server}

こちらでは `input_schema` を手書きするので、キーをそのまま書き込みます。

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* アノテーションは何もチェックされません。不正なものもそのまま配信され、`2026-07-28` のクライアントはそのツールを一覧から除外します。

### 名前からスキーマを取得する {#schemas-by-name}

ヘッダーをチェックするには、SDK は呼び出しをディスパッチする前にツールの入力スキーマを必要とします。`get_tool_input_schema` がない場合、SDK は引数を伴う呼び出しのたびに `on_list_tools` ハンドラーを実行してスキーマを取得します。マークされたツールがあるかどうかは関係ありません。

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* この関数を渡すと、すでに手元にある情報から応答できます。
* チェックするものがないツールには `None` を返してください。

## まとめ {#recap}

* ツールの引数に `x-mcp-header` を付けると、`2026-07-28` のクライアントはその値を `Mcp-Param-*` HTTP ヘッダーとしても送信します。
* サーバーは、ヘッダーとボディが食い違う呼び出しを拒否します。
* マークできるのは `str`、`int`、`bool` の引数だけです。それ以外の場合、`MCPServer` は `InvalidSignature` を送出します。
* 低レベルの `Server` は何もチェックせず、クライアントはアノテーションが不正なツールを除外します。
* `get_tool_input_schema` を使うと、低レベルの `Server` が呼び出しのたびに `on_list_tools` を実行するのを避けられます。

手書きで扱う `Server` API の残りの部分は、**[低レベルの Server](low-level-server.md)** で説明しています。
