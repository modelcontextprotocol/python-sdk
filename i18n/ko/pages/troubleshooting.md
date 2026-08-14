---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# 문제 해결 {#troubleshooting}

이 페이지의 모든 제목은 SDK가 내는 오류 메시지를 글자 그대로 옮긴 것이고, 그 아래에 그 의미와 한 번에 끝나는 해결책이 이어집니다. 트레이스백(또는 서버 로그)의 마지막 줄을 브라우저의 페이지 내 찾기로 이 페이지에서 검색한 뒤, 해당 항목만 읽으세요.

여러 항목이 아래의 서버 하나를 대상으로 합니다. 도구 하나와 템플릿 리소스 하나로 이루어져 있으며, 둘 다 모르는 도시가 들어오면 예외를 일으킵니다.

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

이 페이지에서 인용하는 오류는 모두 실제 오류입니다. SDK 자체의 테스트 스위트가 하나하나 전부 재현합니다.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

이것은 MCP 오류가 아닙니다. anyio가 내는 잡음이며, 진짜 오류는 붙여 넣은 내용의 **마지막 줄**에 있습니다.

`Client.__aenter__`에서 태스크 그룹이 시작됩니다. anyio는 태스크 그룹을 빠져나가는 모든 것을 `ExceptionGroup`으로 감싸므로, `async with Client(...)` 블록을 벗어나는 예외는 종류와 상관없이 **전부** 그 안에 담겨 도착합니다.

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

이에 대해 할 일은 두 가지입니다.

1. **맨 아래를 읽으세요.** `MCPError: No forecast for 'Atlantis'.`가 실패의 원인입니다. 이 페이지에서 찾아야 할 것은 바로 **이** 텍스트입니다.
2. **블록 안에서 잡으세요.** `ExceptionGroup`은 예외가 `async with`를 **벗어날** 때만 나타납니다. 안에서 잡으면 같은 실패가 그룹 없이 평범한 `MCPError`로 나타납니다.

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    **연결** 도중의 실패(잘못된 URL, 실행 중이 아닌 서버, 이 페이지 아래쪽의 `421`)는
    `async with` 자체에서 빠져나오므로, 잡을 수 있는 "안쪽"이 없습니다.
    이런 경우에는 그룹의 맨 아래를 읽으세요.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)`는 객체를 만들기만 합니다. `async with`에 들어가기 전에는 아무것도 연결되지 않으므로 모든 메서드가 거부합니다.

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

블록에 진입하세요. 연결은 `__aenter__`에서 맺어집니다.

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

연결을 끊는 일은 `__aexit__`에서 일어나므로, 잊어버릴 `client.close()` 같은 것은 없습니다. **[테스트](get-started/testing.md)**는 바로 이 패턴 위에 만들어져 있습니다.

## `Error executing tool <name>: <message>` 및 `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

지금 보고 있는 것은 예외가 아니라 **결과**입니다. `call_tool`은 예외를 일으키지 않았고, 실패한 도구에 대해서는 앞으로도 절대 일으키지 않습니다.

서버가 모르는 도시로 `forecast`를 호출하면, 도구가 일으킨 예외는 **성공**으로 표시된 요청에 담겨 돌아옵니다.

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast`는 서버에 등록된 적 없는 이름에 대해 같은 형태로 나타나며, 잘못된 인자도 함수가 실행되기 전에 도구의 입력 스키마에 비추어 같은 방식으로 거부됩니다.

해결책은 클라이언트 쪽에 있습니다. **`result.is_error`를 확인하세요.** `call_tool`을 `try/except`로 감싸도 잡히는 것은 하나도 없습니다. 잡을 것이 없기 때문입니다. 이것은 의도된 설계이며, 이 페이지에서 가장 체득할 가치가 있는 한 가지입니다. 호출을 선택한 것은 **모델**이므로, 메시지를 받고 다시 시도할 기회를 얻는 것도 모델입니다. 예외를 **실제로** 일으키는 `MCPError` 경로를 포함해 자세한 내용은 **[오류 처리](servers/handling-errors.md)**에서 확인하세요.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

`@mcp.tool()` 대신 `@mcp.tool`을 쓴 경우입니다. `tool()`은 데코레이터 **팩토리**이므로, 괄호가 없으면 Python은 함수를 `name=` 매개변수에 넘겨 버립니다.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

괄호를 추가하세요. `@mcp.resource(...)`와 `@mcp.prompt()`도 같은 실수에 같은 메시지를 냅니다.

!!! note
    이 예외는 클라이언트가 연결되기 전, 모듈을 **임포트**하는 시점에 발생합니다. 따라서 호스트가
    서버를 도구 0개로 연결된 상태가 아니라 **시작 실패**(또는 **연결 끊김**)로 표시한다면
    이 경우에 해당합니다. 직접 `python server.py`를 실행해 트레이스백을 읽으세요. 타입 검사기도
    이를 잡아냅니다. 함수는 유효한 `name=` 값이 아니기 때문입니다.

## `Tool already exists: <name>` {#tool-already-exists-name}

두 등록이 같은 도구 이름을 사용한 경우입니다. **먼저** 등록된 쪽이 이기고 두 번째는 조용히 버려지며, **서버 로그**에 남는 이 경고가 유일한 신호입니다.

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list`가 보고하는 `forecast`는 하나뿐이고, 그 정체는 `forecast_today`입니다. 둘 중 하나의 이름을 바꾸세요. `MCPServer(..., warn_on_duplicate_tools=False)`는 결과는 바꾸지 않은 채 경고만 끄므로, 켜 둔 채로 두세요. 리소스와 프롬프트에도 같은 규칙과 같은 로그 줄(`Resource already exists:`, `Prompt already exists:`)이 적용됩니다.

## 호스트에 도구가 하나도 나타나지 않는 경우 {#my-host-lists-zero-tools}

이 경우에는 오류 문자열이 없으며, 바로 그래서 검색하기 어렵습니다. SDK는 등록된 도구를 `tools/list`에서 절대 빠뜨리지 않으므로, 안쪽부터 바깥쪽으로 차례로 확인하세요.

* **서버가 시작되기는 했습니까?** 괄호 없는 `@mcp.tool`은 임포트 시점에 예외를 일으키며, 일부 호스트에서는 죽은 서버가 빈 서버와 매우 비슷하게 보입니다. 직접 `python server.py`를 실행해 보세요.
* **호스트가 실행하는 `mcp`에 도구가 등록되어 있습니까?** 다른 모듈의 두 번째 `MCPServer(...)`는 별개의 빈 서버입니다. 호스트의 명령이 실제로 어느 객체를 임포트하는지 확인하세요.
* **두 도구가 같은 이름을 썼습니까?** 그렇다면 둘 중 하나는 사라졌습니다. 서버 로그에서 `Tool already exists:`를 찾아보세요.
* **호스트의 목록이 오래된 것입니까?** 시작 이후에 추가한 도구는 `notifications/tools/list_changed`를 처리하는 클라이언트에만 전달됩니다. 호스트를 재시작하는 것이 투박하지만 확실한 해결책입니다.
* **전환 구간 밖에서 무언가가 `stdout`에 썼습니까?** 서비스 중에는 SDK가 **플러시된** 엉뚱한 stdout 출력을 stderr로 돌립니다(최선 노력 방식이며, 표준 스트림을 교체하는 환경은 그대로 서비스됩니다). 하지만 그보다 먼저 stdout으로 플러시된 출력(래퍼 스크립트의 echo, 버퍼링이 꺼진 프로세스의 임포트 시점 `print()`)이나 인터프리터 종료 시 비워지는 버퍼링된 `print()`는 프로토콜 스트림에 실리며, 쓰레기 한 줄만으로도 호스트가 연결을 끊을 수 있고 일부 호스트는 이를 아무것도 없는 서버로 표시합니다. 대신 `logging` 모듈로 로그를 남기세요. 호스트 쪽 점검 목록의 나머지는 **[실제 호스트에 연결하기](get-started/real-host.md)**에 있습니다.

"유효하지 않은" 도구 이름은 이 목록에 **없습니다**. 규격에 맞지 않는 이름은 경고를 남기지만, 도구는 어쨌든 등록되고 목록에도 나타납니다.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

서버가 HTTP 요청을 단칼에 거부했고 본문이 JSON-RPC가 아니어서, Python `Client`가 보여 줄 수 있는 것이 이 대체 메시지뿐인 경우입니다.

압도적으로 흔한 원인은 막 배포한 Streamable HTTP 서버입니다. `transport_security=` 없이 쓴 `streamable_http_app()`(그리고 `mcp.run("streamable-http")`)은 기본값이 **DNS 리바인딩 보호**여서, `Host` 헤더가 localhost인 요청만 받습니다. 노트북에서는 올바른 기본값이지만 실제 호스트 이름 뒤에서는 잘못된 기본값입니다.

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

이것을 배포하고 클라이언트를 연결하면, 핸드셰이크에서 연결이 실패합니다.

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

서버가 실제로 보낸 문구인 `421`과 `Invalid Host header`는 클라이언트까지 오지 않습니다. 421 본문에 `Content-Type: application/json`이 없어서 클라이언트가 파싱할 수 없기 때문입니다. 이 문구는 **서버 로그**에 있으며, 다음으로 살펴볼 곳이 바로 거기입니다.

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

해결책은 `transport_security=`입니다. 실제로 서비스하는 호스트 이름을 허용 목록에 넣으세요.

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    바꿀 것은 이것이 전부입니다. 똑같은 클라이언트가 이제 연결되고, `2026-07-28`을 협상하고,
    `forecast`를 호출합니다.

각 필드의 의미, 리버스 프록시의 경우, 그 밖에 배포 시점에 달라지는 모든 것은 **[배포와 확장](run/deploy.md)**에서 다룹니다. 그리고 바로 아래의 `421 Misdirected Request` / `Invalid Host header`는 같은 실패를 반대편에서 본 모습입니다.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

이것은 `Server returned an error response`를 Python `Client`가 **아닌** 곳에서 본 모습입니다. curl, 브라우저의 네트워크 탭, 리버스 프록시의 액세스 로그, 다른 SDK 등이 여기에 해당합니다.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request`는 이 상태 코드에 HTTP 자체가 붙인 사유 문구이고, `Invalid Host header`는 SDK의 응답 본문이며, Python `Client`는 같은 사건을 `Server returned an error response`로 표시합니다. 셋 모두 하나의 거부입니다. 검사는 서버가 바인드한 주소가 아니라 **요청에 실린 `Host` 헤더**를 대상으로 하므로, 공개 호스트 이름을 그대로 전달하는 리버스 프록시도 직접 연결한 클라이언트와 똑같이 이 검사에 걸립니다.

해결책은 `Server returned an error response`에서 보인 것과 같은 `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`입니다. 짚어 둘 만한 세부 사항이 두 가지 있습니다.

* `allowed_hosts`의 항목은 정확히 일치하는 문자열입니다. `"mcp.example.com"` 항목은 포트 없는 `Host` 헤더와 일치하고, `"mcp.example.com:*"` 항목은 명시적 포트가 붙은 모든 경우와 일치합니다. 둘 다 넣으세요.
* 본문이 `Invalid Origin header`인 `403`은 `Origin` 헤더에 대한 자매 검사입니다. 브라우저에서만 발생하며(`Origin`을 보내는 것은 브라우저뿐입니다), 그 허용 목록은 `allowed_origins=`입니다.

검사를 끄는 것이 정직한 설정인 경우를 포함해 자세한 내용은 **[배포와 확장](run/deploy.md)**에서 확인하세요.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

MCP 앱이 다른 ASGI 앱 안에 마운트되어 있고, 아무것도 그 **세션 매니저**를 시작하지 않은 경우입니다.

`mcp.streamable_http_app()`은 자체 lifespan에서 매니저를 시작하는 Starlette 앱을 반환하며, `uvicorn server:app`은 그 lifespan을 대신 실행해 줍니다. 하지만 Starlette은 **마운트된 하위 애플리케이션의 lifespan을 절대 실행하지 않으므로**, 앱이 `Mount` 안으로 들어가는 순간 매니저는 시작되지 않고 첫 요청에서 터집니다.

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

서버는 시작됩니다. 라우트도 확인됩니다. 그런 다음 `uvicorn`이 모든 요청마다 다음을 출력합니다.

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

클라이언트는 500을 받습니다. 해결책은 **호스트** 앱에 `mcp.session_manager.run()`에 진입하는 lifespan을 두는 것입니다.

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

한 앱에 여러 서버를 두는 경우와 FastAPI를 포함해, 이 주제는 **[기존 앱에 추가하기](run/asgi.md)**에서 다룹니다. 같은 클래스에서 나오는 이웃 문자열이 둘 있습니다.

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` 매니저는 일회용이며, 같은 앱의 lifespan에 두 번 진입하면 이 메시지가 나옵니다.
* `mcp.session_manager`는 `streamable_http_app()`이 호출된 **뒤에야** 존재하므로, 라우트를 먼저 만들고 매니저는 lifespan 안에서만 건드리세요.

## `MCPError: Session not found` {#mcperror-session-not-found}

서버가 클라이언트가 보낸 `Mcp-Session-Id`를 알아보지 못하는 경우이며, 거의 언제나 서버가 **재시작**되었기(또는 다른 인스턴스로 라우팅되었기) 때문입니다. 세션은 해당 프로세스 하나의 메모리에만 존재합니다.

찾아야 할 서버 버그는 없습니다. HTTP 응답은 본문이 **실제로** JSON-RPC인 `404`이므로, 위의 `421`과 달리 Python `Client`가 이번에는 그대로 보여 줍니다.

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

해결책은 다시 연결하는 것입니다. `async with Client(...)` 블록을 벗어나 새 블록에 진입하면 새 세션을 협상합니다. 오래 실행되는 클라이언트라면, 호출을 감싸 `MCPError`를 잡은 뒤 이 메시지가 나오면 죽은 세션 안에서 재시도하지 말고 다시 연결해야 한다는 뜻입니다.

재시작 **없이** 이 문제가 발생한다면, 스티키 세션 없이 워커를 둘 이상 실행하고 있는 것입니다. 각 워커가 자기만의 세션 테이블을 가지므로, 엉뚱한 워커로 라우팅된 요청이 여기에 도달합니다. 이 이야기와 두 가지 해결책(스티키 라우팅 또는 `stateless_http=True`)은 **[배포와 확장](run/deploy.md)**과 **[레거시 클라이언트 지원](run/legacy-clients.md)**에서 다룹니다.

서버 운영자 쪽에서 대응하는 로그 줄은 `Rejected request with unknown or expired session ID: <id>`입니다. `INFO` 수준으로 기록되므로 일반적인 `WARNING` 임계값에서는 보이지 않습니다. 배포 직후 이 줄이 한꺼번에 쏟아지는 것은 정상입니다. 연결되어 있던 모든 클라이언트가 다시 연결하는 중이기 때문입니다.

## `MCPError: Method not found` {#mcperror-method-not-found}

한쪽이 상대에게 핸들러가 없는 JSON-RPC 요청을 보낸 경우이며, `e.error.data`에 메서드 이름이 나옵니다. 흔한 원인은 **세대 불일치**입니다. 한 프로토콜 리비전에는 있고 다른 리비전에는 없는 메서드를 엉뚱한 쪽 피어에 보낸 경우로, 예를 들어 `2025` 세대의 `resources/subscribe`가 `2026-07-28` 연결에 도착하거나, `mode="legacy"`로 고정된 클라이언트가 `2026` 전용 `subscriptions/listen`을 보내는 경우입니다. 어느 쪽이 무엇을 말하는지에 관한 지도는 **[프로토콜 버전](protocol-versions.md)**이고, 또 하나의 정직한 원인(핸들러를 등록하지 않은 선택적 기능)은 **[자동 완성](servers/completions.md)**에 있습니다.

최신 프로토콜에서 제거된 요청인데도 이 오류를 **내지 않는** 경우가 하나 있습니다. `2026-07-28` 연결에서 도구가 `ctx.elicit()`을 호출하는 경우입니다. 서버가 그 요청을 **보내는** 것 자체를 거부하므로, 대신 받게 되는 것은 이 페이지 아래쪽의 `Cannot send 'elicitation/create': ...`입니다.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

서버가 사용자에게 무언가를 물어보려 하는데, 이 클라이언트가 물어볼 수 있다고 밝힌 적이 없는 경우입니다.

엘리시테이션(elicitation) 리졸버는 연결된 클라이언트가 폼 엘리시테이션을 선언하지 않았으면 처음부터 거부하며, `e.error.data`가 정확히 무엇이 빠졌는지 알려 줍니다.

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

`Client(...)`에 `elicitation_callback=` 인자를 전달하세요. 콜백을 등록하는 것이 **곧** 기능 선언이며, 별도의 스위치는 없습니다.

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

나머지 콜백(`sampling_callback`, `list_roots_callback`)은 **[클라이언트 콜백](client/callbacks.md)**에 나열되어 있으며, 각각 같은 방식으로 선언 역할을 합니다.

!!! info
    `-32021`은 `MISSING_REQUIRED_CLIENT_CAPABILITY`로, 2026-07-28 사양이 추가한 세 오류 코드 중
    하나입니다. 셋 중 어느 것도 예외 클래스가 아닙니다. 모두 `MCPError`로 도착하며, 살펴볼 곳은
    `e.error.code`입니다. 상수는 `mcp.types`가 내보냅니다. 나머지 둘은
    `-32020` `HEADER_MISMATCH`(HTTP 헤더가 함께 온 요청 본문과 어긋남)와
    `-32022` `UNSUPPORTED_PROTOCOL_VERSION`(요청이 이 서버가 말하지 않는 버전을 지정함)입니다.
    규격을 따르는 SDK 클라이언트는 둘 다 만들어 낼 수 없으므로, 둘 중 하나가 보인다면 클라이언트와
    서버 사이에서 요청을 고쳐 쓰는 무언가를 살펴보세요.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

`Client did not declare the form elicitation capability ...` 항목과 같은 공백을, 미리 검사하지 않는 경로가 표현한 것입니다. 서버는 엘리시테이션에 대한 답이 필요했고, 연결된 클라이언트는 `elicitation_callback`을 등록하지 않았습니다.

이 메시지는 레거시 연결에서 `ctx.elicit()`을 호출할 때 나타나며, 반환된 다중 왕복 질문(**[다중 왕복 요청](handlers/multi-round-trip.md)**)이 답할 콜백이 없는 클라이언트에 도달하면 어떤 연결에서든 나타납니다. 해결책은 동일합니다. `Client(...)`에 `elicitation_callback=` 인자를 전달하세요. "사용자에게 묻지 않았다"는 상황이 도구에 `decline`으로 전달되는 경우는 없습니다. 물어볼 수 없는 클라이언트는 곧 실패한 호출이므로, 도구를 그에 맞게 설계하세요.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

핸들러가 요청 도중에 클라이언트에 손을 뻗으려 했는데, 그 호출에 서버의 요청을 실어 나를 채널이 없는 연결이었던 경우입니다. 호출을 이런 상황에 놓는 서버 구성은 세 가지입니다.

**`2026-07-28` 연결. 트랜스포트와 무관하게 항상.** 최신 프로토콜에는 서버가 시작하는 요청이 아예 없으므로, 서버는 무엇을 보내기도 전에 거부합니다. 도구 안에서 `ctx.elicit()`을 호출하는 것이 이 오류를 만나는 전형적인 길이며(`Client(server)`는 따로 요청하지 않아도 `2026-07-28`을 협상하므로, 첫 인메모리 테스트에서 바로 만납니다), `elicitation_callback=` 인자를 전달해도 달라지는 것은 없습니다. 클라이언트가 답할 요청 자체가 도달하지 않기 때문입니다.

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**`stateless_http=True` 서버의 레거시 연결.** 무상태란 모든 요청이 저마다 독립된 세계라는 뜻입니다. 세션도, 서버에서 클라이언트로 가는 스트림도 없으므로, 해당 메서드가 있는 세대라 해도 `elicitation/create`(또는 `sampling/createMessage`, `roots/list`)를 보낼 곳이 없습니다.

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**`json_response=True` 서버의 레거시 연결.** `POST`에는 JSON 본문 하나로 응답하며, 본문 하나에는 응답만 실리므로, 요청 도중의 `ctx.elicit()`에 필요한 요청 범위 스트림이 여기에도 존재하지 않습니다. 세션, 그 `Mcp-Session-Id`, 독립 스트림은 모두 그대로 있고, 사라진 것은 요청 범위 채널뿐입니다.

메시지에는 보내지 못한 메서드 이름이 나옵니다. 서버가 일으키는 클래스는 `NoBackChannelError`이지만 와이어에는 기반 클래스인 `MCPError`만 실리므로, 트레이스백의 마지막 줄은 클래스 이름이 아니라 위의 문장입니다.

`2026-07-28` 클라이언트라면 해결책은 세 경우 모두 같습니다. 호출 도중에 되돌아 손을 뻗지 마세요. 질문을 **리졸버**로 옮기면(또는 직접 `InputRequiredResult`를 반환하면) 질문이 **응답**의 일부가 되며, 응답은 모든 연결이 실어 나를 수 있습니다.

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

질문도 같고, 클라이언트의 `elicitation_callback`도 같습니다. 차이는 내부에 있습니다. 리졸버를 쓰면 서버가 질문을 밀어 보내는 대신 호출에서 **반환**할 수 있으므로, 서버에서 클라이언트로 흐르는 것이 아무것도 없습니다. 이로써 서버가 세 구성 중 어느 것이든 모든 `2026-07-28` 클라이언트가 구제됩니다. **레거시** 클라이언트는 이렇게 고쳐 쓰는 것만으로는 구제되지 않습니다. `2025-11-25`에는 질문을 반환할 방법이 없으므로, 레거시 연결에서 리졸버는 여전히 요청 범위 채널로 `elicitation/create`를 보내며, 그 채널을 유지하는 서버(`stateless_http=True`도 `json_response=True`도 아닌 서버)가 여전히 필요합니다. 리졸버는 **[엘리시테이션](handlers/elicitation.md)**에서, 와이어에서 일어나는 일은 **[다중 왕복 요청](handlers/multi-round-trip.md)**에서 다룹니다.

!!! check
    `ctx.elicit()`을 쓰는 도구가 틀린 것은 아닙니다. **2026 이전** 방식일 뿐입니다.
    `stateless_http=True`도 `json_response=True`도 아닌 서버에 `mode="legacy"`(고전적인
    `initialize` 핸드셰이크, 사양 `2025-11-25` 및 그 이전)로 연결하면 동작합니다. 거기에는 서버에서
    클라이언트로 가는 채널이 있기 때문입니다.
    버전마다 무엇이 있는지는 **[프로토콜 버전](protocol-versions.md)**에서 다룹니다.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

클라이언트가 되돌려 보낸 `requestState` 토큰을 서버가 검증하지 못해 해당 회차를 거부한 경우입니다.

`requestState`는 **[다중 왕복](handlers/multi-round-trip.md)** 호출이 구간 사이에 들고 다니는 불투명한 재개 토큰입니다. `MCPServer`는 나가는 길에 토큰을 봉인하고 되돌아오는 것을 매번 검증하며, 토큰을 발행하지 않는 핸들러라 해도 `tools/call`, `prompts/get`, `resources/read`로 들어오는 `request_state`를 **전부** 검증합니다. 따라서 이 프로세스가 봉인하지 않은 토큰은 어디에 도착하든 거부됩니다.

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

메시지는 의도적으로 고정되어 있습니다. 와이어는 어느 검사가 실패했는지 절대 드러내지 않습니다. 이유는 **서버 로그**로 가며, 로그를 읽는 것이 진단의 전부입니다.

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

실제로 보게 될 이유는 다음과 같습니다.

* **`unknown key`**가 중요한 이유입니다. 기본 봉인 키는 프로세스 시작 시 생성되므로, **다른 워커**, 로드 밸런서 뒤의 다른 인스턴스, 또는 **재시작 후의** 같은 서버에 도착한 재시도는 이 프로세스가 가져 본 적 없는 키로 봉인된 것입니다. 공격자가 아니라, 기본값이 둘 이상의 프로세스를 만난 것입니다.
* **`audience`**: 토큰이 **서버 이름이 다른** 인스턴스에서 봉인되었습니다. 이름이 봉인의 기본 audience 클레임이므로, 서버 군은 키뿐 아니라 이름도 공유해야 합니다(또는 명시적으로 `RequestStateSecurity(audience=...)`를 설정해야 합니다).
* **`expired`**: 회차가 봉인의 `ttl`보다 오래 걸렸습니다. 이 값은 600초이며 호출 단위가 아니라 회차 단위입니다.
* **`malformed`** / **`codec error`**: 토큰이 전송 중에 변조되었거나, 애초에 봉인된 토큰이 아니었습니다.
* **`request binding`**: 토큰이 다른 도구, 다른 인자, 또는 다른 메서드와 함께 돌아왔습니다.

다중 프로세스 환경의 해결책은 인자 하나(모든 인스턴스에 **같은** `keys`)에, 인자가 아닌 한 가지, 즉 같은 서버 **이름**(또는 명시적으로 공유한 `audience=`)을 더한 것입니다.

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

봉인에는 `keys[0]`만 쓰이고 검증에는 목록의 모든 키가 쓰이며, 이것이 무중단 키 교체를 가능하게 합니다. 봉인이 보호하는 대상과 교체 순서는 **[다중 왕복 요청](handlers/multi-round-trip.md#protecting-requeststate)**에서 설명하고, 워커 두 개의 실패 전체와 두 부분으로 된 해결책은 **[배포와 확장](run/deploy.md)**에서 차근차근 살펴봅니다.

!!! tip
    `keys=[...]` 인자는 약한 키를 즉시 거부하며, 유난히 친절한 메시지를 냅니다.

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    메시지가 시키는 대로 하세요.

## 여전히 해결되지 않는 경우 {#still-stuck}

* SDK가 낸 메시지가 이 페이지에 없다면, 그 자체로 제보할 가치가 있는 문서 버그입니다.
* [이슈 트래커](https://github.com/modelcontextprotocol/python-sdk/issues)를 검색하세요. 거기에 나오는 오류 문자열은 대부분 이미 누군가가 정리해 둔 것입니다.
* 아무것도 찾지 못했다면 전체 트레이스백과 함께 [이슈를 등록](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)하거나, [MCP Contributors Discord의 #python-sdk-dev](https://discord.gg/6CSzBmMkjX)에서 물어보세요.

## 요약 {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup`은 절대 진짜 오류가 아닙니다. **마지막 줄**을 읽으세요. `async with Client(...)` 블록 **안에서** `MCPError`를 잡으면 감싸기를 완전히 건너뜁니다.
* `call_tool`은 실패한 도구에 대해 예외를 일으키지 않습니다. `Error executing tool ...` 및 `Unknown tool: ...` 메시지는 결과이므로 `result.is_error`를 확인하세요.
* `Client must be used within an async context manager` -> `async with`를 사용하세요. `Use @tool() instead of @tool` -> 괄호를 추가하세요.
* 서버 로그의 `Tool already exists:`는 이름이 같은 두 도구가 하나로 합쳐졌다는 유일한 신호입니다.
* 421 하나에 표기는 세 가지입니다. `Server returned an error response`(Python `Client`), `421 Misdirected Request` / `Invalid Host header`(그 밖의 모든 곳), `Invalid Host header: <host>`(서버 로그). 해결책은 `transport_security=TransportSecuritySettings(allowed_hosts=[...])`입니다.
* `Task group is not initialized` -> 마운트된 앱에서 호스트 lifespan이 `mcp.session_manager.run()`에 진입하지 않은 경우입니다.
* `Session not found` -> 서버가 재시작되었습니다. 다시 연결하세요.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()`에는 서버에서 클라이언트로 가는 채널이 필요합니다. `2026-07-28` 연결에는 그런 채널이 아예 없고, `stateless_http=True`는 레거시 채널을 없애며, `json_response=True`는 요청 범위 채널을 없앱니다. 리졸버를 사용하세요(레거시 클라이언트라면 채널을 유지하는 서버도 필요합니다). 이웃인 `Method not found`는 상대편 프로토콜 리비전에 없는 메서드를 요청한 경우입니다.
* `Client did not declare the form elicitation capability ...` 및 `Elicitation not supported` -> 클라이언트에 `elicitation_callback=` 인자가 빠져 있습니다.
* `Invalid or expired requestState`는 와이어에서 이유를 절대 말하지 않습니다. 서버 로그가 말해 주며, `unknown key`는 워커 간에 `RequestStateSecurity(keys=[...])` 설정을 공유하라는 뜻입니다.
