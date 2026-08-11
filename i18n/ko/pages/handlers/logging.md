---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# 로깅 {#logging}

도구에서 로그를 남기는 방법은 다른 Python 함수에서와 똑같습니다. 표준 라이브러리를 사용하세요.

MCP에는 프로토콜 수준의 **로깅 기능**이 있습니다. 서버가 `Context` 객체의 메서드를 통해 로그 메시지를 알림으로 클라이언트에 보낼 수 있는 기능입니다. 사양의 2026-07-28 리비전은 **이 기능을 지원 중단 예정(deprecated)으로 지정하면서 대체 수단을 제공하지 않으므로**, 이 문서에서는 다루지 않습니다. 지원 중단 예정인 항목 전체와 대신 사용할 방법은 **[지원 중단 예정 기능](../deprecated.md)**에서 확인하세요.

대신 할 일은 다른 모든 Python 프로그램에서 하는 것과 같습니다. 표준 라이브러리를 사용합니다.

## 로그를 남기는 도구 {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)`은 모듈 이름을 딴 로거를 돌려줍니다. 파일 맨 위에서 한 번만 만드세요.
* 도구 안에서는 다른 함수에서와 마찬가지로 `logger.info(...)`를 호출합니다. 주입할 것도, `await`할 것도, MCP에 특화된 것도 없습니다.

!!! check
    도구를 호출하고 결과 전체를 살펴보세요.

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    로그 줄은 어디에도 없습니다. 로깅은 서버를 운영하는 **사람**을 위한 것입니다. 모델은
    이를 절대 보지 못합니다. 모델이 읽어야 하는 내용이 있다면 `return`으로 돌려주세요.

## 출력 위치 {#where-it-goes}

**stdio** 서버에서는 이 질문이 평소보다 중요합니다. 호스트는 서버를 서브프로세스로 실행했고, 서버의 **stdout**에서 MCP 메시지를 읽고 있습니다. 표준 에러는 서버의 몫입니다.

표준 라이브러리는 이미 올바르게 동작합니다. 로그 출력은 기본적으로 `sys.stderr`로 갑니다. `logger.info(...)` 줄은 터미널(또는 호스트가 서브프로세스의 stderr를 수집하는 곳)에 도착하고, 프로토콜 스트림은 깨끗하게 유지됩니다.

!!! tip
    stdio 서버에서는 `print()`를 쓰지 마세요. `print`는 **stdout**에 쓰는데, stdout은 프로토콜의 몫입니다.
    서비스 중에 SDK는 실제로 **플러시된** stdout 출력을 stderr로 돌리므로 통신을 망가뜨릴 수는
    없지만, 블록 버퍼링되는 프로세스에서 `print()`의 출력은 대개 플러시되지 않은 채 `sys.stdout`의
    버퍼에 남아 있다가, 인터프리터가 종료 시 버퍼를 비울 때 프로토콜 스트림으로 그대로 흘러 들어갑니다.
    설령 stderr로 돌려지더라도 그 줄은 레벨도, 로거 이름도, 걸러낼 방법도 없이 날것 그대로 로그 출력
    사이에 섞입니다.

    `logger.debug("got here")`는 똑같이 한 줄이면 되고, 올바른 곳으로 갑니다.

## 레벨 {#the-level}

`logging.basicConfig()`를 직접 호출할 필요는 없습니다. `MCPServer`를 생성하는 것만으로 이미 호출되며, 핸들러는 표준 에러를 향하고 레벨은 `log_level=`로 전달한 값을 따릅니다. 따라서 `logger.debug(...)` 줄을 보려면 `MCPServer("Bookshop", log_level="DEBUG")`만으로 충분합니다.

기본값은 `"INFO"`입니다.

`logging.basicConfig()`는 이미 존재하는 핸들러를 절대 교체하지 않습니다. 서버를 만들기 전에 로깅을 직접 설정했다면 그 설정이 우선합니다.

## 직접 해 보기 {#try-it}

MCP Inspector로 서버를 실행하세요.

```console
uv run mcp dev server.py
```

**Tools** 탭에서 `search_books`를 호출하세요. Inspector가 보여주는 결과는 반환값뿐입니다. 다음 줄은

```text
Searching for 'dune'
```

표준 에러로 갔습니다. 통신이 아니라 터미널입니다.

!!! info
    정말로 원하는 것이 **트레이싱**(모든 요청, 걸린 시간, 실패 여부)이라면 로그 줄이 아니라
    스팬이 필요합니다. 서버는 이미 스팬을 내보내고 있습니다. SDK는 기본적으로 모든 메시지를
    OpenTelemetry로 추적합니다. **[OpenTelemetry](../run/opentelemetry.md)**를 참고하세요.

## 요약 {#recap}

* MCP 프로토콜의 로깅 기능은 2026-07-28 사양에서 지원 중단 예정으로 지정되었고 대체 수단이 없습니다. 이 기능 위에 무언가를 만들지 마세요.
* 모듈 수준에 `logger = logging.getLogger(__name__)`, 도구 안에 `logger.info(...)`. 이것이 패턴의 전부입니다.
* 로그 출력은 절대 모델에 닿지 않습니다. `return`한 값만 닿습니다.
* 표준 에러는 서버의 몫이고 stdout은 프로토콜의 몫입니다. SDK는 서비스 중 플러시된 stdout 출력을 stderr로 돌리지만, 플러시되지 않은 `print()`는 종료 시 여전히 통신으로 흘러 들어갈 수 있고, 돌려진 줄은 레이블 없이 도착합니다. 레코드마다 핸들러가 플러시하는 `logging`을 사용하세요.
* `MCPServer(..., log_level="DEBUG")`로 레벨을 설정하며, 먼저 만든 로깅 설정은 그대로 유지됩니다.

서버에서 무언가(도구 목록, 리소스)가 바뀌었음을 연결된 클라이언트에 알리는 방법은 **[구독](subscriptions.md)**에서 다룹니다.
