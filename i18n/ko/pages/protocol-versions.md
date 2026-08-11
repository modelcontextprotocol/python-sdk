---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# 프로토콜 버전 {#protocol-versions}

MCP에는 두 시대가 있습니다.

2026-07-28 이전에 나온 서버는 모든 연결을 **`initialize` 핸드셰이크**로 시작합니다. 클라이언트가 버전을 제안하고, 서버가 다른 버전으로 답하고, 클라이언트가 이를 수락하는 과정이 첫 번째 실질적인 요청보다 앞서 모두 이루어집니다. **2026-07-28** 서버는 핸드셰이크를 없앴습니다. 클라이언트가 **`server/discover`** 프로브를 한 번 보내면 서버는 모든 것을 하나의 결과에 담아 답합니다.

`Client`가 대신 협상하므로 신경 쓸 일은 거의 없습니다. 이 페이지는 이를 제어하는 단 하나의 생성자 인자인 `mode=`와 이 값을 바꾸게 되는 세 가지 경우를 다룹니다.

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

`mode`를 전달하지 않았으므로 기본값인 `"auto"`가 적용됩니다. `async with`에 진입하면 이 SDK가 지원하는 가장 새 버전으로 `server/discover` 프로브를 한 번 보냅니다. 그다음은 다음과 같습니다.

* **최신 서버**는 프로브에 응답합니다. 클라이언트는 그 결과를 채택합니다. 왕복 한 번으로 끝납니다.
* **오래된 서버**는 `server/discover`를 알지 못하므로 오류를 반환합니다. 클라이언트는 전통적인 `initialize` 핸드셰이크로 되돌아가 거기서 협상된 결과를 그대로 받아들입니다.

어느 쪽이든 연결된 상태가 되며, `client.protocol_version`이 어느 경우였는지 알려 줍니다.

```text
2026-07-28
```

이것이 기능의 전부입니다. `Client` 하나로 어느 시대의 서버든 상대하며, 코드에 분기가 필요 없습니다.

!!! info
    `MCPServer`는 인메모리, stdio, Streamable HTTP 등 모든 트랜스포트에서 `server/discover`에
    응답하므로, 직접 작성한 서버를 상대로는 `auto`가 항상 `2026-07-28`에 도달합니다. 폴백은
    실제 2026년 이전 서버를 상대할 때만 발동하며, 바로 그때가 폴백이 필요한 순간입니다.

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"`는 프로브를 보내지 않습니다. `initialize` 핸드셰이크를 실행하며, 이는 2026년 이전 클라이언트가 여는 것과 같은 연결입니다.

```text
2025-11-25
```

같은 서버입니다. 이 서버는 `2026-07-28`을 문제없이 지원하지만, 클라이언트에게 묻지 말라고 지시한 것입니다.

이 모드는 **푸시 방식** 기능에 필요합니다.

서버 시작 요청이란 서버가 **클라이언트를** 호출하는 것입니다. `ctx.elicit(...)`가 사용자 앞에 폼을 띄우거나, 샘플링이 도구 호출 도중에 클라이언트의 모델에 컴플리션을 요청하는 경우가 여기에 해당합니다. 이 채널은 핸드셰이크 시대의 세션에만 존재합니다.

2026-07-28에서는 이 채널이 사라졌습니다. 서버는 질문을 **반환**하고, 클라이언트는 답을 담아 호출을 재시도합니다(**[다중 왕복 요청](handlers/multi-round-trip.md)**).

`mode="auto"`는 서버가 너무 오래되어 다른 방법이 없을 때만 핸드셰이크를 합니다. `mode="legacy"`는 핸드셰이크를 보장합니다. `Client(...)`에 `sampling_callback`, 요청으로 구동되기를 원하는 `elicitation_callback`, 또는 `message_handler`를 넘길 때마다 이 모드를 사용하세요. 각각은 **[클라이언트 콜백](client/callbacks.md)**에서 다룹니다.

## 버전 고정 {#pinning-a-version}

`mode`에는 최신 프로토콜 버전 문자열도 넣을 수 있습니다. 현재 그 집합은 정확히 `["2026-07-28"]`입니다.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

버전을 고정하면 **아무것도** 보내지 않습니다. 프로브도, 핸드셰이크도 없습니다. 클라이언트는 로컬에서 `2026-07-28`을 채택하고, `async with`가 반환되는 순간 연결이 살아 있습니다.

버전 고정은 **개발자가** 하는 약속입니다. 서버가 해당 버전을 지원한다는 것을 이미 알고 있다는 약속이며, 클라이언트는 이를 확인하지 않습니다.

!!! check
    버전 고정은 디스커버리가 아닙니다. `client.server_info`를 출력해 보면 그 대가가 바로 드러납니다.

    ```text
    None
    ```

    클라이언트가 서버에게 정체를 물은 적이 없으므로 `server_info`는 `None`입니다. `client.server_capabilities`도
    마찬가지로 모든 기능이 `None`입니다. 도구 호출은 여전히 동작하지만(프로토콜은 이 정보가 전혀 필요 없습니다),
    `server_capabilities`를 읽어 무엇을 제공할지 결정하는 코드는 동작하지 않습니다.

    해결책은 다음 절에 있습니다.

고정할 수 있는 것은 최신 버전뿐입니다. 핸드셰이크 시대의 문자열은 어떤 I/O도 일어나기 전인 생성 시점에 거부되며, 오류 메시지가 대신 무엇을 써야 하는지 알려 줍니다.

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## `prior_discover`로 다시 연결하기 {#reconnecting-with-prior_discover}

프로브는 가볍지만, 다시 연결할 때마다 치러야 하는 왕복인 것은 변함없고, 그 답은 거의 바뀌지 않습니다.

그러니 보관해 두세요. `auto` 연결 후 `client.session.discover_result`에는 서버가 보낸 `DiscoverResult`가 그대로 담겨 있습니다. `supported_versions`, `capabilities`, `instructions`, 그리고 서버가 결과의 `_meta`에 새겨 넣은 신원 정보까지 포함됩니다. 다음번에는 이를 `prior_discover=`로 다시 넘기세요.

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

두 번째 연결은 협상 왕복을 **한 번도** 하지 않았으면서도 상대가 누구인지 정확히 알고 있습니다. 이것이 고정 모드를 제대로 쓰는 방법입니다. `mode=`가 버전을 지정하고, `prior_discover=`가 신원 정보를 제공합니다.

`DiscoverResult`는 Pydantic 모델입니다. `saved.model_dump_json()`의 결과는 파일이나 캐시에 저장하고, 다음 프로세스에서 `DiscoverResult.model_validate_json(...)`으로 되살립니다.

!!! tip
    `prior_discover=`는 `mode`가 버전 고정일 때만 효과가 있습니다. `"auto"`에서는 클라이언트가
    어차피 서버에 프로브를 보내고, `"legacy"`에서는 무시됩니다.

## 네 가지 모드 {#the-four-modes}

| 작성하는 코드 | 협상 트래픽 | 결과 |
| --- | --- | --- |
| `Client(target)` | `server/discover` 프로브 한 번, 실패하면 `initialize` 핸드셰이크 | 시대와 관계없이 양쪽이 모두 지원하는 가장 새 버전 |
| `Client(target, mode="legacy")` | `initialize` 핸드셰이크 | 핸드셰이크 시대 버전, 서버 시작 요청이 동작함 |
| `Client(target, mode="2026-07-28")` | 없음 | 해당 버전으로 고정, `server_info`는 `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | 없음 | 해당 버전으로 고정, **그리고** 지난번에 저장한 신원 정보 |

## 요약 {#recap}

* MCP에는 핸드셰이크 시대(`2025-11-25`까지, `initialize` 핸드셰이크)와 최신 시대(`2026-07-28`, `server/discover`)가 있습니다. `Client`가 둘 사이를 이어 줍니다.
* `mode="auto"`가 기본값이며, 프로브를 보내고 실패하면 폴백합니다. 나머지 세 행 중 하나에 해당하지 않는 한 그대로 두세요.
* "무엇을 얻었는가?"에 대한 답은 언제나 `client.protocol_version`입니다.
* `mode="legacy"`는 핸드셰이크를 강제합니다. 샘플링, 푸시 엘리시테이션(elicitation), `message_handler` 같은 서버 시작 요청에 필요한 모드입니다.
* 버전 고정(`mode="2026-07-28"`)은 협상 트래픽을 전혀 보내지 않는 대신 `client.server_info`가 `None`이 됩니다.
* `prior_discover=`가 그 대가를 되돌려 줍니다. `client.session.discover_result`를 저장해 두었다가 그 값으로 다시 연결하면 둘 다 얻습니다.

최신 연결에는 푸시 채널이 없습니다. 그렇다면 2026 서버는 호출 도중 어떻게 질문합니까? 질문을 반환합니다. 자세한 내용은 **[다중 왕복 요청](handlers/multi-round-trip.md)**에서 확인하세요.
