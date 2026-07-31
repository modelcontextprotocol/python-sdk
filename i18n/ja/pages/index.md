# MCP Python SDK {#mcp-python-sdk}

!!! info "このドキュメントは、現在の安定版リリースラインである v2 について説明しています"
    v2 が初めて、あるいは v1 から移ってきた場合は、**[v2 の新機能](whats-new.md)** が変更点を 5 分でたどれるツアーになっています。破壊的変更は **[移行ガイド](migration.md)** がすべて網羅しています。
    まだ v1.x を使っている場合、そのドキュメントは [v1.x のドキュメント](https://py.sdk.modelcontextprotocol.io/v1/) にあります。
    わかりにくい点や不備を見つけたら、[お知らせください](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

**Model Context Protocol（MCP）** を使うと、アプリケーションは標準化された方法で LLM にコンテキストを提供できます。コンテキストを「提供する」という関心事を、LLM とのやり取りそのものから切り離せます。

これはその公式 Python SDK です。この SDK では次のことができます。

* 任意の MCP ホストに対してツール、リソース、プロンプトを公開する **MCP サーバーを構築する**。
* 任意の MCP サーバーに接続する **MCP クライアントを構築する**。
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

`[cli]` エクストラを入れると `mcp` コマンドが使えます。開発では必要になるでしょう。
各依存関係が何のためのものかは [インストール](get-started/installation.md) を参照してください。

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

これでサーバーが起動し、[MCP Inspector](https://github.com/modelcontextprotocol/inspector) が開きます。Inspector はサーバーを対話的に試せる UI です。表示された URL を開いてください。

!!! note
    Inspector は Node.js アプリなので、`mcp dev` を使うには `PATH` に `npx` が必要です。

### 試す {#try-it}

Inspector で **Tools** を開き、`a=1`、`b=2` を指定して `add` を呼び出します。

`3` が返ってきます。✨

Inspector は、そのフォーム（`a` 用の必須の整数フィールドと、`b` 用のもう 1 つのフィールド）を型ヒントから組み立てています。Claude も、ほかのすべての MCP ホストも同じようにします。

次に **Resources** を開き、`greeting://World` を読み取ってみましょう。

```text
Hello, World!
```

### おさらい {#recap}

**書かなかった** ものをもう一度見てみましょう。

* JSON Schema はありません。`a: int, b: int` がそのままスキーマです。
* リクエストの解析も、シリアライズも、バリデーションのコードもありません。
* プロトコルの処理は一切ありません。

書いたのは、型ヒントと docstring が付いた Python 関数 2 つだけです。残りは SDK が引き受けます。

## 次に読むもの {#where-to-go-next}

* **[はじめる](get-started/index.md)** では、インストールから動作しテスト済みのサーバーまでを案内します。
* MCP サーバーを「利用する」アプリケーションを作るなら、**[クライアント](client/index.md)** から始めてください。
* すでに FastAPI や Starlette のアプリがあるなら、**[既存のアプリに追加する](run/asgi.md)** でその中に MCP サーバーをマウントできます。
* 特定のエラーメッセージを探しているなら、**[トラブルシューティング](troubleshooting.md)** がそのままの文言で引けるようになっています。
* v2 の変更点が気になるなら、**[v2 の新機能](whats-new.md)** で 5 分で把握できます。
* v1 から移行するなら、**[移行ガイド](migration.md)** から始めてください。
* 正確なシグネチャを探しているなら、**[API リファレンス](api/mcp/index.md)** がソースから生成されています。
* LLM と一緒に読むなら、このドキュメントは [llms.txt](https://llmstxt.org/) 形式でも公開されています。
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) はページの索引で、
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) にはすべてのページが 1 つのファイルにまとめられています。
