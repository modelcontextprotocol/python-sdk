---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# 취소 {#cancellation}

클라이언트는 호출을 포기할 수 있습니다. 사용자가 중지 버튼을 눌렀거나 타임아웃이 만료된 경우입니다.

그러면 SDK가 **핸들러를 취소**합니다. 핸들러가 기다리던 `await`에서 예외가 발생하고, 함수가 빠져나오며, 함수가 반환하는 값은 전송되지 않습니다. 대부분의 핸들러는 이에 대해 아무것도 할 필요가 없습니다.

두 가지 경우는 예외입니다. 정리할 것이 있는 핸들러와 일반 `def`로 작성한 핸들러입니다.

## `async def` 도구에서 정리하기 {#clean-up-in-an-async-def-tool}

정리 코드를 `finally`에 넣으세요.

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* `finally`는 도구가 어떻게 끝나든 실행됩니다. 값을 반환했든, 예외를 발생시켰든, 취소되었든 마찬가지입니다.
* `await`가 필요한 정리 작업에는 `shield=True`가 필요합니다. 취소된 핸들러에서는 이후의 모든 `await`에서도 예외가 발생하므로, shield가 없으면 `release_hold`는 첫 줄에서 멈춥니다.
* shield로 보호된 블록은 무엇으로도 취소할 수 없으므로 시간 제한을 두세요. 여기서는 `5`초입니다.

!!! tip
    `except`가 아니라 `finally`를 사용하세요. 정리가 끝난 뒤에도 취소는 계속 위로 전파되어야 하는데,
    `finally`를 쓰면 그렇게 됩니다.

## 일반 `def` 도구에서 일찍 멈추기 {#stop-early-in-a-plain-def-tool}

일반 `def` 도구는 스레드에서 실행되며, 스레드는 외부에서 중단시킬 수 없습니다. 도구가 직접 확인해야 합니다.

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()`는 호출이 살아 있는 동안에는 아무 일도 하지 않고, 호출이 취소된 뒤에는 예외를 발생시킵니다. 작업 단위 사이마다 호출하세요.
* 여기서도 정리 코드는 `finally`에 넣습니다. 스레드에서는 아무것도 await하지 않으므로 shield가 필요 없습니다.
* 한 번도 확인하지 않는 `def` 도구는 끝까지 실행되고, 그 결과는 버려집니다.

## 적용 범위 {#where-it-applies}

프롬프트 함수와 리소스 함수도 도구와 똑같이 취소됩니다.

stdio와 Streamable HTTP에서 동일하게 동작합니다. 이 SDK의 `Client`에서 호출을 포기한다는 것은 `call_tool`을 await하는 태스크를 취소하거나, `read_timeout_seconds`가 만료되도록 두는 것을 뜻합니다.

!!! warning
    Streamable HTTP 옵션 두 가지는 취소 소식이 핸들러에 전달되지 않게 합니다. `2026-07-28` 연결에서의
    `json_response=True`와 레거시 연결에서의 `stateless_http=True`입니다. 이 경우 클라이언트가 무엇을 했든
    핸들러는 끝까지 실행됩니다.

## 요약 {#recap}

* 클라이언트가 호출을 포기하면 SDK가 핸들러를 취소합니다. 도구, 프롬프트, 리소스 모두 해당합니다.
* `async def`: `finally`에서 정리하고, await가 필요한 정리 작업은 `anyio.move_on_after(seconds, shield=True)` 안에 넣으세요.
* 일반 `def`: 작업 단위 사이마다 `anyio.from_thread.check_cancelled()`를 호출하세요. 그렇지 않으면 도구가 끝까지 실행됩니다. 정리는 일반 `finally`로 충분합니다.
* `json_response=True`(최신 연결)와 `stateless_http=True`(레거시 연결)는 취소를 비활성화합니다.

진행 상황과 취소는 실행 중인 도구와 그 **호출자** 사이의 일입니다. 서버 **운영자**를 위해 도구가 남기는 로그는 별도의 채널이며, **[로깅](logging.md)**에서 다룹니다.
