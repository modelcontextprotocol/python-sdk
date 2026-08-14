---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# 다중 왕복 요청 {#multi-round-trip-requests}

도구가 한 번의 왕복으로 끝나지 않을 때가 있습니다. 선택, 확인, 자격 증명처럼 사용자만 가진 무언가가 필요한 경우입니다.

2026-07-28 이전에는 서버가 **역방향 호출**로 이를 얻었습니다. 원래 요청을 처리하는 도중에 엘리시테이션(elicitation)이나 샘플링 호출 같은 자체 요청을 클라이언트에게 여는 방식입니다. 2026-07-28 사양은 이 백채널을 폐지합니다.

대신 서버는 **반환**합니다.

## 역방향 호출 대신 반환 {#return-dont-call-back}

서버는 `tools/call`에 `CallToolResult` 대신 **`InputRequiredResult`**로 응답합니다. 핵심은 두 필드입니다.

* **`input_requests`**: 서버에 아직 필요한 것으로, 서버가 고른 이름을 키로 하는 dict입니다. 각 값은 `ElicitRequest`, `CreateMessageRequest`, `ListRootsRequest` 중 하나입니다.
* **`request_state`**: 불투명 토큰입니다. 클라이언트는 재시도할 때 이 토큰을 그대로 되돌려 보냅니다. 이 토큰을 읽는 것은 서버뿐입니다.

클라이언트는 각 요청을 처리한 뒤, 답을 `input_responses`에, 토큰을 `request_state`에 담아 **같은 도구를 다시** 호출합니다. 이제 서버는 부족했던 것을 갖추었으므로 일반적인 `CallToolResult`를 반환합니다.

프로토콜은 이것이 전부입니다. 모든 구간은 클라이언트가 서버로 보내는 평범한 요청입니다. 반대 방향으로 흐르는 것은 아무것도 없습니다.

## 서버 측 {#the-server-side}

`@mcp.tool()`에서는 이것을 직접 만드는 일이 거의 없습니다. 사용자에게 묻거나(`Elicit`), 클라이언트의 LLM을 샘플링하거나(`Sample`), 루트를 나열하는(`ListRoots`) 의존성을 선언하면 SDK가 대신 `InputRequiredResult`를 반환합니다. 이 형태는 **[의존성](dependencies.md)** 페이지에서 다룹니다. 두 형태는 섞어 쓸 수 없습니다. 호출 하나에는 `input_responses`/`request_state` 채널이 하나뿐이므로, `Resolve(...)` 매개변수를 쓰는 도구는 본문에서 `InputRequiredResult`를 함께 반환할 수 없습니다. `InputRequiredResult` 반환을 선언하면 등록 시점에 거부되고(`InvalidSignature`), 선언하지 않고 반환하면 런타임에 호출이 실패합니다. 수동 형태는 **저수준** `Server`이며, 그 `on_call_tool` 핸들러는 두 결과 타입 중 어느 쪽이든 반환할 수 있습니다.

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool`의 타입은 `-> CallToolResult | InputRequiredResult`입니다. 두 번째를 반환하는 것이 서버 측 API의 전부입니다.
* 첫 호출에서 `params.input_responses`는 `None`이므로 가드가 작동하여 핸들러는 답하는 대신 묻습니다.
* 재시도에서는 클라이언트가 보낸 `ElicitResult`가 서버가 `input_requests`에서 사용한 것과 **같은 키**(`"region"`) 아래에 들어 있습니다.

그 파일의 나머지(명시적인 `input_schema`, 직접 만든 `CallToolResult`)는 평범한 저수준 `Server`이며 **[저수준 Server](../advanced/low-level-server.md)**에서 다룹니다. 이 페이지는 두 번째 반환 타입만 더합니다.

## 도구 외의 경우 {#beyond-tools}

`tools/call`만 특별한 것은 아닙니다. 2026-07-28에서는 서버가 `prompts/get`과 `resources/read`에도 같은 방식으로 응답할 수 있습니다. `MCPServer`에서는 `@mcp.prompt()` 함수(또는 `@mcp.resource()` **템플릿** 함수)가 직접 `InputRequiredResult`를 반환하고, 재시도의 답을 컨텍스트에서 읽습니다.

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* 첫 라운드는 `InputRequiredResult`를 반환합니다. 재시도에서는 `ctx.input_responses`가 같은 키 아래에 답을 담고 있으며, 함수는 평소의 결과를 반환합니다. 여기서는 프롬프트 메시지이고, 템플릿 리소스라면 리소스 콘텐츠입니다.
* 직접 설정한 `request_state`는 서버의 다른 모든 것과 마찬가지로 전송되기 전에 봉인되고 되돌아올 때 검증됩니다. 봉인이 무엇을 보장하는지, 언제 키를 설정해야 하는지는 아래 **[`requestState` 보호](#protecting-requeststate)**에서 다룹니다.
* 의존성 형태가 맞지 않을 때는 `@mcp.tool()` 함수도 같은 방식으로 결과를 직접 반환할 수 있습니다.
* 정적 `@mcp.resource()` 함수는 참여하지 않습니다. `Context`를 받지 않으므로 재시도를 읽을 방법이 없기 때문입니다. 물을 수 있는 것은 템플릿 리소스뿐입니다.
* 아래의 프로토콜 세대 규칙은 그대로 적용됩니다. 2026 이전 세션에서 `InputRequiredResult`를 반환하면 경고에서 설명하는 것과 같은 `-32603`입니다.

## 클라이언트 측 {#the-client-side}

`Client`가 루프를 대신 돌립니다.

서버가 요청할 수 있는 콜백(`elicitation_callback`, `sampling_callback`, `list_roots_callback`)을 등록하고 도구를 호출하세요. `InputRequiredResult`가 도착하면 `Client`는 `input_requests`의 각 항목을 해당 콜백으로 보내고, 답과 되돌려 보낼 `request_state`를 담아 재시도하며, `CallToolResult`가 돌아올 때까지 계속합니다.

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* 이 `elicitation_callback`은 2026 이전 서버의 백채널 `elicitation/create`가 호출했을 바로 그 콜백입니다. `sampling/createMessage`의 `sampling_callback`, `roots/list`의 `list_roots_callback`도 마찬가지입니다. 2026-07-28에서는 독립적인 서버->클라이언트 RPC가 사라졌지만, 동일한 `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` 페이로드가 `input_requests` 안에 실려 와서 같은 세 콜백으로 전달됩니다. 한 벌의 콜백이 두 세대를 모두 처리합니다.
* `call_tool`은 평범한 `CallToolResult`를 반환합니다. 중간 라운드는 호출자에게 보이지 않습니다.
* `get_prompt`와 `read_resource`도 같은 루프를 구동합니다.

!!! check
    콜백을 빼면 루프는 첫 라운드에서 실패합니다. SDK의 대체 콜백은 모든 엘리시테이션에
    오류로 답하며, `call_tool`은 *"Elicitation not supported"*라는 메시지와 함께 `MCPError`를
    발생시킵니다.

루프에는 한도가 있습니다. `Client(..., input_required_max_rounds=10)`이 기본 상한이며, 이를 넘겨서도 계속 `InputRequiredResult`를 반환하는 서버는 `call_tool`에서 예외를 일으킵니다. 라운드에 `input_requests` 없이 `request_state`만 실려 있으면 `Client`는 재시도 전에 잠시 쉽니다(50ms에서 시작해 250ms 상한까지 두 배씩 늘어납니다). 그래서 그저 "아직 끝나지 않았음"을 알리는 서버를 바쁘게 폴링하지 않습니다.

### 루프 직접 구동 {#driving-the-loop-yourself}

단일 프로세스 클라이언트에는 자동 루프로 충분합니다. 다음과 같은 경우에는 루프를 직접 맡으세요.

* 클라이언트가 **분산**되어 있을 때. 사용자에게 질문을 표시하는 프로세스가 `call_tool`을 호출한 프로세스와 다르므로 다른 워커가 재시도를 보냅니다. `request_state`는 그 경계를 넘어 자체 저장소를 통해 운반하는 영속 가능한 토큰이고, `input_responses`는 반대편이 그 토큰과 함께 돌려보내는 것입니다.
* 각 라운드를 **검사**하고 싶을 때. 모든 `input_requests` 항목을 기록하거나 감사하고, 특정 종류의 요청을 거부하거나, 구간 사이에 자체 백오프를 적용합니다.
* 라운드 수가 아니라 **실제 경과 시간**으로 한도를 두고 싶을 때. `input_required_max_rounds`에 기대는 대신 자체 루프를 `anyio.fail_after(...)`로 감싸세요.

하위 세션으로 내려가면 `allow_input_required=True`가 유니언을 직접 건네줍니다.

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)`는 반환 타입을 `CallToolResult | InputRequiredResult`로 넓힙니다. 다시 좁히는 것은 `isinstance`입니다.
* 이제 `request_state`는 직접 다룹니다. 구간 사이에 기록해 두면 새 프로세스에서 대화를 재개할 수 있습니다.
* `input_requests`의 모든 항목에 대해 `input_responses`의 **같은 키** 아래에 `InputResponse`를 넣습니다. `fulfil`이 UI가 들어갈 자리이며, 이 예제는 답을 하드코딩합니다.
* 모든 구간에서 같은 도구 이름, 같은 `arguments`입니다. 재시도는 원래 호출을 다시 수행하는 것이지 새 메서드가 아닙니다.

## `requestState` 보호 {#protecting-requeststate}

위의 모든 내용은 `request_state`를 단순 에코로 취급하며, 전송 구간에서는 실제로 그것이 전부입니다. 하지만 클라이언트가 구간 사이에 이를 보관하므로(프로세스를 넘어 기록해 두는 것이 바로 앞 절에서 허용한 일입니다), 돌아오는 것은 **클라이언트가 제공한 입력**입니다. 변조되었거나, 만료되었거나, 아예 다른 호출에서 가져온 것일 수 있습니다. 사양은 상태가 인가, 리소스 접근, 비즈니스 로직에 영향을 줄 수 있는 경우 서버가 이 상태의 무결성을 보호하고 검증에 실패하면 라운드를 거부할 것을 요구합니다.

`MCPServer`는 기본적으로 이를 보호합니다. 모든 서버는 프로세스 시작 시 생성된 키로 나가는 `requestState`를 봉인하고, 리졸버 상태든 직접 만든 상태든 되돌아오는 모든 에코를 검증합니다. 아무것도 설정할 필요 없이 평문을 쓰고 평문을 읽으며, 전송 구간에는 불투명한 암호화 토큰만 오갑니다.

기본 키는 프로세스와 생사를 함께합니다. 단일 프로세스를 넘어 배포하기 전에 반드시 알아야 할 한 가지가 바로 이것입니다.

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **기본값(설정 없음)**은 단일 프로세스에 적합합니다. stdio 또는 정확히 하나의 HTTP 워커입니다. 다른 워커, 로드 밸런서 뒤의 다른 인스턴스, 또는 재시작 후의 같은 서버에 도착한 재시도는 그 프로세스가 갖고 있지 않은 키로 봉인되어 있으므로, 클라이언트는 아래의 고정된 거부 응답을 받고 흐름을 처음부터 다시 시작해야 합니다.
* **`keys=[...]`** 설정은 재시도가 **다른 인스턴스**에 도달할 수 있거나(다중 워커 `uvicorn`, 로드 밸런싱된 HTTP) 재시작 후에도 살아남아야 할 때 필수입니다. 모든 인스턴스가 형제 인스턴스가 발급한 것을 검증합니다. 같은 장치이되, 생성된 비밀 대신 직접 제공한 비밀을 씁니다.
* KMS나 기존 토큰 서비스 같은 자체 암호화를 쓰려면 `keys` 대신 `RequestStateSecurity(codec=...)`를 전달하세요. 계약은 아래 **[자체 암호화 사용](#bring-your-own-crypto)**에서 다룹니다.

### 봉인이 담는 것 {#what-the-seal-carries}

기본값이든 설정했든, 전송 구간의 `requestState`는 암호화되고 인증된 토큰입니다. 코드에서는 이를 볼 일이 없습니다. 핸들러와 리졸버는 평문을 쓰고 평문을 읽으며(`ctx.request_state`), SDK가 나갈 때 봉인하고 들어올 때 검증합니다. 무결성 외에도 각 토큰은 다음에 묶입니다.

* **시간 창.** 매 라운드마다 새 만료 시각으로 다시 봉인하므로, `RequestStateSecurity(ttl=...)`(기본 600초)는 전체 흐름이 아니라 라운드별 생각할 시간을 제한합니다.
* **인증된 주체.** 요청이 SDK가 검증한 OAuth 액세스 토큰을 지니고 있으면 상태는 토큰의 클라이언트, 발급자(issuer), 사용자 식별자(subject)에 묶입니다. 한 사용자를 위해 발급된 상태는 두 사용자가 하나의 OAuth 클라이언트를 공유하더라도 다른 사용자 아래에서는 실패합니다. subject를 제공하지 않는 검증기는 바인딩을 클라이언트 ID만으로 약화시키는데, URL 기반 클라이언트 ID에서는 그 클라이언트 소프트웨어의 모든 사용자가 이를 공유합니다. 인증이 SDK 바깥(앞단 프록시)에서 종료되거나 트랜스포트가 인증되지 않은 경우에는 묶을 주체가 없으므로 이 검사는 작동하지 않습니다. 단, `RequestStateSecurity(bind_principal=...)`로 자체 ID 신호에서 주체를 제공하면 작동합니다. 토큰 검증기가 어떤 구성 요소를 제공하든 일관되게 제공해야 합니다. 어떤 요청에는 subject를 포함하고 다른 요청에는 빼는 검증기는 흐름 도중에 주체를 바꾸는 셈이고, 진행 중인 라운드는 거부됩니다.
* **원래 요청.** 메서드, 도구 또는 프롬프트 이름(또는 리소스 URI), 그리고 인수의 다이제스트입니다. 다른 도구, 다른 인수, 다른 메서드에 재사용된 토큰은 실패합니다.
* **질문한 내용 그대로.** 모든 리졸버 답은 클라이언트에게 표시된 렌더링된 질문에 고정됩니다. 답이 처음 도착한 라운드에서도, 기록된 답을 나중에 재사용할 때도 마찬가지입니다. 문구를 바꾼 메시지나 변경된 스키마로 재배포하면 서버는 오래된 답을 소비하는 대신 다시 묻습니다. 같은 고정은 반대로도 작용합니다. 메시지는 호출별 데이터가 아니라 도구의 인수에서 만드세요. 타임스탬프나 실시간 시세로 만든 메시지는 라운드마다 다르게 렌더링되므로 기록된 모든 답이 오래된 것으로 보이고, 서버는 클라이언트의 라운드 한도가 호출을 끝낼 때까지 다시 묻습니다.

이 모든 것은 SDK의 일이지 작성자의 일이 아니며, 자체 코덱을 가져오더라도 코덱의 일이 아닙니다.

### 키 교체 {#rotating-keys}

`keys[0]`이 새 상태를 봉인하고, 목록의 모든 키가 검증에 쓰입니다. 무중단 교체는 세 단계이며, 각 단계는 다음 단계로 넘어가기 전에 완전히 배포되어야 합니다.

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

발급 키를 먼저 승격하지 마세요. 일부 인스턴스가 아직 검증할 수 없는 키로 발급하면 배포 도중 진행 중인 라운드가 버려집니다.

키는 하나의 서비스에 한정됩니다. 봉인된 봉투에는 서버 이름도 audience 클레임으로 담기므로, 우연히 같은 비밀을 공유하는 다른 서비스가 발급한 토큰은 어차피 거부됩니다. 클레임의 변별력은 이름만큼이므로, 명시적 정책이 주어진 서버는 실제 이름이 있거나 `RequestStateSecurity(audience=...)`를 설정해야 합니다. 이름 없는 서버는 생성 시점에 예외를 일으킵니다. `audience=`는 한 서비스가 다른 서비스가 발급한 상태를 받아들여야 하는 의도적인 다중 서비스 토폴로지에도 쓰입니다. (설정 없는 기본값은 예외입니다. 키가 프로세스를 떠나지 않으므로 audience 클레임이 더할 것이 없습니다.)

### 자체 암호화 사용 {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)`에는 `seal(bytes) -> str`과 `unseal(str) -> bytes`를 갖추고 자신이 발급하지 않은 토큰에 대해 `InvalidRequestState`를 발생시키는 것이면 무엇이든 전달할 수 있습니다. 전형적인 형태는 KMS를 이용한 봉투 암호화로, 시작 시 데이터 키를 한 번 풀고 토큰별 암호화는 로컬에서 수행합니다.

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL, 주체 바인딩, 요청 바인딩은 코덱의 일이 **아닙니다**. SDK가 모든 코덱에 대해 `seal` 전에 페이로드에 이를 찍어 넣고 `unseal` 후에 다시 검증합니다. 코덱의 의무는 무결성(변조되었으면 예외를 발생시킴)과, 가능하면 기밀성뿐입니다.

### 검증 실패 시 {#when-verification-fails}

들어오는 쪽의 모든 실패는 변조든, 만료든, 다른 요청이나 주체에 대한 재사용이든, 이 서버가 모르는 키로 봉인된 것이든 같은 답을 받습니다.

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

원인이 무엇이든 하나의 고정된 메시지이므로 전송 구간에서는 어떤 검사가 실패했는지 드러나지 않으며, 실제 이유는 서버 로그에 남습니다. `tools/call`, `prompts/get`, `resources/read`로 들어오는 모든 `requestState`가 검사되며, 상태를 발급한 적 없는 핸들러로 오는 것도 포함됩니다. 실제로 가장 흔한 거부는 공격자가 아니라, 기본 프로세스 로컬 키가 재시작 이전이나 다른 인스턴스에서 온 재시도를 만나는 경우입니다. 클라이언트는 흐름을 다시 시작하며, 이것이 문제가 된다면 `keys=[...]` 설정이 해결책입니다.

### 직접 만든 상태 {#hand-built-state}

직접 설정한 `request_state`(도구, 프롬프트, 리소스 템플릿 함수에서 `InputRequiredResult`를 반환하는 경우)는 코드 변경 없이 리졸버 상태와 같은 장치로 봉인되고 검증됩니다. 평문을 쓰고 평문을 읽으면 위의 모든 바인딩이 적용됩니다.

설정했더라도 SDK가 대신 고정할 수 없는 한 가지는 질문의 동일성입니다. 상태에 있는 답이 **직접 만든** 질문 중 어느 것에 속하는지 SDK는 알지 못합니다. 답을 질문별로 키를 매겨 저장한다면 자체 질문 식별자를 상태에 넣고 재시도에서 확인하세요.

저수준 `Server`는 기본 제공 기능이 없는 계층입니다. `MCPServer`와 달리 경계를 직접 덧붙이기 전까지는 아무것도 봉인되지 않으며, 그러기 전까지 `request_state`는 작성한 그대로 전송 구간을 건너갑니다. 한 줄짜리 옵트인은 **[저수준 Server](../advanced/low-level-server.md#the-other-handlers)**에 나와 있습니다.

## 2026-07-28 전용 결과 {#a-2026-07-28-result}

`InputRequiredResult`는 프로토콜 버전 **2026-07-28**에만 존재합니다. 인메모리 `Client(server)`는 이를 대신 협상하고, 네트워크를 통할 때는 `mode="auto"`가 이를 발견합니다. 연결한 뒤에는 `client.protocol_version`이 무엇을 얻었는지 알려 줍니다.

!!! warning
    2026 이전 세션에는 `InputRequiredResult`를 넣을 곳이 없습니다. `mode="legacy"` 연결에서
    핸들러가 이를 반환하면 러너는 협상된 버전으로 직렬화할 수 없고, 클라이언트는 `-32603`
    *"Handler returned an invalid result"* 오류를 돌려받습니다. 두 세대를 모두 지원하는 서버는
    이를 쓰기 전에 `ctx.protocol_version`을 확인해야 합니다.

!!! info
    **URL 모드 엘리시테이션**은 2026 연결에서 바로 이 메커니즘을 탑니다. `input_requests`의
    항목은 params가 `ElicitRequestURLParams`인 `ElicitRequest`입니다. 사용자가 대역 외 흐름을
    마치면 클라이언트가 호출을 재시도합니다. 같은 루프이고 새 API는 없습니다. 고수준 서버 쪽
    절반은 **[엘리시테이션](elicitation.md)**에 있습니다.

## 요약 {#recap}

* 2026-07-28에서 호출 도중 입력이 필요한 서버는 `InputRequiredResult`를 **반환**합니다. 클라이언트에게 요청을 여는 일은 없습니다.
* `input_requests`는 필요한 것이고, `request_state`는 서버만 읽는 불투명한 재개 토큰입니다.
* `Client`가 재시도 루프를 대신 돌립니다. `elicitation_callback` / `sampling_callback` / `list_roots_callback`을 등록하면 `call_tool`은 평범한 `CallToolResult`를 반환합니다. `input_required_max_rounds`(기본 10)가 한도입니다.
* 라운드를 검사하거나 영속화하려면 `client.session.call_tool(..., allow_input_required=True)`를 쓰고 `while isinstance(result, InputRequiredResult)` 루프를 직접 맡으세요.
* `@mcp.tool()`에서는 사용자에게 묻는 의존성이 이 결과를 대신 만들어 줍니다(**[의존성](dependencies.md)**). 수동 형태는 **저수준** `Server`입니다.
* 프롬프트와 리소스도 참여합니다. `@mcp.prompt()` 또는 템플릿 `@mcp.resource()` 함수가 직접 `InputRequiredResult`를 반환하고 재시도에서 `ctx.input_responses`를 읽습니다.
* `requestState`는 클라이언트가 제공한 입력으로 돌아오므로 `MCPServer`는 리졸버 상태든 직접 만든 상태든 기본적으로 프로세스 로컬 키로 봉인합니다. 다중 인스턴스 배포에서는 `RequestStateSecurity(keys=[...])`나 커스텀 코덱을 전달하여 모든 인스턴스가 형제 인스턴스가 발급한 것을 검증할 수 있게 합니다. 봉인은 모든 토큰을 시간 창과 원래 요청에 묶으며, 요청이 SDK가 검증한 인증을 지니거나 `bind_principal=`이 자체 ID 신호를 제공하는 경우에는 인증된 주체에도 묶습니다(**[`requestState` 보호](#protecting-requeststate)**).

이것이 서버 주도 샘플링과 그 밖의 푸시 방식 백채널을 대체하는 메커니즘입니다. **[지원 중단 예정 기능](../deprecated.md)**을 참고하세요.
