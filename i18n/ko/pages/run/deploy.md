---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# 배포와 확장 {#deploy-scale}

서버는 잘 동작합니다. 이제 실제 호스트명이 필요하고, 그 뒤에 워커도 둘 이상 두어야 합니다.

그중 MCP가 관여하는 부분은 거의 없습니다. ASGI 서버, 프로세스 매니저, 로드 밸런서는 직접 준비합니다. 이 페이지가 다루는 것은 MCP가 **실제로** 관여하는 몇 가지뿐입니다. 모든 배포의 관문이 되는 설정 하나, 그리고 "워커가 둘 이상"일 때 SDK의 동작이 달라지는 두 곳입니다.

## 가장 먼저: Host 허용 목록 {#before-anything-else-the-host-allowlist}

`streamable_http_app()`은 어떤 호스트명 뒤에서 서비스될지 알 수 없으므로 가장 안전한 답인 localhost를 가정합니다. `transport_security=` 인자를 지정하지 않으면 앱은 **DNS 리바인딩 보호**를 켜고, `Host` 헤더가 `127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>` 중 하나일 때만 요청을 받습니다. `Origin` 헤더가 있다면 같은 값의 `http://` 형태여야 합니다. 개발 머신에서는 이것이 정확히 맞는 동작입니다. 악성 웹 페이지가 `127.0.0.1`로 리바인딩한 DNS 이름을 통해 로컬 서버를 조종하지 못하게 막아 줍니다.

실제 호스트명 뒤에 배포하면 바로 그 기본값이 별도로 지정하기 전까지 **모든 요청**을 거부합니다. 이 검사는 MCP와 관련된 어떤 처리보다 먼저 실행되므로, 작성한 코드는 참조조차 되지 않습니다.

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

해결책은 `transport_security=`입니다. 실제로 서비스하는 것을 허용 목록에 넣으세요.

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* `allowed_hosts` 항목은 정확히 일치하는 문자열입니다. `"mcp.example.com"`은 포트 없는 `Host` 헤더와 일치하고, `"mcp.example.com:*"` 형태는 모든 포트와 일치합니다. 둘 다 나열하세요.
* `allowed_origins`는 브라우저에만 의미가 있습니다. 다른 것은 `Origin`을 보내지 않기 때문입니다. 이는 **[기존 앱에 추가하기](asgi.md)**에서 다루는 CORS 설정과 짝을 이루는 서버 측 설정입니다.
* `Host` 헤더를 이미 통제하는 리버스 프록시 뒤에서는 `TransportSecuritySettings(enable_dns_rebinding_protection=False)`로 검사를 끄는 것이 정직한 설정입니다.
* localhost가 아닌 `host=` 값(예: `host="mcp.example.com"`)을 전달해도 그 호스트명이 허용 목록에 들어가지 **않습니다**. localhost 기본값이 보호를 활성화하지 않게 할 뿐이며, 그러면 모든 Host와 Origin이 허용됩니다. 대신 `transport_security=` 인자로 의도를 명확히 지정하세요.

!!! check
    `transport_security=security` 인자를 지우고 앱을 그대로 배포해 보세요. 앱은 시작되고 `/mcp`도
    라우팅되지만, 모든 요청(평범한 `curl`도 포함)이 다음과 같이 돌아옵니다.

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    클라이언트 쪽에서는 이 문구를 볼 수 없습니다. `421`은 JSON-RPC 오류가 아니라 평문 HTTP 응답이므로
    MCP 클라이언트는 일반적인 트랜스포트 오류를 발생시키고, 거부된 호스트명은 **서버** 로그에
    경고 한 줄로만 나타납니다. 새로 배포한 서버가 모든 연결을 거부한다면, 달리 밝혀지기 전까지는
    Host 허용 목록 문제입니다. **[문제 해결](../troubleshooting.md)**도 여기서 시작합니다.

## 워커, 그리고 스티키가 필요한 쪽 {#workers-and-who-has-to-be-sticky}

호스트명이 응답하기 시작했다면 그 뒤에 워커를 둘 이상 두세요. 이를 위한 SDK 설정은 없습니다. Starlette 앱은 다른 ASGI 앱과 똑같이, 포크할 줄 아는 도구에 객체를 넘겨서 확장합니다.

```console
uvicorn server:app --workers 4
```

프로세스 네 개, 소켓 하나. 이제 모든 배포가 답해야 하는 질문은 **요청이 직전 요청을 받았던 바로 그 워커에 도달해야 하는가**입니다.

**2026-07-28** 프로토콜을 사용하는 클라이언트라면 그럴 필요가 없습니다. 최신 방식의 요청은 독립된 POST 하나입니다. 그 앞에 `initialize` 핸드셰이크도 없고, 응답에 `Mcp-Session-Id`도 없으며, 두 번째 요청이 되돌아갈 **대상** 자체가 없습니다. 어느 워커로 보내도 됩니다.

이것은 켜는 모드가 아닙니다. `stateless_http=True`가 그런 스위치처럼 보이지만, 트랜스포트는 `MCP-Protocol-Version` 요청 헤더로 라우팅하여 최신 요청을 최신 핸들러에 넘기고 **반환합니다**. `stateless_http`를 읽는 줄은 그 반환 **뒤에** 있습니다. 2026-07-28 경로에서 이 플래그가 무시되는 것이 아니라 아예 도달하지 않는 것입니다. `stateless_http`는 **레거시** 경로 전용 설정이며, 최신 경로는 구조상 세션이 없습니다.

사양 버전 2025-11-25 이하의 레거시 클라이언트라면 답은 그 플래그에 따라 달라집니다.

| 클라이언트의 프로토콜 버전 | 세션 | 로드 밸런서가 해야 할 일 |
| --- | --- | --- |
| **2026-07-28** | 없음. `Mcp-Session-Id`는 설정되지 않습니다. | 없음. 어느 워커든 어느 요청이든 처리합니다. |
| **2025-11-25 이하**(기본값) | `Mcp-Session-Id`, 한 워커의 메모리에 보관됩니다. | **스티키 세션.** 후속 요청이 다른 워커에 도달하면 `404` *"Session not found"*를 받습니다. |
| **2025-11-25 이하**, `stateless_http=True` 사용 | 없음. | 없음. 대가는 서버에서 클라이언트로 가는 역방향 채널, 즉 샘플링, 푸시 엘리시테이션(elicitation), `roots/list`와 재개 기능을 잃는 것입니다. |

스티키 세션과 레거시 경로의 비용은 별도 페이지인 **[레거시 클라이언트 지원](legacy-clients.md)**에서 다루고, 두 시대 자체는 **[프로토콜 버전](../protocol-versions.md)**에서 다룹니다. 여기서 중요한 것은 답의 형태입니다. **2026-07-28에서는 이미 무상태이며 설정할 것이 없습니다.**

이 페이지의 나머지는 무상태라고 해서 저절로 해결되지 **않는** 두 가지입니다.

## 워커 간 `requestState` {#requeststate-across-workers}

**[다중 왕복](../handlers/multi-round-trip.md)** 도구는 클라이언트가 가져와야 하는 것(확인, 선택, 자격 증명)이 필요하므로, 답 대신 질문을 반환하고 재시도에서 마무리합니다. 두 라운드 사이에 클라이언트는 서버가 발급한 불투명한 `request_state` 토큰을 들고 있습니다. 재시도 때 서버는 그 토큰을 다시 열어야 합니다.

**문제는 어떤 키로 봉인하느냐입니다.** 기본적으로는 서버가 생성 시점에 `os.urandom(32)`로 만든 키입니다. `--workers 4`에서는 네 프로세스에서 생성이 네 번 일어납니다. 서로 다른 키 네 개가 어디에도 기록되지 않고, 공유되지 않으며, 재시작하면 사라집니다.

다음은 아무것도 설정하지 않은 서버에서, 실행하기 전에 먼저 묻는 도구입니다.

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

첫 라운드는 워커 A에 도달합니다. 워커 A는 **자신의** 키로 `refund:120` 값을 봉인하고 토큰을 반환합니다. 클라이언트는 질문을 사람에게 보여 주고 승낙을 받은 뒤 재시도합니다. 재시도는 완전히 새로운 HTTP 요청입니다.

!!! check
    그 재시도가 워커 B에 도달하게 해 보세요. B는 자신이 발급하지 않은 토큰의 봉인을 풀려고 하지만
    풀 수 없어 라운드 전체를 거부합니다. `refund`는 호출되지 않고, 클라이언트는 JSON-RPC 오류를
    받습니다.

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    이 메시지는 **고정**되어 있습니다. 만료됐든, 변조됐든, 다른 인자로 재전송됐든, (실제 배포에서
    단연 가장 흔한 원인인) 형제 워커가 봉인했든, 클라이언트는 매번 같은 메시지를 받으므로 어떤
    검사가 실패했는지 와이어에서는 드러나지 않습니다. 진짜 이유는 서버 로그의 `WARNING` 한 줄에
    있습니다.

    ```text
    requestState rejected on tools/call: unknown key
    ```

    워커 하나일 때는 잘 되다가 둘이 되자 **가끔씩** 실패하기 시작한 다중 왕복 도구가 바로 이
    경우입니다. 두 라운드가 여전히 같은 프로세스에 도달해야 하므로, 로드 밸런서가 둘을 갈라놓는
    빈도만큼 정확히 실패합니다.

두 라운드는 독립된 HTTP 요청 두 개이며, 평범한 일 몇 가지가 둘을 갈라놓습니다. 요청 단위로 분산하는 프록시, 중간에 끊어진 연결, 배포나 재시작, `request_state`를 저장해 두었다가 전혀 다른 프로세스에서 재개하는 클라이언트(**[루프를 직접 구동하기](../handlers/multi-round-trip.md#driving-the-loop-yourself)**) 등입니다. 이 중 어느 것이든 "다른 워커"가 됩니다.

해결책은 인자 하나입니다. 이 인자에는 **두** 부분이 있습니다.

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`**는 누구나 찾아내는 부분입니다. 모든 인스턴스에 같은 비밀 값(최소 32바이트)을 주면, 어느 형제가 발급한 것이든 모든 인스턴스가 봉인을 풀 수 있습니다. `keys[0]` 항목이 봉인하고 목록의 모든 키가 봉인을 푸는데, 이것이 로테이션 링입니다. 다운타임 없이 이를 돌리는 방법은 **[키 로테이션](../handlers/multi-round-trip.md#rotating-keys)**에서 확인하세요.
* **서버의 이름**은 거의 아무도 찾지 못하는 부분이자, 키를 공유한 뒤에도 인스턴스 간 재시도가 계속 실패하는 이유입니다. 봉인된 모든 토큰은 서버의 `name`을 **audience 클레임**으로 담고 있으며, 돌아올 때 엄격하게 검사됩니다. 같은 코드로 만든 두 인스턴스는 이름이 같으므로 이를 알아챌 일이 없습니다. 이름을 서로 다르게 지으면(`MCPServer(f"billing-{POD}")`는 관측 가능성 측면에서 좋은 습관처럼 보입니다), 키를 공유했든 아니든 모든 인스턴스 간 재시도가 위와 똑같이 거부됩니다. 로그에는 `unknown key` 대신 `audience`가 찍히지만, 클라이언트는 그 차이를 알 수 없습니다.

비밀 값은 한 번만 만들어 모든 인스턴스에 같은 값을 넘기세요. 32바이트 미만을 전달하면 SDK의 오류 메시지가 직접 실행하라고 알려 주는 명령이 바로 이것입니다.

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "같은 키, **그리고** 같은 이름"
    다중 인스턴스 배포는 둘 다 공유해야 합니다. 인스턴스별 이름이 꼭 필요하다면 대신
    `RequestStateSecurity(keys=[...], audience="billing")`처럼 전체 인스턴스에 명시적인 audience 하나를
    지정하세요. 그러면 이름이 무엇이든 모든 인스턴스가 `"billing"`으로 발급하고 수락합니다.

봉인에 관한 나머지 모든 것, 즉 무엇을 묶는지, 라운드별 `ttl`(기본 600초), 자체 코덱 사용하기, 설정하지 않은 기본값이 `stdio`에서는 정확히 맞는 이유는 **[`requestState` 보호하기](../handlers/multi-round-trip.md#protecting-requeststate)**에서 다룹니다. 이 페이지가 보태는 것은 두 항목짜리 체크리스트뿐입니다. **같은 키, 같은 이름.**

!!! info
    `InputRequiredResult`를 한 번도 입력해 본 적이 없어도 이 경로에 해당합니다. 매개변수에
    `Resolve(...)`를 쓰는 도구(**[의존성](../handlers/dependencies.md)**)는 다중 왕복 도구이며,
    SDK가 대신 `request_state`를 발급하고 봉인합니다. 기본 키도 같고, 워커 간 실패도 같고,
    해결책도 같습니다.

## 레플리카 간 변경 알림 {#change-notifications-across-replicas}

클라이언트의 `subscriptions/listen` 스트림은 오래 유지되는 응답 하나이므로 살아 있는 동안 내내 레플리카 하나에 고정됩니다. **다른** 레플리카에서 발행한 `ctx.notify_resource_updated(...)`가 그 스트림에 도달해야 합니다.

둘 사이의 접점은 `SubscriptionBus`입니다. 서버에 어떤 버스를 주든 모든 발행이 그 버스로 들어가고 열려 있는 모든 스트림이 그 버스를 듣습니다. 따라서 모든 레플리카에 같은 버스를 넘기세요.

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

팬아웃은 스트림이 어느 서버 객체에 붙어 있는지 전혀 신경 쓰지 않습니다. `InMemorySubscriptionBus` 하나를 공유하는 서버 두 개는 이미 이렇게 동작합니다. 한쪽에서 listen 스트림을 열고 다른 쪽에서 `edit_note`를 호출하면 스트림이 그 소식을 듣습니다. 이 인메모리 버스는 한 프로세스 안의 서버 객체에만 걸쳐 있으므로, 배포 방식이 아니라 모델일 뿐입니다.

* 실제 프로세스 간에는 **SDK가 제공하는 버스 중 도움이 되는 것이 없습니다.** `SubscriptionBus`는 메서드 두 개(`publish`와 `subscribe`)짜리 `Protocol`이며, 자체 pub/sub 백엔드(Redis, NATS, 이미 운영 중인 무엇이든) 위에 구현해서 `MCPServer(subscriptions=...)`로 전달합니다. 스케치와 계약은 **[구독](../handlers/subscriptions.md#scaling-past-one-process)**에서 확인하세요.
* 버스는 작은 타입 이벤트 네 가지만 나르며, JSON-RPC는 절대 나르지 않습니다. 확인 응답, 필터링, 스트림 생명 주기는 SDK에 남아 있으므로, 버스가 프로토콜을 깨뜨릴 수는 없고 프로세스 간에 이벤트를 옮길 수만 있습니다.
* 스트림은 재개할 수 **없고** 이벤트는 재생되지 **않습니다**. 레플리카를 잃으면 그 스트림도 끊기고, 클라이언트는 다시 listen하고 다시 가져옵니다. 공유할 이벤트 저장소도, 따로 설정할 것도 없습니다. 확장이 정말로 같은 것을 더 늘리는 일에 불과한 곳은 여기 하나뿐입니다.

## SDK가 제공하지 않는 것 {#what-the-sdk-does-not-give-you}

`MCPServer`는 애플리케이션 서버가 아니라 프로토콜 구현체입니다. 다음으로 찾게 될 배포 설정은 의도적으로 빠져 있습니다.

* **`workers=` 없음.** `mcp.run("streamable-http")` 호출은 uvicorn 프로세스를 정확히 하나 시작하며, 앞으로도 그 이상은 시작하지 않습니다. 다중 프로세스는 `streamable_http_app()`을 이미 ASGI 배포에 쓰고 있는 도구, 즉 `uvicorn --workers`, gunicorn, 플랫폼의 프로세스 매니저에 넘기는 것입니다. 이 페이지는 일부러 그중 어느 것의 튜토리얼도 되지 않습니다. 여기에 옮겨 적는 것보다 각 도구의 문서가 더 낫기 때문입니다.
* **헬스 체크 라우트 없음.** `@mcp.custom_route("/health", methods=["GET"])`가 답의 전부이며, 서버의 나머지가 인증을 요구하더라도 이 라우트는 인증되지 않습니다. 활성 프로브에는 맞지만 비공개여야 하는 것에는 맞지 않습니다. 예시는 **[기존 앱에 추가하기](asgi.md#custom-routes)**에서 확인하세요.
* **프로덕션 설정 객체 없음.** `MCPServer`에는 타임아웃, TLS, 정상 종료, 연결 제한을 적어 둘 곳이 없습니다. 그중 어느 것도 이 클래스의 일이 아니기 때문입니다. 이들은 ASGI 서버의 몫이며 거기서 설정합니다. 생성자가 **실제로** 받는 몇 안 되는 설정은 **[서버 실행하기](index.md)**에서 다룹니다.
* **제공되는 `EventStore` 없음, 그리고 2026-07-28에서는 쓸 일도 없음.** 재개 기능은 레거시 상태 유지 경로의 기능입니다. 최신 방식의 교환은 POST 하나, 응답 하나이며 재개할 것이 없습니다.

## 요약 {#recap}

* 기본적으로 이 앱은 localhost로 오는 요청만 받습니다. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`가 서비스 개시의 관문입니다. 이를 전달하기 전까지 실제 호스트명 뒤의 모든 요청은 `421`이 되며, 그 이유는 서버 로그에만 남습니다.
* 2026-07-28에는 세션이 없고, 로드 밸런서가 스티키로 붙들 대상도 없습니다. `stateless_http=True`는 레거시 전용 설정입니다. 최신 요청은 이 플래그를 읽기도 전에 라우팅되고 응답되기 때문입니다.
* 기본 `requestState` 키는 프로세스마다 만들어지는 `os.urandom(32)`입니다. 다른 워커에 도달한 다중 왕복 재시도는 `-32602` *"Invalid or expired requestState"*로 실패합니다.
* 해결책은 `RequestStateSecurity(keys=[...])`를 쓰는 것, **그리고** 모든 인스턴스에 같은 서버 이름을 쓰는 것입니다. 이름은 토큰의 기본 audience 클레임입니다. 같은 키, 같은 이름.
* 변경 알림은 공유 `SubscriptionBus` 하나를 통해 레플리카를 넘나듭니다. SDK의 유일한 구현은 프로세스 내부용이며, 자체 pub/sub 위의 메서드 두 개짜리 `Protocol`은 직접 작성해야 합니다.
* `workers=`도, 헬스 라우트도, 프로덕션 설정 객체도 없습니다. ASGI 서버는 직접 준비하세요.

실제 호스트명 앞에 필요한 또 하나는 토큰입니다. **[인가](authorization.md)**에서 이어집니다.
