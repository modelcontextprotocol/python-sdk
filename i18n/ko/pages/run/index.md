---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# 서버 실행하기 {#running-your-server}

`mcp.run()`이 서버를 시작합니다.

결정해야 할 것은 **트랜스포트** 하나뿐입니다. 서버와 클라이언트 사이에서 바이트가 실제로 어떻게 오가는지를 정하는 것입니다.

## 트랜스포트 선택 {#pick-a-transport}

| 트랜스포트 | 설명 | 사용 시점 |
|---|---|---|
| `stdio` | 호스트가 파일을 서브프로세스로 실행하고 stdin과 stdout으로 통신합니다. | 로컬 서버. 기본값입니다. |
| `streamable-http` | 포트에서 수신 대기하는 실제 HTTP 서버입니다. | 배포하는 모든 것. |
| `sse` | 예전 HTTP 트랜스포트입니다. | 사용하지 않습니다. |

!!! warning
    SSE는 2025-03-26 프로토콜 개정에서 Streamable HTTP로 대체되었습니다.
    `mcp.run(transport="sse")`는 여전히 동작하며 고유한 `sse_path=`와 `message_path=`
    옵션도 있지만, 아직 옮겨 가지 않은 클라이언트를 위해 남아 있을 뿐입니다. 새로 만드는 것은 여기에 기반하지 마세요.

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()`은 동기 함수입니다. 서버가 살아 있는 동안 블로킹합니다.
* 인수가 없으면 트랜스포트는 `stdio`입니다.
* `if __name__ == "__main__":` 아래에 두는 이유는 서버를 불러오는 모든 것(`mcp dev`, `mcp run`, `mcp install`, 테스트)이 이 파일을 **임포트**하기 때문입니다. 이 가드가 임포트가 실행 중인 서버로 바뀌는 것을 막아 줍니다.

### stdio {#stdio}

설정할 것이 없습니다. 호스트가 파일을 자식 프로세스로 시작하고, stdin에 요청을 쓰고, stdout에서 응답을 읽습니다.

직접 실행해 보면 그 결과를 확인할 수 있습니다.

```console
python server.py
```

아무것도 출력되지 않고, 반환하지도 않습니다. 호스트가 먼저 말을 걸기를 stdin에서 기다리고 있는 것입니다.

이는 stdout이 **곧 통신 회선**이라는 뜻이기도 합니다. 서비스하는 동안 SDK는 이 회선을 비공개 디스크립터로 옮기고, stdout으로 **플러시되는** 출력(상속받은 stdout에 쓰는 서브프로세스, 플러시된 `print()`)을 스트림을 망가뜨릴 수 없는 stderr로 돌립니다. 서비스가 시작되기 **전에** stdout으로 플러시된 출력(래퍼 스크립트의 echo, 버퍼링되지 않은 임포트 시점의 print)은 여전히 회선에 실리며, 인터프리터가 종료 시 비울 때까지 버퍼에 남아 있는 `print()`도 마찬가지입니다. 실제로 원하는 출력에는 `logging` 모듈이 알맞은 도구입니다. 이 모듈의 핸들러는 각 레코드를 발생 즉시 stderr로 플러시합니다. 자세한 내용은 **[로깅](../handlers/logging.md)**에서 확인하세요.

### 직접 해 보기 {#try-it}

```console
uv run mcp dev server.py
```

Inspector는 실제 호스트가 하는 일을 그대로 합니다. `server.py`를 서브프로세스로 실행하고 stdio로 연결합니다.

포트를 지정한 적이 없습니다. 포트는 애초에 없습니다.

## Streamable HTTP {#streamable-http}

같은 서버를 포트에 올리려면 `run()`에 트랜스포트(와 그 옵션)를 지정하세요.

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

그 한 줄이 Starlette 앱을 만들고 uvicorn으로 서비스합니다. 클라이언트는 `http://127.0.0.1:3001/mcp`에 연결합니다.

트랜스포트마다 고유한 키워드 인수가 있으며, 모두 `run()`에 전달합니다.

* `host` / `port`: 수신 대기할 위치. 기본값은 `127.0.0.1`과 `8000`입니다.
* `streamable_http_path`: MCP 엔드포인트가 위치하는 경로. 기본값은 `/mcp`입니다.
* `json_response=True`: 각 POST에 SSE 스트림 대신 단일 JSON 본문으로 응답합니다. 이 본문에는 응답 외에 다른 것을 담을 자리가 없으므로, 요청 도중 클라이언트를 다시 호출하는 도구(`ctx.elicit()`, 샘플링)는 이 구간에서 `NoBackChannelError`를 발생시키고, 진행 중인 호출에 묶인 알림(`ctx.report_progress()`의 진행 상황, 호출별 로그 메시지)은 버려집니다. 독립된 `GET` 스트림은 관련 없는 알림을 여전히 전달합니다.
* `stateless_http=True`: 요청마다 새 트랜스포트를 만들고 세션을 추적하지 않습니다.
* `max_request_body_size`: 허용되는 POST 본문의 최대 크기(바이트). 기본값은 4MiB이며, 더 큰 요청은
  파싱이나 세션 생성 전에 HTTP 413을 받습니다. 정상적인 MCP 메시지가 이 크기를 넘을 때만
  올리세요.
* `event_store`, `retry_interval`, `transport_security`: 재개 가능성과 DNS 리바인딩 보호. localhost가 아닌 곳에 배포하기 전까지는 미뤄도 됩니다. `transport_security`는 **[배포와 확장](deploy.md)**에서 다룹니다.

!!! warning
    트랜스포트 옵션은 `MCPServer(...)`가 **아니라** `run()`에 전달합니다. 생성자는 서버가
    **무엇인지**(이름, 버전, 지침)를 기술하고, `run()`은 어떻게 서비스되는지를 기술합니다. 거꾸로
    하면 MCP가 관여하기도 전에 Python이 답합니다.

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()`은 지름길입니다. 더 많은 것이 필요한 순간(기존 앱 안에 서버를 마운트하기, 한 프로세스에 서버 두 개, 브라우저 클라이언트를 위한 CORS)이 오면, ASGI 앱을 직접 만들어 아무 ASGI 호스트에나 넘기면 됩니다. 그 내용은 **[기존 앱에 추가하기](asgi.md)**에 있습니다.

## 서버 설정 {#server-settings}

실행에 관한 것 중 몇 가지는 트랜스포트와 관계가 없습니다. 생성자 인수입니다.

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: `MCPServer(...)`가 생성되는 순간 `logging.basicConfig()`에 전달됩니다. 이는 **루트** 로거를 설정하므로 SDK의 로거뿐 아니라 직접 만든 로거의 레벨도 정합니다. 기본값은 `"INFO"`입니다.
* `debug`: HTTP 트랜스포트가 만드는 Starlette 앱으로 전달됩니다. 기본값은 `False`입니다.

둘 다 `mcp.settings`에 저장되며, 런타임에 다시 읽을 수 있습니다.

## `mcp` 명령 {#the-mcp-command}

`[cli]` 엑스트라는 이 모든 것을 감싸는 작은 명령줄 도구를 설치합니다.

`mcp dev`는 **MCP Inspector** 아래에서 서버를 실행합니다.

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with`는 빌드되는 환경에 패키지를 추가하고, `--with-editable`은 직접 만든 패키지를 그 환경에 설치합니다. `PATH`에 `npx`가 있어야 합니다. Inspector는 Node.js 앱이기 때문입니다.

`mcp run`은 파일을 임포트하고, 서버 객체(모듈 수준의 `mcp`, `server`, `app`)를 찾아 `run()`을 호출합니다.

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

`:` 접미사는 객체 이름이 `mcp`, `server`, `app`이 아닐 때 객체를 지정합니다.

여기서는 `if __name__ == "__main__":` 블록이 전혀 실행되지 않습니다. `mcp run`이 직접 `run()`을 호출하며, 전달하는 옵션은 `--transport`뿐입니다.

`mcp install`은 서버를 **Claude Desktop**에 등록해 앱이 대신 실행하도록 합니다.

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE`와 `-f .env`는 환경 변수를 해당 항목에 기록합니다. Claude Desktop은 서버를 자체 프로세스에서 시작합니다. 셸의 환경은 거기에 없습니다.

`mcp install`이 아는 호스트는 Claude Desktop뿐입니다. 다른 호스트(Claude Code, Cursor, VS Code)는 모두 같은 실행 명령을 각자의 설정 파일에 받으며, 호스트별 방법은 **[실제 호스트에 연결하기](../get-started/real-host.md)**에서 확인하세요.

`mcp version`은 설치된 SDK 버전을 출력합니다.

!!! tip
    `mcp dev`와 `mcp run`은 `MCPServer`만 이해합니다. 저수준 `Server`로 만들었다면
    직접 실행해야 합니다. **[저수준 Server](../advanced/low-level-server.md)**를 참고하세요.

## 요약 {#recap}

* **트랜스포트**는 바이트가 서버에 도달하는 방식입니다. 로컬 서브프로세스에는 `stdio`, 포트에는 `streamable-http`를 씁니다. SSE는 대체되었습니다.
* `mcp.run()`이 트랜스포트를 고릅니다. 인수가 없으면 `stdio`이고, 블로킹합니다.
* 모든 트랜스포트 옵션(`host`, `port`, `streamable_http_path`, ...)은 `run()`의 인수이지, 결코 `MCPServer(...)`의 인수가 아닙니다.
* `run()`은 `if __name__ == "__main__":` 아래에 두세요. 서버를 불러오는 모든 것이 먼저 파일을 임포트합니다.
* `log_level=`과 `debug=`는 생성자 인수이며 `mcp.settings`에 저장됩니다.
* Inspector에는 `mcp dev`, 파일 실행에는 `mcp run`, Claude Desktop에는 `mcp install`, 버전 확인에는 `mcp version`을 씁니다.
* 트랜스포트는 서버가 **무엇인지**를 결코 바꾸지 않습니다. 이 페이지의 세 파일은 모두 동일한 도구를 노출합니다.

`run()` 자체가 한계인 경우(이미 존재하는 앱 안에 서버를 넣는 경우)는 **[기존 앱에 추가하기](asgi.md)**에서 다룹니다. 실제 호스트 이름과 둘 이상의 워커는 **[배포와 확장](deploy.md)**에서 다룹니다. 그리고 일부 클라이언트가 아직 사양 버전 2025-11-25 이하에 머물러 있다면, **[레거시 클라이언트 서비스하기](legacy-clients.md)**에서 반가운 소식을 확인하세요.
