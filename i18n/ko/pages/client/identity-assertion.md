---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# ID 어설션 {#identity-assertion}

일반적인 OAuth 공급자(**[OAuth 클라이언트](oauth-clients.md)**)는 먼저 MCP 서버에 **어느 인가 서버를 신뢰하는지** 묻는 것으로 시작합니다. 그 답이 가리키는 곳이면 어디든 따라가고, 그런 다음 사람이 로그인하거나 사전 공유된 시크릿이 사람을 대신합니다.

기업은 이 둘 중 어느 것도 서버마다 따로 결정되기를 원하지 않습니다. 기업은 이미 ID 공급자(Okta, Microsoft Entra ID, 또는 자체 운영하는 것)를 운영하고 있고, 사용자는 오늘 아침에 이미 거기에 로그인했으며, 보안 팀이 누가 무엇에 접근할 수 있는지를 결정하고 싶어 하는 유일한 곳이 바로 그곳입니다. **Enterprise-Managed Authorization** 확장인 [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)은 그 결정을 그곳으로 옮깁니다. IdP는 수명이 짧은 JWT, 즉 **Identity Assertion JWT Authorization Grant**, 줄여서 **ID-JAG**에 서명합니다. **이 사용자**가 **이 클라이언트**를 통해 **이 MCP 서버**에 접근해도 된다는 진술입니다. 클라이언트는 이를 일반적인 액세스 토큰으로 교환합니다. 브라우저도, 동의 화면도, 동적 등록도 없습니다.

이 페이지는 그 교환의 양쪽 끝을 모두 다룹니다. MCP 서버 자체는 전혀 바뀌지 않습니다. 여전히 **[인가](../run/authorization.md)**에서 본 리소스 서버이며, 들어오는 토큰이 무엇이든 검사할 뿐입니다.

## 두 번의 토큰 요청 {#two-token-requests}

여기에는 서로 다른 두 권한 주체가 등장하며, 이 둘을 구분해서 부르는 것이 이 페이지를 이해하는 일의 대부분입니다. **엔터프라이즈 IdP**는 조직의 ID 공급자입니다. 직원이 누구인지 알고, 정책이 있는 곳이며, ID-JAG를 발급합니다. SDK는 이 IdP와 절대 통신하지 않습니다. **MCP 인가 서버**는 **[인가](../run/authorization.md)**에서와 같은 당사자입니다. MCP 서버의 메타데이터에 명시된 발급자이자, 그 MCP 서버가 받아들이는 토큰을 발급하는 주체입니다. 일반적인 OAuth 흐름에서는 이 두 역할이 보통 하나의 시스템입니다. 여기서는 둘로 나뉘며, 이 그랜트 전체는 결국 후자가 전자를 신뢰하기로 동의하는 것입니다.

클라이언트는 각각에 토큰 요청을 한 번씩 보냅니다.

1. **엔터프라이즈 IdP에 보내는 요청.** 클라이언트는 사용자의 로그인(OpenID Connect ID 토큰)을 ID-JAG로 교환합니다. 이것은 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 토큰 교환이고, 전적으로 IdP의 API이며, **SDK는 이 요청을 보내지 않습니다**. 하나의 async 콜백 안에서 직접 보냅니다. 정책 결정이 일어나는 곳도 여기입니다. IdP가 거부하면 ID-JAG는 발급되지 않고, 제시할 것도 없습니다.
2. **MCP 인가 서버에 보내는 요청.** 클라이언트는 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) `jwt-bearer` 그랜트(`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, ID-JAG를 `assertion`으로)로 ID-JAG를 제시하고 액세스 토큰을 받습니다. **이것이 SDK가 보내는 요청이며**, 이 요청을 받아들이는 것이 이 페이지가 인가 서버에 추가하는 단 하나의 기능입니다.

아래의 모든 내용은 두 번째 요청, 즉 이를 보내는 클라이언트와 이에 응답하는 인가 서버에 관한 것입니다.

## 클라이언트 {#the-client}

**`IdentityAssertionOAuthProvider`**는 `mcp.client.auth.extensions.identity_assertion`에 있습니다. **[OAuth 클라이언트](oauth-clients.md)**의 모든 공급자와 마찬가지로 `httpx2.Auth`입니다. 하나를 생성해 `auth=`에 넣고, `httpx2.AsyncClient`를 트랜스포트에 넘기면 됩니다.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

아래에서부터 읽어 보세요.

* `main()`은 표준 OAuth 클라이언트의 `main()`(**[OAuth 클라이언트](oauth-clients.md)**)이며, 한 줄도 바뀌지 않았습니다. 그것이 핵심입니다. 공급자가 일단 존재하면, 그 뒤의 어떤 코드도 어떤 그랜트가 토큰을 만들어 냈는지 알지 못합니다.
* 공급자는 다른 공급자가 스스로 알아낼 수 없는 것을 받습니다. 누군가가 인가 서버에 **사전 등록**해 둔 `client_id`와 `client_secret`, 그 인가 서버의 `issuer`, 그리고 요청할 때마다 새 ID-JAG를 반환하는 async 콜백인 `assertion_provider`입니다.
* `storage`는 같은 `TokenStorage` 프로토콜입니다. 호출되는 것은 토큰 관련 메서드 두 개뿐입니다. 여기에는 동적 등록이 없으므로 기억해 둘 `client_info`도 없습니다.

### 어설션 공급자 {#the-assertion-provider}

`fetch_id_jag(audience, resource)`가 직접 작성하는 유일한 코드입니다. 토큰 교환마다 한 번씩 await되고, 생성 시점에는 절대 호출되지 않으며, 인가 서버의 메타데이터를 가져와 검증한 **뒤에만** 호출되므로 잘못 설정된 발급자로 어설션이 새어 나가는 일은 없습니다. 두 인수는 ID-JAG를 발급할 때 담아야 하는 클레임 중 두 가지입니다. `audience`는 인가 서버의 발급자(ID-JAG의 `aud`)이고 `resource`는 MCP 서버의 정식 식별자(ID-JAG의 `resource`)입니다. 세 번째는 이미 가지고 있는 값입니다. ID-JAG의 `client_id` 클레임은 공급자에 넘긴 `client_id`를 가리켜야 하며, 그렇지 않으면 인가 서버가 교환을 거부합니다.

그 위에 있는 `idp_issue_id_jag`는 **작성할 코드가 아닙니다**. ID 공급자를 대신하는 것으로, 파일이 그 자체로 완결되고 ID-JAG가 담는 모든 클레임을 읽어 볼 수 있도록 프로세스 안에서 어설션에 서명합니다. 실제 `fetch_id_jag`는 그 대신 앞 절의 첫 번째 토큰 요청을 보냅니다. IdP를 상대로 한 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 토큰 교환이며, [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)이 프로파일로 삼는 Identity Assertion JWT Authorization Grant 초안이 이를 정의합니다. 로그인한 사용자의 ID 토큰이 `subject_token`으로 들어가고, `requested_token_type`은 ID-JAG 고유의 URN(`urn:ietf:params:oauth:token-type:id-jag`)이며, `audience`와 `resource`는 그대로 전달되고, 응답에 ID-JAG가 실려 옵니다. IdP 문서에서 찾아봐야 할 것이 바로 이 이름들로 이루어지는 이 교환입니다.

!!! tip
    교환할 때마다 새 ID-JAG를 요청하며, 그것이 의도된 설계입니다. ID-JAG는 수명이 몇 분에 불과한
    일회용 그랜트이고, 이 페이지의 인가 서버는 같은 ID-JAG를 두 번 받아들이지 않습니다. 캐시하지
    마세요. 재사용되는 것은 ID-JAG로 얻은 액세스 토큰입니다.

### 설정으로 지정하는 발급자 {#the-issuer-is-configuration}

여기서 관계가 뒤집힙니다. `OAuthClientProvider`는 어느 인가 서버를 쓸지 리소스 서버에 묻고 그 답이 가리키는 곳이면 어디든 따라갑니다. 이 공급자는 그렇게 하기를 거부합니다. `issuer`는 필수이고, [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) 메타데이터는 그 발급자 자신의 well-known 경로에서 가져오며, 토큰 엔드포인트는 그 발급자의 오리진에 있어야 하고, 리소스 서버에는 아무것도 묻지 않습니다.

확장이 이를 요구하는 것은 아닙니다. 의도적으로 더 엄격하게 선택한 것입니다. 이 클라이언트는 훔칠 가치가 있는 것을 두 가지 지니고 있습니다. 사전 등록된 시크릿과 audience에 묶인 어설션입니다. 침해된 MCP 서버가 공격자의 인가 서버로 유도하도록 내버려 두는 클라이언트라면 둘 다 그곳에 POST하게 됩니다. 생성 시점에 발급자를 고정하면 그런 대화 자체가 사라집니다.

!!! warning
    설정한 `issuer`는 메타데이터 문서의 `issuer` 필드와 RFC 8414 §3.3의 단순 문자열 비교로
    대조됩니다. 한 글자씩, 끝의 슬래시까지 포함해, 정규화 없이 비교합니다. 추측하지 마세요. 인가
    서버에서 `/.well-known/oauth-authorization-server`를 가져와 반환된 `issuer` 값을 그대로
    복사하세요. 이 페이지의 인가 서버라면 그 값은 슬래시가 붙은 `https://auth.example.com/`입니다.
    발급자가 pydantic URL 객체로부터 만들어졌기 때문입니다. 일치하지 않으면 자격 증명이나 어설션을
    단 하나도 보내기 전에 `OAuthFlowError: Authorization server metadata issuer
    mismatch`에서 흐름이 멈춥니다.

### 기밀 클라이언트 {#a-confidential-client}

`client_secret`은 필수이며, 없으면 생성자가 `ValueError`를 발생시킵니다. [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)의 기반이 되는 IETF 프로파일은 이 그랜트를 기밀 클라이언트 전용으로 두고, SEP-990은 클라이언트가 인증할 것을 요구하며, 이 SDK는 공유 시크릿을 반드시 요구함으로써 둘 다 강제합니다. `token_endpoint_auth_method`는 시크릿이 어디에 실려 가는지를 고릅니다. `client_secret_post`(기본값, 폼 본문에)나 `client_secret_basic`(HTTP Basic 헤더) 중 하나입니다. 프로파일은 `private_key_jwt`도 허용하지만, 이 공급자는 지원하지 않습니다.

!!! tip
    `client_secret`은 환경 변수나 시크릿 관리자에서 읽어 오세요. 소스 관리에서 읽어서는 절대 안 됩니다.

### 공급자가 대신 처리하는 일 {#what-the-provider-does-for-you}

첫 번째 요청은 인증 없이 나가고, 서버의 `401`이 흐름을 시작합니다.

1. **탐색.** 설정된 발급자의 [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known 경로에서 인가 서버 메타데이터를 가져오고, 문서의 `issuer`가 일치하는지 확인하고, 토큰 엔드포인트가 발급자의 오리진에 있는지 확인합니다.
2. **어설션.** `assertion_provider`를 await합니다.
3. **교환.** 토큰 엔드포인트에 `jwt-bearer` 그랜트를 POST하고, `OAuthToken`을 저장한 뒤, 원래 요청을 `Authorization: Bearer ...`를 붙여 다시 보냅니다.

`WWW-Authenticate`에 `insufficient_scope`가 명시된 `403`을 받으면 설정한 `scope`와 챌린지로 요구된 범위의 합집합으로 2단계와 3단계를 다시 실행합니다. (`scope`는 어디까지나 요청일 뿐입니다. 이 페이지의 인가 서버는 ID-JAG에 적힌 것만 부여하고 그 외에는 아무것도 부여하지 않습니다.) 이 과정 어디에도 리프레시 토큰은 없습니다. 액세스 토큰이 만료되면 다음 `401`에서 새 ID-JAG를 발급받아 다시 교환하며, 바로 **그것이** IdP가 쥐고 있는 지렛대입니다. 실패는 **[OAuth 클라이언트](oauth-clients.md)**의 나머지와 같은 두 가지 예외로 나타납니다. 탐색과 검증에는 `OAuthFlowError`, 토큰 엔드포인트가 거부하면 그 하위 클래스인 `OAuthTokenError`입니다.

## 인가 서버 {#the-authorization-server}

대부분의 경우 여기서 멈추면 됩니다. MCP 인가 서버는 다른 누군가의 제품이고, ID-JAG를 받아들이는 것은 그 제품에서 켜야 할 설정이며, [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)에서 SDK가 맡는 절반은 위의 클라이언트입니다.

SDK가 직접 인가 서버가 **될** 수도 있습니다. `create_auth_routes`는 인가 서버의 라우트를 어떤 Starlette 앱이든 마운트할 수 있는 리스트로 반환하며, 저장소의 `examples/servers/simple-auth/`가 바로 이 방식으로 인가 서버를 실행합니다. SEP-990은 그 표면에 플래그 하나와 메서드 하나를 추가합니다.

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True`가 모든 것의 관문입니다. 꺼져 있으면(기본값), 훅을 구현했더라도 `/token`은 이 그랜트에 `unsupported_grant_type`으로 응답하고 메타데이터에도 언급되지 않습니다. 켜면 메타데이터에 `jwt-bearer` 그랜트 유형이 추가되고, 확장이 지원을 알리는 데 쓰는 필드인 `authorization_grant_profiles_supported`에 `urn:ietf:params:oauth:grant-profile:id-jag`가 나열됩니다. (이 SDK의 클라이언트는 이 필드를 읽지 않습니다. 발급자 하나에 맞춰 프로비저닝되어 있으므로 그냥 요청할 뿐입니다.)
* **`exchange_identity_assertion`**이 훅입니다. 이 훅이 실행되기 전에 SDK는 이미 클라이언트를 인증하고, 공개 클라이언트를 거부하고, 등록 정보에 이 그랜트가 나열되지 않은 클라이언트를 거부한 상태입니다. `IdentityAssertionParams`(원시 `assertion`, 요청된 `scopes`와 `resource`)를 받아 평범한 `OAuthToken`을 반환합니다.
* 동적 클라이언트 등록은 이 그랜트를 무조건 거부하므로, 여기서 `get_client`는 수동으로 프로비저닝한 클라이언트를 내줍니다. ID-JAG 클라이언트는 스스로 등록해서 생겨날 수 없습니다.
* 클래스의 절반은 거부 코드입니다. `OAuthAuthorizationServerProvider`는 인가 서버 **전체**이므로 인가 코드 흐름도 요구합니다. 사용자 로그인까지 처리하는 서버라면 그 부분을 실제로 구현하지만, 이 서버에는 문이 정확히 하나뿐입니다.

!!! warning
    SDK는 어설션을 절대 디코딩하지 않습니다. 어떤 IdP를 신뢰하고 그 IdP가 어떤 키를 공개하는지는
    해당 배포 환경만 알기 때문이며, 따라서 `exchange_identity_assertion` 안의 모든 코드가 보안을
    떠받칩니다. [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3에 따라 IdP가 공개한 키(JWKS, 여기서 쓰는 공유 시크릿은
    데모용입니다)로 서명을 검증하고, `iss`와 `exp`도 검증하세요. JWT 헤더의 `typ`이
    `oauth-id-jag+jwt`일 것을 요구하세요. 다른 JWT가 그랜트로 재사용되는 것을 막는 프로파일의
    안전장치입니다. `aud`가 자기 자신의 발급자일 것을 요구하세요. ID-JAG의 `client_id` 클레임이
    핸들러가 인증한 클라이언트와 같을 것을, 그리고 `resource` 클레임이 실제로 서비스하는 리소스를
    가리킬 것을 요구하세요. 어설션이 한 번만 받아들여지도록 어설션의 `exp`까지 `jti`를 추적하세요.
    그리고 부여하는 범위와, 무엇보다도 발급하는 토큰의 `resource`는 검증된 ID-JAG에서 가져오고
    절대 요청에서 가져오지 마세요. `params.resource`는 클라이언트가 입력한 값일 뿐입니다. 전체
    처리 규칙은 [Enterprise-Managed Authorization 사양](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization)에
    있습니다.

잘못된 어설션은 `TokenError("invalid_grant", ...)`로 거부하세요. 이 흐름의 다른 오류 코드는 `invalid_target`입니다. 서비스하지 않는 리소스를 가리키는 ID-JAG는 이 코드로 거부되며, 이것이 이 서버가 다른 누군가의 리소스용 토큰을 발급하지 못하게 막는 장치입니다. 그리고 부여되는 범위는 ID-JAG의 `scope` 클레임에서 옵니다(이 클레임이 없는 어설션도 거부됩니다). 실제 구현에서는 대신 사용자의 그룹을 매핑할 수도 있습니다.

반환되는 `OAuthToken`에 무엇이 없는지도 눈여겨보세요. 리프레시 토큰이 없습니다. IdP는 다음 ID-JAG를 발급할지 말지를 결정함으로써 이 사용자가 얼마나 오래 접근을 유지할지 결정합니다. 여기서 리프레시 토큰을 발급하면 그 결정권을 조용히 되돌려주는 셈이 됩니다.

!!! info
    여전히 `auth_server_provider=`로 인가 서버를 내장하는 서버는
    `AuthSettings(identity_assertion_enabled=True)`를 통해 같은 코드에 도달합니다. 새 서버가 왜 그
    방식으로 시작하면 안 되는지는 **[인가](../run/authorization.md)**에서 설명합니다.

!!! check
    이 페이지의 두 파일을 서로 연결하면 그랜트 전체가 `POST /token` 한 번입니다.

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    `/authorize`도, `/register`도, protected-resource-metadata 가져오기도 없습니다. 실제로 오가는
    요청은 `401`을 끌어낸 요청, well-known 가져오기, 이 교환, 그리고 그 뒤로 bearer를 붙인 일반적인
    MCP 트래픽뿐입니다. 그리고 검증 코드가 ID-JAG에서 읽어 낸 `sub`는 도구 안에서
    `get_access_token().subject`가 보고하는 값과 정확히 같습니다.

### 직접 해 보기 {#try-it}

SDK 저장소의 `examples/stories/identity_assertion/`은 이 페이지를 실제로 실행한 것입니다. 같은 `exchange_identity_assertion` 검증 코드, 그 토큰으로 보호되는 MCP 서버, 대역 IdP, 그리고 클라이언트까지, 스스로 검증하는 프로그램 하나에 모두 담겨 있습니다. `uv run python -m stories.identity_assertion.client --http`는 교환 전체를 실행하고 IdP가 지명한 사용자가 도구가 보는 사용자와 같은지 assert합니다.

## 요약 {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)은 최종 사용자가 아니라 엔터프라이즈 ID 공급자가 클라이언트가 어느 MCP 서버에 접근할 수 있는지를 결정하게 합니다. IdP는 그 결정을 **ID-JAG**에 서명해 담습니다.
* ID-JAG를 얻는 것은 **자체 IdP**를 상대로 한 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 토큰 교환이며, SDK는 이를 수행하지 않습니다. ID-JAG를 MCP 인가 서버에 제시하는 것은 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) `jwt-bearer` 그랜트이며, SDK는 그 양쪽을 모두 수행합니다.
* `IdentityAssertionOAuthProvider`는 또 하나의 `httpx2.Auth`입니다. 사전 등록된 기밀 클라이언트, 고정된 `issuer`, 그리고 `assertion_provider(audience, resource)` 콜백 하나로 이루어집니다. 브라우저도, 등록도, 리프레시 토큰도 없습니다.
* 인가 서버를 리소스 서버를 통해 찾아내는 일은 없습니다. `issuer`는 메타데이터 문서가 내주는 문자열과 정확히 같게 설정하세요. 비교는 한 글자씩 이루어집니다.
* 서버 쪽에서는 `identity_assertion_enabled=True`에 `exchange_identity_assertion`을 더합니다. SDK는 클라이언트를 인증하고 그랜트의 관문을 지키며, ID-JAG 검증은 전적으로 직접 구현할 몫이고, 발급되는 토큰은 요청의 것이 아니라 ID-JAG의 `resource`에 묶입니다.

이 페이지가 한 번도 건드리지 않은 당사자는 MCP 서버입니다. 방금 발급한 토큰으로 MCP 서버가 하는 일은 이미 **[인가](../run/authorization.md)**에서 하던 일입니다.
