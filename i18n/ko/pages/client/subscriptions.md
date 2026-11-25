---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# 구독 {#subscriptions}

서버의 카탈로그는 고정되어 있지 않습니다. 도구는 런타임에 생겨나고, 리소스 URI 뒤에 있는 내용은 바뀝니다. 클라이언트는 `client.listen(...)`을 통해 이런 변화를 전달받습니다. `subscriptions/listen` 요청 하나를 보내면 그 응답 자체가 **스트림**이 됩니다. 이 스트림은 열린 채로 유지되며 클라이언트가 요청한 변경 알림을 실어 나릅니다.

이 페이지는 클라이언트 쪽 이야기입니다. 스트림을 열고, 메인 흐름 옆에서 지켜보고, 스트림이 끝나는 상황을 처리하는 방법을 다룹니다. 변경 사항 발행, 필터링, 메서드 제공은 서버 쪽 이야기이며, **핸들러 내부** 아래의 **[구독](../handlers/subscriptions.md)**에서 설명합니다. 여기 나오는 예제는 그 페이지에서 만든 스프린트 보드 서버와 통신합니다.

## 스트림 지켜보기 {#watching-the-stream}

구독은 컨텍스트 매니저 하나입니다. 진입하면 키워드 인수를 구독 필터로 삼아 요청을 보내고 서버의 확인 응답을 기다리므로, 블록이 시작될 때는 이미 스트림이 살아 있습니다.

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

반복하면 네 가지 타입의 이벤트가 나옵니다. `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged`, `ResourceUpdated(uri=...)`입니다.

이벤트는 **무엇이** 바뀌었는지만 알려 주고 **어떻게** 바뀌었는지는 알려 주지 않습니다. `follow_board`가 `read_resource`와 `list_tools`를 호출하는 이유가 바로 이것입니다. 이벤트는 다시 가져오라는 신호입니다. 어느 리소스가 바뀌었는지 짐작하지 말고 `event.uri`를 읽으세요. 필터 하나가 여러 URI를 지정할 수 있고, 서버가 그중 하나의 하위 리소스에 대한 변경을 보고할 수도 있습니다.

소비되기를 기다리는 중복 이벤트는 하나로 합쳐지며, 그래도 다시 가져오면 현재 상태를 얻습니다. 합쳐지는 것은 동일한 이벤트뿐입니다. 서로 다른 URI에 대한 `ResourceUpdated` 두 개는 두 개의 이벤트입니다.

핸들에는 속성이 두 가지 더 있습니다.

* `sub.honored`는 서버가 확인 응답으로 인정한 필터입니다. 전달한 필드를 담은 `SubscriptionFilter`이며 속성으로 읽습니다(`sub.honored.prompts_list_changed`). `MCPServer`는 요청한 종류를 모두 인정하므로 요청을 그대로 되돌려 줍니다. 더 적은 종류를 지원하는 서버는 더 적게 인정하며, 인정된 종류라도 한 번도 발생하지 않을 수 있습니다. 서버가 요청을 인정하는 대신 통째로 거부할 수도 있는데(서버 페이지의 [누가 지켜볼 수 있는지 결정하기](../handlers/subscriptions.md#deciding-who-may-watch) 참고), 이 경우 요청의 오류로 나타납니다.
* `sub.subscription_id`는 listen 요청의 id이며, 이 스트림의 모든 프레임에 찍히는 바로 그 값입니다. 여러 구독을 동시에 열어 둘 수 있고, 각각은 자신의 id로 역다중화됩니다.

## 블로킹 없이 지켜보기 {#watching-without-blocking}

`follow_board`는 서버가 스트림을 닫을 때까지 실행되는데, 그 시점이 영영 오지 않을 수도 있으므로 단독으로 두면 프로그램 전체를 차지합니다. 실제 클라이언트는 감시자를 메인 흐름 **옆에** 두고 싶어 합니다. 에이전트가 도구를 호출하는 동안 감시자는 캐시나 UI를 최신 상태로 유지합니다.

먼저 구독을 열고, 그다음 감시자를 시작한 뒤 하던 일을 계속하세요.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py`는 첫 번째 예제에서 `BOARD`와 `read_board`를 가져오는데, 이 저장소에서는 그 예제를
    `tutorial003.py`로 저장합니다. 렌더링된 파일을 `client.py`와 `app.py`로 나란히 저장했다면
    대신 `from client import BOARD, read_board`라고 쓰세요. 아래쪽의 `watch.py` 예제도
    같은 방식으로 `read_board`를 가져옵니다.

핵심은 순서입니다. 아무것도 재생되지 않으므로 스트림이 존재하기 전에 발행된 이벤트는 놓칩니다. `client.listen(...)`에 진입하면 확인 응답을 기다리므로, 그 순간부터의 모든 변경이 감시자에게 도달하며 블록 안에서 찍은 스냅샷은 하나도 빠뜨리지 않습니다.

열린 스트림 옆에서도 요청은 자유롭게 실행됩니다. 감시자 태스크에서든 다른 태스크에서든 같은 클라이언트로 보낼 수 있습니다. 소비되지 않은 **중복** 이벤트는 합쳐지므로, 메인 흐름이 바쁘면 다시 가져오기가 세 번이 아니라 한 번만 일어날 수 있습니다. 서로 다른 이벤트는 합쳐지지 않습니다. 여러 URI를 지정한 필터는 URI마다 대기 중인 이벤트를 하나씩 큐에 쌓습니다.

지켜보기를 멈추려면 블록을 벗어나세요. `unsubscribe` 호출은 없습니다. 블록을 소유한 태스크를 취소하면 그렇게 되며, SDK는 트랜스포트가 기대하는 방식으로 listen 요청을 취소합니다. Streamable HTTP에서는 해당 요청의 스트림을 닫습니다. 앱이 살아 있는 동안 계속 도는 감시자는 스스로 반환하지 않으므로, 종료 시 그 감시자나 감시자가 속한 태스크 그룹의 스코프를 취소하세요.

## 스트림의 끝 {#streams-end}

스트림은 두 가지 방식 중 하나로 끝나며, 둘 다 평범한 제어 흐름입니다. 서버가 정상적으로 닫으면 `async for`가 끝나고, 갑자기 끊기면 `SubscriptionLost`가 발생합니다.

이 차이는 진단용일 뿐, 다음에 할 일이 달라지지는 않습니다. 스트림은 사라졌고, 재생된 것은 없으며, 여전히 관심이 있는 감시자는 다시 listen하고 다시 가져옵니다.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

서버는 나름의 이유로 스트림을 정상적으로 닫습니다. 백로그가 너무 커진 구독자를 떼어 내는 경우도 여기에 포함되므로, 깔끔한 종료가 지켜보기를 멈추라는 신호는 아닙니다. 다시 listen하기 전에 백오프하세요.

`SubscriptionLost`에는 로컬 원인도 하나 있습니다. 클라이언트는 소비되지 않은 이벤트를 최대 1024개까지 보관하며, 그만큼 뒤처진 소비자는 한없이 불어나는 대신 구독을 잃습니다. `async for` 본문은 짧게 유지하고 느린 작업은 다른 곳에서 하세요.

`keep_following`은 `SubscriptionLost`만 잡습니다. `listen()`에 진입할 때는 `MCPError`(연결이 실패했거나 서버가 해당 메서드를 제공하지 않음), `TimeoutError`(확인 응답이 도착하지 않음), `ListenNotSupportedError`(2026년 이전 연결)도 발생할 수 있습니다. 감시자가 이 중 무엇을 재시도해야 할지 정하세요. 마지막 것은 결코 회복되지 않습니다.

## 요약 {#recap}

* `async with client.listen(...)`에 진입하세요. 진입하면 확인 응답을 기다리므로 그 이후에 발행된 것은 하나도 놓치지 않습니다.
* `async for event in sub`로 반복하세요. 이벤트는 다시 가져오라는 신호이지 페이로드가 아닙니다.
* 구독을 연 다음 감시자를 태스크로 실행하면, 도구 호출은 그 옆에서 계속 흐릅니다.
* 깔끔한 종료는 루프를 멈추고, 끊김은 `SubscriptionLost`를 발생시킵니다. 어느 쪽이든 다시 listen하고, 다시 가져오되, 먼저 백오프하세요.
* 블록을 벗어나는 것이 곧 구독 해지입니다.

이 이벤트를 발행하고, 필터를 좁히고, 단일 프로세스를 넘어 확장하는 것은 서버 쪽 이야기입니다. 자세한 내용은 **[구독](../handlers/subscriptions.md)**에서 확인하세요. 같은 이벤트는 클라이언트 쪽 캐시를 정확하게 유지하는 데도 쓰이며, 다음 페이지는 **[캐싱](caching.md)**입니다.
