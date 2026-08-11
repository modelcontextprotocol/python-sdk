---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# 実際のホストに接続する {#connect-to-a-real-host}

**ホスト**とは、サーバーが最終的にその中で動くことになるアプリケーションのことです。Claude Desktop、Claude Code、IDE などがそうです。ユーザーがやり取りする相手はホストです。その内部では、MCP **クライアント**がサーバーを子プロセスとして起動し、そのプロセスの stdin と stdout を介してサーバーと通信します。

つまり、ホストに接続するためにやることは 1 つだけです。**サーバーを起動するコマンド**をホストに伝えます。このページに出てくるもの（2 つの CLI コマンドと 3 つの JSON ファイル）はすべて、その同じコマンドの置き場所が違うだけです。

## 1 つのサーバー、すべてのホスト {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

ツール 2 つとリソース 1 つが、1 つのファイルに収まっています。このファイルについて、以降のどのホストにも関わる点が 3 つあります。

* 引数なしの `mcp.run()` は **stdio** サーバーを起動します。ブロックし、stdin でプロトコルメッセージを読み、stdout に書き出します。これが、このページのどのホストも話すトランスポートです。ホストはこのファイルを子プロセスとして起動し、その 2 本のパイプを所有します。だからこそ、接続は常に「これがコマンドです」と伝えるだけで済みます。ポートを選ぶことはなく、どこかのポートで待ち受けるものもありません。
* `run()` は `if __name__ == "__main__":` の下にあります。以降のものはすべてこのファイルを実行するのではなく**インポート**するので、ガードのない `run()` だと、何かがモジュールを読み込んだ瞬間にサーバーが起動してしまいます。
* サーバーオブジェクトは `mcp` という名前のモジュールレベルのグローバル変数です。これは `mcp run` が探す名前です（`server` と `app` でも動きます）。別の名前を付けた場合は、`mcp run server.py:bookshop` のように明示的に指定します。

このページの Python はこれが最後の 1 行です。ここから下はすべてホストの設定です。

## 起動コマンド {#the-launch-command}

以降のどのホストにも同じコマンドを渡します。

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

どのホストにも 1 つのコマンドで済むのは、`uv run --with` がその場で SDK を新しい環境へ解決してくれるからです。どのディレクトリからでも動き、プロジェクトも、有効化すべき仮想環境も要りません。このことがほかのどこよりもここで効いてくるのは、ホストがサーバーを起動するのがシェルからではなく、ほぼ空の環境でホスト自身の作業ディレクトリからだからです。

このコマンドは、`mcp install` が Claude Desktop の設定に書き込んでくれるコマンドでもあります（後述）。そのため、手で入力するものとツールが生成するものは、ツールが付け加える正確なバージョン固定を除いて一致します。

!!! tip "ホストが `uv` を見つけられない場合"
    ホストは最小限の `PATH` でサーバーを起動するため、そこに `uv` が入っていないことがあります。`uv` とだけ書いた部分を、`which uv`（macOS/Linux）または `where uv`（Windows）で得られる絶対パスに置き換えてください。`mcp install` が書き込むのもまさにこの形です。

!!! note "このページはローカルの話"
    ここで扱うものはすべて、ホストと同じマシン上でサーバーを動かします。ホストがファイルを stdio 経由で起動する形です。個人用のツールや 1 台のマシンで使うツールなら、まさにこれが正解です。ファイルを持って**いない**人たちにサーバーを渡すには、コマンドではなく **URL** を配ります。つまり、同じ `mcp` オブジェクトを Streamable HTTP で提供します。**[サーバーの実行](../run/index.md)** はその判断を 1 つの表にまとめており、**[デプロイとスケール](../run/deploy.md)** はそこから実際のホスト名に至るまでの道のりです。

    また、ホストとは内部に MCP クライアントを持つアプリケーションにすぎないので、自分の Python コードがホストの役を演じることもできます。**[クライアントのトランスポート](../client/transports.md)** ではこの同じファイルを `stdio_client(...)` でサブプロセスとして起動し、**[テスト](testing.md)** ではプロセスを一切使わずにメモリ内で接続します。

## Claude Desktop {#claude-desktop}

SDK が代わりに設定してくれる唯一のホストです。

```bash
uv run mcp install server.py
```

これだけです。`mcp install` はファイルをインポートしてサーバーの名前を読み取り、Claude Desktop の設定ファイルを探し出し、そこに起動コマンドを書き込みます。その過程でパスを絶対パスに変換してくれるので、自分で変換する必要はありません。

謎めいたところは何もありません。書き込まれるエントリは次のとおりです。

```json
{
  "mcpServers": {
    "Bookshop": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--frozen",
        "--with",
        "mcp[cli]==2.0.0",
        "mcp",
        "run",
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

これは前の節の起動コマンドに 3 つの要素を加えたものです。`uv` への絶対パス、たまたま近くにあるロックファイルを `uv` が書き換えることのないようにする `--frozen`、そしてインストール済みの `mcp` のバージョンへの正確な固定です。書き込み先は `claude_desktop_config.json` で、このファイルは次の場所にあります。

* **macOS**：`~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**：`%APPDATA%\Claude\claude_desktop_config.json`

このファイルは手で書くこともできます。`mcp install` があるのは、手で書くときにありがちなミス（相対パス）を避けるためです。

Claude Desktop を（ウィンドウだけでなく）完全に終了し、もう一度開いてください。

!!! warning
    Claude Desktop の設定「ディレクトリ」がまだ存在しない場合、`mcp install` は `Claude app not found` で失敗します。Claude Desktop をインストールして一度起動してください。ディレクトリはそのときに作られます。

!!! tip
    Claude Desktop はサーバーを自身のプロセスで起動するので、シェルの環境変数はそこにはありません。`uv run mcp install server.py -v API_KEY=abc123`（または `-f .env`）とすると、それらがエントリの `env` フィールドに記録されます。`--name` はエントリ名を上書きします。デフォルトはサーバーの `name` です。

## Claude Code {#claude-code}

編集するファイルはありません。`claude` CLI でサーバーを登録してください。`--` の後ろはすべて起動コマンドです。

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Claude Code のセッション内で `/mcp` を実行し、`bookshop` が接続されていてそのツールが一覧表示されることを確認してください。

## Cursor {#cursor}

プロジェクトのルートに `.cursor/mcp.json` を作成してください。

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Claude Desktop が使うのと同じ `mcpServers` キーの下に、同じ `command` と `args` を置きます。サーバーは Cursor の MCP 設定に表示され、両方のツールが一覧に並びます。

## VS Code {#vs-code}

プロジェクトのルートに `.vscode/mcp.json` を作成してください。

```json
{
  "servers": {
    "bookshop": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Cursor のファイルとの違いは 2 つだけです。ラッパーのキーが `mcpServers` ではなく `servers` であること、そして各エントリが `type` を宣言することです。信頼を確認するプロンプトを承認すると、コマンドパレットの **MCP: List Servers** に `bookshop` が実行中として表示されます。

!!! note
    VS Code 1.99 以降と、サインイン済みの **GitHub Copilot** 拡張機能が必要です（Copilot Free で十分です）。また、Copilot Chat は **Agent** モードでなければなりません。ほかのモードはツールを呼び出さないからです。

## 表示されないとき {#it-doesnt-show-up}

ホストの設定に手を付ける前に、起動コマンドを自分で実行してみてください。

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

何も表示されず、コマンドも戻ってきません。この沈黙は正しい動作です。stdio サーバーは、ホストが先に stdin で話しかけてくるのを待っています（止めるには `Ctrl-C`）。本当のバグはトレースバックや即座の終了のほうで、こうして実行すれば、ホスト越しに推測する代わりにそれを直接読めます。

このコマンドがじっと待機するようになったら、残る原因はほぼ決まって次の 3 つのどれかです。

* **相対パス。** ホストがサーバーを起動するのは、登録したときのディレクトリではなく、ホスト自身の作業ディレクトリからです。`/absolute/path/to/server.py` が必要なところに `server.py` と書くのが、飛び抜けて多い失敗です。ホストが `uv` も見つけられないなら、そのパスも絶対パスにする必要があります。
* **ホストがまだ古い設定で動いている。** ホストは起動時に設定を読み込みます。特に Claude Desktop は、`claude_desktop_config.json` の編集を反映させるには、ウィンドウを閉じるだけでなく「完全に終了」してから開き直す必要があります。
* **退避される期間の外で、何かが stdout に届いた。** stdio では、stdout がプロトコルそのものです。SDK はサービス中、フラッシュされた余計な出力を stderr に退避させます。しかし、それ以前に stdout へフラッシュされた出力（echo するラッパースクリプトや、バッファリングなしのプロセスでのインポート時の `print()`）や、インタープリター終了時に書き出されるバッファ済みの `print()` は別です。これらは壊れたメッセージをホストに渡してしまい、ホストは接続を切ります。ログ出力にはデフォルトの `logging` 設定を使ってください。その stderr ハンドラーはレコードごとにフラッシュします。独自のハンドラーも stdout を避ける必要があります。詳しくは **[ロギング](../handlers/logging.md)** を参照してください。

Claude Desktop はサーバーごとにログを残します。`mcp-server-<NAME>.log` がサーバーの stderr で、接続についての `mcp.log` と並んで、macOS では `~/Library/Logs/Claude`、Windows では `%APPDATA%\Claude\logs` の下にあります。

この 3 つに当てはまらない場合は、**[トラブルシューティング](../troubleshooting.md)** のページを参照してください。

## まとめ {#recap}

* **ホスト**（Claude Desktop や IDE）は MCP クライアントを動かし、そのクライアントがサーバーを子プロセスとして stdio 経由で起動します。接続とは、起動コマンドを 1 つ渡すことです。
* そのコマンドは `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py` です。有効化する venv は不要で、どのディレクトリからでも動きます。
* **Claude Desktop** は、`mcp install` が代わりに設定してくれる唯一のホストです。その同じコマンド（`uv` への絶対パス、`--frozen`、インストール済みバージョンへの正確な固定を加えたもの）を `claude_desktop_config.json` に書き込むので、自分で書く必要はありません。
* **Claude Code** は `claude mcp add bookshop -- <launch command>` です。**Cursor** は `mcpServers` の下に書く `.cursor/mcp.json` です。**VS Code** は `servers` の下に書く `.vscode/mcp.json` で、各エントリに `type` を付けます。
* どこでも絶対パスを使い、設定を編集したらホストを再起動し、SDK 以外のものには決して stdout に書き込ませないでください。

このページのどのホストも、同じファイルに同じコマンドで接続しました。そのファイルが何を「公開」できるかが、このドキュメントの残りのテーマです。**[ツール](../servers/tools.md)**、**[リソース](../servers/resources.md)**、そして stdio 以外のあらゆるトランスポートを扱う **[サーバーの実行](../run/index.md)** へと続きます。
