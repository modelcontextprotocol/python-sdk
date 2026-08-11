---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# 실제 호스트에 연결하기 {#connect-to-a-real-host}

**호스트**는 서버가 최종적으로 들어가 동작하는 애플리케이션입니다. Claude Desktop, Claude Code, IDE가 여기에 해당하며, 사용자가 대화하는 상대가 바로 호스트입니다. 호스트 안에서는 MCP **클라이언트**가 서버를 자식 프로세스로 실행하고, 그 프로세스의 stdin과 stdout을 통해 서버와 통신합니다.

따라서 호스트에 연결하는 일은 단 하나의 동작으로 끝납니다. **서버를 시작하는 명령**을 호스트에 알려 주는 것입니다. 이 페이지에 나오는 모든 것(CLI 명령 두 개, JSON 파일 세 개)은 바로 그 명령을 넣어 두는 서로 다른 위치일 뿐입니다.

## 서버 하나, 모든 호스트 {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

도구 두 개와 리소스 하나가 파일 하나에 들어 있습니다. 이 파일에서 아래의 모든 호스트에 중요한 점은 세 가지입니다.

* 인자 없이 호출한 `mcp.run()`은 **stdio** 서버를 시작합니다. 블로킹 상태로 동작하며, stdin에서 프로토콜 메시지를 읽고 stdout에 씁니다. 이 페이지의 모든 호스트가 사용하는 트랜스포트가 바로 이것입니다. 호스트가 파일을 자식 프로세스로 시작하고 그 두 파이프를 소유하기 때문에, 연결은 언제나 "명령은 이것입니다"로 끝납니다. 포트를 고를 일이 없고, 포트에서 대기하는 것도 없습니다.
* `run()`은 `if __name__ == "__main__":` 아래에 있습니다. 아래에 나오는 모든 방법은 이 파일을 실행하는 대신 **임포트**하므로, 가드 없이 `run()`을 두면 무엇이든 이 모듈을 로드하는 순간 서버가 시작되어 버립니다.
* 서버 객체는 `mcp`라는 이름의 모듈 수준 전역 변수입니다. `mcp run`이 찾는 이름이 바로 이것입니다(`server`와 `app`도 동작합니다). 다른 이름을 쓴다면 `mcp run server.py:bookshop`처럼 명시적으로 지정합니다.

이것이 이 페이지의 마지막 Python 코드입니다. 여기서부터는 전부 호스트 설정입니다.

## 실행 명령 {#the-launch-command}

아래의 모든 호스트에는 같은 명령을 사용합니다.

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

모든 호스트에 명령 하나로 충분한 이유는 `uv run --with`가 그 자리에서 SDK를 새 환경에 설치해 주기 때문입니다. 어느 디렉터리에서든 동작하며, 프로젝트도 활성화할 가상 환경도 필요 없습니다. 이 점은 다른 어느 곳보다 여기서 중요합니다. 호스트는 셸이 아니라 **호스트 자신의** 작업 디렉터리에서, 거의 비어 있는 환경으로 서버를 실행하기 때문입니다.

이 명령은 `mcp install`이 Claude Desktop 설정에 대신 써 주는 명령이기도 합니다(아래 참고). 따라서 직접 입력하는 내용과 도구가 생성하는 내용은, 도구가 덧붙이는 정확한 버전 고정만 빼면 일치합니다.

!!! tip "호스트가 `uv`를 찾지 못할 때"
    호스트는 최소한의 `PATH`로 서버를 실행하므로 `uv`가 그 안에 없을 수 있습니다. 그냥 `uv`라고
    쓴 부분을 `which uv`(macOS/Linux) 또는 `where uv`(Windows)로 얻은 절대 경로로 바꾸세요.
    `mcp install`이 쓰는 것도 정확히 이것입니다.

!!! note "이 페이지는 로컬 실행을 다룹니다"
    여기 나오는 모든 방법은 호스트가 있는 바로 그 머신에서 서버를 실행합니다. 호스트가 파일을
    stdio로 직접 실행하는 방식입니다. 개인용 도구나 머신 한 대에서 쓰는 도구라면 이것이 정확히
    맞는 방법입니다. 파일을 **가지고 있지 않은** 사람들에게 서버를 제공하려면 명령이 아니라
    **URL**을 건네야 합니다. 같은 `mcp` 객체를 Streamable HTTP로 서비스하는 것입니다.
    **[서버 실행하기](../run/index.md)**는 그 결정을 표 하나로 정리하고,
    **[배포와 확장](../run/deploy.md)**은 거기서 실제 호스트 이름까지 가는 길을 안내합니다.

    그리고 호스트란 MCP 클라이언트를 품은 애플리케이션에 지나지 않으므로, 직접 작성한 Python
    코드도 호스트 역할을 할 수 있습니다. **[클라이언트 트랜스포트](../client/transports.md)**에서는
    `stdio_client(...)`로 같은 파일을 서브프로세스로 실행하고, **[테스트](testing.md)**에서는
    프로세스 없이 인메모리로 연결합니다.

## Claude Desktop {#claude-desktop}

SDK가 대신 설정해 줄 수 있는 유일한 호스트입니다.

```bash
uv run mcp install server.py
```

이게 전부입니다. `mcp install`은 파일을 임포트해 서버 이름을 읽고, Claude Desktop의 설정 파일을 찾아 실행 명령을 써 넣습니다. 그 과정에서 경로를 절대 경로로 바꿔 주므로 직접 할 필요가 없습니다.

감춰진 것은 아무것도 없습니다. 써 넣는 항목은 다음과 같습니다.

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

앞 절의 실행 명령에 세 가지가 더해진 것입니다. `uv`의 절대 경로, 근처에 있는 락파일을 `uv`가 다시 쓰지 않도록 하는 `--frozen`, 그리고 설치된 `mcp` 버전을 정확히 지정하는 버전 고정입니다. 이 항목은 `claude_desktop_config.json`에 들어가며, 파일 위치는 다음과 같습니다.

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

이 파일은 손으로 직접 써도 됩니다. `mcp install`은 그 과정에서 흔히 하는 실수(상대 경로)를 막기 위해 존재합니다.

Claude Desktop을 창만 닫지 말고 완전히 종료한 뒤 다시 여세요.

!!! warning
    Claude Desktop의 설정 **디렉터리**가 아직 없으면 `mcp install`은 `Claude app not found` 오류로
    실패합니다. Claude Desktop을 설치하고 한 번 실행하세요. 디렉터리는 그때 만들어집니다.

!!! tip
    Claude Desktop은 서버를 별도의 프로세스로 시작하므로 셸의 환경 변수는 거기에 없습니다.
    `uv run mcp install server.py -v API_KEY=abc123` 명령(또는 `-f .env` 옵션)을 사용하면 환경
    변수가 항목의 `env` 필드에 기록됩니다. `--name` 옵션은 항목 이름을 덮어쓰며, 기본값은 서버의
    `name`입니다.

## Claude Code {#claude-code}

편집할 파일은 없습니다. `claude` CLI로 서버를 등록하세요. `--` 뒤에 오는 모든 것이 실행 명령입니다.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Claude Code 세션 안에서 `/mcp`를 실행해 `bookshop`이 연결되어 있고 도구가 나열되는지 확인하세요.

## Cursor {#cursor}

프로젝트 루트에 `.cursor/mcp.json` 파일을 만드세요.

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

Claude Desktop이 쓰는 것과 같은 `mcpServers` 키 아래에, 같은 `command`와 `args`가 들어갑니다. 서버는 Cursor의 MCP 설정에 두 도구와 함께 나타납니다.

## VS Code {#vs-code}

프로젝트 루트에 `.vscode/mcp.json` 파일을 만드세요.

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

Cursor의 파일과 다른 점은 두 가지이며, 정확히 그 두 가지뿐입니다. 감싸는 키가 `mcpServers`가 아니라 `servers`라는 점, 그리고 각 항목이 `type`을 선언한다는 점입니다. 신뢰 여부를 묻는 메시지를 확인한 뒤 명령 팔레트에서 **MCP: List Servers**를 실행하면 `bookshop`이 실행 중으로 표시됩니다.

!!! note
    VS Code 1.99 이상이 필요하고 **GitHub Copilot** 확장에 로그인되어 있어야 합니다(Copilot Free면
    충분합니다). 또한 Copilot Chat은 **Agent** 모드여야 합니다. 다른 모드는 도구를 호출하지 않기
    때문입니다.

## 서버가 나타나지 않을 때 {#it-doesnt-show-up}

호스트 설정을 건드리기 전에 실행 명령을 직접 실행해 보세요.

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

아무것도 출력되지 않고, 명령이 반환되지도 않습니다. 이 침묵이 정상입니다. stdio 서버는 호스트가 stdin으로 먼저 말을 걸기를 기다리고 있습니다(멈추려면 `Ctrl-C`를 누르세요). 트레이스백이 뜨거나 즉시 종료된다면 그것이 진짜 버그이며, 이제 호스트 너머로 추측하는 대신 직접 읽을 수 있습니다.

이 명령이 가만히 대기하는 상태가 되었다면, 남은 원인은 거의 항상 다음 세 가지 중 하나입니다.

* **상대 경로.** 호스트는 등록할 때 있던 디렉터리가 아니라 **호스트 자신의** 작업 디렉터리에서 서버를 실행합니다. `/absolute/path/to/server.py`가 필요한 자리에 `server.py`를 쓰는 것이 단연 가장 흔한 실패 원인입니다. 호스트가 `uv`도 찾지 못한다면 그 경로 역시 절대 경로여야 합니다.
* **호스트가 아직 예전 설정으로 동작 중인 경우.** 호스트는 시작할 때 설정을 읽습니다. 특히 Claude Desktop은 창만 닫는 것이 아니라 **완전히 종료**한 뒤 다시 열어야 `claude_desktop_config.json`을 수정한 내용이 반영됩니다.
* **우회 구간 밖에서 무언가가 stdout에 도달한 경우.** stdio에서는 stdout이 **곧** 프로토콜입니다. SDK는 서버가 동작하는 동안 플러시된 엉뚱한 출력을 stderr로 돌려 보내지만, 그 전에 stdout으로 플러시된 출력(래퍼 스크립트의 echo, 버퍼링하지 않는 프로세스에서 임포트 시점에 실행된 `print()`)이나 인터프리터 종료 시점에 비워지는 버퍼링된 `print()`는 호스트에 손상된 메시지를 건네게 되고, 호스트는 연결을 끊어 버립니다. 기본 `logging` 설정으로 로그를 남기세요. 기본 설정의 stderr 핸들러는 레코드마다 플러시합니다. 사용자 정의 핸들러도 stdout을 피해야 합니다. 자세한 내용은 **[로깅](../handlers/logging.md)**에서 확인하세요.

Claude Desktop은 서버마다 로그를 남깁니다. `mcp-server-<NAME>.log`가 서버의 stderr이고, 연결을 기록하는 `mcp.log`가 그 옆에 있습니다. 위치는 macOS에서 `~/Library/Logs/Claude`, Windows에서 `%APPDATA%\Claude\logs`입니다.

이 세 가지를 넘어서는 문제는 **[문제 해결](../troubleshooting.md)** 페이지를 참고하세요.

## 요약 {#recap}

* **호스트**(Claude Desktop, IDE)는 MCP 클라이언트를 실행하고, 이 클라이언트가 서버를 자식 프로세스로 띄워 stdio로 통신합니다. 연결한다는 것은 호스트에 실행 명령 하나를 알려 주는 것입니다.
* 그 명령은 `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`입니다. 활성화할 가상 환경이 필요 없고, 어느 디렉터리에서든 동작합니다.
* **Claude Desktop**은 `mcp install`이 대신 설정해 주는 유일한 호스트입니다. 바로 그 명령에 `uv`의 절대 경로, `--frozen`, 설치된 버전을 정확히 지정하는 버전 고정을 더해 `claude_desktop_config.json`에 써 주므로 직접 쓸 일이 전혀 없습니다.
* **Claude Code**는 `claude mcp add bookshop -- <launch command>`입니다. **Cursor**는 `.cursor/mcp.json`의 `mcpServers` 아래입니다. **VS Code**는 `.vscode/mcp.json`의 `servers` 아래이며, 각 항목에 `type`을 둡니다.
* 어디서나 절대 경로를 쓰고, 설정을 수정한 뒤에는 호스트를 다시 시작하며, SDK 외에는 무엇도 stdout에 쓰지 못하게 하세요.

이 페이지의 모든 호스트가 같은 파일에, 같은 명령으로 연결했습니다. 그 파일이 무엇을 **노출할 수 있는지**는 이 문서의 나머지가 다룹니다. **[도구](../servers/tools.md)**, **[리소스](../servers/resources.md)**, 그리고 stdio 외의 모든 트랜스포트는 **[서버 실행하기](../run/index.md)**에서 확인하세요.
