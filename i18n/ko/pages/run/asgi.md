---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# 기존 앱에 추가하기 {#add-to-an-existing-app}

`mcp.run("streamable-http")`는 웹 서버를 대신 띄워 줍니다. 하지만 그걸 원하지 않을 때도 있습니다. MCP 서버가 더 큰 웹 애플리케이션의 한 부분이거나, 이미 ASGI 배포 환경이 있는 경우입니다.

이럴 때 `mcp.streamable_http_app()`은 **Starlette 애플리케이션**을 반환합니다.

Starlette 앱은 ASGI 앱이므로, ASGI를 호스팅할 수 있는 것이라면 무엇이든(uvicorn, Hypercorn, 또 다른 Starlette, FastAPI) MCP 서버를 호스팅할 수 있습니다.

## 앱 {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app`은 평범한 ASGI 애플리케이션입니다. 아무 ASGI 서버에나 넘기면 됩니다.

```console
uvicorn server:app
```

MCP 엔드포인트는 `/mcp`에 있으므로, 클라이언트는 `http://127.0.0.1:8000/mcp`에 연결합니다.

이 앱은 이미 두 가지를 갖추고 있습니다.

* 라우트 하나, `/mcp`: Streamable HTTP 엔드포인트입니다.
* `mcp.session_manager`를 시작하는 **lifespan**: 살아 있는 모든 세션의 백그라운드 작업을 소유하는 객체입니다.

앱을 단독으로 실행하면(`uvicorn server:app`) 둘 다 신경 쓸 일이 없습니다.

!!! tip
    `streamable_http_app()`은 `mcp.run("streamable-http", ...)`과 같은 키워드 인자를 받되,
    `port`만 빠집니다. 포트는 앱을 서빙하는 쪽의 몫이기 때문입니다. `host`는 여전히 받지만
    여기서는 아무것도 바인딩하지 않습니다. 이 값이 실제로 무엇을 제어하는지는 **[배포와 확장](deploy.md)**에서 설명합니다.
    옵션 자체는 **[서버 실행하기](index.md)**에서 다룹니다.

`mcp.sse_app()`은 이제 대체된 SSE 트랜스포트에 대해 같은 일을 합니다.

## 별도로 지정하기 전까지는 localhost 전용 {#localhost-only-until-you-say-otherwise}

기본적으로 이 앱은 localhost로 오는 요청**만** 받습니다. `streamable_http_app()`은
자신이 어떤 호스트 이름 뒤에서 서빙될지 알 수 없으므로, 가능한 한 가장 안전한 허용 목록으로 DNS 리바인딩 보호를
켭니다. 개발 머신에서는 이 설정이 정확히 맞습니다. 실제 호스트 이름 뒤에 배포하면,
실제로 서빙하는 대상의 허용 목록을 `transport_security=`로 넘기기 전까지 **모든 요청이 `421 Misdirected Request`로 거부됩니다**.
작성한 코드는 아예 참조되지도 않습니다. 이 허용 목록을 비롯해, 동작하는 앱과 실제 호스트 이름 사이에 있는 모든 것은
**[배포와 확장](deploy.md)**에서 다룹니다.

## 마운트하기 {#mounting-it}

MCP 서버가 더 큰 애플리케이션의 **일부**가 되는 순간, 앱을 `Mount` 안에 넣게 됩니다. 그리고 그렇게 하는 순간 lifespan은 직접 챙겨야 할 일이 됩니다.

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)`에 기본 경로 `/mcp`가 더해져 엔드포인트는 `/mcp`에 그대로 유지됩니다. Starlette는 라우트를 순서대로 시도하고 `Mount("/")`는 **모든** 경로와 매칭되므로, 직접 만든 라우트는 목록에서 그 **앞에** 두어야 합니다. 뒤에 오는 것은 무엇이든 도달할 수 없습니다.
* `lifespan` 함수는 **호스트** 앱이 살아 있는 동안 `mcp.session_manager.run()`에 진입합니다. 다들 잊어버리는 줄이 바로 이것입니다.
* `mcp.session_manager`는 `streamable_http_app()`이 호출된 **뒤에야** 존재합니다. 그래서 라우트는 모듈 수준에서 만들고, 매니저는 lifespan 안에서만 건드립니다.

Starlette의 `Host` 라우트도 같은 방식으로 동작합니다. 경로 대신 호스트 이름으로 라우팅하려면 `Mount("/", ...)`를 `Host("mcp.example.com", ...)`로 바꾸세요. lifespan 규칙은 달라지지 않으며, 트랜스포트 보안 규칙도 마찬가지입니다. `Host("mcp.example.com", ...)` 라우트는 해당 호스트 이름으로 오는 요청만 받지만, 트랜스포트 자체의 Host 허용 목록(**[배포와 확장](deploy.md)**)이 여전히 먼저 실행됩니다. 그 목록에 `"mcp.example.com"`이 없으면, 이 라우트는 모든 요청에 `421`로 응답합니다.

!!! warning "lifespan은 호스트 앱의 소유입니다"
    `streamable_http_app()`은 반환하는 Starlette의 lifespan에 `session_manager.run()`을 연결해 두지만,
    **마운트된 하위 애플리케이션의 lifespan은 절대 실행되지 않습니다**. 앱을 마운트하면
    내장된 lifespan은 죽은 코드가 됩니다. ASGI 스택의 맨 위에 있는 앱이 무엇이든, 그 앱이 자신의 lifespan에서
    `mcp.session_manager.run()`에 진입해야 합니다.

!!! check
    `lifespan=lifespan` 줄을 지우고 서버를 시작해 보세요. 시작됩니다. 라우트도 해석됩니다.
    그런데 `/mcp`로 가는 첫 요청이 다음과 같이 실패합니다.

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    세션 매니저를 시작하는 것은 `run()`뿐입니다.

## 서버 둘, 앱 하나 {#two-servers-one-app}

각 `MCPServer`는 자체 세션 매니저를 가진 독립된 앱입니다. 원하는 만큼 마운트하고, 하나의 호스트 lifespan에서 모든 매니저에 진입하세요.

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack`이 두 매니저에 모두 진입합니다. 함께 시작하고 역순으로 종료됩니다.
* 엔드포인트는 `/notes/mcp`와 `/tasks/mcp`입니다. 마운트 접두사에 기본 경로를 더한 것입니다.

## 경로 바꾸기 {#changing-the-path}

끝에 붙는 `/mcp`는 `streamable_http_path`입니다. 이 값을 `"/"`로 설정하면 마운트 접두사가 공개 경로 전체가 됩니다.

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

이제 클라이언트는 `/notes/mcp`가 아니라 `/notes`에 연결합니다.

## 브라우저 클라이언트를 위한 CORS {#cors-for-browser-clients}

브라우저 기반 클라이언트에는 두 가지 허가가 필요합니다. MCP 요청 헤더를 **보내는** 허가와, MCP가 돌려보내는 헤더를 **읽는** 허가입니다. 둘 다 호스트 앱의 CORS 설정이며, 위의 트랜스포트 보안 허용 목록도 이와 일치해야 합니다.

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers`는 다들 잊어버리는 절반입니다. `Content-Type: application/json`과 `Mcp-*` 요청 헤더는 CORS 안전 목록에 없기 때문에 브라우저는 모든 MCP 요청에 대해 **프리플라이트**를 수행하고, 프리플라이트가 허용하지 않은 헤더가 있으면 브라우저는 그 요청을 아예 보내지 않습니다. (`allow_headers=["*"]`도 동작합니다. Starlette는 프리플라이트가 요청한 것을 그대로 응답합니다.)
* `expose_headers=["Mcp-Session-Id"]`는 읽는 쪽 절반입니다. Streamable HTTP는 세션 ID를 이 응답 헤더로 돌려주며, 브라우저는 CORS가 이름으로 노출하지 않는 한 응답 헤더를 JavaScript로부터 숨깁니다. 이것이 없으면 클라이언트는 두 번째 요청을 결코 보낼 수 없습니다.
* `allow_origins`는 MCP가 아니라 직접 결정할 사항입니다. 정확하게 지정하고, 위의 `allowed_origins=`에도 똑같이 반영하세요. CORS는 브라우저가 강제하지만 서버도 `Origin`을 직접 검사하므로, 트랜스포트가 신뢰하지 않는 오리진은 프리플라이트를 깔끔하게 통과한 뒤에도 `403`을 받습니다.
* `allow_methods`는 Streamable HTTP가 쓰는 세 가지 메서드를 나열합니다. 메시지를 보내는 `POST`, 서버에서 클라이언트로 가는 스트림을 여는 `GET`, 세션을 끝내는 `DELETE`입니다.

## 커스텀 라우트 {#custom-routes}

`@mcp.custom_route()`는 같은 앱에 평범한 HTTP 엔드포인트를 등록합니다. 배포된 모든 서비스에 필요하지만 MCP와는 무관한 것, 이를테면 헬스 체크나 OAuth 콜백을 위한 것입니다.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* 핸들러는 평범한 Starlette입니다. `Request`를 받아 `Response`를 돌려주는 `async` 함수입니다.
* `streamable_http_app()`은 모든 커스텀 라우트를 가져갑니다. 이제 `app.routes`는 `/mcp`와 `/health`입니다.
* `GET /health`는 MCP와 전혀 상관없이 `{"status": "ok"}`로 응답합니다.

!!! warning
    커스텀 라우트는 서버의 나머지 부분이 인증되더라도 **절대 인증되지 않습니다**. 이는
    의도된 것입니다. 헬스 체크와 OAuth 콜백은 토큰이 존재하기 전에도 도달할 수 있어야 하기 때문입니다.
    비공개인 것은 그 뒤에 두지 마세요.

## 요약 {#recap}

* `mcp.streamable_http_app()`은 라우트 하나(`/mcp`)를 가진 Starlette 앱을 반환합니다. 어떤 ASGI 서버로든 실행할 수 있습니다.
* 기본적으로 이 앱은 localhost로 오는 요청만 받으며, 실제 호스트 이름 뒤에서는 `transport_security=`로 허용 목록을 넘기기 전까지 모든 요청을 `421`로 거부합니다. 이 부분과 프로덕션까지의 나머지 여정은 **[배포와 확장](deploy.md)**에서 다룹니다.
* `Mount`(또는 `Host`)로 더 큰 Starlette나 FastAPI 앱 안에 넣습니다.
* **마운트하면 내장 lifespan이 비활성화됩니다.** 호스트 앱의 lifespan이 `mcp.session_manager.run()`에 진입해야 하며, 그러지 않으면 첫 요청이 실패합니다.
* 한 앱에 여러 서버를 두려면 마운트를 여러 개 하고, 모든 세션 매니저에 진입하는 lifespan 하나를 둡니다.
* `streamable_http_path="/"`는 엔드포인트를 마운트 접두사 자체로 옮깁니다.
* 브라우저 클라이언트에는 CORS가 필요합니다. `Mcp-*` 요청 헤더를 위한 `allow_headers`, 응답을 위한 `expose_headers=["Mcp-Session-Id"]`입니다.
* `@mcp.custom_route()`는 `/mcp` 옆에 인증되지 않는 평범한 HTTP 엔드포인트를 추가합니다.

서버가 실제 URL로 도달 가능해지면, **[클라이언트](../client/index.md)**는 서버 객체 대신 그 URL로 연결합니다.
