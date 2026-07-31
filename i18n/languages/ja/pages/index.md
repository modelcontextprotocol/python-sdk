# MCP Python SDK {#mcp-python-sdk}

!!! info "このドキュメントは現在の安定版リリースラインである v2 を対象としています"
    v2 をはじめて使う場合、または v1 から移行する場合は、**[v2 の新機能](whats-new.md)** で変更点を 5 分で把握できます。破壊的変更のすべては **[移行ガイド](migration.md)** にまとめてあります。
    まだ v1.x を使っている場合は、[v1.x のドキュメント](https://py.sdk.modelcontextprotocol.io/v1/) を参照してください。
    分かりにくい点や不十分な点があれば、[お知らせください](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

**Model Context Protocol (MCP)** は、LLM にコンテキストを提供するための標準的な方法を定め、コンテキストを *提供する* という関心事を LLM とのやり取りそのものから切り離します。

これはその公式 Python SDK です。これを使うと、次のことができます。

* あらゆる MCP ホストに対してツール、リソース、プロンプトを公開する **MCP サーバーを構築する**。
* あらゆる MCP サーバーに接続する **MCP クライアントを構築する**。
* 標準のトランスポートをすべて扱う：stdio、Streamable HTTP、SSE。

## 要件 {#requirements}

Python 3.10 以上。

## インストール {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` エクストラを入れると `mcp` コマンドが使えるようになります。開発時には必要になるはずです。
各依存関係が何のためにあるかは [インストール](get-started/installation.md) を参照してください。

## 例 {#example}

### 作成する {#create-it}

`server.py` というファイルを作成します。

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

これで完全な MCP サーバーです。

**ツール** `add` を 1 つと、テンプレート化された **リソース** `greeting://{name}` を 1 つ公開しています。

### 実行する {#run-it}

```console
uv run mcp dev server.py
```

これでサーバーが起動し、[MCP Inspector](https://github.com/modelcontextprotocol/inspector) が開きます。サーバーを対話的に試せる UI です。表示された URL を開いてください。

!!! note
    Inspector は Node.js のアプリなので、`mcp dev` を使うには `PATH` に `npx` が必要です。

### 試してみる {#try-it}

Inspector で **Tools** を開き、`a=1`、`b=2` を指定して `add` を呼び出してみてください。

`3` が返ってきます。✨

Inspector がそのフォーム（`a` に必須の整数フィールド、`b` にもう 1 つ）を組み立てたのは、型ヒントからです。Claude も、ほかのあらゆる MCP ホストも同じように動作します。

続いて **Resources** を開き、`greeting://World` を読み取ってみましょう。

```text
Hello, World!
```

### まとめ {#recap}

書か**なかった**ものをもう一度見てみましょう。

* JSON Schema はありません。`a: int, b: int` が *そのまま* スキーマです。
* リクエストの解析も、シリアライズも、バリデーションのコードもありません。
* プロトコルの処理は一切ありません。

書いたのは、型ヒントと docstring の付いた Python の関数 2 つだけです。残りは SDK が引き受けます。

## 次に読むもの {#where-to-go-next}

* **[はじめに](get-started/index.md)** では、インストールからテスト済みの動くサーバーまでを案内します。
* MCP サーバーを *利用する* アプリケーションを作るなら、**[クライアント](client/index.md)** から始めてください。
* すでに FastAPI や Starlette のアプリがあるなら、**[既存のアプリに追加する](run/asgi.md)** でその中に MCP サーバーをマウントできます。
* 特定のエラーメッセージを探しているなら、**[トラブルシューティング](troubleshooting.md)** がそのままの文面で引けるようになっています。
* v2 での変更点が気になるなら、**[v2 の新機能](whats-new.md)** で 5 分で把握できます。
* v1 から移行するなら、**[移行ガイド](migration.md)** から始めてください。
* 正確なシグネチャを探しているなら、**[API リファレンス](api/mcp/index.md)** がソースから生成されています。
* LLM と一緒に読む場合、このドキュメントは [llms.txt](https://llmstxt.org/) 形式でも公開されています。
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) はページの索引で、
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) には全ページが 1 つのファイルにまとめられています。
