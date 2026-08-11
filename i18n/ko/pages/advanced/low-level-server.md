---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# 저수준 Server {#the-low-level-server}

`@mcp.tool()`은 하나의 계층입니다. 그 아래에는 두 번째 서버 클래스인 `Server`가 있으며, 이 클래스는 MCP를 날것 그대로 다룹니다. 프로토콜 객체를 넘기면 변경 없이 그대로 와이어에 실어 보냅니다.

`MCPServer`는 그 위에 만들어져 있습니다. 편의 계층이 방해가 될 때 저수준으로 내려갑니다.

* Python 시그니처에서 도출한 스키마가 아니라 **정확히 그대로의** 스키마(파일에서 읽어 오거나 데이터베이스에서 생성한 스키마)를 내보내야 할 때.
* 결과를 완전히 제어해야 할 때: `_meta`, `is_error`, `structured_content`의 모든 키.
* MCP가 정의하지 않은 메서드를 처리해야 할 때.

그 밖의 모든 경우에는 `MCPServer`를 계속 사용하세요.

## 같은 도구를 직접 작성하기 {#the-same-tool-by-hand}

다음은 **[도구](../servers/tools.md)**에서 `@mcp.tool()` 아홉 줄로 작성한 `search_books` 도구에서 문법적 편의를 걷어 낸 모습입니다.

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

세 가지가 바뀌었고, 이 세 가지가 저수준 API의 전부입니다.

* **핸들러는 생성자 매개변수입니다.** `on_list_tools=`와 `on_call_tool=`은 `Server(...)`에 들어갑니다. 여기에는 데코레이터가 없으며, 모든 핸들러의 형태가 `async (ctx, params) -> result`로 동일합니다.
* **입력 스키마를 직접 작성합니다.** `Tool.input_schema`는 평범한 JSON Schema `dict`입니다. 타입 힌트에서 대신 도출해 주는 곳이 없습니다. 도출할 타입 힌트 자체가 없기 때문입니다.
* **결과를 직접 만듭니다.** `CallToolResult(content=[TextContent(...)])`를 손으로 작성합니다. 감싸거나 변환하거나 반환 어노테이션에서 추론하는 것은 아무것도 없습니다.

`params`는 파싱된 요청입니다. `CallToolRequestParams`에는 `.name`과 `.arguments`가 있습니다. `ctx`는 `ServerRequestContext`입니다. 클라이언트에 다시 말을 거는 데 쓰는 `ctx.session`, 그리고 `ctx.lifespan_context`, `ctx.request_id`, 요청에 실려 들어온 `_meta`인 `ctx.meta`가 있습니다.

!!! info
    FastAPI를 써 봤다면 이 관계를 이미 알고 있습니다. `MCPServer`는 데코레이터와 타입 힌트로 이루어진 계층이고, `Server`는 그 아래의 Starlette에 해당합니다. 둘은 경쟁 관계가 아닙니다. `MCPServer`는 `Server`를 생성하고 그 위에 바로 이런 핸들러를 등록합니다.

### 직접 해 보기 {#try-it}

이번에는 Inspector를 쓸 수 없습니다. `mcp dev`와 `mcp run`은 `MCPServer`만 받습니다. 인메모리 `Client`는 상관하지 않으며, `MCPServer`를 받는 것과 똑같이 저수준 `Server`도 받습니다.

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

`@mcp.tool()` 버전이 만들어 낸 것과 같은 텍스트입니다. 숨김없이 말하면 차이점이 두 가지 있습니다.

* `result.structured_content`가 `None`입니다. 고수준 서버는 `-> str` 반환값을 `{"result": ...}`로 감싸 주지만, 여기서는 직접 만들지 않은 것을 대신 만들어 주는 곳이 없습니다.
* `list_tools`는 **직접** 입력한 스키마를 글자 하나까지 그대로 반환합니다. 고수준 버전에는 모든 속성에 `"title": "Query"`가, 루트에 `"title": "search_booksArguments"`가 있었습니다. Pydantic이 남긴 흔적입니다. 여기서는 와이어에 실린 것이라면 전부 직접 넣은 것입니다.

## 자동 검증 없음 {#nothing-is-checked-for-you}

`MCPServer`는 함수가 실행되기도 전에, 생성한 스키마에 호출을 대조해 검증하여 잘못된 인수를 거부합니다(**[도구](../servers/tools.md)**).

`Server`는 그렇게 하지 않습니다. `input_schema`는 클라이언트에 **알려지기만** 할 뿐, `params.arguments`에 **적용되는** 일은 없습니다.

!!! check
    `limit` 없이 `search_books`를 호출하면 `args["limit"]`에서 `KeyError`가 발생합니다. 클라이언트가 보는 것은 다음과 같습니다.

    ```text
    MCPError: Internal server error
    ```

    코드 `-32603`의 JSON-RPC 오류이며, 메시지는 일부러 포괄적으로 되어 있습니다. SDK는 트레이스백을 원격 호출자에게 새어 나가게 하지 않습니다. 모델은 무엇을 잘못했는지 끝내 알지 못하므로 재시도할 수 없습니다. (테스트에서는 `raise_exceptions=True`로 실제 예외를 대신 드러낼 수 있습니다. **[테스트](../get-started/testing.md)**를 참고하세요.)

이것은 일반적인 규칙입니다. 저수준 핸들러에서 발생한 예외는 **언제나** 프로토콜 오류이며, 결코 `is_error=True` 도구 결과가 되지 않습니다. 모델이 실패 내용을 읽고 복구하기를 원한다면 `params.arguments`를 직접 검증하고 `CallToolResult(content=[TextContent(...)], is_error=True)`를 반환하세요. 이 두 가지 실패는 **[오류 처리](../servers/handling-errors.md)**에서 다룹니다.

## 도구 두 개, 핸들러 하나 {#two-tools-one-handler}

`on_call_tool`은 서버에 있는 모든 도구의 단일 진입점입니다. `params.name`으로 분기합니다.

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools`는 둘 다 알립니다. `call_tool`은 이름에 따라 디스패치합니다.
* `else` 분기가 중요합니다. `Server`는 목록에 올린 적 없는 이름의 `tools/call`도 기꺼이 핸들러로 그대로 전달합니다. 거기서 예외를 일으키면 위와 같은 `-32603`이 됩니다.

## 구조화된 출력 직접 작성하기 {#structured-output-by-hand}

`Tool`에 `output_schema`를 선언하고 결과에 `structured_content`를 넣습니다. 둘 다 직접 작성합니다.

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

호출하면 결과에 두 가지 표현이 모두 실립니다.

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

`_meta` 블록은 서버의 신원 도장입니다. SDK는 2026 계열 프로토콜의 모든 결과에 이것을 추가하며, `version`은 생성자에서 가져옵니다(버전을 설정하지 않은 서버는 빈 문자열을 보고합니다). 자신을 드러내서는 안 되는 서버는 미들웨어로 이 키를 제거할 수 있습니다. 미들웨어는 자신이 반환하는 결과를 소유하기 때문입니다.

서버는 두 필드를 비교하지 않습니다. 이 SDK의 `Client`는 비교합니다. 선언한 `output_schema`를 만족하지 않는 `structured_content`를 반환하면 `call_tool`이 `RuntimeError`를 일으키는데, 메시지는 `Invalid structured content returned by tool search_books`로 시작해 `jsonschema` 실패 내용을 인용합니다. 스키마를 약속하기는 쉽지만, 지키는 것은 작성자의 몫입니다. 반환 타입과 스키마의 전체 단계는 **[구조화된 출력](../servers/structured-output.md)**에서 확인하세요.

## `_meta`: 모델이 아닌 애플리케이션을 위한 데이터 {#\_meta-for-the-application-not-the-model}

`content`는 답변 중 모델이 읽는 부분입니다. `structured_content`는 같은 답변을 타입이 있는 데이터로 나타낸 것입니다. `_meta`는 세 번째 채널입니다. 답변의 일부가 전혀 아니면서 결과에 함께 실려 **클라이언트 애플리케이션**으로 가는 데이터입니다.

레코드 ID, 트레이스 ID처럼 UI에는 필요하고 프롬프트에는 필요 없는 것이라면 무엇이든 여기에 넣으세요.

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* 구성할 때는 와이어 이름인 `_meta=`로 씁니다. 클라이언트는 `result.meta`로 읽습니다.
* 키에 네임스페이스를 붙이세요(`bookshop/record_ids`). `io.modelcontextprotocol/*` 키는 프로토콜이 예약해 두었습니다.

!!! warning
    `_meta`는 작성자와 클라이언트 애플리케이션 사이의 관례이지, 무엇이 모델에 도달하는지에 관한 보장이
    아닙니다. 무엇을 렌더링할지는 호스트가 결정합니다. 도구 결과의 어느 부분에도 절대 비밀 값을 넣지 마세요.

## 핸들러에 따라 결정되는 기능 {#capabilities-follow-your-handlers}

`Server`는 핸들러를 제공한 메서드 군만 정확히 알립니다. 위의 `Bookshop`은 `on_list_tools`와 `on_call_tool`만 전달하고 다른 것은 전달하지 않으므로, 여기에 연결하는 클라이언트가 보는 것은 다음과 같습니다.

```json
{"tools": {"listChanged": false}}
```

`resources`도 `prompts`도 없습니다. 뒷받침할 것이 없기 때문입니다. `on_list_prompts`를 전달하면 `prompts`가 나타나고, `on_completion`을 전달하면 `completions`가 나타납니다.

`MCPServer`는 등록한 것이 있든 없든 항상 도구, 리소스, 프롬프트를 알립니다. 관리자 객체가 항상 존재하기 때문입니다. 여기서는 선언이 **곧** 생성자 호출입니다.

## lifespan 제네릭 {#the-lifespan-generic}

`Server`는 lifespan이 yield하는 타입에 대해 제네릭입니다. 어노테이션을 한 번 달면 그 객체가 나타나는 모든 곳에서 타입이 지정됩니다.

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* lifespan은 `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]` 형태이며, `async` 제너레이터에 `@asynccontextmanager`를 붙이면 정확히 이것이 됩니다.
* `yield`한 것은 무엇이든 `ctx.lifespan_context`가 되고, 핸들러에 `ServerRequestContext[Catalog]` 어노테이션이 달려 있으므로 `.search(...)`가 자동 완성되고 타입 검사를 통과합니다.
* 서버가 시작할 때 한 번 진입하고 멈출 때 한 번 빠져나옵니다. 시작, 정리, 그리고 같은 개념의 `MCPServer` 버전은 **[Lifespan](../handlers/lifespan.md)**에서 확인하세요.

`lifespan=` 인수가 없으면 `ctx.lifespan_context`는 빈 `dict`입니다.

## 직접 정의하는 메서드 {#a-method-of-your-own}

생성자는 MCP가 정의한 메서드를 다룹니다. 그 밖의 모든 것은 `add_request_handler`가 다룹니다.

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* 첫 번째 인수는 메서드 문자열입니다. 알림에는 짝이 되는 `add_notification_handler`가 있습니다.
* `params_type`은 핸들러가 실행되기 **전에** 들어오는 `params`를 검증하는 기준 모델입니다. 따라서 커스텀 메서드는 도구가 받지 못하는 검증을 **받습니다**. `_meta` 필드가 다른 모든 메서드처럼 파싱되도록 `RequestParams`를 상속하세요.
* 핸들러는 `BaseModel`, `dict`, `None` 중 하나를 반환합니다. SDK가 이를 JSON-RPC 결과로 직렬화합니다.

솔직한 단서 하나가 있습니다. 고수준 `Client`에는 MCP가 정의한 메서드용 동사만 있으므로 `client.reindex()`는 없습니다. 벤더 메서드는 그 메서드의 존재를 이미 아는 상대를 위한 것입니다. 함께 배포하는 클라이언트나, JSON-RPC를 말하는 자체 서비스가 여기에 해당합니다.

차지할 수 없는 메서드가 하나 있습니다.

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

핸드셰이크는 러너의 소유입니다. `server/discover`, `ping`, 그 밖의 모든 내장 메서드는 자유롭게 대체할 수 있습니다.

!!! tip
    오류 메시지에 언급된 `Server.middleware`는 `initialize`를 포함해 들어오는 **모든** 메시지를 감쌉니다. 새 메서드에 응답하는 것이 아니라 트래픽을 관찰하거나 다시 쓰고 싶다면 **[미들웨어](middleware.md)**부터 시작하세요.

## 나머지 핸들러 {#the-other-handlers}

다음은 각각 이제 이해할 어휘를 갖춘 개념 하나씩이며, 각각 별도의 페이지가 있습니다.

* `on_call_tool`, `on_get_prompt`, `on_read_resource`는 호출을 일시 중지하고 클라이언트에 입력을 요청하기 위해 평소의 결과 대신 `InputRequiredResult`를 반환할 수 있습니다. **[다중 왕복 요청](../handlers/multi-round-trip.md)**을 참고하세요. 이 계층답게 대신 설치해 주는 것은 없습니다. `MCPServer`가 기본적으로 `requestState`를 봉인하는 반면, 여기서는 설정한 `request_state`가 `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))`로 명시적으로 켜기 전까지 쓴 그대로 와이어를 건너갑니다. 이 한 줄(두 이름 모두 `mcp.server.request_state`에서 임포트합니다)이면 `MCPServer`가 수행하는 것과 동일한 봉인과 검증이 이루어집니다(**[`requestState` 보호하기](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion`은 나머지 프리미티브용으로 같은 `(ctx, params) -> result` 형태입니다.
* `on_subscriptions_listen`은 2026-07-28의 `subscriptions/listen` 스트림을 제공합니다. `SubscriptionBus` 위에 만든 `ListenHandler`를 전달하고 다른 핸들러에서 버스로 이벤트를 발행하세요. 전체 구성은 **[구독](../handlers/subscriptions.md)**에서 확인하세요.
* `server.streamable_http_app()`은 `MCPServer`의 것과 같은 Starlette 앱을 반환합니다. **[서버 실행하기](../run/index.md)**에서 다른 ASGI 앱을 배포하는 방식 그대로 배포하세요. 여기에는 `server.run(transport=...)` 같은 것이 없습니다. `server.run(read_stream, write_stream, server.create_initialization_options())` 호출이 스트림 한 쌍 위에서 연결 하나를 구동하며, 이 한 줄이 전부입니다.

## 요약 {#recap}

* 저수준 `Server`는 핸들러를 `on_*` **생성자 매개변수**로 받으며, 모든 핸들러는 `async (ctx, params) -> result`입니다.
* `input_schema` dict를 직접 작성하고 `CallToolResult`를 직접 만듭니다. 대신 도출하거나 감싸거나 검증해 주는 것은 없습니다.
* 핸들러의 예외는 `-32603` 프로토콜 오류입니다. 모델이 읽을 수 있는 도구 오류는 `is_error=True`인 `CallToolResult`이며 **직접** 반환해야 합니다.
* 결과의 `_meta`는 모델이 아니라 클라이언트 애플리케이션에 보내는 것입니다.
* `Server[T]`는 lifespan이 yield하는 것에 대해 제네릭이며, `ctx.lifespan_context`는 타입이 지정된 `T`입니다.
* `add_request_handler(method, params_type, handler)`는 어떤 메서드든 제공합니다. `initialize`는 예약되어 있습니다.
* `Server`가 알리는 기능은 등록한 핸들러에서 도출됩니다.

`Client(server)`가 두 서버를 똑같이 다룬 것은 둘이 **같은** 프로토콜이기 때문이며, 바로 그 점이 핵심입니다. 그다음 아래 계층은 클래스가 아닙니다. 바로 **[미들웨어](middleware.md)**입니다.
