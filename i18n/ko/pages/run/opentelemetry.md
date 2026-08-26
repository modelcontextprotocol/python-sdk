---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

서버는 이미 추적되고 있습니다. 아무것도 추가하지 않아도 됩니다.

생성하는 모든 서버는 처리하는 모든 메시지에 대해 [OpenTelemetry](https://opentelemetry.io/) 스팬을 내보냅니다. 직접 작성하지도 않았고, 임포트하지도 않습니다. `MCPServer(...)`를 호출하는 순간 이미 들어 있습니다.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

이것으로 추적이 적용된 완전한 서버가 완성됩니다. `search_books`를 호출하면 그에 해당하는 스팬이 만들어집니다. 저수준 `Server`도 마찬가지입니다. 추적은 양쪽 모두에 들어 있습니다.

## 얻게 되는 것 {#what-you-get}

들어오는 모든 메시지는 메서드와 그 대상의 이름을 딴 `SERVER` 스팬이 됩니다. 따라서 `search_books`에 대한 `tools/call`은 `tools/call search_books` 스팬이 되고, 대상이 없는 `tools/list`는 그냥 `tools/list`가 됩니다.

각 스팬에는 몇 가지 속성이 붙습니다.

* `mcp.method.name`과 `mcp.protocol.version`은 모든 스팬에 있습니다.
* `jsonrpc.request.id`는 요청에 있습니다(알림에는 없습니다).
* 핸들러가 예외를 일으키면 스팬 상태가 오류로 설정됩니다. `is_error=True`인 도구 결과도 마찬가지입니다.

도구 호출을 추적하려는 요구가 워낙 흔하기 때문에, `tools/call` 스팬은 OpenTelemetry의 [GenAI 시맨틱 컨벤션](https://opentelemetry.io/docs/specs/semconv/gen-ai/)을 따릅니다.

* `gen_ai.operation.name`은 `"execute_tool"`로 설정됩니다.
* `gen_ai.tool.name`은 호출되는 도구로 설정됩니다.

`prompts/get` 스팬에도 같은 취지로 `gen_ai.prompt.name`이 붙습니다. 목록 조회 메서드에는 이름을 붙일 대상이 없으므로 `gen_ai.*` 키가 없습니다.

!!! tip
    이 GenAI 속성 덕분에 추적 UI가 도구 호출을 다른 에이전트의 호출과 같은 방식으로 묶어 보여 줍니다. 추가 코드 없이 이 그룹화를 그대로 얻습니다.

## 원할 때까지는 비용이 들지 않습니다 {#it-costs-nothing-until-you-want-it}

"기본적으로 켜져 있음"이 부담 없는 기본값이 되는 이유는 다음과 같습니다.

SDK는 OpenTelemetry의 가벼운 절반인 `opentelemetry-api`에만 의존합니다. SDK와 익스포터가 설치되어 있지 않으면 스팬을 만드는 일은 아무 동작도 하지 않습니다. 따라서 서버가 지금 내보내고 있는 스팬은 비용이 거의 들지 않으며, 아무도 수집하지 않습니다.

스팬을 실제로 **보고** 싶은 날이 오면, 나머지 절반을 설치하고 보낼 곳을 지정하면 됩니다.

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

일반적인 OpenTelemetry 방식으로 익스포터를 설정하면, SDK가 조용히 만들어 오던 모든 스팬이 드러납니다. 서버 코드는 바뀌지 않습니다. 단 한 줄도 바뀌지 않습니다.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/)가 그런 백엔드 중 하나이며, 설정까지 대신 해 줍니다. `pip install logfire`, `logfire.configure()`만 하면 MCP 스팬이 라이브 뷰에 나타납니다. OpenTelemetry 위에 만들어졌으므로 아래 내용도 모두 적용됩니다.

## 네트워크를 건너는 트레이스 {#traces-that-cross-the-wire}

트레이스는 클라이언트에서 서버까지 요청을 하나로 이어진 그림으로 따라갈 때 가장 유용합니다.

클라이언트와 서버가 모두 SDK를 실행하면 이 연결은 자동으로 이루어집니다. 클라이언트는 요청에 [W3C 트레이스 컨텍스트](https://www.w3.org/TR/trace-context/)를 주입하고, 서버는 이를 다시 읽어 내어 서버 스팬이 같은 트레이스 안에서 클라이언트 스팬 아래에 중첩됩니다. 이것이 [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414)이며, 따로 요청하지 않아도 얻습니다.

들어오는 메시지에 트레이스 컨텍스트가 없으면, 예를 들어 SDK가 아닌 클라이언트가 보낸 요청이면, 서버 스팬은 완전히 새로운 고아 트레이스를 시작하는 대신 서버에서 이미 현재 상태인 스팬을 부모로 삼습니다.

## 끄기 {#turning-it-off}

추적은 미들웨어이며, 서버 목록의 첫 번째 미들웨어입니다. 스팬을 전혀 내보내지 않는 서버를 정말로 원한다면 제거하세요.

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    이 임포트에는 앞에 밑줄이 붙어 있으며, 의도된 것입니다. 이 클래스는 [`Server.middleware`](../advanced/middleware.md)가 잠정적인 것과 마찬가지로 잠정적이므로, 임포트 경로는 바뀔 수 있다고 예상해야 합니다. 이 작업이 필요한 경우는 거의 없습니다. 익스포터가 설치되어 있지 않으면 스팬은 공짜이므로, 보통은 켜 둔 채 익스포터를 설치하지 않는 것이 답입니다.

## 요약 {#recap}

* 모든 `MCPServer`와 모든 저수준 `Server`는 기본적으로 들어오는 메시지마다 `SERVER` 스팬을 하나씩 내보냅니다. 작성할 것은 아무것도 없습니다.
* 스팬에는 `mcp.method.name`과 `mcp.protocol.version`이 붙고, `tools/call`과 `prompts/get`에는 GenAI 속성도 붙어 도구 호출이 다른 에이전트의 호출처럼 묶입니다.
* OpenTelemetry SDK와 익스포터를 설치하기 전까지는 비용이 들지 않으며, 설치하고 나면 서버를 바꾸지 않고도 드러납니다.
* 양쪽이 모두 SDK를 실행하면 클라이언트에서 서버로 트레이스 컨텍스트가 자동으로 전파됩니다.

요청을 아예 실행할지 말지를 결정하는 것은 **[인가](authorization.md)**입니다.
