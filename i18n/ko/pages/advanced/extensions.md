---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# 확장 {#extensions}

**확장**은 하나의 식별자 아래에 묶어 두고 원할 때만 켜서 쓰는 MCP 동작의 묶음입니다.

서버에서는 도구, 리소스, 새로운 요청 메서드를 제공할 수 있고 `tools/call`을 감쌀 수 있습니다. 클라이언트에서는 추가적인 `tools/call` 결과 형태를 클레임하고 벤더 알림을 관찰할 수 있습니다. 양쪽 모두 각자의 `capabilities.extensions` 아래에 이를 광고하며, 요청하지 않은 쪽에는 아무것도 달라지지 않습니다. 이것이 계약([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133))이고, 황금률은 단 하나입니다. **확장은 기본적으로 꺼져 있습니다**.

## 확장 사용하기 {#using-an-extension}

생성할 때 인스턴스를 전달하세요.

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

끝입니다. 이제 서버는 `capabilities.extensions` 아래에 `io.modelcontextprotocol/ui`를 광고하고 확장이 제공하는 모든 것을 서비스합니다.

`Apps`는 내장된 참조 확장이며 별도의 페이지에서 다룹니다. **[MCP Apps](apps.md)**를 참고하세요.

!!! note
    확장은 생성 시점에 고정됩니다. 나중에 호출할 `add_extension`은 없습니다. 클라이언트가 연결되어 있는 동안 서버의 기능 맵이 바뀌어서는 안 되기 때문입니다.

기능 맵은 `server/discover`에 실려 전달되는데, 이는 **2026-07-28** 경로입니다. 레거시 `initialize` 핸드셰이크에는 이를 담을 자리가 없으므로 레거시 클라이언트는 확장을 아예 보지 못합니다. 이를 고려해 설계하세요. 확장은 서버를 **보강**하는 것이지, 서버를 사용할 수 있는 유일한 방법이 되어서는 안 됩니다.

## 직접 작성하기 {#writing-your-own}

`Extension`을 서브클래싱하고 필요한 것만 재정의하세요. 모든 메서드에는 기본 구현이 있습니다.

### 식별자 {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

식별자는 사양의 `_meta` 키 문법을 따르는 `vendor-prefix/name` 문자열입니다. 점으로 구분된 레이블(각각 문자로 시작하고 문자 또는 숫자로 끝남), 슬래시, 그리고 이름 순서입니다. **클래스가 정의될 때** 검증되므로 오타가 서버 부팅까지 숨어 있지 않습니다.

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

직접 관리하는 도메인을 접두사로 사용하세요. `io.modelcontextprotocol/*`는 MCP 프로젝트 자체가 규정하는 확장을 위한 것입니다.

### 도구 제공하기 {#contributing-tools}

쓸모 있는 가장 작은 확장은 도구 하나와 설정 맵 하나입니다.

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()`는 `ToolBinding`을 반환합니다. 서버는 각각을 직접 `mcp.add_tool(...)`을 호출한 것과 똑같이 등록합니다. 스키마 생성도, `Context` 주입도, 나머지도 모두 같습니다.
* `settings()`는 `capabilities.extensions["com.example/stamps"]`에 광고되는 값입니다. 설정 없이 확장을 광고하려면 `{}`(기본값)을 반환하세요.
* 확장은 서버를 절대 전달받지 않습니다. 기여할 내용을 데이터로 선언하고, `MCPServer`가 이를 소비합니다. 변경할 `self.server` 같은 것은 없습니다.

그리고 `main()`이 그 증거입니다. `mcp`에 바로 연결하는 인메모리 클라이언트입니다.

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### 자체 메서드 제공하기 {#serving-your-own-methods}

확장은 **새로운 요청 메서드**를 등록할 수 있습니다. 사양의 동사 옆에서 함께 서비스되는 자체 동사입니다.

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams`는 `RequestParams`를 서브클래싱하므로 2026 `_meta` 봉투가 일관되게 파싱되고, 핸들러는 원시 dict가 아니라 검증된 params를 받습니다. 클라이언트가 제어하는 값에는 한계를 두세요. `Field(ge=1, le=100)`은 코드가 무언가를 할당하기 전에 터무니없는 `limit`을 거부합니다.
* `require_client_extension(ctx, EXTENSION_ID)`가 관문입니다. 확장을 선언하지 않은 클라이언트는 사양이 요구하는 기계 판독 가능한 `requiredCapabilities` 페이로드와 함께 `-32021`(필수 클라이언트 기능 누락) 오류를 받습니다.
* `protocol_versions=frozenset({"2026-07-28"})`은 메서드를 하나의 와이어 버전에 고정합니다. 다른 버전에서는 클라이언트가 `METHOD_NOT_FOUND`를 받는데, 그 버전에 메서드가 존재하지 않는 것과 똑같습니다. 그 클라이언트에게는 실제로 존재하지 않는 셈입니다.

메서드는 **엄격하게 추가만 가능**합니다. SDK는 이를 런타임이 아니라 생성 시점에 강제합니다.

* 사양에 정의된 메서드(`tools/list`, `completion/complete`, ...)에 대한 `MethodBinding`은 바인딩이 생성될 때 `ValueError`를 일으킵니다. 핵심 동사는 서버의 것입니다.
* 두 확장이 같은 메서드를 바인딩하면 두 번째가 등록될 때 오류가 납니다. 마지막 쓰기가 이기는 방식은 플러그인이 서로를 망가뜨리는 원인이므로 그렇게 하지 않습니다.
* 빈 `protocol_versions` 집합도 오류를 일으킵니다. 절대 서비스될 수 없는 메서드는 설정이 아니라 버그입니다.

### 클라이언트 측 {#the-client-side}

같은 파일의 `main()`이 클라이언트 쪽 이야기의 전부이며, 두 부분을 모두 담고 있습니다.

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])`가 확장을 선언합니다. 선언은 `ClientCapabilities.extensions`가 됩니다. 2026-07-28 연결에서는 이 맵이 요청별 `_meta` 봉투에 실려 이동하므로 서버는 **모든** 요청에서 이를 봅니다. 레거시 연결에서는 `initialize` 핸드셰이크에 실립니다. 서버 코드는 어느 쪽인지 신경 쓰지 않습니다. `require_client_extension(ctx, ...)`와 `ctx.session.check_client_capability(...)`는 두 경로 모두에서 올바른 출처를 읽습니다.
* 벤더 메서드는 한 계층 아래인 `client.session.send_request(...)`로 내려갑니다. `Client`는 사양 동사에 대해서만 일급 메서드를 갖춥니다. `send_request`는 모든 `Request` 서브클래스를 받으므로 벤더 요청은 그대로 통과합니다.

### `tools/call` 가로채기 {#intercepting-toolscall}

유일하게 개입하는 훅입니다. 도구 호출을 관찰하거나, 단락시키거나, 거부하려면 `intercept_tool_call`을 재정의하세요.

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params`는 검증된 `CallToolRequestParams`입니다. 원시 JSON을 건드리지 않고 `params.name`과 `params.arguments`를 얻습니다. 어느 도구 호출이 실행될지 결정하는 것도 바로 이것입니다. 다시 작성한 컨텍스트를 `call_next`에 넘기면 핸들러가 `ctx`에서 관찰하는 내용이 바뀔 뿐 도구 호출 자체는 바뀌지 않습니다. 와이어 수준의 요청 재작성은 [미들웨어](middleware.md)의 몫입니다.
* `call_next(ctx)`는 체인의 나머지를 실행하고 핸들러의 결과를 반환합니다. 그대로 반환하거나(관찰), 다른 것을 반환하거나(대체), `MCPError`를 일으키세요(거부). 무엇을 반환하든 2026 계열의 `serverInfo` 신원 스탬프를 포함해 다른 핸들러 결과와 똑같이 직렬화되므로, 단락시키는 인터셉터가 익명이거나 스키마에 어긋나는 응답을 만들어 내는 일은 없습니다.
* 확장이 여럿이면 인터셉터는 등록 순서대로 중첩됩니다. `extensions=[...]`의 첫 번째 확장이 가장 바깥쪽입니다.
* 기본 구현은 그대로 통과시키며, 확장이 이 훅을 재정의하지 않는 서버는 원래의 `tools/call` 핸들러를 그대로 유지합니다. 쓰지 않는 것에는 비용을 치르지 않습니다.

이 훅은 `tools/call`만 감싸고 다른 것은 감싸지 않습니다. 모든 메시지에 걸친 관심사에는 [미들웨어](middleware.md)를 사용하세요. 미들웨어는 바로 그런 용도입니다.

## 클라이언트 확장 사용하기 {#using-a-client-extension}

**클라이언트 확장**은 소비하는 쪽에서 본 같은 계약으로, 하나의 식별자 아래 묶인 클라이언트 측 동작의 묶음입니다. `Client(extensions=[...])`에 인스턴스를 전달하고 평소처럼 도구를 호출하세요.

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)`은 다른 모든 호출처럼 평범한 `CallToolResult`를 반환합니다. 확장이 바꾼 것은 이렇습니다. 이제 서버는 `buy`에 최종 결과 대신 `receipt` **결과 형태**로 응답할 수 있고, `call_tool`이 반환하기 전에 `Receipts`가 이를 마무리합니다(여기서는 후속 호출로 영수증을 정산합니다). 호출 지점에서는 아무것도 달라지지 않습니다.

확장을 빼면 이 중 어떤 것도 존재하지 않습니다. 서버의 관문은 확장을 선언하지 않은 클라이언트를 거부하고(오류 -32021), 관문을 건너뛰는 서버가 보낸 클레임된 형태는 인식되지 않은 `resultType`에 대해 사양이 요구하는 그대로 검증에 실패합니다. 와이어 양 끝 모두에서 기본적으로 꺼져 있습니다.

클라이언트 측 동작이 **전혀 없는** 식별자를 광고하려면(위의 검색 클라이언트처럼 서버는 기능을 기준으로 관문을 두고 클라이언트는 아무것도 하지 않는 경우) `advertise()`를 사용하세요.

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## 클라이언트 확장 작성하기 {#writing-a-client-extension}

`ClientExtension`을 서브클래싱하고 필요한 것만 재정의하세요. 기여 종류는 세 가지이며 각각 기본 구현이 있습니다. `settings()`, `claims()`, `notifications()`입니다.

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* 식별자는 서버의 것과 같은 문법을 따르며 클래스가 정의될 때 검증됩니다.
* `claims()`는 `ResultClaim`을 반환합니다. 와이어 태그, 이를 파싱하는 모델, 마무리하는 리졸버로 구성됩니다. 모델은 `result_type: Literal["receipt"]`으로 태그를 고정해야 하며 해당 동사의 핵심 결과 타입을 서브클래싱해서는 안 됩니다. 둘 다 클레임이 생성될 때 강제됩니다. `receipt_token` 같은 벤더 필드는 와이어에 그대로 실립니다. 대체된 형태는 클라이언트에 원문 그대로 도달합니다.
* 리졸버는 파싱된 모델과 `ClaimContext`를 받습니다. `ctx.session`은 `client.session`과 같은 공개 핸들이므로 후속 작업은 평범한 세션 호출입니다. 리졸버는 해당 동사의 일반적인 `CallToolResult`를 반환합니다.
* `settings()`는 `ClientCapabilities.extensions[identifier]`에 광고되는 값이며 `Client` 생성 시 한 번 읽힙니다.

`notifications()`는 관찰할 벤더 서버 알림을 선언합니다.

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

핸들러는 검증된 params를 디스패치 순서대로 하나씩 받습니다. 관찰만 할 뿐, 거부하거나 응답할 수는 없습니다.

조용한 규칙이 두 가지 있습니다. 클레임은 2026-07-28 연결에서만 활성화되며 기능 광고도 이를 따릅니다. 레거시 연결에서는 클레임이 사라지고 식별자도 함께 광고에서 빠지므로, 클라이언트가 스스로 거부할 형태의 확장을 광고하는 일은 없습니다. 그리고 리졸버 대신 클레임된 형태를 직접 받고 싶다면 `client.session.call_tool(..., allow_claimed=True)`를 호출하세요. 이 플래그가 없으면 세션 계층 호출자에게 도달한 클레임된 형태는 `UnexpectedClaimedResult`를 일으킵니다.

### 확장 동사 {#extension-verbs}

확장의 자체 요청 메서드에는 클라이언트 측 등록이 필요 없습니다. 벤더 요청 타입은 `mcp.types.Request`를 서브클래싱하고, [자체 메서드 제공하기](#serving-your-own-methods)에서처럼 `client.session.send_request`를 거칩니다. 한 가지가 더 있습니다. params 키가 `Mcp-Name` 헤더에 실려야 할 때(tasks 같은 확장 사양은 자신의 동사에 이를 요구합니다) 요청 타입이 `name_param`을 선언합니다.

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

세션은 모든 전송 경로에서 `params["jobId"]`를 `Mcp-Name`에 반영하며, 값이 없으면 필수 헤더를 조용히 빠뜨리는 대신 명시적으로 실패합니다.

## 확장이 할 수 없는 것 {#what-an-extension-cannot-do}

기여 범위는 의도적으로 **닫혀** 있습니다. 서버에서는 설정, 도구, 리소스, 메서드, `tools/call` 인터셉터 하나입니다. 클라이언트에서는 설정, 결과 클레임, 알림 바인딩입니다. 확장은 다음을 할 수 없습니다.

* **호스트 내부에 손대기.** 데이터를 선언할 뿐, 서버나 클라이언트 참조를 쥐지 않습니다.
* **핵심 동작 바꾸기.** 사양 메서드와 핵심 결과 태그는 생성 시점에 거부되며(`initialize`는 러너가 아예 예약해 둡니다), 핵심 어휘에 가려지는 알림 바인딩은 대신 경고와 함께 조용해집니다.
* **늦게 등록하기.** `MCPServer(...)`나 `Client(...)`가 반환된 뒤에는 확장 집합이 그대로 확정됩니다.

이 벽과 씨름하고 있다면 확장을 작성하는 것이 아니라 포크를 작성하는 것입니다. 벽이 곧 기능입니다. `extensions=[Apps(), Stamps()]`라는 코드를 읽는 사용자는 그 둘이 건드렸을 수 있는 **모든 것**을 압니다.
