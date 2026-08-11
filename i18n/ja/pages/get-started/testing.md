---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# テスト {#testing}

Python SDK には、**インメモリトランスポート**を備えた `Client` クラスが付属しています。サーバーオブジェクトを渡せば、そのサーバーに直接接続します。

サブプロセスも、ポートも要りません。トランスポートすら使いません。FastAPI の `TestClient` と同じ発想です。

## 基本的な使い方 {#basic-usage}

ツールを 1 つだけ持つシンプルなサーバーがあるとします。

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

以下のテストを実行するには、追加の（開発用）依存関係が 2 つ必要です。

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    このドキュメントは、[`pytest`](https://docs.pytest.org/en/stable/) をすでに知っていることを前提にしています。

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) は、以下のテストで結果オブジェクト全体を 1 行でアサートするために使っているライブラリです。テストの出力を、コードにあるとおりの `snapshot(...)` リテラルとして記録します。使いたくない場合は import を削除し、ほかのテストと同じように、関心のあるフィールド（`result.content[0].text == "3"`）をアサートしてください。

テストは次のとおりです。

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. `trio` を使っている場合は、代わりに `"trio"` を返してください。詳しくは [anyio のドキュメント](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) を参照してください。
2. このフィクスチャは接続済みのクライアントを yield します。`client` を受け取るテストごとに、同じサーバーへの新しいインメモリ接続が用意されます。

これで準備完了です。あとはテストを拡張して、さらに多くのシナリオをカバーしていけます。

## なぜ `raise_exceptions=True` なのか {#why-raise_exceptionstrue}

問題が起こりうる場所は 2 種類あり、このフラグが関わるのはそのうちの一方だけです。

**ツール**の内部で発生した例外は、プロトコル上の失敗ではありません。`is_error=True` の付いた通常の結果になり、モデルがそのメッセージを読みます。`raise_exceptions` はこの挙動を変えません。指定してもしなくても、`call_tool` は同じ `is_error=True` の結果を返します。これについては専用のページがあります。**[エラーの処理](../servers/handling-errors.md)** を参照してください。

ツール本体の**外側**で起きた失敗は事情が異なります。`Client(mcp)` で得られる接続では、クライアントの目に触れる前に、サーバーがその失敗を汎用の `"Internal server error"` にサニタイズします。予期しないクラッシュの詳細は、リモートの呼び出し側に決して漏らしてはいけないからです。しかしテストでは、これはまさに望まない挙動です。そして `raise_exceptions=True` が変えるのはまさにこの点で、テストからはサニタイズ後のメッセージではなく本来のメッセージが見えるようになります。

テストでは有効にしたままにしてください。本番コードでは意味を持ちません。

## デフォルトはインプロセス {#in-process-by-default}

!!! note
    `Client(mcp)` はインプロセスで接続し、デフォルトでは**プロトコルの世代を問いません**。サーバーを調べ、適切なプロトコル経路を選びます。テストがレガシー固有のセマンティクス（サンプリングやエリシテーション（elicitation）のプッシュ、`message_handler`）を検証する場合は `mode="legacy"` に固定し、その場合は `raise_exceptions=True` を外してください。レガシー接続はそもそもサニタイズを行わず、このフラグを付けると失敗がテストの中ではなくサーバータスクの中で再送出されてしまうからです。

この 1 行こそが、このドキュメントが「掲載している例は動く」と約束できる理由でもあります。すべてのサンプルファイルは SDK 自身のテストスイートで実行されており、そのほぼすべてがまさにこのクライアントを経由しています。SDK が自分自身に対して使っているのと同じツールを使っているわけです。

これで、きちんと動く、テスト済みのサーバーが手元にあります。実際のアプリケーション（Claude Desktop や IDE）に組み込む方法は **[実際のホストに接続する](real-host.md)** に、それ以外の提供方法はすべて **[サーバーの実行](../run/index.md)** にまとまっています。
