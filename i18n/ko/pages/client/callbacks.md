---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# 클라이언트 콜백 {#client-callbacks}

MCP에서 거의 모든 요청은 한 방향, 즉 클라이언트에서 서버로 갑니다.

서버도 **클라이언트**에 무언가를 요청할 수 있습니다. 사용자에게 질문을 하거나, 사용자의 모델을 샘플링하거나, 사용자의 작업 공간 폴더 목록을 달라고 하는 식입니다. 이런 요청에는 `Client(...)`에 **콜백**을 전달해 응답합니다.

## 요청하는 서버 {#a-server-that-asks}

다음은 도구가 혼자서는 완료할 수 없는 서버입니다.

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` 호출은 `elicitation/create` 요청을 **클라이언트로** 보내고 기다립니다.
* 누군가(폼 앞의 사람이든, 작성한 코드든)가 `name`을 제공하기 전까지 도구는 반환하지 않습니다.

여기까지가 서버 쪽 절반이며, 이 부분은 **[엘리시테이션(elicitation)](../handlers/elicitation.md)** 페이지에서 다룹니다. 이 페이지는 연결의 반대쪽 끝을 다룹니다.

## 엘리시테이션 콜백 {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* 엘리시테이션 콜백은 `async (context, params) -> ElicitResult` 형태입니다.
* `params.message`는 질문입니다. `params.requested_schema`는 서버가 원하는 답의 JSON Schema입니다. 실제 클라이언트는 이것으로 폼을 그리지만, 이 예제는 자동으로 채웁니다.
* `ElicitResult(action="accept", content={...})`를 반환하거나, `action="decline"` 또는 `action="cancel"`을 반환합니다. 그 외 유일한 선택지는 `ErrorData(...)`로, 요청을 거부하고 호출 전체를 실패시킵니다.
* `context`는 `ClientRequestContext`입니다. 살아 있는 `session`, 서버의 `request_id`, 서버가 첨부한 `meta`가 들어 있습니다.

!!! tip
    `params`는 두 가지 엘리시테이션 모드의 유니온입니다. 여기서 `params.mode`는 `"form"`이며, `"url"` 요청은
    스키마 대신 `params.url`을 담고 있습니다. 콜백 하나로 둘 다 처리하며, `params.mode`로 분기하세요.
    전체 패턴은 **[엘리시테이션](../handlers/elicitation.md)**에서 확인하세요.

### 직접 해 보기 {#try-it}

`issue_card`를 호출하고 양쪽 끝을 지켜보세요.

콜백은 이미 파싱된 서버의 질문을 받습니다.

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

콜백이 응답하면 도구 안에서 `ctx.elicit(...)` 호출이 다시 진행되고, 도구가 완료됩니다.

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

클라이언트가 보낸 `tools/call` 하나, 서버가 되돌려 보낸 `elicitation/create` 하나, 그리고 그에 대한 함수의 응답까지, 모두 단일 도구 호출 안에서 일어납니다.

!!! info
    `Client(...)` 호출의 `mode="legacy"`는 실제로 중요한 역할을 합니다. 기본적으로 `Client(...)`는 최신
    프로토콜 경로를 협상하는데, 그 경로에는 서버에서 클라이언트로 가는 요청을 위한 역방향 채널이 없어서
    콜백이 실행되기도 전에 `ctx.elicit` 호출이 실패합니다. 이를 결정하는 것은 트랜스포트가 아니라 협상된
    프로토콜이며, 인메모리든 URL을 통하든 마찬가지입니다. 클라이언트가 이런 요청에 응답해야 할 때마다
    `mode="legacy"`로 고정하세요. 이 페이지를 뒷받침하는 모든 테스트가 그렇게 합니다. 자세한 내용은 **[프로토콜 버전](../protocol-versions.md)**에서 확인하세요.

    2026-07-28 세션에서도 콜백이 쓸모없어지는 것은 아니며, 입력을 받는 방식이 다를 뿐입니다. 도구가
    `ElicitRequest`를 담은 `InputRequiredResult`를 반환하면 `Client`는 그 항목을 같은
    `elicitation_callback`으로 전달하고 호출을 대신 재시도합니다. 이 흐름은 **[다중 왕복 요청](../handlers/multi-round-trip.md)**에서 다룹니다.

## 콜백이 곧 기능 {#a-callback-is-a-capability}

클라이언트가 엘리시테이션 요청에 응답할 수 있다고 서버에 알린 적은 없습니다. SDK가 대신 알렸습니다.

클라이언트는 연결할 때 자신의 `capabilities`를 선언하며, 이는 서버 쪽 선언과 거울처럼 대응됩니다. 이 객체를 직접 작성하지는 않습니다. **콜백을 등록하는 것이 곧 선언입니다.**

| 전달하는 것 | 클라이언트가 선언하는 것 |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| 아무것도 전달하지 않음 | `{}` |

샘플링 하위 기능이 유일하게 더 세밀한 부분입니다. 샘플러가 `tools` / `tool_choice` 매개변수를 처리한다면 `sampling_callback`과 함께 `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())`를 전달하세요. 서버는 `sampling.tools`가 선언된 것을 확인해야만 이 매개변수를 보낼 수 있습니다.

`logging_callback`과 `message_handler`는 표에 없습니다. 이 둘은 알림을 처리하며, 알림에는 기능 선언이 필요 없습니다.

서버는 `ctx.session.check_client_capability(...)`로 이 선언을 읽어 옵니다. 그렇게 하는 도구를 추가하세요.

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

`elicitation_callback`만 전달해 연결하고 호출하세요.

```python
result.structured_content  # {'result': ['elicitation']}
```

콜백 세 개를 모두 전달하면 `['elicitation', 'sampling', 'roots']`를 받습니다. 아무것도 전달하지 않으면 `[]`를 받습니다.

!!! check
    이번에는 잘못된 방식으로 해 보세요. `elicitation_callback` **없이** 연결하고 그래도 `issue_card`를 호출하세요.

    서버의 `elicitation/create` 요청은 여전히 클라이언트에 도달하며, 처리할 수 있다고 알린 적이 없으므로
    SDK가 대신 오류로 응답합니다. 그 오류가 호출 전체를 무너뜨립니다.
    `call_tool`은 `is_error` 결과를 반환하지 않고 예외를 던집니다.

    ```text
    MCPError: Elicitation not supported
    ```

    이는 도구 오류가 아니라 프로토콜 오류(`-32600`, *invalid request*)입니다. 모델이 읽고 재시도할 것이
    아무것도 없습니다. 바로 이 때문에 `client_features`를 둘 가치가 있습니다. 제대로 동작하는 서버는
    요청하기 전에 확인합니다.

## 지원 중단 예정(deprecated)인 두 콜백 {#the-deprecated-pair}

`sampling_callback`은 `sampling/createMessage`에 응답합니다. 서버가 **클라이언트 쪽** 모델에 무언가를 완성해 달라고 요청하는 것입니다. `list_roots_callback`은 `roots/list`에 응답합니다. 서버가 어느 디렉터리에서 작업해도 되는지 묻는 것입니다.

둘 다 동작합니다. 둘 다 위의 규칙을 따릅니다. 그리고 둘 다 **2026-07-28 사양에서 제거되는** RPC를 처리합니다. 최신 서버는 요청 도중에 클라이언트를 역으로 호출하지 않고, 요청을 도구 결과의 일부로 되돌려 줍니다(**[다중 왕복 요청](../handlers/multi-round-trip.md)**). 콜백 자체가 쓸모없어지는 것은 아닙니다. `InputRequiredResult`가 `CreateMessageRequest`나 `ListRootsRequest`를 담고 있으면 `Client`의 자동 루프가 여기서 등록한 바로 그 `sampling_callback` 또는 `list_roots_callback`으로 전달합니다. 전체 목록은 **[지원 중단 예정 기능](../deprecated.md)**에서 확인하세요.

아직 옮겨 가지 않은 서버와 통신하려면 여전히 이 콜백이 필요합니다. 시그니처는 다음과 같습니다.

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* 샘플링 콜백은 전체 `CreateMessageRequestParams`(`messages`, `model_preferences`, `max_tokens`)를 받고 `CreateMessageResult`를 반환합니다. 모델을 실행하는 것은 **클라이언트 쪽**이며 방식은 자유입니다. SDK는 요청을 전달할 뿐입니다.
* 루트 콜백은 params를 전혀 받지 않고 `ListRootsResult`를 반환합니다.
* 둘 다 거부하려면 대신 `ErrorData(...)`를 반환할 수 있습니다.

`elicitation_callback`과 똑같이 `Client(...)`에 전달하세요.

## 알림 콜백 {#the-notification-callbacks}

두 개가 더 있습니다. 둘 다 아무것도 선언하지 않습니다.

`logging_callback`은 서버가 보내는 `notifications/message`를 `LoggingMessageNotificationParams`(`level`, `logger`, `data`)로 받습니다. 프로토콜 로깅 자체가 2026-07-28 사양에서 지원 중단 예정이므로(대신 무엇을 해야 하는지는 **[로깅](../handlers/logging.md)**에서 다룹니다), 이 콜백은 여전히 로그를 내보내는 서버를 위해 존재합니다. 2026년 세대 연결에서는 콜백만으로는 아무것도 받지 못합니다. 2026 서버는 옵트인한 요청에만 로그 메시지를 보내기 때문입니다. `Client(...)`에 `log_level="info"`(또는 다른 레벨)를 전달하면 모든 요청에 이 옵트인이 찍혀 해당 레벨 이상을 받습니다. 2026 이전 서버는 이를 무시하고 기존 `logging/setLevel` 동작을 유지합니다.

`message_handler`는 모든 것을 받는 콜백입니다. 세션이 드러내는 모든 서버 알림이 (각각의 전용 콜백과 더불어) 여기에 도달하며, 스트림 기반 트랜스포트에서는 트랜스포트 수준의 모든 `Exception`도 마찬가지입니다. 절대 도달하지 않는 것이 두 가지 있습니다. `notifications/cancelled`는 드러나는 대신 SDK가 직접 적용하고, 살아 있는 `listen()` 스트림에 대한 구독 확인 응답은 그 스트림이 소비합니다. 매개변수에는 `IncomingMessage`(`ServerNotification | Exception`, `mcp.client`에서 내보냄)로 타입을 표기하세요. 알아 둘 만한 패턴은 `if isinstance(message, Exception): raise message` 하나로, 끊어진 연결이 조용히 사라지는 대신 확실하게 실패하도록 합니다.

## 요약 {#recap}

* 서버는 클라이언트에 요청을 보낼 수 있습니다. `Client(...)`에 전달한 콜백으로 응답합니다.
* 현재 기준의 콜백은 엘리시테이션 콜백입니다. `async (context, params) -> ElicitResult` 형태이며, 폼 모드와 URL 모드 모두 함수 하나로 처리합니다.
* **콜백을 등록하는 것이 곧 기능을 선언하는 것입니다.** 콜백이 없으면 SDK가 대신 서버의 요청을 거부하고 호출 전체가 `MCPError`로 실패합니다.
* 서버는 `ctx.session.check_client_capability(...)`로 요청하기 전에 미리 확인합니다.
* `sampling_callback`과 `list_roots_callback`도 같은 방식으로 동작하지만 지원 중단 예정 기능을 처리합니다. 최신 서버는 대신 다중 왕복 요청을 사용합니다.
* `logging_callback`과 `message_handler`는 알림을 받습니다. 아무것도 선언하지 않습니다.

`Client(...)`의 첫 번째 인자는 트랜스포트 객체입니다. 모든 종류는 **[클라이언트 트랜스포트](transports.md)**에서 다룹니다.
