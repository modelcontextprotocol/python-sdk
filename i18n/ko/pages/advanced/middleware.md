---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# 미들웨어 {#middleware}

**미들웨어**는 서버가 받는 모든 메시지를 감싸는 하나의 async 함수입니다.

`async (ctx, call_next)` 형태로 작성해서 `server.middleware`에 추가하면 됩니다. 이것이 API의 전부입니다.

!!! warning
    미들웨어 목록은 소스에서 **잠정적**(provisional)으로 표시되어 있습니다. 시그니처와 동작 의미는
    2.x 마이너 릴리스에서 바뀔 수 있습니다. 메시지를 **관찰**(시간 측정, 로깅, 트레이싱)하고
    **거부**하는 데 사용하세요. 서버가 딛고 서는 기반으로 삼지는 마세요.

`MCPServer`는 생성 시 목록을 받아(`MCPServer(name, middleware=[...])`) `mcp.middleware`로 노출하고,
저수준 `Server`는 같은 목록을 `server.middleware`로 노출합니다. 아래 예제는 저수준 `Server`를
사용합니다. `Server(name, on_call_tool=...)`가 처음이라면
**[저수준 Server](low-level-server.md)**를 먼저 읽으세요.

## 시간을 재는 미들웨어 {#a-timing-middleware}

서버 하나, 도구 하나, 그리고 메시지마다 걸린 시간을 로그로 남기는 미들웨어 하나입니다.

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx`는 핸들러가 받는 것과 같은 `ServerRequestContext`입니다. `ctx.method`는 원시 메서드
  문자열이고, `ctx.params`는 어떤 검증도 거치기 **전**의 원시 params입니다.
* `call_next(ctx)`는 체인의 나머지, 즉 검증, 핸들러 조회, 작성한 핸들러를 실행합니다.
  반환된 값을 그대로 반환하면 응답은 손대지 않은 채로 나갑니다.
* `try`/`finally`는 의도적인 선택입니다. 예외를 일으키는 핸들러도 시간이 측정됩니다. 실패는
  `call_next`에서 빠져나오는 예외로 미들웨어에 도달하기 때문입니다.
* `server.middleware.append(...)`로 등록합니다. 목록은 바깥쪽부터 실행되므로
  `middleware[0]`이 와이어에 가장 가까운 미들웨어입니다.

### 직접 해 보기 {#try-it}

클라이언트를 연결하고, 도구 목록을 조회하고, 하나를 호출해 보세요. 로그에는 **세** 줄이 남습니다.

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

호출은 두 번 했는데 줄은 세 개입니다. 첫 번째 줄은 `server/discover`로, 아무것도 요청하기 전에
클라이언트가 연결을 설정하려고 보낸 요청입니다.

바로 이것이 핵심입니다. 미들웨어는 들어오는 **모든** 메시지를 감쌉니다.

* 연결 설정. `server/discover`이거나, 레거시 세션에서는 `initialize`와
  `notifications/initialized`입니다.
* 모든 요청과 모든 알림. 알림의 경우 `ctx.request_id is None`이고,
  `call_next(ctx)`는 `None`을 반환하며, 무엇을 반환하든 버려집니다.
* 서버에 핸들러가 없는 메서드까지도 포함됩니다. `call_next`가
  `MCPError(-32601, "Method not found")`를 일으키고, 이 예외는 클라이언트로 가는 길에
  미들웨어를 **통과합니다**.

## 미들웨어 안에서 할 수 있는 일 {#what-you-can-do-inside-one}

망설임이 적게 필요한 것부터 순서대로 나열합니다.

* **관찰.** 시간을 재고, 횟수를 세고, 로그를 남기세요. 위의 예제가 이에 해당합니다.
* **거부.** `call_next(ctx)`를 호출하는 **대신** `MCPError`를 일으키면 그 메시지 하나에
  JSON-RPC 오류로 응답합니다. 연결은 유지되고 다음 메시지는 그대로 통과합니다. 서버가
  호출자별로 `subscriptions/listen`을 제한하는 방법이 바로 이것입니다. 구독 페이지의
  **[누가 지켜볼 수 있는지 정하기](../handlers/subscriptions.md#deciding-who-may-watch)**에서
  단계별로 설명합니다.
* **재작성.** `ctx`는 데이터클래스입니다. `await call_next(dataclasses.replace(ctx, params=...))`는
  체인의 나머지에 클라이언트가 보낸 것과 다른 params를 넘깁니다. `initialize`에는 절대 이렇게
  하지 마세요. 클라이언트가 돌려받는 결과는 재작성한 params로 만들어지지만, 서버는 원래 와이어
  params를 기준으로 연결 상태를 확정합니다. 양쪽이 무엇을 협상했는지 서로 다르게 이해한 채로
  핸드셰이크를 마칠 수 있습니다.
* **응답.** `call_next(ctx)`를 호출하지 않고 결과를 반환하면 그 결과가 응답으로 클라이언트에
  전달됩니다. `call_next`는 완성된 와이어 형식을 넘겨주고, 파이프라인은 반환한 값을 손보지
  않으므로 봉투 전체가 미들웨어의 몫입니다. 2026년 세대의 연결에서는 `serverInfo` `_meta`
  스탬프가 여기에 포함되는데, SDK는 이를 핸들러 결과에는 추가하지만 미들웨어가 반환한 결과에는
  추가하지 않습니다.

!!! check
    `initialize`도 미들웨어가 감싸는 대상 중 하나이며, 미들웨어는 이에 대해 얻을 수
    있는 **유일한** 훅입니다. `add_request_handler`로 가로채려고 하면 SDK가 거부합니다.

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize`는 인라인으로 처리됩니다. 미들웨어 체인이 반환할 때까지 서버는 들어오는 메시지를
    더 읽지 않습니다. 따라서 `initialize`를 처리하는 동안 서버에서 클라이언트로 가는 요청
    (`ctx.session.send_request(...)`, 엘리시테이션(elicitation))을 await하면 **연결이 교착 상태에
    빠집니다**. 기다리는 응답은 결코 읽힐 수 없기 때문입니다. 보내고 잊는 방식의 알림은 괜찮습니다.

## 기본으로 켜져 있는 단 하나의 미들웨어 {#the-one-middleware-that-ships-on-by-default}

SDK에는 미들웨어가 정확히 하나 포함되어 있으며, 이미 서버의 목록에 들어 있습니다. 모든 메시지마다
OpenTelemetry 스팬을 내보내는 미들웨어입니다. 직접 추가할 필요가 없고, 대부분의 경우 신경 쓸
필요도 없습니다. 익스포터를 설치하기 전까지는 아무 일도 하지 않으며, 별도의 페이지가 있습니다.
**[OpenTelemetry](../run/opentelemetry.md)**를 참고하세요.

!!! info
    ASGI 미들웨어를 작성해 본 적이 있다면 이 형태가 이미 익숙할 것입니다. Starlette의
    `(scope, receive, send)`가 `(ctx, call_next)`가 되었고, 트랜스포트 **이후에**, 원시 HTTP 요청이
    아니라 디코딩된 메시지를 대상으로 실행됩니다. 둘은 함께 조합됩니다. `streamable_http_app()`에
    붙인 Starlette 미들웨어는 HTTP를 보고, 이 미들웨어는 MCP를 봅니다.

## 요약 {#recap}

* 미들웨어는 `async (ctx, call_next) -> result` 형태이며, `MCPServer(middleware=[...])`로
  전달하거나(또는 `mcp.middleware`에 추가하거나) 저수준 `Server`에서는 `server.middleware`에
  추가합니다.
* 들어오는 **모든** 메시지(`server/discover`, `initialize`, 요청, 알림, 알 수 없는 메서드)를
  감싸며 바깥쪽부터 실행됩니다.
* `ctx.request_id is None`으로 알림과 요청을 구분합니다.
* `call_next`를 호출하는 대신 예외를 일으키면 메시지 하나를 거부합니다. 연결은 유지됩니다.
* SDK 자체의 OpenTelemetry 트레이싱도 미들웨어이며, 이미 목록에 있습니다.
  **[OpenTelemetry](../run/opentelemetry.md)**를 참고하세요.
* 이 표면 전체가 잠정적입니다. 관찰하는 데 사용하고, 그 위에 무언가를 쌓지는 마세요.

요청을 감싸는 것은 이것이 전부입니다. 요청이 애초에 실행될 수 있는지를 결정하는 것은
**[인가](../run/authorization.md)**입니다.
