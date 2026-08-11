---
translation:
  sections: [20541a40dbdd5980, 01262a123ad9501d, 429db5b574a2ac08, 56b2d49da412cb28, 6a1717123fe4513c]
  tool: 1
---
# 지원 중단 예정 기능 {#deprecated-features}

2026-07-28 사양은 다섯 가지를 퇴역시킵니다. SDK는 여전히 이 다섯 가지를 모두 구현하며, 이제 모두에 **지원 중단 예정(deprecated) 경고**가 붙습니다.

아래 표는 지원 중단 예정인 각 기능의 이름, 사라지는 이유, 그리고 대신 사용할 대체 수단을 정리한 것입니다.

## 지원 중단 예정 대상 {#what-is-deprecated}

| 지원 중단 예정 | 이유 | 대신 할 일 |
|---|---|---|
| **루트**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, `Client(...)`에 전달하는 `list_roots_callback=` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)이 이 기능을 퇴역시킵니다. | 경로를 일반 도구 인자나 리소스 URI로 받거나, `InputRequiredResult`에 `ListRootsRequest`를 담으세요(**[다중 왕복 요청](handlers/multi-round-trip.md)** 참고). |
| **서버 주도 샘플링**: `ctx.session.create_message()`, `Client(...)`에 전달하는 `sampling_callback=` | SEP-2577이 이 기능을 퇴역시킵니다. | `InputRequiredResult`를 반환하고 클라이언트가 호출을 재시도하게 하세요(**[다중 왕복 요청](handlers/multi-round-trip.md)** 참고). |
| **프로토콜 로깅**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577이 이 기능을 퇴역시킵니다. 프로토콜 안에서 이를 대체하는 것은 없습니다. | stderr로 보내는 일반 `import logging`을 사용하세요(**[로깅](handlers/logging.md)** 참고). |
| **`ping`**: `client.send_ping()` | 단순히 지원 중단 예정이 아니라 프로토콜에서 **제거되었습니다**. 2026-07-28에는 `ping` 메서드가 없습니다. | 없습니다. `mode="legacy"` 연결에서만 동작합니다. |
| **클라이언트->서버 진행 상황**: `client.send_progress_notification()` | 2026-07-28에서는 진행 상황이 서버->클라이언트 방향만 허용됩니다. | 보낼 것이 없습니다. **서버**가 `ctx.report_progress()`로 진행 상황을 보고합니다(**[진행 상황](handlers/progress.md)** 참고). |

이 표에서 세 가지를 읽어낼 수 있습니다.

* 루트, 샘플링, 로깅은 한 묶음입니다. 하나의 제안인 **SEP-2577**이 세 기능을 한꺼번에 지원 중단 예정으로 지정합니다.
* 샘플링과 루트는 더 근본적인 문제를 공유합니다. 둘 다 **서버**가 **클라이언트**에게 **요청**을 보내는 지점입니다. 2026-07-28은 바로 이 방향 전체를 **[다중 왕복 요청](handlers/multi-round-trip.md)**으로 대체합니다. 사라지는 것은 독립된 RPC 메서드(`sampling/createMessage`, `roots/list`, 푸시 방식의 `elicitation/create`)이고, `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` 페이로드 타입은 `InputRequiredResult.input_requests`에 담긴 형태로 살아남으며, 클라이언트에서는 같은 콜백에 도달합니다.
* `ping`은 예외적인 경우입니다. 프로토콜은 이를 지원 중단 예정으로 지정한 것이 아니라 제거합니다. SDK 메서드는 여전히 경고를 내며(경고 메시지는 *deprecated*가 아니라 *removed*라고 말합니다), 최신 연결에서 호출하면 *"Method not found"*가 돌아옵니다.

## 지원 중단 예정은 권고 사항입니다 {#deprecated-is-advisory}

오늘 당장 깨지는 것은 없습니다.

위의 모든 메서드는 **2025-11-25 또는 그 이전**으로 협상된 세션에서 계속 동작합니다. 클라이언트에서 `mode="legacy"`로 고정하면 2026년 이전과 정확히 같은 동작을 얻습니다. 와이어 변경은 없고 기능 협상도 그대로입니다.

달라지는 점은 각 메서드가 처음 실행될 때 눈에 띄는 경고가 나온다는 것입니다.

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning`은 `DeprecationWarning`이 **아니라** `UserWarning`의 하위 클래스입니다. 의도된 선택입니다. Python의 기본 필터는 `__main__`으로 직접 실행되는 코드에서만 `DeprecationWarning`을 보여 주는데, 라이브러리가 이런 식으로 지원 중단 예정을 알리면 2년 동안 아무도 눈치채지 못합니다. 이 경고는 `-W` 플래그 없이도 어디서나 나타납니다.

!!! warning
    "권고 사항"은 와이어 앞에서 멈춥니다. 샘플링과 루트는 서버에서 클라이언트로 가는
    **요청**이고, 2026-07-28 세션에는 이를 실어 나를 채널이 없습니다. 최신 연결의 도구
    안에서 `ctx.session.create_message()`를 호출하면 경고는 여전히 발생하고, 그다음 전송이
    오류와 함께 실패합니다.

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    두 개의 신호가 이 순서로 나옵니다. `MCPDeprecationWarning`은 어떤 연결에서든 메서드를
    호출하는 순간 발생합니다. 오류는 그다음 SDK가 전송을 시도할 때 돌아오는 결과입니다.
    이 두 기능은 클라이언트가 해당 콜백을 등록한 `mode="legacy"` 연결에서만 처음부터
    끝까지 동작합니다.

## 경고 끄기 {#silencing-the-warning}

새 코드에서는 끄지 마세요.

하지만 유지보수 중인 서버가 실제로 2026년 이전 클라이언트를 상대한다면 조용한 로그를 가질 자격이 충분합니다. 지원 중단 예정 호출이 처음 실행되기 전에 카테고리를 필터링하세요.

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

이것이 API의 전부입니다. 메서드별 스위치는 없으며, 있을 필요도 없습니다. 카테고리가 하나라는 것의 핵심은 한 줄로 끄고 한 줄로 다시 켤 수 있다는 점입니다.

!!! check
    필터를 반대 방향으로 적용하면 회귀 테스트를 거저 얻습니다. pytest 설정의
    `filterwarnings` 항목에 `"error::mcp.MCPDeprecationWarning"`을 추가하면 지원 중단 예정
    호출이 경고 대신 예외를 **발생시킵니다**. 여전히 `ctx.info()`를 호출하는 `old_log`라는
    도구는 더 이상 통과하지 못하고 다음과 같이 보고하기 시작합니다.

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    pytest 설정 한 줄이면, 지원 중단 예정 호출이 테스트를 실패시키지 않고 코드베이스에
    몰래 다시 들어오는 일은 결코 없습니다.

## 요약 {#recap}

* 2026-07-28 사양은 **루트**, 서버 주도 **샘플링**, 프로토콜 **로깅**을 지원 중단 예정으로 지정하고(모두 [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), **진행 상황**을 서버에서 클라이언트 방향으로 제한하며, **`ping`**을 제거합니다.
* 대체 수단 열이 다음 단계를 안내합니다. 샘플링과 루트는 **[다중 왕복 요청](handlers/multi-round-trip.md)**, 로깅은 **[로깅](handlers/logging.md)**, 진행 상황은 **[진행 상황](handlers/progress.md)**을 보세요. `ping`은 아무것도 필요 없습니다.
* 지원 중단 예정은 권고 사항입니다. 와이어 변경은 없고, 2026년 이전 세션에서는 모든 것이 계속 동작하며, 눈에 띄는 `MCPDeprecationWarning`이 나옵니다(`UserWarning`이므로 기본적으로 켜져 있습니다).
* 샘플링과 루트는 추가로 2026-07-28 세션에는 없는 백채널이 필요합니다. 최신 연결에서는 경고를 낸 뒤 예외를 발생시킵니다.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)`은 카테고리 전체를 끄고, pytest의 `"error::mcp.MCPDeprecationWarning"`은 이를 테스트 실패로 바꿉니다.
* 새 코드는 이 기능 중 어느 것에도 기반해서는 안 됩니다.

이 문서의 다른 모든 페이지는 현재 API를 설명합니다.
