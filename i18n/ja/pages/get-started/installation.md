---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# インストール {#installation}

Python SDK は PyPI 上で [`mcp`](https://pypi.org/project/mcp/) として公開されています。**Python 3.10 以上**が必要です。

このドキュメントは、現在の安定版リリースラインである **v2** について説明しています。

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "v1 から移行する場合"
    v2 は破壊的変更を含むメジャーバージョンです。変更点はすべて **[移行ガイド](../migration.md)** にまとめてあります。自分のパッケージが `mcp` に依存していて、まだ移行の準備ができていない場合は、バージョンの上限として `<2` を付けておいてください（たとえば `mcp>=1.28,<2`）。そうすれば、バージョンを固定しない依存解決でも 1.x 系にとどまります。

## インストールされるもの {#what-gets-installed}

SDK を使うだけなら、以下の内容を知っている必要はありません。それぞれの依存関係が何のためにあるのか気になる場合のために、まとめておきます。

* `mcp-types`：すべてのプロトコル型（リクエスト、結果、コンテンツブロック）を独立したパッケージにしたもので、SDK と足並みをそろえてバージョン管理されます。`mcp` に依存するコードは、`mcp.types` というエイリアス経由でこれをインポートします（このドキュメントに出てくる `from mcp.types import ...` はすべてそうです）。`mcp_types` を直接インポートするのは、SDK なしで `mcp-types` をインストールするプロジェクトだけにしてください。
* [`anyio`](https://anyio.readthedocs.io/)：非同期ランタイムです。SDK 全体が anyio を前提に書かれているので、`asyncio` でも `trio` でも動きます。
* [`pydantic`](https://docs.pydantic.dev/)：`mcp.types` のあらゆるモデルの土台であり、スキーマの生成と検証もすべて担っています。
* [`httpx2`](https://pypi.org/project/httpx2/)：Streamable HTTP と SSE のクライアント側トランスポートを支える HTTP クライアントで、Server-Sent Events のサポートを内蔵しています。
* [`starlette`](https://www.starlette.io/)、[`uvicorn`](https://www.uvicorn.org/)、[`sse-starlette`](https://pypi.org/project/sse-starlette/)、[`python-multipart`](https://pypi.org/project/python-multipart/)：HTTP のサーバー側トランスポートです。
* [`jsonschema`](https://pypi.org/project/jsonschema/)：ツールの構造化出力を、宣言された出力スキーマに照らして検証します。
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/)：認可のための OAuth トークン処理を担います。
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/)：軽量な API だけです。そのため、OpenTelemetry の SDK とエクスポーターを自分でインストールしない限り、この SDK のトレーシングミドルウェアにコストは発生しません。
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) と [`typing-inspection`](https://pypi.org/project/typing-inspection/)：Python 3.10 でも新しい型付け機能を使えるようにします。
* [`pywin32`](https://pypi.org/project/pywin32/)：Windows 専用で、`stdio` のサブプロセス管理に使われます。

## オプションの extras {#optional-extras}

* `mcp[cli]` は、`mcp` コマンドラインツール（`mcp dev`、`mcp run`、`mcp install`）のために [`typer`](https://typer.tiangolo.com/) と [`python-dotenv`](https://pypi.org/project/python-dotenv/) を追加します。開発中は入れておきたいところですが、デプロイしたサーバーでは必要ないかもしれません。
* `mcp[rich]` は、サーバーのログを見やすくするために [`rich`](https://rich.readthedocs.io/) を追加します。
