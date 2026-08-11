---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# 엘리시테이션 {#elicitation}

작업을 절반쯤 진행하다가 답 하나가 모자란 도구라고 해서 실패해야 하는 것은 아닙니다.

**엘리시테이션**(elicitation)을 사용하면 도구가 물어볼 수 있습니다. 도구 호출 도중에 사용자는 질문을 받고, 사용자의 답은 같은 함수 호출 안으로 돌아옵니다.

두 가지 모드가 있습니다.

* **폼 모드**: 값(확인, 날짜, 수량)이 필요한 경우입니다. 필드를 기술하면 클라이언트가 폼을 렌더링합니다.
* **URL 모드**: 사용자가 다른 곳(OAuth 동의 화면, 결제 페이지)으로 가야 하는 경우입니다. 사용자가 그곳에서 하는 일은 프로토콜을 전혀 거치지 않습니다.

그리고 물어보는 방법도 두 가지입니다. 먼저 손이 가야 할 것은 **리졸버**입니다. 질문을 파라미터에 걸어 두면 SDK가 대신 물어봅니다. 어떤 연결에서든, 클라이언트가 어느 시대의 프로토콜을 쓰든 상관없습니다. 직접적인 방법인 `await ctx.elicit(...)`은 **서버**가 **클라이언트**에게 보내는 요청인데, 이 채널은 레거시 연결(사양 버전 2025-11-25 이하)을 쓰는 클라이언트에게만 존재합니다. 두 방법 모두 이 페이지에서 다루며, 리졸버부터 시작하세요.

## 리졸버로 물어보기 {#ask-with-a-resolver}

도구 전체의 실행을 좌우하는 질문("정말 실행할까요?", "일치하는 계정 세 개 중 어느 것인가요?")은 도구 본문에서 꺼내 **리졸버**로 옮길 수 있으며, 그러면 프레임워크가 대신 물어봅니다.

`Annotated[T, Resolve(fn)]`로 어노테이션한 파라미터는 도구 본문보다 먼저 `fn`을 실행해 채워집니다. 리졸버는 값을 이미 알고 있으면 그대로 반환하고, 프레임워크가 물어보게 하려면 `Elicit(...)`을 반환합니다.

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete`는 도구 자신의 `path` 인자를 이름으로 읽고 폴더 내용을 나열하며, **꼭 필요할 때만 사용자에게 묻습니다**. 빈 폴더라면 클라이언트와 왕복할 필요 없이 `Confirm(ok=True)` 값으로 바로 결정됩니다.
* `delete_folder`는 `ElicitationResult[Confirm]`으로 어노테이션하므로 프레임워크가 결과 전체를 주입하고, 도구는 `match`로 모든 경우를 처리합니다. 수락 후 확인, 수락했지만 유지(`ok=False`), 거절, 취소입니다.
* `confirm` 파라미터는 도구의 입력 스키마에 전혀 나타나지 않습니다. `path`는 클라이언트가, `confirm`은 리졸버가 제공합니다.

도구가 분기할 필요가 없다면 대신 감싸지 않은 모델(`Annotated[Confirm, Resolve(confirm_delete)]`)로 어노테이션하세요. 수락하면 도구가 모델을 받고, 거절이나 취소면 호출이 오류와 함께 중단됩니다.

리졸버는 **모든** 연결에서 동작합니다. 레거시 연결을 쓰는 클라이언트에게는 SDK가 질문을 직접 보내고, **2026-07-28** 연결에서는 SDK가 호출에서 질문을 **반환**하며 클라이언트의 다음 시도에 답이 실려 옵니다. 리졸버는 그 차이를 전혀 알지 못합니다. 그 아래에서 일어나는 일은 **[다중 왕복 요청](multi-round-trip.md)**에서 다룹니다.

물어보는 것은 리졸버가 할 수 있는 일 중 하나일 뿐입니다. 묻지 않고 계산하는 의존성, 의존성의 의존성, 모델이 제공할 수 있는 것과 없는 것 같은 일반적인 메커니즘은 **[의존성](dependencies.md)** 페이지에서 다룹니다.

## 도구 안에서 물어보기 {#ask-from-inside-the-tool}

도구는 자기 본문 한가운데서 멈추고 물어볼 수도 있습니다.

!!! warning
    `ctx.elicit()`과 `ctx.elicit_url()`은 **서버**가 **클라이언트**에게 보내는 요청이며, 이 채널은
    레거시 연결(사양 버전 **2025-11-25** 이하)을 쓰는 클라이언트에게만 존재합니다.
    **2026-07-28** 연결에는 서버가 시작하는 요청이 없으므로 이 호출은 실패합니다.
    리졸버는 양쪽 모두에서 동작합니다. 자세한 내용은 **[프로토콜 버전](../protocol-versions.md)**에서
    확인하세요.

`await ctx.elicit()`은 메시지와 Pydantic 모델을 받습니다.

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** 파라미터가 있어야 `ctx.elicit`을 쓸 수 있으며, 어떤 도구든 이 파라미터를 받을 수 있습니다. 이 객체는 별도의 페이지 **[Context](context.md)**에서 다룹니다.
* `AlternativeDate`는 원하는 답의 **스키마**입니다.
* 도구는 `async def`입니다. 그래야만 합니다. 도중에 멈춰서 사람을 기다리기 때문입니다.
* 그 밖의 날짜라면 도구는 곧바로 반환합니다. 꼭 필요할 때만 묻습니다.
* 사용자가 수락한 날짜는 다시 `book_table` 자체를 거칩니다. 답도 다른 입력과 마찬가지로 입력입니다. 대안 날짜 역시 예약이 꽉 차 있다면 무작정 확정하지 않고 다시 물어봅니다.

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

이 스키마가 곧 폼입니다. `Field(description=...)`은 레이블이 되고, 기본값은 입력란을 미리 채우며 그 필드를 선택 사항으로 만듭니다. **[도구](../servers/tools.md)** 페이지가 도구 인자를 두고 설명하는, Pydantic을 JSON Schema로 변환하는 바로 그 장치입니다.

!!! warning
    엘리시테이션 스키마는 도구의 입력 스키마만큼 표현력이 높지 않습니다. 평평한 원시 타입 필드만
    가능합니다. `str`, `int`, `float`, `bool`, 또는 문자열 `Literal`(`enum`이 됩니다)입니다.
    모델 안에 모델을 넣으면 클라이언트에 아무것도 보내기 전에 `ctx.elicit`이 예외를 일으킵니다.

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    작업 중인 사람을 가로막고 있는 것입니다. 답에 중첩 구조가 필요하다면 애초에 도구의 인자로
    받았어야 합니다.

### 세 가지 답 {#the-three-answers}

`result.action`은 사용자가 무엇을 했는지 알려 주며, 가능한 경우는 정확히 세 가지입니다.

* `"accept"`: 폼을 제출했습니다. `result.data`는 이미 검증된 `AlternativeDate` 인스턴스입니다.
* `"decline"`: 거절했습니다.
* `"cancel"`: 선택하지 않고 질문을 닫았습니다.

`result.data`는 `"accept"`일 때만 존재하며, 그래서 예제는 `result.action`을 먼저 확인합니다. 타입 체커가 이 순서를 강제합니다. `result.action == "accept"`를 확인한 뒤에는 `result.data`가 `AlternativeDate`이고, 그 전에는 `.data` 자체가 없습니다.

거절은 오류가 아닙니다. 거절이 무엇을 뜻하는지(여기서는 예약하지 않음)는 도구가 정하고, 모델에게는 평소처럼 답합니다.

!!! tip
    답은 코드가 보기 전에 모델을 기준으로 검증됩니다. `bool` 자리에 `"maybe"`를 보내는 클라이언트가
    예약을 망가뜨리지는 않습니다. 호출은 스키마 불일치 오류로 실패하고, `if` 문은 실행되지
    않습니다.

## 사용자를 URL로 보내기 {#send-the-user-to-a-url}

모델이나 클라이언트를 거쳐서는 안 되는 것이 있습니다. 자격 증명, 카드 번호, OAuth 동의가 그렇습니다. 이런 경우에는 데이터를 요청하지 않고, 사용자에게 어딘가로 가 달라고 요청합니다.

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()`은 메시지, 방문할 **URL**, 그리고 직접 정하는 `elicitation_id`를 받습니다. 서버 안에서 이 엘리시테이션을 식별하는 문자열이면 무엇이든 됩니다.
* 결과에는 action만 있고 그 외에는 아무것도 없습니다. `"accept"`는 사용자가 URL을 열겠다고 동의했다는 뜻이지, 그 너머에 있는 일을 끝냈다는 뜻이 **아닙니다**.
* 결제는 대역 외로, 사용자의 브라우저와 결제 제공자 사이에서 이루어집니다. 어떤 내용도 MCP를 통해 돌아오지 않습니다.

두 번째 도구를 보세요. 서버가 대역 외 흐름이 끝났음을 알게 되면(웹훅, 폴링, 여기서는 두 번째 도구로 모델링했습니다) `ctx.session.send_elicit_complete(...)`가 같은 `elicitation_id`로 `notifications/elicitation/complete`를 보냅니다. 클라이언트는 이를 통해 *"waiting for payment..."* 표시를 멈춰도 된다는 것을 압니다. 이 알림이 없으면 클라이언트는 짐작만 할 수 있습니다.

## 클라이언트 쪽 {#the-client-side}

서버는 묻고, 클라이언트는 `Client(...)`에 **`elicitation_callback`**을 전달해 답합니다.

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 콜백 하나가 두 모드를 모두 처리합니다. `params`는 `ElicitRequestFormParams`와 `ElicitRequestURLParams`의 유니언이며, `isinstance`로 분기합니다.
* URL이면 사용자에게 `params.url`을 보여 주고 사용자가 고른 action을 반환합니다. `content`는 절대 넣지 않습니다.
* 폼이면 실제 애플리케이션은 `params.requested_schema`를 렌더링하고 사용자의 입력을 `content`로 반환합니다. 이 예제는 항상 미리 준비된 답으로 예라고 답하는데, 테스트에서 원하는 콜백이 바로 이런 것입니다.
* 콜백을 전달하는 것이 곧 **기능 선언**이기도 합니다. 서버는 이를 통해 이 클라이언트에게 물어볼 수 있다는 것을 알게 됩니다. 클라이언트가 서버에게 답해 줄 수 있는 다른 것은 **[클라이언트 콜백](../client/callbacks.md)**에 있습니다.

!!! info
    엘리시테이션은 **서버**가 **클라이언트**에게 보내는 요청이며, 이런 요청은 고전적인 핸드셰이크
    세션에만 존재합니다. 그래서 이 클라이언트는 `mode="legacy"`를 전달합니다.
    **2026-07-28** 연결에서는 도구가 호출에서 질문을 **반환**하는 방식으로 묻습니다.
    그 흐름은 **[다중 왕복 요청](multi-round-trip.md)**에서 다룹니다.

### 직접 해 보기 {#try-it}

`ctx.elicit` 폼 모드 `server.py`(`book_table`이 있는 것)를 Streamable HTTP로 시작하고(한 줄짜리 명령은 **[서버 실행하기](../run/index.md)**에 있습니다), 클라이언트의 `main()`을 실행해 `book_table`에 크리스마스 당일을 요청하세요.

콜백은 전달받은 질문을 출력합니다.

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

콜백은 `{"accept_alternative": True, "date": "2025-12-27"}`로 답하고, 그동안 `await ctx.elicit(...)` 안에서 내내 기다리던 도구가 예약을 마무리합니다.

```text
Booked a table for 2 on 2025-12-27.
```

이제 URL 모드 `server.py`로 바꾸고 같은 `main()`이 `pay_deposit`을 호출하게 하세요. 같은 콜백이 다른 쪽 분기를 타서 결제 링크를 출력하고, 도구는 *"Complete the payment in your browser."*를 돌려줍니다. 호출 도중에 양방향으로 왕복 한 번이 오간 것입니다.

!!! check
    이제 `Client`에서 `elicitation_callback=`을 제거하고 다시 크리스마스 당일로 `book_table`을
    호출해 보세요. 호출 전체가 프로토콜 오류로 실패합니다.

    ```text
    Elicitation not supported
    ```

    콜백을 등록하지 않은 클라이언트는 `elicitation` 기능을 선언한 적이 없으므로 물어볼 상대가
    없습니다. 도구는 `"decline"`을 받은 것이 아니라 예외를 받았습니다. 이 경우를 염두에 두고
    설계하세요. 모든 엘리시테이션에는 "물어볼 수 없다면 어떻게 할 것인가?"에 대한 합리적인 답이
    필요합니다.

## 요약 {#recap}

* `Annotated[T, Resolve(fn)]`로 어노테이션한 파라미터는 리졸버가 채우며, 리졸버는 물어봐야 할 때 `Elicit(...)`을 반환합니다. 모든 연결에서 동작합니다.
* 스키마는 평평한 Pydantic 모델입니다. 원시 타입 필드만 가능하며, 돌아오는 길에 검증됩니다.
* `result.action`은 `"accept"`, `"decline"`, `"cancel"` 중 하나이며, `result.data`는 accept일 때만 존재합니다.
* `await ctx.elicit(message, schema=Model)`은 도구 본문 안에서 묻고, `await ctx.elicit_url(message, url, elicitation_id)`는 모델을 거쳐서는 안 되는 모든 것을 위한 것입니다(`ctx.session.send_elicit_complete(elicitation_id)`는 대역 외 부분이 끝났음을 알립니다). 둘 다 서버가 클라이언트에게 보내는 요청이므로 클라이언트가 레거시 연결을 쓰고 있어야 합니다.
* 클라이언트는 `elicitation_callback` 하나로 답하며 params 타입에 따라 분기합니다. 콜백을 등록하는 것이 곧 기능을 선언하는 것입니다.
* 2026-07-28 연결에서는 서버가 질문을 밀어 넣는 대신 반환하며, 같은 콜백에 **[다중 왕복 요청](multi-round-trip.md)**이 질문을 공급합니다.

그 반환 아래에 있는 모든 것(재시도 루프, `requestState` 보호, 직접 구동하기)은 **[다중 왕복 요청](multi-round-trip.md)**에서 다룹니다.
