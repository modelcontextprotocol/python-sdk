# 엘리시테이션(elicitation) {#elicitation}

작업을 절반쯤 진행한 도구가 답 하나를 얻지 못했다고 해서 실패할 필요는 없습니다.

**엘리시테이션**을 사용하면 도구가 직접 물어볼 수 있습니다. 도구 호출 중간에 사용자에게 질문이 전달되고, 그 답은 같은 함수 호출 안으로 돌아옵니다.

모드는 두 가지입니다.

* **폼 모드**: 값이 필요한 경우입니다(확인, 날짜, 수량). 필드를 설명하면 클라이언트가 폼을 렌더링합니다.
* **URL 모드**: 사용자가 다른 곳으로 이동해야 하는 경우입니다(OAuth 동의 화면, 결제 페이지). 그곳에서 사용자가 하는 일은 프로토콜을 거치지 않습니다.

질문하는 방법도 두 가지입니다. 먼저 택해야 할 쪽은 **리졸버**입니다. 매개변수에 질문을 걸어 두면 SDK가 대신 물어봅니다. 어떤 연결에서든, 클라이언트가 어느 프로토콜 시대의 말을 쓰든 동작합니다. 직접 방식인 `await ctx.elicit(...)`는 **서버**가 **클라이언트**에게 보내는 요청이며, 이 채널은 레거시 연결(명세 버전 2025-11-25 이하)의 클라이언트에만 존재합니다. 이 페이지에서는 두 가지를 모두 다루지만, 리졸버부터 시작하세요.

## 리졸버로 질문하기 {#ask-with-a-resolver}

도구 전체를 가로막는 질문, 예를 들어 **정말 삭제할까요? 일치하는 세 계정 중 어느 것일까요?** 같은 질문은 도구 본문 밖으로 꺼내 **리졸버**로 옮길 수 있고, 그러면 프레임워크가 대신 물어봅니다.

`Annotated[T, Resolve(fn)]`로 표기한 매개변수는 도구 본문보다 먼저 `fn`을 실행해 채워집니다. 리졸버는 값을 이미 알고 있으면 그대로 반환하고, 프레임워크가 대신 묻게 하려면 `Elicit(...)`을 반환합니다.

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete`는 도구 자신의 `path` 인자를 이름으로 읽어 폴더 목록을 확인하고, **꼭 필요할 때만 사용자에게 묻습니다**. 폴더가 비어 있으면 클라이언트로 왕복하지 않고 `Confirm(ok=True)`로 해결됩니다.
* `delete_folder`는 `ElicitationResult[Confirm]`으로 표기하므로 프레임워크가 결과 전체를 주입하고, 도구는 모든 경우를 `match`로 처리합니다. 수락 후 확인, 수락했지만 유지(`ok=False`), 거절, 취소가 그것입니다.
* `confirm` 매개변수는 도구의 입력 스키마에 전혀 나타나지 않습니다. `path`는 클라이언트가, `confirm`은 리졸버가 제공합니다.

도구가 분기할 필요가 없다면 래핑하지 않은 모델(`Annotated[Confirm, Resolve(confirm_delete)]`)로 표기하세요. 수락 시에는 모델을 받고, 거절이나 취소 시에는 호출이 오류로 중단됩니다.

리졸버는 **모든** 연결에서 동작합니다. 레거시 연결의 클라이언트에는 SDK가 질문을 직접 보내고, **2026-07-28** 연결에서는 SDK가 호출의 결과로 질문을 **반환**하며 클라이언트의 다음 시도가 답을 실어 옵니다. 리졸버는 그 차이를 전혀 알지 못합니다. 그 아래에서 벌어지는 일은 **[다중 왕복 요청](multi-round-trip.md)**에서 다룹니다.

질문은 리졸버가 할 수 있는 일 중 하나일 뿐입니다. 묻지 않고 계산하는 의존성, 의존성의 의존성, 모델이 제공할 수 있는 것과 없는 것 같은 일반적인 메커니즘은 **[의존성](dependencies.md)** 페이지에서 다룹니다.

## 도구 안에서 질문하기 {#ask-from-inside-the-tool}

도구는 자기 본문 한가운데서 멈춰 서서 직접 물어볼 수도 있습니다.

!!! warning
    `ctx.elicit()`과 `ctx.elicit_url()`은 **서버**가 **클라이언트**에게 보내는 요청이며, 이 채널은
    레거시 연결(명세 버전 **2025-11-25** 이하)의 클라이언트에만 존재합니다. **2026-07-28** 연결에는
    서버가 시작하는 요청이 없으므로 이 호출은 실패합니다. 리졸버는 양쪽 모두에서 동작합니다.
    자세한 내용은 **[프로토콜 버전](../protocol-versions.md)**에서 확인하세요.

`await ctx.elicit()`은 메시지와 Pydantic 모델을 받습니다.

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** 매개변수가 있어야 `ctx.elicit`을 쓸 수 있으며, 어떤 도구든 이 매개변수를 받을 수 있습니다. 이 객체는 별도 페이지인 **[Context](context.md)**에서 다룹니다.
* `AlternativeDate`는 받고 싶은 답의 **스키마**입니다.
* 도구는 `async def`입니다. 그럴 수밖에 없습니다. 중간에 멈춰서 사람을 기다리기 때문입니다.
* 다른 날짜라면 도구는 곧바로 반환합니다. 꼭 필요할 때만 묻습니다.
* 사용자가 수락한 날짜는 `book_table` 자신을 통해 다시 처리됩니다. 답도 다른 입력과 똑같습니다. 대안으로 제시한 날짜마저 예약이 꽉 찼다면 무턱대고 확정하지 않고 다시 물어봅니다.

### 클라이언트가 받는 것 {#what-the-client-receives}

클라이언트는 메시지와 함께, 모델에서 생성된 JSON Schema를 받습니다.

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

이 스키마가 곧 폼입니다. `Field(description=...)`는 레이블이 되고, 기본값은 입력란을 미리 채우면서 해당 필드를 선택 사항으로 만듭니다. **[도구](../servers/tools.md)**에서 도구 인자를 설명할 때 나온, Pydantic을 JSON Schema로 바꾸는 바로 그 장치입니다.

!!! warning
    엘리시테이션 스키마는 도구의 입력 스키마만큼 표현력이 높지 않습니다. 평평한 원시 필드만 쓸 수
    있습니다. `str`, `int`, `float`, `bool`, 또는 문자열 `Literal`(이 경우 `enum`이 됩니다)입니다.
    모델 안에 모델을 넣으면 클라이언트로 아무것도 보내기 전에 `ctx.elicit`이 예외를 발생시킵니다.

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    작업 중인 사람을 중간에 방해하는 일입니다. 답에 중첩 구조가 필요하다면 애초에 도구의 인자여야
    했습니다.

### 세 가지 답 {#the-three-answers}

`result.action`은 사용자가 무엇을 했는지 알려주며, 가능성은 정확히 세 가지입니다.

* `"accept"`: 폼을 제출했습니다. `result.data`는 이미 검증을 마친 `AlternativeDate` 인스턴스입니다.
* `"decline"`: 거절했습니다.
* `"cancel"`: 선택하지 않고 질문을 닫았습니다.

`result.data`는 `"accept"`일 때만 존재하므로, 예제는 `result.action`을 먼저 확인합니다. 타입 검사기가 이 순서를 강제합니다. `result.action == "accept"` 이후에는 `result.data`가 `AlternativeDate`이고, 그 전에는 `.data` 자체가 없습니다.

거절은 오류가 아닙니다. 거절이 무엇을 뜻하는지는 도구가 정하고(여기서는 예약하지 않음), 모델에게는 평소대로 답합니다.

!!! tip
    답은 코드가 보기 전에 모델로 검증됩니다. `bool` 자리에 `"maybe"`를 보내는 클라이언트가
    예약을 망가뜨리지는 못합니다. 호출이 스키마 불일치 오류로 실패하므로 `if`는 실행조차
    되지 않습니다.

## 사용자를 URL로 보내기 {#send-the-user-to-a-url}

자격 증명, 카드 번호, OAuth 동의처럼 모델이나 클라이언트를 거쳐서는 안 되는 것들이 있습니다. 이런 경우에는 데이터를 요청하는 대신 사용자에게 어딘가로 이동해 달라고 요청합니다.

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()`은 메시지, 방문할 **URL**, 그리고 직접 정하는 `elicitation_id`를 받습니다. `elicitation_id`는 서버 안에서 이 엘리시테이션을 식별하는 임의의 문자열입니다.
* 결과에는 action만 있고 그 외에는 아무것도 없습니다. `"accept"`는 사용자가 URL을 열기로 했다는 뜻이지, 그 너머의 일을 끝냈다는 뜻은 **아닙니다**.
* 결제는 사용자의 브라우저와 결제 제공자 사이에서 대역 외로 이뤄집니다. 어떤 내용도 MCP를 통해 돌아오지 않습니다.

두 번째 도구를 보세요. 대역 외 흐름이 끝났다는 사실을 서버가 알게 되면(웹훅이나 폴링으로, 여기서는 두 번째 도구로 표현했습니다) `ctx.session.send_elicit_complete(...)`가 같은 `elicitation_id`로 `notifications/elicitation/complete`를 보냅니다. 클라이언트는 이 알림을 보고 *"waiting for payment..."* 표시를 멈춰도 된다는 것을 압니다. 이 알림이 없으면 클라이언트는 추측할 수밖에 없습니다.

## 클라이언트 쪽 {#the-client-side}

서버는 묻고, 클라이언트는 `Client(...)`에 **`elicitation_callback`**을 전달해 답합니다.

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 콜백 하나가 두 모드를 모두 처리합니다. `params`는 `ElicitRequestFormParams`와 `ElicitRequestURLParams`의 유니온이고, 분기는 `isinstance`로 합니다.
* URL 모드에서는 `params.url`을 사용자에게 보여주고 사용자가 선택한 action을 반환합니다. `content`는 절대 반환하지 않습니다.
* 폼 모드에서 실제 애플리케이션이라면 `params.requested_schema`를 렌더링하고 사용자의 입력을 `content`로 반환합니다. 여기 있는 콜백은 정해진 답으로 항상 수락하는데, 테스트에서는 이런 콜백이 딱 알맞습니다.
* 콜백을 전달하는 것은 곧 **기능 선언**이기도 합니다. 서버는 이를 통해 이 클라이언트에게 물어봐도 된다는 것을 알게 됩니다. 클라이언트가 서버를 대신해 답할 수 있는 나머지 항목은 **[클라이언트 콜백](../client/callbacks.md)**에서 다룹니다.

!!! info
    엘리시테이션은 **서버**가 **클라이언트**에게 보내는 요청이고, 이런 요청은 클래식 핸드셰이크
    세션에서만 존재합니다. 그래서 이 클라이언트는 `mode="legacy"`를 전달합니다.
    **2026-07-28** 연결에서는 도구가 호출의 결과로 질문을 **반환**하는 방식으로 묻습니다.
    그 흐름은 **[다중 왕복 요청](multi-round-trip.md)**에서 다룹니다.

### 직접 해보기 {#try-it}

`ctx.elicit`을 쓰는 폼 모드 `server.py`(`book_table`이 있는 쪽)를 Streamable HTTP로 실행하고(한 줄 명령은 **[서버 실행하기](../run/index.md)**에 있습니다), 클라이언트의 `main()`을 실행해 `book_table`에 크리스마스 날짜를 요청하세요.

콜백은 전달받은 질문을 출력합니다.

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

콜백이 `{"accept_alternative": True, "date": "2025-12-27"}`으로 답하면, 그동안 `await ctx.elicit(...)` 안에서 기다리고 있던 도구가 예약을 마칩니다.

```text
Booked a table for 2 on 2025-12-27.
```

이번에는 URL 모드 `server.py`로 바꾸고 같은 `main()`이 `pay_deposit`을 호출하게 해보세요. 동일한 콜백이 다른 분기를 타고 결제 링크를 출력하며, 도구는 *"Complete the payment in your browser."*로 돌아옵니다. 호출 도중에 양방향으로 한 번 왕복한 셈입니다.

!!! check
    이제 `Client`에서 `elicitation_callback=`을 제거하고 크리스마스 날짜로 `book_table`을 다시
    호출해 보세요. 호출 전체가 프로토콜 오류로 실패합니다.

    ```text
    Elicitation not supported
    ```

    콜백을 등록하지 않은 클라이언트는 `elicitation` 기능을 선언한 적이 없으므로, 물어볼 상대가
    없습니다. 도구가 받은 것은 `"decline"`이 아니라 예외입니다. 이 점을 염두에 두고 설계하세요.
    모든 엘리시테이션에는 "물어볼 수 없다면 어떻게 할 것인가"에 대한 합리적인 답이 있어야 합니다.

## 요약 {#recap}

* `Annotated[T, Resolve(fn)]`로 표기한 매개변수는 리졸버가 채우며, 리졸버는 물어봐야 할 때 `Elicit(...)`을 반환합니다. 모든 연결에서 동작합니다.
* 스키마는 평평한 Pydantic 모델입니다. 원시 필드만 쓸 수 있고, 돌아오는 길에 검증됩니다.
* `result.action`은 `"accept"`, `"decline"`, `"cancel"` 중 하나이며, `result.data`는 수락했을 때만 존재합니다.
* `await ctx.elicit(message, schema=Model)`은 도구 본문 안에서 묻고, `await ctx.elicit_url(message, url, elicitation_id)`은 모델을 거쳐서는 안 되는 모든 것에 씁니다(`ctx.session.send_elicit_complete(elicitation_id)`는 대역 외 작업이 끝났음을 알립니다). 둘 다 서버에서 클라이언트로 보내는 요청이므로, 클라이언트가 레거시 연결이어야 합니다.
* 클라이언트는 `elicitation_callback` 하나로 답하며, params 타입으로 분기합니다. 이 콜백을 등록하는 것이 곧 기능을 선언하는 일입니다.
* 2026-07-28 연결에서는 서버가 질문을 밀어 보내는 대신 반환합니다. 같은 콜백에 값을 공급하는 것은 **[다중 왕복 요청](multi-round-trip.md)**입니다.

그 반환 아래에서 일어나는 모든 것, 즉 재시도 루프, `requestState` 보호, 직접 흐름을 제어하는 방법은 **[다중 왕복 요청](multi-round-trip.md)**에서 다룹니다.
