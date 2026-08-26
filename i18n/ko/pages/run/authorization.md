---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# 인가 {#authorization}

Streamable HTTP에서 MCP 서버는 평범한 웹 서비스이며, 다른 웹 서비스와 똑같은 방식으로 보호합니다. 바로 OAuth 2.1 bearer 토큰입니다.

OAuth 용어로 말하면 서버는 **리소스 서버**입니다. 누구도 로그인시키지 않고 토큰을 발급하지도 않습니다. 하는 일은 단 하나, 각 요청의 `Authorization` 헤더를 보고 그 안의 토큰이 유효한지 판단하는 것입니다.

이 페이지는 서버 쪽을 다룹니다. 인가 서버를 찾아내고 토큰을 가져오는 클라이언트는 **[OAuth 클라이언트](../client/oauth-clients.md)**에서 확인하세요.

## 세 당사자 {#the-three-parties}

* **인가 서버**는 사용자를 로그인시키고 액세스 토큰을 발급합니다. 직접 작성하는 것이 아닙니다. ID 제공자(Auth0, Keycloak, Entra, 자체 구축한 것)가 이 역할을 합니다.
* **리소스 서버**는 MCP 서버입니다. 모든 요청에서 토큰을 검증합니다.
* **클라이언트**는 서버가 신뢰하는 인가 서버가 어디인지 찾아내고, 거기서 토큰을 받아 `Authorization: Bearer <token>`으로 서버에 보냅니다.

삼각형은 이것이 전부입니다. 이 페이지의 모든 내용은 가운데 항목에 관한 것입니다.

## 토큰 검증기 {#a-token-verifier}

SDK는 유효한 토큰이 어떤 모습인지에 대해 아무런 의견이 없습니다. **`TokenVerifier`**를 구현해서 알려 주면 됩니다.

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier`는 async 메서드 하나를 가진 프로토콜입니다. `verify_token`은 `Authorization` 헤더에서 꺼낸 원시 토큰을 받아, 유효하면 **`AccessToken`**을, 유효하지 않으면 `None`을 반환합니다. 그 외에 구현할 것은 없습니다.
* 이 예제는 테이블에서 토큰을 조회합니다. 실제 구현은 JWT 서명을 검증하거나 인가 서버의 토큰 인트로스펙션 엔드포인트를 호출합니다. 그 코드는 직접 작성하는 것이고, SDK는 호출만 합니다.
* `token_verifier=`와 `auth=`는 항상 함께 다닙니다. 한쪽만 전달하면 `MCPServer(...)`가 요청을 하나도 처리하기 전에 `ValueError`를 발생시킵니다.

`AuthSettings`는 리소스 서버의 공개 정보입니다.

* `issuer_url`: 토큰을 발급하는 인가 서버입니다.
* `resource_server_url`: 이 MCP 엔드포인트의 공개 URL입니다. 토큰이 **어떤** 리소스를 위한 것인지 지칭하며, 디스커버리 문서가 위치하는 곳이기도 합니다.
* `required_scopes`: 모든 토큰이 이 스코프를 전부 가지고 있어야 합니다.

!!! tip
    SDK 저장소의 `examples/servers/simple-auth/`에는 실제 인가 서버의
    [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) 엔드포인트를 호출하는 `IntrospectionTokenVerifier`가 있습니다. 대부분의 프로덕션 검증기가 취하는 형태입니다.

## HTTP에서 얻는 것 {#what-you-get-over-http}

인가는 HTTP 헤더에 있으므로 HTTP 트랜스포트에서만 존재합니다. 배포할 트랜스포트로 실행하세요. `mcp.run(transport="streamable-http")`는 서버를 `http://127.0.0.1:8000/mcp`에 올리며, 나머지는 **[서버 실행하기](index.md)**에서 확인하세요. 이제 앱에는 라우트가 두 개 있습니다.

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

등록한 도구는 하나입니다. 두 번째 라우트는 SDK가 만든 것입니다.

### 디스커버리 {#discovery}

이 well-known 경로에 `GET` 요청을 보내면 `AuthSettings`에서 곧바로 만들어진 **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata**가 돌아옵니다.

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

서버를 전혀 모르는 클라이언트가 들어오는 길을 찾는 수단이 바로 이 문서입니다. `authorization_servers`를 읽고 그곳에서 토큰을 받아옵니다. 이 문서는 한 줄도 직접 작성하지 않았습니다.

!!! check
    토큰 없이(또는 검증기가 `None`을 반환한 토큰으로) `/mcp`를 호출하면 요청은
    문 앞에서 차단됩니다.

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    아무것도 파싱되지 않았고 어떤 도구도 실행되지 않았습니다. 그리고 `WWW-Authenticate`의 `resource_metadata`
    포인터가 디스커버리를 자동으로 만들어 줍니다. 401 -> 메타데이터 문서 -> 인가 서버 -> 토큰 -> 재시도 순서입니다.

!!! warning
    이 중 어느 것도 `stdio`를 보호하지 않습니다. 파이프에는 `Authorization` 헤더가 없으므로
    `token_verifier`는 거기서 전혀 호출되지 않습니다. `stdio` 서버의 보안 경계는 서버를 실행한 프로세스입니다.
    테스트에서 사용하는 인메모리 `Client(mcp)`도 마찬가지입니다. 서버 객체에 직접 연결하여
    인가를 포함한 HTTP 계층을 건너뜁니다.

## 호출자의 신원 {#the-callers-identity}

어떤 핸들러 안에서든 **`get_access_token()`**은 현재 요청에 대해 검증기가 반환한 `AccessToken`입니다.

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* 도구, 리소스, 프롬프트에서 모두 동작하며 전달해야 할 것은 아무것도 없습니다. 인증 미들웨어가 요청마다 컨텍스트 변수에 저장합니다.
* **검증기가 만든 것과 동일한 객체**가 돌아옵니다. `client_id`, `scopes`, `subject`, `expires_at`, 그리고 덧붙인 추가 `claims`까지 그대로입니다. 도구별 규칙을 걸 지점이 바로 여기입니다. 스코프를 읽고 거부하면 됩니다.
* 인증된 HTTP 요청 밖에서는 `None`을 반환합니다. 인메모리와 `stdio`에서는 항상 `None`입니다.

`Authorization: Bearer alice-token`으로 `whoami`를 호출하면 모델은 다음을 읽습니다.

```text
alice (scopes: notes:read)
```

## SDK가 하지 않는 절반 {#the-half-the-sdk-doesnt-do}

SDK는 리소스 서버 쪽 절반을 제공합니다. 검증하고, 알리고, 거부합니다. 로그인 페이지, 동의 화면, 토큰은 제공하지 않습니다.

세 당사자가 모두 움직이는 모습을 보려면 SDK 저장소의 `examples/servers/simple-auth/`(작은 인가 서버와 이 페이지와 똑같이 설정된 리소스 서버)를 실행한 다음, `examples/clients/simple-auth-client/`를 그 서버로 연결해 디스커버리부터 토큰까지의 전체 흐름을 확인하세요.

!!! info
    두 번째 생성자 인자인 `auth_server_provider=`는 MCP 서버 안에 완전한 인가 서버를
    내장합니다. MCP 인가 사양의 근간인 AS/RS 분리가 도입되기 전에 만들어진 것입니다.
    새 서버에서는 사용하지 않아야 합니다.

인가 서버는 사용자가 동의 화면을 클릭하는 대신 기업 ID 제공자의 서명된 어설션을 받을 수도 있으며, SDK는 이 교환의 양쪽을 모두 지원합니다. 이 그랜트와 이를 제시하는 클라이언트는 **[ID 어설션](../client/identity-assertion.md)**에서 확인하세요.

## 요약 {#recap}

* Streamable HTTP에서 서버는 OAuth 2.1 **리소스 서버**입니다. 토큰을 검증할 뿐, 결코 발급하지 않습니다.
* `TokenVerifier`가 통합 지점의 전부입니다. async 메서드 하나에 토큰이 들어가고 `AccessToken | None`이 나옵니다.
* `token_verifier=`와 `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])`는 항상 함께 다닙니다.
* SDK는 `/.well-known/oauth-protected-resource/...`에 [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata를 게시하고, 인증되지 않은 요청에는 이 문서를 가리키는 `WWW-Authenticate` 헤더가 담긴 401로 응답합니다. 디스커버리는 이것이 전부입니다.
* 어떤 핸들러에서든 `get_access_token()`이 곧 호출자입니다.
* 인가는 HTTP의 관심사입니다. `stdio`와 인메모리 클라이언트에서는 인가가 전혀 보이지 않습니다.

클라이언트 쪽 절반(인가 서버를 찾아내고 토큰을 대신 가져오는 일)은 **[OAuth 클라이언트](../client/oauth-clients.md)**에서 확인하세요. 그리고 사용자에게 신원을 묻는 대신 신원을 **어설션**하는 클라이언트는 **[ID 어설션](../client/identity-assertion.md)**에서 확인하세요.
