---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "このドキュメントの対象は v2（現行の安定版リリース系列）"
    v2 が初めての場合や v1 から移行する場合は、**[v2 の新機能](whats-new.md)**で変更点を 5 分で確認できます。破壊的変更は**[移行ガイド](migration.md)**がすべて扱っています。まだ v1.x を使っている場合、そのドキュメントは [v1.x のドキュメント](https://py.sdk.modelcontextprotocol.io/v1/)にあります。わかりにくい点や使いにくい点があれば、[教えてください](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

**Model Context Protocol（MCP）**を使うと、アプリケーションは標準化された方法で LLM にコンテキストを提供できます。コンテキストを「提供する」という関心事を、LLM とのやり取りそのものから切り離せます。

これはその公式 Python SDK です。この SDK を使うと次のことができます。

* あらゆる MCP ホストにツール、リソース、プロンプトを公開する **MCP サーバーを構築**できます。
* あらゆる MCP サーバーに接続する **MCP クライアントを構築**できます。
* stdio、Streamable HTTP、SSE という標準のトランスポートすべてを扱えます。

## 要件 {#requirements}

Python 3.10 以上が必要です。

## インストール {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` エクストラを付けると `mcp` コマンドが使えるようになります。開発には入れておくことをおすすめします。各依存関係の用途については[インストール](get-started/installation.md)を参照してください。

## 例 {#example}

### 作成する {#create-it}

`server.py` というファイルを作成します。

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

これだけで完全な MCP サーバーです。

このサーバーは、**ツール**を 1 つ（`add`）と、テンプレート化された**リソース**を 1 つ（`greeting://{name}`）公開しています。

### 実行する {#run-it}

```console
uv run mcp dev server.py
```

これでサーバーが起動し、[MCP Inspector](https://github.com/modelcontextprotocol/inspector) が開きます。サーバーをあれこれ触って試せる対話型の UI です。表示される URL を開いてください。

!!! note
    Inspector は Node.js アプリなので、`mcp dev` を使うには `PATH` 上に `npx` が必要です。

### 試してみる {#try-it}

Inspector で **Tools** を開き、`a=1`、`b=2` を指定して `add` を呼び出してください。

`3` が返ってきます。✨

Inspector はこのフォーム（`a` 用の必須の整数フィールドが 1 つ、`b` 用にもう 1 つ）を型ヒントから組み立てました。Claude も、そのほかのあらゆる MCP ホストも同じことをします。

今度は **Resources** を開き、`greeting://World` を読み取ってみてください。

```text
Hello, World!
```

### まとめ {#recap}

ここで、**書かなかった**ものに改めて目を向けてみましょう。

* JSON Schema はありません。`a: int, b: int` がそのままスキーマです。
* リクエストの解析も、シリアライズも、バリデーションのコードもありません。
* プロトコルの処理は一切ありません。

書いたのは、型ヒントと docstring を付けた Python 関数 2 つだけです。残りは SDK が引き受けます。

## 次に読むもの {#where-to-go-next}

* **[はじめに](get-started/index.md)**では、インストールから、テストも済んだ動作するサーバーの完成までを案内します。
* MCP サーバーを「使う」側のアプリケーションを作るなら、**[クライアント](client/index.md)**から始めてください。
* すでに FastAPI や Starlette のアプリがあるなら、**[既存のアプリに追加する](run/asgi.md)**でその中に MCP サーバーをマウントできます。
* 特定のエラーメッセージを探しているなら、**[トラブルシューティング](troubleshooting.md)**がメッセージの文言そのままで引けるように整理されています。
* v2 で何が変わったか気になるなら、**[v2 の新機能](whats-new.md)**が 5 分で読めるツアーです。
* v1 から移行するなら、**[移行ガイド](migration.md)**から始めてください。
* 正確なシグネチャを探しているなら、**[API リファレンス](api/mcp/index.md)**がソースから生成されています。
* LLM と一緒に読んでいるなら、このドキュメントは [llms.txt](https://llmstxt.org/) 形式でも公開されています。[llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) は各ページの索引で、[llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) は全ページを 1 つのファイルに収めたものです。
