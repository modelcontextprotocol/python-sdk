---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# v2에서 달라진 점 {#whats-new-in-v2}

v2에서는 두 가지 일이 동시에 일어났습니다. **SDK가 새로 만들어졌습니다**. 클라이언트와 서버 양쪽 아래에 새 엔진이 들어갔고, `Client`가 일급 객체가 되었으며, v1 코드베이스가 첫 import에서 바로 마주치는 일련의 이름 변경이 있습니다. 그리고 **프로토콜이 바뀌었습니다**. v2는 MCP의 2026-07-28 개정판을 사용하며, 이 개정판은 이미 사용 중인 클라이언트를 낙오시키지 않으면서 연결 핸드셰이크, 세션, 서버가 시작하는 모든 요청을 제거합니다.

이 페이지는 두 부분을 둘러보는 안내입니다. 주요 변경 사항마다 한 섹션씩 다루고, 각 섹션은 해당 주제를 담당하는 페이지로 안내하며 끝납니다. 포팅 매뉴얼은 아닙니다. 포팅 매뉴얼은 **[마이그레이션 가이드](migration.md)**이며, 호환성이 깨지는 모든 변경 사항을 변경 전후 코드와 함께 담고 있습니다.

!!! note "v2가 안정 릴리스 라인입니다"
    `pip install mcp`는 2.x를 설치하며, 복사해 붙여 넣을 수 있는 설치 명령은
    **[설치](get-started/installation.md)**에 있습니다. v2에서 무언가가 깨지거나, 뜻밖으로 동작하거나, 작업을 더디게 만든다면
    [알려 주세요](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

## SDK: v1에서 v2로 {#the-sdk-v1-to-v2}

### `MCPServer`로 바뀐 `FastMCP` {#fastmcp-is-now-mcpserver}

고수준 서버 클래스의 이름이 바뀌었고, 모듈도 함께 바뀌었습니다. 이전 import 경로가 지원 중단 예정(deprecated)이 아니라 아예 사라졌기 때문에, 모든 v1 서버가 가장 먼저 부딪히는 변경입니다.

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

데코레이터로 만든 서버라면 포팅 작업의 대부분도 이것으로 끝납니다. `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`는 v1에서 받던 것을 그대로 받고(`@mcp.resource()`에는 선택적 `security=` 키워드가 하나 추가되었습니다), 입력 스키마는 여전히 타입 힌트에서 만들어집니다. 주변부의 변경은 다음과 같습니다. `mcp.server.fastmcp.*` 아래에 있던 모든 것은 이제 `mcp.server.mcpserver.*` 아래에 있고, `ctx.fastmcp`는 `ctx.mcp_server`가 되었으며, `get_context()`는 사라졌고(대신 `ctx: Context` 매개변수를 선언하세요), 예외 기반 클래스 `FastMCPError`는 `MCPServerError`가 되었습니다. import 대응표는 **[마이그레이션 가이드](migration.md#fastmcp-renamed-to-mcpserver)**에 있습니다.

### `Resolve`: 사용자에게 입력을 요청하는 새로운 방법 {#resolve-the-new-way-to-ask-the-user-for-input}

도구에 필요한 모든 것이 모델에서 와야 하는 것은 아닙니다. v2에 새로 추가된 기능으로, `Resolve(fn)` 어노테이션이 붙은 도구 매개변수는 모델에게 보이지 않게 직접 작성한 함수가 대신 채우며, 그 함수는 `Elicit(...)`을 반환해 사용자에게 질문을 띄울 수 있습니다. 호출 도중 클라이언트로부터 무언가를 얻는 방법으로는 이것이 권장됩니다. SDK는 연결이 지원하는 메커니즘을 통해 질문을 전달합니다. 레거시 클라이언트에는 실시간 엘리시테이션(elicitation) 요청으로, 2026-07-28 연결에는 다중 왕복으로 전달하므로, 도구 본문 하나로 두 시대를 모두 지원합니다. 자세한 내용은 **[의존성](handlers/dependencies.md)**에서 확인하세요.

!!! note
    필요할 때는 나머지 두 형태도 그대로 쓸 수 있습니다. `ctx.elicit()`은 레거시 연결의 클라이언트에 대해
    여전히 동작하고(**[엘리시테이션](handlers/elicitation.md)**), 핸들러가 직접
    `InputRequiredResult`를 반환해 왕복을 손수 진행할 수도 있습니다. 2026-07-28에서 샘플링과
    루트 요청이 전달되는 방식도 바로 이것입니다(**[다중 왕복 요청](handlers/multi-round-trip.md)**).

### 일급 `Client` {#a-first-class-client}

v1은 세 겹으로 중첩된 계층을 건네주었습니다. 원시 스트림을 내놓는 트랜스포트 컨텍스트 매니저, 이를 감싸는 `ClientSession`, 그리고 직접 호출해야 하는 `await session.initialize()`입니다. v2에는 객체가 하나뿐입니다.

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client`는 서버 객체(트랜스포트 없이 인메모리로 동작하며, 테스트에 쓰는 방식입니다), URL(Streamable HTTP), 또는 `stdio_client(...)` 같은 임의의 트랜스포트 컨텍스트 매니저를 받습니다. `async with`에 진입하면 서버가 어느 시대의 프로토콜을 말하든 연결을 맺고 프로토콜 버전을 협상합니다. 그 뒤에는 `client.server_capabilities`와 `client.protocol_version`이 그냥 준비되어 있고, 서버가 자신을 식별하는 경우에는 `client.server_info`도 마찬가지입니다(2026 시대에는 식별 정보가 선택 사항이므로 이제 타입은 `Implementation | None`입니다). v1에서 등록한 샘플링 및 엘리시테이션 콜백은 여전히 동작하며(콜백 본문에는 이 페이지의 다른 모든 것과 마찬가지로 snake_case 속성 이름 변경이 적용됩니다), 이제 2026 방식의 결과 속 요청(아래 참고)에도 응답하고, 한 번에 하나씩이 아니라 동시에 실행됩니다. 저수준 인터페이스를 원하는 경우를 위해 `ClientSession`은 여전히 그 아래에 있으며 `client.session`으로 얻을 수 있습니다. 다만 이 클래스 역시 바뀌었으므로(새 디스패처 엔진 위에서 실행되고, 자체 시그니처 일부도 변경되었습니다) 아래 계층으로 내려가기 전에 **[마이그레이션 가이드](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)**를 읽어 보세요.

**[클라이언트](client/index.md)**에서 소개하고, **[클라이언트 트랜스포트](client/transports.md)**에서 세 가지 연결 형태를, **[클라이언트 콜백](client/callbacks.md)**에서 콜백 자체를 다루며, **[테스트](get-started/testing.md)**에서는 v1의 `create_connected_server_and_client_session()` 헬퍼를 대체하는 인메모리 패턴을 보여 줍니다.

### 저수준 `Server`: 이름 변경이 아닌 재구축 {#the-low-level-server-was-rebuilt-not-renamed}

JSON-RPC 계층에서 작업한다면, v2에서 "모든 것이 달라진" 부분이 바로 여기입니다. 도구가 하나인 같은 서버를 두 방식으로 보여 드립니다. 마커를 클릭하면 무엇이 바뀌었는지 볼 수 있습니다.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. 핸들러는 서버가 생성된 뒤 언제든 데코레이터로 등록합니다(괄호를 붙여 호출하는 형태로).
2. `list[Tool]`을 그대로 반환하면 SDK가 `ListToolsResult`로 감싸 줍니다.
3. 필드는 Python에서 camelCase이고, 스키마는 **강제됩니다**. 함수가 실행되기 전에 SDK가 `call_tool` 인자를 이 스키마에 맞춰 jsonschema로 검증하므로, 아래의 `arguments["query"]`가 안전합니다.
4. `call_tool` 핸들러 하나가 모든 도구를 처리하며, 도구 이름과 이미 검증된 인자를 받습니다. 인자는 풀어서 전달되고 `None`인 경우는 없습니다.
5. v1 도구는 예외를 발생시켜 실패를 알립니다. 어떤 예외든 잡혀서 `str(e)` 값을 텍스트로 하는 `CallToolResult(isError=True)`로 반환되므로, 호출한 모델이 이 메시지를 읽고 재시도할 수 있습니다.
6. 컨텍스트는 암묵적 ContextVar에서 오며, 요청 도중 서버 객체를 통해 접근합니다.
7. 콘텐츠 블록을 그대로 반환하면 `CallToolResult`로 감싸 줍니다.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. 필드는 이제 snake_case이고, 스키마는 **알려 주기만 할 뿐 적용되지는 않습니다**. 핸들러가 실행되기 전에 인자를 검사하는 것은 아무것도 없습니다.
2. 모든 핸들러는 `async (ctx, params) -> result`라는 같은 형태입니다. 컨텍스트가 첫 번째 인자이며(`ctx.session`, `ctx.request_id`, `ctx.protocol_version`이 여기에 있습니다), `server.request_context`가 옮겨 간 곳이 바로 여기입니다.
3. 완전한 `ListToolsResult`를 직접 만듭니다. 리스트를 그대로 반환하면 이제 SDK가 감싸 주는 것이 아니라 서버 측 `TypeError`가 됩니다.
4. 타입이 지정된 params가 들어오고(`params.name`, `params.arguments`), 완전한 결과가 나갑니다. 풀어 주거나, 감싸 주거나, 변환해 주는 것은 없습니다.
5. 검사는 같고 수단이 다릅니다. 여기서 `ValueError`를 발생시키면 모델에는 불투명한 `-32603` 오류로 전달되므로(아래 참고), 의도적인 와이어 오류는 `MCPError`로 발생시킵니다. 이 오류는 코드와 메시지를 유지한 채 그대로 통과하며, 이 텍스트를 담은 `-32602` 응답은 알 수 없는 도구에 대해 사양 자체가 정한 응답입니다.
6. `params.arguments`는 `None`일 수 있습니다. v1에서는 코드가 이 값을 보기도 전에 빈 딕셔너리(`{}`)가 기본값으로 채워졌습니다. 핸들러 앞단에 검증이 없으므로 이 줄은 없어서는 안 됩니다.
7. 여기서 예상치 못한 예외가 발생하면 **내용이 가려진(sanitized)** 프로토콜 오류, 즉 `-32603` `"Internal server error"` 오류가 되며 모델은 메시지를 보지 못합니다. 모델이 읽고 반응해야 하는 실패라면 `CallToolResult(is_error=True, ...)`를 반환하세요.
8. 핸들러는 생성자 인자이므로, 서버의 인터페이스는 서버가 만들어지는 순간 완성됩니다. `add_request_handler()`는 생성 이후에 쓸 수 있는 비상 탈출구이자, 커스텀 메서드로 통하는 문입니다.

이 예제가 곧 패턴입니다. 더 일반적으로 말하면 다음과 같습니다. 모든 핸들러는 타입이 지정된 params가 들어오고 완전한 결과 타입이 나가는 같은 형태이고, 도구 인자에 대한 예전의 jsonschema 검사는 사라졌으며, 예외는 언제나 프로토콜 오류이지 `is_error=True` 도구 결과가 되는 일은 없고, 암묵적 `server.request_context` ContextVar는 사라졌습니다. 벤더 네임스페이스를 붙인 커스텀 메서드는 `add_request_handler(method, params_type, handler)`를 통해 일급으로 지원되며, 이 함수는 핸들러가 실행되기 전에 들어오는 params를 작성한 모델에 맞춰 검증합니다. 그리고 `middleware` 목록(의도적으로 잠정적인 것으로 표시되어 있습니다)이 들어오는 모든 메시지를 감싸며, 사람들이 오버라이드하던 비공개 `_handle_*` 메서드를 대체합니다.

그 아래에서는 v1의 `BaseSession` 수신 루프가 이제 클라이언트와 서버가 공유하는 디스패처 엔진으로 교체되었으며, 이 페이지의 여러 내용이 동시에 성립하는 것도 이 엔진 덕분입니다. `Server` 객체 하나가 두 프로토콜 시대를 모두 지원하고, `Client(server)`는 JSON-RPC 프레이밍 없이 프로세스 안에서 디스패치하며, 시간 초과된 클라이언트 요청은 이제 실제로 서버 측 핸들러를 취소합니다.

자세한 내용은 **[저수준 Server](advanced/low-level-server.md)**에서 확인하세요. **[마이그레이션 가이드](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)**는 제거된 훅을 하나하나 짚어 줍니다. `MCPServer` 아래로 내려간 적이 없다면 이 내용은 전혀 해당하지 않습니다.

### `mcp-types`로 옮겨 간 와이어 타입과 snake_case가 된 모든 필드 {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

프로토콜 타입은 이제 별도의 배포 패키지 `mcp-types`에 있습니다. 이 패키지는 pydantic과 typing-extensions 외에는 아무것에도 의존하지 않으므로, 게이트웨이나 프록시, 코드 생성기가 HTTP 스택을 설치하지 않고도 MCP의 와이어 형태를 사용할 수 있습니다. 그런 프로젝트는 `mcp-types`를 설치하고 `mcp_types`를 import합니다. `mcp` 자체는 그 패키지의 정확한 버전에 의존하며 이를 다시 노출하므로, SDK에 의존하는 코드는 계속 `import mcp.types as types`와 `from mcp.types import Tool`을 쓰고(영구적인 별칭이며, 모든 이름이 같은 객체입니다) 실제 의존성인 `mcp` 하나만 선언하면 됩니다. 경험칙은 이렇습니다. 실제로 의존하는 패키지를 통해 import하세요.

이 타입에서 모든 Python 속성은 이제 snake_case입니다. `result.is_error`, `tool.input_schema`, `listing.next_cursor`처럼 씁니다. 와이어 위의 JSON은 전과 똑같이 camelCase이며, 바뀐 것은 속성 표기뿐입니다. 더 엄격해진 기본값 두 가지도 함께 따라옵니다. 알 수 없는 필드는 왕복 보존되는 대신 무시되고(추가 데이터는 `_meta`에 넣으세요), 양쪽 모두 협상한 프로토콜 버전에 맞춰 트래픽을 검증합니다. 이름 변경 표는 **[마이그레이션 가이드](migration.md#field-names-changed-from-camelcase-to-snake_case)**를 참고하세요.

### `run()`으로 옮겨 간 트랜스포트 설정 {#transport-configuration-moved-to-run}

`MCPServer(...)`는 서버가 **무엇인지**에 관한 것입니다. 이름, instructions, lifespan, 인증이 여기에 해당합니다. 서버를 어떻게 **구동하는지**는 이제 `run()`과 앱 빌더의 몫이며, `host`, `port`, `stateless_http`, `json_response`, 엔드포인트 경로, `transport_security`가 그쪽으로 옮겨 갔습니다(`MCPServer("x", port=9000)`처럼 쓰면 `TypeError`가 납니다). 오버로드는 트랜스포트별로 타입이 지정되어 있으므로, `stdio`가 받는 옵션과 `streamable-http`가 받는 옵션을 에디터가 알려 줍니다. 알아 둘 만한 제거 사항이 하나 있습니다. `mount_path`가 사라졌으며, 접두 경로 아래에서 서비스하려면 ASGI 앱을 마운트하는 것이 지원되는 방법입니다.

옵션은 **[서버 실행하기](run/index.md)**에서, 마운트는 **[기존 앱에 추가하기](run/asgi.md)**에서 다룹니다.

### import 오류 없이 바뀌는 동작 {#behavior-that-changes-without-an-import-error}

이름 변경은 스스로 존재를 알립니다. 다음 항목은 그렇지 않습니다.

* **동기 함수는 워커 스레드에서 실행됩니다.** `def` 도구(또는 리소스, 프롬프트, 리졸버)는 더 이상 이벤트 루프를 막지 않습니다. 그 대가로 본문이 더 이상 이벤트 루프 스레드 **위에서** 실행되지 않으며, 이는 특정 스레드에서 실행되어야 하는 코드에는 중요한 차이입니다. `async def` 핸들러는 영향이 없습니다. **[마이그레이션 가이드](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**를 참고하세요.
* **도구 안에서 발생시킨 `MCPError`(v1의 `McpError`)는 이제 프로토콜 오류입니다.** 모델은 이 오류를 보지 못합니다. 그 밖의 모든 예외는 여전히 모델이 읽고 반응할 수 있는 `is_error=True` 결과가 됩니다. 이 구분은 **[오류 처리](servers/handling-errors.md)**에서 다룹니다.
* **결과는 나가기 전에 검증됩니다.** `input_schema`가 `{}`인 손수 만든 `Tool`은 이제 `tools/list`에서 실패합니다(사양은 `"type": "object"`를 요구합니다). `@mcp.tool()`로 만든 서버는 이 문제를 겪지 않습니다. 스키마를 SDK가 작성하기 때문입니다.
* **클라이언트는 받은 것을 검증합니다.** `list_tools()`와 `call_tool()`은 서버의 응답을 협상한 프로토콜 버전에 맞춰 검사하므로, v1의 관대한 파싱이 눈감아 주던 완전히 유효하지는 않은 서버는 이제 `pydantic.ValidationError`를 발생시킵니다. 직접 제어하지 않는 서버에 연결한다면 그런 서버를 가장 먼저 발견하는 쪽이 될 것을 예상하세요. 자세한 내용은 **[마이그레이션 가이드](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)**에 있습니다.
* **URI 템플릿은 이제 진짜 RFC 6570입니다.** `{+path}`, `{?query}` 등이 동작하고, 매칭은 정규식처럼 느슨한 것이 아니라 정확하며, 추출된 값의 경로 탐색(path traversal)은 기본적으로 거부됩니다. 더 엄격해진 템플릿은 첫 요청 때가 아니라 데코레이터를 적용하는 시점에 실패합니다. **[URI 템플릿](servers/uri-templates.md)**을 참고하세요.
* **Streamable HTTP의 lifespan은 한 번만 실행됩니다.** 시작 시에 실행되며, 그 상태는 모든 세션과 요청이 공유합니다. v1에서는 세션마다 한 번, `stateless_http=True`에서는 요청마다 한 번 실행되었습니다. lifespan에서 만드는 풀과 캐시는 훨씬 저렴해지고, 거기서 연결별 리소스를 획득하던 코드는 이제 핸들러 본문에 있어야 합니다. **[Lifespan](handlers/lifespan.md)**을 참고하세요.
* **`mcp dev`와 `mcp install`은 생성하는 환경을** 설치된 SDK 버전에 고정합니다. 두 명령 모두 새로운 `uv run --with ...` 환경에서 서버를 실행하는데, 예전에는 이 환경이 `mcp`를 개발 중인 버전이 아니라 최신 안정 릴리스로 해석했습니다. **[마이그레이션 가이드](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**를 참고하세요.
* **HTTP 클라이언트는 이제 `httpx`가 아니라 `httpx2`입니다.** 의존성이 바뀌면서 코드가 잡고 전달하는 대상이 달라지고(`httpx2.AsyncClient`, `httpx2.ConnectError`), TLS 인증서를 검증하는 방식도 달라집니다. `httpx2`는 certifi에 번들된 CA 목록 대신 `truststore`를 통해 운영 체제의 신뢰 저장소에 맞춰 검증합니다. 대부분의 환경에서는 전혀 알아채지 못합니다. 시스템 CA 저장소가 없는 최소 구성 컨테이너나, certifi 번들만 알고 있던 사설 CA는 TLS 핸드셰이크에 실패하기 시작합니다. `SSL_CERT_FILE`/`SSL_CERT_DIR` 환경 변수를 설정하거나 클라이언트에 `verify=ssl_context`를 전달하세요. **[마이그레이션 가이드](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**를 참고하세요.

### 완전히 제거된 것 {#removed-outright}

다음 각 항목은 **[마이그레이션 가이드](migration.md)**에 섹션으로 정리되어 있습니다.

* **WebSocket 트랜스포트**(양쪽 모두)와 `mcp[ws]` extra. MCP 사양의 일부였던 적이 없습니다.
* **실험적 Tasks** API(`mcp.*.experimental`). 2026-07-28은 태스크를 핵심 프로토콜에서 빼내 공식 확장([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663))으로 옮겼으며, 이 SDK는 아직 이를 구현하지 않습니다.
* import 경로로서의 `mcp.shared.version`, `mcp.shared.progress`, `mcp.shared.session`(v1 `message_handler` 어노테이션이 import하던 `RequestResponder` 스텁 포함). (`mcp.types`는 제거되지 **않았습니다**. 독립 패키지 `mcp_types`의 영구 별칭으로 남아 있습니다.)
* 지원 중단 예정이던 `streamablehttp_client` 표기, 그리고 `streamable_http_client`의 `get_session_id` 콜백(이 함수는 이제 정확히 스트림 두 개를 내놓습니다).
* `McpError`. `(code, message, data)`를 직접 받는 생성자를 갖춘 **`MCPError`**로 이름이 바뀌었습니다.
* `MCPServer.get_context()`, `mount_path=`, 그리고 저수준 `Server`의 데코레이터 메서드, ContextVar, 핸들러 딕셔너리.

## 프로토콜: 2025-11-25에서 2026-07-28로 {#the-protocol-2025-11-25-to-2026-07-28}

v2는 2026-07-28 개정판을 구현하며, **두** 개정판을 동시에 지원합니다. 동일한 `streamable_http_app()`과 동일한 stdio 서버가 아무것도 설정할 필요 없이, 켜야 할 플래그도, 별도의 배포도 없이 2025 시대 클라이언트의 `initialize`와 2026 시대 클라이언트의 요청에 모두 응답합니다. 새 개정판을 지원한다고 해서 예전 개정판을 쓰는 클라이언트가 낙오되지 않습니다. 아래는 새 개정판 자체가 바꾸는 내용입니다.

### 핸드셰이크도 세션도 없음 {#no-handshake-no-session}

2026-07-28 클라이언트는 연결을 열고, 협상하고, 그다음 대화하는 식으로 동작하지 않습니다. 모든 요청이 프로토콜 버전, 클라이언트 정보, 클라이언트 기능을 `_meta`에 담아 보내며, 유일한 탐색 호출인 `server/discover`도 다른 요청과 다를 바 없는 평범한 요청입니다. `Client`는 기본적으로 알맞게 동작합니다. `server/discover`를 한 번 시도해 보고, 서버가 더 오래된 경우 `initialize` 핸드셰이크로 되돌아갑니다.

Streamable HTTP에서는 2026 경로에 `Mcp-Session-Id`가 없으며, 운영 측면에서 가장 중요한 점이 바로 이것입니다. **최신 방식의 요청을 특정 워커에 묶는 것이 아무것도 없으므로**, 단순한 라운드 로빈 로드 밸런서 뒤의 어느 복제본이든 응답할 수 있습니다. 솔직하게 두 가지 단서를 달아 둡니다. 2025 시대 클라이언트(오늘날 대부분의 클라이언트가 여기에 해당합니다)는 여전히 세션을 열고, v1에서 필요했던 고정(stickiness)이 무엇이든 여전히 필요합니다. 이 클라이언트에게는 아무것도 바뀌지 않습니다. 그리고 **다중 왕복** 재시도가 워커를 가로질러 가지고 다녀야 하는 단 하나는 봉인된 `request_state`인데, 그 기본 키는 프로세스마다 발급되므로 수평 확장한 배포에서는 `RequestStateSecurity(keys=[...])`를 전달합니다. (`stateless_http=True`는 이와 무관합니다. 2025 시대 클라이언트를 어떻게 지원하는지에만 영향을 주며 2026 트래픽은 이 값을 읽지 않습니다. v1에서 이미 설정해 두었다면 아무것도 바뀌지 않습니다.)

클라이언트 쪽 이야기는 **[프로토콜 버전](protocol-versions.md)**에서, 운영자용 체크리스트(Host 허용 목록, `request_state` 키, 복제본 간 알림)는 **[배포와 확장](run/deploy.md)**에서, 두 시대를 동시에 지원하는 이야기는 **[레거시 클라이언트 지원](run/legacy-clients.md)**에서 확인하세요.

### 클라이언트를 호출할 수 없는 서버: 다중 왕복 요청 {#the-server-cannot-call-the-client-multi-round-trip-requests}

2026-07-28에서는 서버가 시작하는 요청이 모두 사라졌습니다. 푸시 방식 엘리시테이션, 샘플링, `roots/list`가 여기에 해당합니다. 2026 연결에는 이를 위한 채널이 없으므로, `ctx.elicit()`과 `ctx.session.create_message()`는 그 연결에서 `NoBackChannelError`로 실패합니다(레거시 클라이언트에 대해서는 여전히 동작합니다).

대체 방식은 호출의 방향을 뒤집습니다. 사용자로부터 무언가가 필요한 도구는 질문을 **반환**하고(`InputRequiredResult`), 클라이언트는 늘 갖고 있던 것과 같은 콜백으로 질문에 답하며, 답이 첨부된 채로 호출이 재시도됩니다. 이 루프는 `Client`가 대신 돌려 줍니다. 서버에서 결과를 직접 만드는 일은 드뭅니다. **[의존성](handlers/dependencies.md)**이 대신 해 주기 때문입니다. 매개변수에 `Resolve(ask_quantity)` 어노테이션을 달면(`ask_quantity`는 직접 작성하는 평범한 함수입니다), SDK가 연결이 지원하는 메커니즘, 즉 레거시 세션에서는 실시간 엘리시테이션 요청, 2026에서는 다중 왕복을 통해 질문합니다. 도구 본문 하나로 두 시대를 지원합니다.

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

이 파일 하나에 핵심이 모두 담겨 있습니다. 서버 하나, `Resolve` 기반 도구 하나, 그리고 레거시 클라이언트와 최신 클라이언트가 모두 인메모리로 답을 받습니다. 메커니즘(SDK가 대신 봉인하고 검증하는 `request_state` 포함)은 **[다중 왕복 요청](handlers/multi-round-trip.md)**에서 설명하고, 질문하는 쪽은 **[엘리시테이션](handlers/elicitation.md)**에서 다룹니다.

!!! warning "포팅한 v1 서버의 동작이 바뀌는 유일한 지점입니다"
    가장 먼저 부딪히는 것은 직접 작성한 테스트입니다. `Client(mcp)`는 기본적으로 v2 서버와 2026-07-28을
    협상하므로, `ctx.elicit()`을 호출하는 도구는 v1에서 통과하던 테스트에서 실패합니다. 질문을
    `Resolve(...)` 매개변수로 옮기거나(시대에 구애받지 않습니다), 정말로 푸시 동작을 원한다면 테스트 클라이언트를
    `mode="legacy"`로 고정하세요.

### 지원 중단 예정인 루트, 샘플링, 프로토콜 로깅과 제거된 `ping` {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)은 모든 프로토콜 버전에서 **기능** 세 가지를 통째로 지원 중단 예정으로 지정합니다. 루트, 샘플링, 그리고 MCP 수준 로깅(`ctx.info()` 등)입니다. 이는 위에서 말한 백 채널 부재와는 별개의 축입니다. 지원 중단 예정은 권고일 뿐이며, 2025 시대 세션에 대해서는 모든 것이 계속 동작하고, 와이어에서는 아무것도 바뀌지 않습니다. 눈에 띄는 것은 `MCPDeprecationWarning`인데, 이는 `UserWarning`이므로 기본적으로 출력됩니다. 업그레이드 후 처음 호출하는 `ctx.info(...)`에서 이 경고가 나타날 것으로 예상하세요.

`ping`은 더 엄격합니다. 지원 중단 예정이 아니라 프로토콜에서 제거되었습니다. 지원 중단 예정 기능의 독립 메서드 중 두 개, 즉 `logging/setLevel`과 클라이언트의 `notifications/roots/list_changed`도 2026-07-28에서 같은 방식으로 제거되었으며, 진행 상황 알림은 이제 서버에서 클라이언트 방향으로만 갑니다.

전체 표와 각각의 대체 방법, 그리고 레거시 클라이언트를 지원하는 동안 조용한 로그가 필요할 때 쓸 한 줄짜리 필터는 **[지원 중단 예정 기능](deprecated.md)**에서 확인하세요.

### 하나의 스트림이 된 변경 알림 {#change-notifications-become-one-stream}

2026-07-28에서는 독립적인 HTTP GET 스트림과 `resources/subscribe`가 `subscriptions/listen`으로 대체됩니다. 클라이언트가 오래 유지되는 스트림 하나를 열고 원하는 알림 종류를 지정하는 방식입니다. `MCPServer`는 이를 기본으로 지원합니다. `await ctx.notify_resource_updated(uri)`를 호출해 발행하고(`notify_tools_changed()` 등도 마찬가지입니다), 미들웨어는 호출자별로 listen 요청을 거부할 수 있으며, 복제본이 여럿인 배포에서는 공유 `SubscriptionBus`를 연결합니다. 클라이언트에서는 `async with client.listen(...)`이 스트림을 엽니다. 필터는 키워드 인자로 들어가고, 타입이 지정된 변경 이벤트가 돌아오며, `sub.honored`는 서버가 전달하기로 동의한 부분집합입니다.

발행과 서비스는 **[구독](handlers/subscriptions.md)**에서, 지켜보는 쪽은 **[클라이언트 섹션의 구독 페이지](client/subscriptions.md)**에서, 버스는 **[배포와 확장](run/deploy.md)**에서 다룹니다.

### 나머지 변경 사항 한눈에 보기 {#the-rest-quickly}

* **식별 정보는 선택적인 메시지별 메타데이터입니다.** 요청 쪽의 `clientInfo` `_meta` 키는 선택 사항이고(필수 쌍은 `protocolVersion` + `clientCapabilities`입니다), `serverInfo`는 `server/discover` 결과 본문에서 빠졌습니다. 대신 서버가 2026 시대의 모든 결과의 `_meta`에 찍어 넣습니다([사양 #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). SDK는 항상 찍어 넣으며, 서버가 자신을 식별하지 않는 경우(예를 들어 미들웨어가 키를 제거한 경우) `client.server_info`는 `None`입니다. 와이어에 찍힌 모습은 **[저수준 Server](advanced/low-level-server.md)**에서 볼 수 있습니다.
* **본문을 파싱하지 않고도 요청을 라우팅할 수 있습니다.** 최신 방식의 HTTP 요청에는 `Mcp-Method`가 실리고(도구 성격의 호출 세 가지에는 `Mcp-Name`도 실립니다), `x-mcp-header`로 어노테이션한 도구 입력 스키마 속성은 `Mcp-Param-*` 헤더로 복제되어 서버가 교차 검증합니다([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). 게이트웨이와 속도 제한기는 헤더만으로 라우팅할 수 있습니다. 규칙은 **[마이그레이션 가이드](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)**에 있습니다.
* **결과에 캐시 힌트가 실립니다.** 목록 및 읽기 결과는 `ttlMs`, `cacheScope` 두 필드를 선언합니다([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)). 메서드별로 `cache_hints=` 인자로 설정하며, `Client`는 내장 응답 캐시로 이를 따릅니다. 힌트를 보내지 않는 서버(2026 이전의 모든 서버)는 이전과 동일한, 캐시되지 않은 트래픽을 받습니다. **[캐시 힌트](client/caching.md)**를 참고하세요.
* **확장은 일급입니다.** 서버와 클라이언트는 역방향 DNS 식별자 아래에 선택적 기능 묶음을 선언합니다([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)). 내장 `Apps` 확장(MCP Apps)이 참조 구현입니다. **[확장](advanced/extensions.md)**과 **[MCP Apps](advanced/apps.md)**를 참고하세요.
* **오류 코드가 표준화되었습니다.** 없는 리소스는 `error.data`에 URI를 담은 `-32602` 오류이고, 사양이 새로 예약한 코드는 `-32020`(헤더 불일치), `-32021`(필수 기능 누락), `-32022`(지원하지 않는 프로토콜 버전)입니다. **[문제 해결](troubleshooting.md)**은 정확한 메시지를 기준으로 정리되어 있습니다.
* **인가를 잘못 쓰기가 더 어려워졌습니다.** 클라이언트는 인가 코드와 함께 반환되는 `iss`를 검증하고([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207), 이에 따라 `callback_handler`는 이제 `AuthorizationCodeResult`를 반환합니다), 등록할 때 `application_type`을 보내며, 자격 증명을 다른 인가 서버에 재사용하지 않습니다. 엔터프라이즈 쪽에 새로 추가된 것은 [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 신원 어설션(identity assertion) 흐름입니다. 모든 OAuth 변경 사항은 **[마이그레이션 가이드](migration.md)**에 나열되어 있고, 관련 페이지는 **[클라이언트용 OAuth](client/oauth-clients.md)**와 **[신원 어설션](client/identity-assertion.md)**입니다.
* **모든 서버는 추적 가능합니다.** OpenTelemetry가 미들웨어로 기본 활성화되어 제공됩니다. 모든 요청에 서버 스팬이 생기며, 프로세스가 익스포터를 구성하기 전까지는 비용이 들지 않습니다. 양쪽 끝이 모두 SDK를 실행하면 클라이언트가 W3C 트레이스 컨텍스트도 `_meta`로 전파하므로 트레이스가 이어집니다. **[OpenTelemetry](run/opentelemetry.md)**를 참고하세요.

## v1에서 업그레이드하는 경우 {#upgrading-from-v1}

* 무엇을 바꿔야 하는지 완전하고 정확하게 정리한 목록은 **[마이그레이션 가이드](migration.md)**입니다. 이 페이지는 그 이유를 설명한 것입니다.
* **v1.x는 사라지지 않습니다.** 유지 보수 단계로 전환되어 중요한 수정과 보안 패치를 계속 받으며, 2026-07-28 사양 릴리스의 어떤 것도 v1.x를 깨뜨리지 않습니다. 문서는 [/v1/](https://py.sdk.modelcontextprotocol.io/v1/)에 있습니다. `mcp`에 의존하는 라이브러리를 배포하고 있고 아직 마이그레이션할 준비가 되지 않았다면, 버전을 고정하지 않은 의존성 해석이 1.x에 머물도록 상한을 두세요(예: `mcp>=1.28,<2`).
* 거칠거나, 헷갈리거나, 망가진 부분이 있다면 **[v2 피드백을 남겨 주세요](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**. 빠짐없이 읽습니다.
