---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# 샘플링과 루트 {#sampling-and-roots}

핸들러는 연결된 클라이언트에 두 가지를 더 요청할 수 있습니다. 클라이언트가 가진 모델의 완성 결과(**샘플링**)와 클라이언트의 작업 공간 폴더(**루트**)입니다.

두 기능 모두 SDK가 지원하는 모든 프로토콜 버전에서 여전히 동작합니다. 다만 이를 중심으로 설계하기 전에 아래 경고를 먼저 읽어 보세요.

!!! warning "2026-07-28 사양에서 지원 중단 예정"
    샘플링과 루트는 `2026-07-28`부터 지원 중단 예정(deprecated)입니다([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). 완전히 동작하는 상태로 유지되며 제거 대상이 되기 전까지 최소 12개월 동안 사양에 남아 있지만, 새로 구현하는 경우에는 이 기능을 기반으로 삼지 않아야 합니다. 권장하는 마이그레이션 방법은 다음과 같습니다. 샘플링 대신 LLM 제공자의 API와 직접 통합하고, 루트 대신 도구 매개변수, 리소스 URI 또는 서버 설정으로 디렉터리를 전달하세요. SDK 전체 목록은 **[지원 중단 예정 기능](../deprecated.md)**에서 확인하세요.

## 샘플링: 클라이언트의 모델 빌려 쓰기 {#sampling-borrow-the-clients-model}

리졸버가 `Sample(...)`을 반환하면 도구는 완성 결과를 받습니다. **[의존성](dependencies.md)**에서 `Elicit`를 실행하는 것과 같은 의존성 메커니즘을 거칩니다.

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)`은 `sampling/createMessage` 매개변수를 그대로 따릅니다. 주입되는 값은 클라이언트의 `CreateMessageResult`이며, `tools`나 `tool_choice`를 전달하면 대신 `CreateMessageResultWithTools`가 됩니다.
* 클라이언트는 `sampling` 기능을 선언해 두어야 합니다(`tools`나 `tool_choice`를 전달한다면 `sampling.tools`). 선언하지 않았다면 클라이언트가 처리할 수 없는 요청을 보내는 대신 `-32021` 프로토콜 오류로 호출이 실패합니다. 백채널이 없는 2026 이전 세션은 보낼 통로가 없으므로 평소와 같은 백채널 없음 오류로 실패합니다.
* `2026-07-28`에서는 요청이 다중 왕복 흐름(**[다중 왕복 요청](multi-round-trip.md)**) 안에서 전달되고, `2025-11-25`에서는 클라이언트로 가는 독립된 요청입니다. 코드는 어느 쪽이든 동일하지만 다중 왕복 규칙에 유의하세요. 요청은 재시도 라운드마다 동일하게 구성되어야 하므로 도구의 인자와 그 밖의 안정적인 데이터만으로 만들어야 합니다.
* `include_context`는 건드리지 마세요. `"none"` 이외의 값은 그 자체로 지원 중단 예정(SEP-2596)이며, 거의 어떤 클라이언트도 선언하지 않는 기능이 필요합니다.

## 루트: 어디에 두어야 할까 {#roots-where-should-this-go}

루트는 서버가 작업해도 된다고 클라이언트가 알려 주는 폴더입니다. 참고용 안내일 뿐 접근 제어 메커니즘이 아닙니다. 리졸버가 `ListRoots()`를 반환합니다.

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* 주입되는 `ListRootsResult`에는 `Root` 목록이 담깁니다. 각 항목은 `file://` URI와 선택적인 표시 이름으로 이루어집니다.
* 조건은 샘플링과 같습니다. `roots` 기능이 선언되어 있지 않으면 요청을 보내는 대신 `-32021`로 호출이 실패합니다.

연결 반대편에서 클라이언트는 이미 가지고 있는 콜백인 `sampling_callback`과 `list_roots_callback`으로 두 요청에 응답합니다. 자세한 내용은 **[클라이언트 콜백](../client/callbacks.md)**에서 확인하세요.

## 2025년대 연결에서 {#on-2025-era-connections}

세션을 직접 다루는 코드를 위해 `ctx.session.create_message(...)`와 `ctx.session.list_roots()`가 여전히 존재합니다. 백채널이 있는 곳(2025년대, 비무상태 연결)에서만 동작하며, 호출하면 지원 중단 경고가 발생합니다. 위의 리졸버 마커가 지원되는 형태입니다. 협상된 버전에 따라 전달 방식을 선택하며 경고를 내지 않습니다.

## 요약 {#recap}

* 리졸버에서 `Sample(...)`이나 `ListRoots()`를 반환하세요. 도구는 다른 의존성과 마찬가지로 `CreateMessageResult`나 `ListRootsResult`를 받습니다.
* 클라이언트는 해당하는 기능을 선언해야 하며, 그렇지 않으면 요청이 전송되는 대신 `-32021`로 호출이 실패합니다.
* 두 기능 모두 `2026-07-28`에서 지원 중단 예정입니다. 지금은 완전히 동작하지만 새 설계에는 적합하지 않습니다. 샘플링보다는 제공자 API를, 루트보다는 명시적 매개변수를 사용하세요.

느린 도구가 얼마나 진행되었는지 보고하는 방법은 **[진행 상황](progress.md)**에서 확인하세요.
