---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# はじめに {#get-started}

MCP が初めてでも、この SDK が初めてでも、ここから始めてください。ここにあるページでは、何もない状態から、テスト済みの動くサーバーができあがるまでを案内します。[SDK をインストール](installation.md)し、[最初のサーバー](first-steps.md)を作り、[実際のホストに接続](real-host.md)して、インメモリクライアントで[テスト](testing.md)します。

## コードを実行する {#run-the-code}

コードブロックはすべて、そのままコピーして使えます。どれも完結した、実際に動くファイルです。

一緒に進めるには、コードブロックを `server.py` に貼り付けて、MCP Inspector で開いてください。

```console
uv run mcp dev server.py
```

コードを自分で書き（またはコピーし）、編集し、ローカルで実行することを**強くおすすめします**。自分のエディターで使ってみてこそ、肝心な点が実感できます。書く量がどれほど少ないか、自動補完が効くこと、そして何も実行しないうちに型チェックがミスを見つけてくれることです。

## 推測に頼る必要はない {#you-will-not-be-guessing}

このドキュメントの例はすべて、SDK 自身のリポジトリの [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) 以下に置かれた完結したファイルです。そのどれもが、SDK のテストスイートによって**インメモリクライアント**を通じて実行されています。

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

サブプロセスも、ポートも、トランスポートもありません。`Client(mcp)` がサーバーオブジェクトに直接接続します。

SDK への変更によってこれらのページの例が壊れた場合、ページが壊れるより先に CI が赤くなります。ここで読むコードが、実際に動くコードそのものです。

この仕組みは[テスト](testing.md)で実際に使うことになります。自分のサーバーをテストする方法も、まさにこれです。

## 次に進む先 {#where-to-go-next}

サーバーが動くようになれば、残りのドキュメントは講座ではなくリファレンスです。どのページも単独で完結しているので、必要なところへ直接進んでください。

* サーバーが公開するもの（ツール、リソース、プロンプト）は **[サーバー](../servers/index.md)** です。
* 登録した関数の中で使えるものは **[ハンドラーの中で](../handlers/index.md)** です。
* クライアントから使えるようにする方法（stdio、HTTP、既存の FastAPI アプリ）は **[サーバーの実行](../run/index.md)** です。
* 反対側、つまり MCP サーバーを「使う」側のアプリケーションを作る方法は **[クライアント](../client/index.md)** です。
