---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# 連接到真正的主機 {#connect-to-a-real-host}

**主機（host）** 指的是伺服器最後會被放進去的那個應用程式：Claude Desktop、Claude Code、IDE。使用者直接面對、互動的就是主機。在主機內部，MCP **用戶端**會把你的伺服器當成子處理程序啟動，並透過該處理程序的 stdin 和 stdout 與它溝通。

也就是說，連接到主機只有一個動作：告訴它**啟動伺服器的指令**。這一頁上的所有內容（兩個 CLI 指令、三個 JSON 檔案），都只是放這同一道指令的不同位置。

## 一個伺服器，所有主機 {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

兩個工具加一個資源，全在一個檔案裡。這個檔案有三件事對下面每個主機都很重要：

* `mcp.run()` 不帶引數時會啟動 **stdio** 伺服器：它會阻塞，從 stdin 讀取協定訊息，並把訊息寫到 stdout。這一頁上每個主機說的都是這種傳輸方式。主機把你的檔案當成子處理程序啟動，並掌管這兩條管道，所以連接永遠只是「指令在這裡」。不需要挑連接埠，也沒有任何東西在監聽連接埠。
* `run()` 放在 `if __name__ == "__main__":` 底下。下面所有做法都是**匯入**這個檔案而不是執行它，所以沒有這層保護的 `run()` 會在任何東西載入模組的那一刻就啟動伺服器。
* 伺服器物件是模組層級的全域變數，名稱是 `mcp`。`mcp run` 找的就是這個名稱（`server` 和 `app` 也可以）。如果取別的名字，就要明確指定：`mcp run server.py:bookshop`。

這是這一頁最後一行 Python。從這裡往下全都是主機設定。

## 啟動指令 {#the-launch-command}

下面每個主機拿到的都是同一道指令：

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

所有主機共用一道指令，是因為 `uv run --with` 會當場把 SDK 解析進一個全新的環境：從任何目錄都能執行，不需要專案，也不需要啟用虛擬環境。這一點在這裡比任何地方都重要，因為主機是從**它自己**的工作目錄、帶著幾乎空白的環境來啟動伺服器，而不是從你的 shell。

這也是 `mcp install` 替你寫進 Claude Desktop 設定檔的指令（見下文），所以手動輸入的和工具產生的會一致，差別只在工具多加了精確的版本鎖定。

!!! tip "如果主機找不到 `uv`"
    主機用極簡的 `PATH` 產生你的伺服器處理程序，`uv` 可能不在裡面。把單獨的 `uv` 換成 `which uv`（macOS/Linux）或 `where uv`（Windows）給出的絕對路徑。`mcp install` 寫的正是這個。

!!! note "這一頁講的是本機情境"
    這裡的一切都是在主機所在的那台機器上執行伺服器：主機透過 stdio 啟動你的檔案。對個人用或單機工具來說，這完全正確。要把伺服器交給**沒有**你這個檔案的人，給出去的是 **URL** 而不是指令：同一個 `mcp` 物件，改用 Streamable HTTP 提供服務。**[執行伺服器](../run/index.md)** 用一張表講清楚這個抉擇，**[部署與擴展](../run/deploy.md)** 則是從那裡走到真正主機名稱的路。

    而主機不過就是內含 MCP 用戶端的應用程式，所以你自己的 Python 也能扮演主機的角色：**[用戶端傳輸方式](../client/transports.md)** 用 `stdio_client(...)` 把同一個檔案當成子處理程序啟動，**[測試](testing.md)** 則在記憶體內連接它，完全不需要處理程序。

## Claude Desktop {#claude-desktop}

SDK 唯一能替你設定的主機：

```bash
uv run mcp install server.py
```

就這樣。`mcp install` 會匯入檔案來讀取伺服器名稱，找到 Claude Desktop 的設定檔，然後把啟動指令寫進去。過程中它會把你的路徑轉成絕對路徑，不用自己動手。

沒什麼神祕的。它寫進去的項目長這樣：

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

這就是上一節的啟動指令，外加三樣東西：`uv` 的絕對路徑、`--frozen`（讓 `uv` 永遠不會改寫它剛好碰到的 lockfile），以及精確鎖定在你已安裝的 `mcp` 版本。它會寫進 `claude_desktop_config.json`，這個檔案位於：

* **macOS**：`~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**：`%APPDATA%\Claude\claude_desktop_config.json`

這個檔案可以手寫。`mcp install` 存在的意義，是讓你手寫時不會犯那個經典錯誤（相對路徑）。

完全結束 Claude Desktop（不只是關掉視窗），再重新開啟。

!!! warning
    如果 Claude Desktop 的設定**目錄**還不存在，`mcp install` 會以 `Claude app not found` 失敗。安裝 Claude Desktop 並執行一次：目錄就是這樣建立的。

!!! tip
    Claude Desktop 在它自己的處理程序裡啟動你的伺服器，所以 shell 的環境變數不會在那裡。`uv run mcp install server.py -v API_KEY=abc123`（或 `-f .env`）會把它們記錄在項目的 `env` 欄位裡。`--name` 可以覆寫項目名稱；預設為伺服器的 `name`。

## Claude Code {#claude-code}

沒有檔案要編輯。用 `claude` CLI 註冊伺服器；`--` 之後的全部都是啟動指令。

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

在 Claude Code 工作階段裡執行 `/mcp`，確認 `bookshop` 已連線且列出了它的工具。

## Cursor {#cursor}

在專案根目錄建立 `.cursor/mcp.json`。

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

同樣的 `command` 加 `args`，放在 Claude Desktop 也在用的同一個 `mcpServers` 鍵底下。伺服器會出現在 Cursor 的 MCP 設定裡，兩個工具都會列出來。

## VS Code {#vs-code}

在專案根目錄建立 `.vscode/mcp.json`。

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

和 Cursor 的檔案只有兩處不同，就這兩處：外層的鍵是 `servers` 而不是 `mcpServers`，而且每個項目都要宣告 `type`。確認信任提示後，在命令選擇區執行 **MCP: List Servers**，就會看到 `bookshop` 正在執行。

!!! note
    需要 VS Code 1.99 以上，並安裝已登入的 **GitHub Copilot** 延伸模組（Copilot Free 就夠了），而且 Copilot Chat 必須在 **Agent** 模式，因為其他模式都不會呼叫工具。

## 沒有出現 {#it-doesnt-show-up}

動任何主機設定之前，先自己執行一次啟動指令：

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

什麼都不會印出，也不會結束返回。這種沉默是正確的：stdio 伺服器正在等主機先從 stdin 開口（按 `Ctrl-C` 停止）。出現 traceback 或立刻結束才是真正的 bug，而現在可以直接讀到它，不用隔著主機瞎猜。

一旦這道指令乖乖停在那裡等，剩下的問題幾乎一定是這三件事之一：

* **相對路徑。** 主機是從**它自己**的工作目錄啟動伺服器，不是你註冊時所在的目錄。該寫 `/absolute/path/to/server.py` 卻寫成 `server.py`，是最常見的失敗原因。如果主機也找不到 `uv`，那個路徑也得是絕對路徑。
* **主機還在用舊的設定。** 主機在啟動時讀取設定。特別是 Claude Desktop，必須**完全結束**（不只是關掉視窗）再重新開啟，對 `claude_desktop_config.json` 的修改才會生效。
* **有東西在轉向的時段之外寫到了 stdout。** 在 stdio 上，stdout **就是**協定。SDK 在提供服務期間會把已 flush 的雜散輸出轉到 stderr，但在那之前就 flush 到 stdout 的輸出（包裝腳本的 echo、未緩衝處理程序中匯入階段的 `print()`），或是在直譯器結束時才排出的緩衝 `print()`，都會交給主機一則損壞的訊息，主機就會斷線。用預設的 `logging` 設定來記錄，它的 stderr handler 會逐筆 flush；自訂 handler 也必須避開 stdout。完整說明請見 **[記錄](../handlers/logging.md)**。

Claude Desktop 會為每個伺服器各留一份記錄：`mcp-server-<NAME>.log` 是伺服器的 stderr，旁邊的 `mcp.log` 記錄連線，macOS 在 `~/Library/Logs/Claude` 底下，Windows 在 `%APPDATA%\Claude\logs`。

超出這三件事的問題，請見 **[疑難排解](../troubleshooting.md)**。

## 重點回顧 {#recap}

* **主機**（Claude Desktop、IDE）執行一個 MCP 用戶端，透過 stdio 把你的伺服器當成子處理程序啟動。連接就是給它一道啟動指令。
* 這道指令是 `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`：不用啟用 venv，從任何目錄都能執行。
* **Claude Desktop** 是 `mcp install` 唯一能替你設定的主機。它把同一道指令（加上 `uv` 的絕對路徑、`--frozen`，以及精確鎖定你已安裝的版本）寫進 `claude_desktop_config.json`，你永遠不必自己動手。
* **Claude Code** 是 `claude mcp add bookshop -- <launch command>`。**Cursor** 是 `.cursor/mcp.json`，放在 `mcpServers` 底下。**VS Code** 是 `.vscode/mcp.json`，放在 `servers` 底下，每個項目都有 `type`。
* 到處都用絕對路徑，改完設定後重新啟動主機，而且除了 SDK 之外，絕不讓任何東西寫到 stdout。

這一頁上每個主機都連到同一個檔案，用的是同一道指令。這個檔案能**公開**什麼，就是這份文件其餘的內容：**[工具](../servers/tools.md)**、**[資源](../servers/resources.md)**，以及 **[執行伺服器](../run/index.md)** 裡 stdio 以外的每一種傳輸方式。
