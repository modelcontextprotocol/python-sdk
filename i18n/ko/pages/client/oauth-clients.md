---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth 클라이언트 {#oauth-clients}

일부 MCP 서버는 보호되어 있습니다. 토큰 없이 요청을 보내면 `401 Unauthorized`로 응답합니다.

**`OAuthClientProvider`**가 바로 토큰을 얻는 수단입니다. MCP 객체가 전혀 아닙니다. "모든 요청에 무언가를 한다"는 표준 httpx2 훅인 `httpx2.Auth`입니다. `httpx2.AsyncClient`에 붙이고, 그 클라이언트를 Streamable HTTP 트랜스포트에 넘긴 다음에는 더 신경 쓰지 않아도 됩니다.

이 페이지는 클라이언트 쪽을 다룹니다. 작성한 서버가 토큰을 요구하도록 만드는 방법은 **[인가](../run/authorization.md)**에서 다룹니다.

## 프로바이더 {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

프로바이더에는 네 가지를 넘깁니다.

* `server_url`: 연결할 MCP 엔드포인트입니다. 프로바이더가 나머지는 모두 여기서 알아냅니다.
* `client_metadata`: 인가 서버의 "애플리케이션 등록" 양식에 입력할 만한 내용입니다.
* `storage`: 실행과 실행 사이에 토큰이 보관되는 곳입니다.
* `redirect_handler`와 `callback_handler`: 사람이 개입하는 두 순간입니다.

파일의 나머지 부분에는 OAuth가 등장하지 않습니다. `main()`은 토큰을 전혀 보지 못합니다.

### 클라이언트 메타데이터 {#client-metadata}

`OAuthClientMetadata`는 실제 [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) 등록 문서를 Pydantic 모델로 옮긴 것입니다.

세 필드를 설정합니다. 나머지는 기본값이 채웁니다. `grant_types`는 이미 `["authorization_code", "refresh_token"]`이고 `response_types`는 이미 `["code"]`이며, 이 프로바이더가 실행하는 흐름이 정확히 이것입니다.

!!! check
    Pydantic 모델이므로 **네트워크로 단 한 바이트도 나가기 전에** 검증합니다.
    `redirect_uris`를 빼면 생성하는 즉시 그 필드를 지목하는 `ValidationError`와 함께
    실패합니다.

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    브라우저도 열리지 않고, 인가 서버에 반쯤 끝난 등록이 남지도 않습니다.

### 토큰 저장소 {#token-storage}

**`TokenStorage`**는 비동기 메서드 네 개를 가진 `Protocol`입니다. 아무것도 상속하지 않습니다. 메서드만 작성하면 어떤 클래스든 토큰 저장소가 됩니다.

* `get_tokens` / `set_tokens`는 `OAuthToken`을 보관합니다. 액세스 토큰, 리프레시 토큰, 만료 시각, 스코프가 여기에 담깁니다.
* `get_client_info` / `set_client_info`는 프로바이더가 등록할 때 인가 서버가 발급한 `OAuthClientInformationFull`을 보관하며, 여기에는 `client_id`가 포함됩니다.

위의 인메모리 버전도 동작합니다. 다만 프로세스가 종료되면 모든 것을 잊어버리므로 다음 실행 때 전체 절차를 처음부터 다시 밟습니다. 파일이나 플랫폼의 키링에 영속화하면 다음 실행은 조용히 지나갑니다.

!!! tip
    토큰만이 아니라 `client_info`도 저장하세요. 프로바이더는 저장된 `client_info`가 없으면
    처음에 동적으로 등록합니다. 이를 버리면 실행할 때마다 새 등록을 만들어 냅니다.

### 두 핸들러 {#the-two-handlers}

인가 코드 흐름에는 사람이 정확히 한 번 필요합니다. 누군가 로그인해서 "허용"을 클릭해야 합니다.

* **`redirect_handler`**는 완전히 조립된 인가 URL과 함께 await됩니다. `client_id`, `redirect_uri`, `state`, PKCE 챌린지가 이미 들어 있습니다. 할 일은 브라우저를 그 URL로 보내는 것뿐입니다. 데스크톱 앱이라면 `webbrowser.open`을 호출하고, 이 파일은 URL을 출력합니다.
* **`callback_handler`**가 그다음에 await됩니다. 사용자가 `redirect_uri`로 되돌아올 때까지 기다렸다가 그 리다이렉트의 쿼리 파라미터를 `AuthorizationCodeResult`로 반환합니다.

실제 클라이언트는 `input()`을 호출하는 대신 리다이렉트 URI에서 작은 로컬 HTTP 서버를 띄웁니다. 형태는 똑같습니다. 리다이렉트를 받고 `code`, `state`, `iss`를 돌려줍니다.

!!! warning
    `state`와 `iss`는 도착한 그대로 전달하세요. 프로바이더는 `state`를 자신이 생성한 값과,
    `iss`를 디스커버리로 알아낸 발급자와 비교하고, 일치하지 않으면 거부합니다. 이 둘이 CSRF와
    서버 혼동(mix-up) 공격을 막는 방어 장치입니다.

### `Client`에 넣기 {#into-the-client}

`main()`을 보세요. 프로바이더는 **httpx2 클라이언트**에 붙고, httpx2 클라이언트는 `streamable_http_client(url, http_client=...)`에 들어가며, 그 트랜스포트가 `Client`에 들어갑니다.

`streamable_http_client`에는 `auth=` 키워드가 없습니다. HTTP 수준의 것(인증, 헤더, 타임아웃, 프록시)은 모두 직접 가져오는 `httpx2.AsyncClient`에 속합니다. 이 계층 구조는 **[클라이언트 트랜스포트](transports.md)**에서 다룹니다.

## 프로바이더가 대신 해 주는 일 {#what-the-provider-does-for-you}

`Client`가 처음 요청을 보내면 서버는 `401`로 응답합니다. 그러면 프로바이더가 이어받습니다.

1. **디스커버리.** `WWW-Authenticate` 헤더를 읽고, `/.well-known/oauth-protected-resource`에서 서버의 Protected Resource Metadata를 가져오고, 어느 인가 서버가 이 리소스를 보호하는지 알아낸 뒤, **그** 서버의 메타데이터를 가져옵니다.
2. **등록.** 저장소에 아무것도 없으면 `OAuthClientMetadata`로 동적으로 등록하고 결과를 저장합니다.
3. **인가.** PKCE 쌍과 `state`를 생성하고, 인가 URL을 조립하고, `redirect_handler`를 await한 다음, 코드를 받기 위해 `callback_handler`를 await합니다.
4. **교환.** 코드를 `OAuthToken`으로 교환해 저장하고, 원래 요청에 `Authorization: Bearer ...`를 붙여 다시 보냅니다.

그다음부터는 조용합니다. 토큰은 저장소에서 꺼내 쓰고, 만료된 액세스 토큰은 리프레시 토큰으로 갱신하며, 그 어느 것도 통하지 않을 때에만 흐름을 다시 실행합니다.

이 가운데 직접 작성한 코드는 하나도 없습니다. 키워드 인자가 두 개 더 남아 있는데(`client_metadata_url`과 `validate_resource_url`), 이 파일에는 둘 다 필요 없습니다. 알아 둘 만한 것은 `client_metadata_url`이며, 아래에 별도 섹션이 있습니다.

### 직접 해 보기 {#try-it}

이 문서의 예제 대부분은 인메모리 `Client(server)`로 확인할 수 있습니다. 이 예제는 아닙니다. 이 흐름의 핵심이 HTTP `401`인데, 인메모리 클라이언트와 서버 사이에는 HTTP가 없기 때문입니다.

리포지토리에는 실제로 동작하는 버전이 들어 있습니다. `examples/servers/simple-auth/`는 독립 실행형 인가 서버와 보호된 MCP 서버를 실행하고, `examples/clients/simple-auth-client/`는 이 페이지의 클라이언트를 작은 CLI로 키운 것입니다. 그 README에 두 명령이 있습니다. 서버를 시작하고, 그 서버를 대상으로 클라이언트를 실행하면 네 단계가 지나가는 모습을 볼 수 있습니다.

## Client ID Metadata Documents {#client-id-metadata-documents}

사양의 2026-07-28 리비전은 동적 클라이언트 등록을 지원 중단 예정(deprecated)으로 돌리고 **Client ID Metadata Documents**(CIMD)를 권장합니다. 만나는 인가 서버마다 새 등록을 POST하는 대신, 클라이언트는 자신을 설명하는 JSON 문서 하나를 안정적인 HTTPS URL에 게시하고, 그 URL **자체가** `client_id`가 됩니다. 문서는 인가 서버가 가져가며, 프로바이더는 이를 전혀 건드리지 않습니다.

SDK는 이미 이를 지원합니다. 프로바이더를 생성할 때 URL을 `client_metadata_url=`로 전달하세요. 인가 서버의 메타데이터가 `client_id_metadata_document_supported: true`를 광고하면 프로바이더는 `/register` 요청을 완전히 건너뜁니다. URL이 `client_id`로 흐름에 들어가고 `client_secret`은 없습니다. 서버가 이를 광고하지 않거나(아직 대부분 그렇습니다) URL을 전달하지 않으면 프로바이더는 **조용히** 동적 등록으로 되돌아가며, 위의 모든 내용이 설명한 그대로 동작합니다. 저장된 `client_info`는 여전히 둘보다 우선합니다.

URL은 루트가 아닌 경로를 가진 HTTPS여야 합니다. 그 외에는 네트워크 통신이 일어나기 전, 생성 시점에 `ValueError`가 납니다. 함께 제공되는 `examples/clients/simple-auth-client/`는 이를 `MCP_CLIENT_METADATA_URL` 환경 변수로 받습니다.

## 머신 대 머신 {#machine-to-machine}

야간 작업, CI 단계, 다른 서비스. 브라우저도 없고 "허용"을 클릭할 사람도 없습니다. 이것이 **클라이언트 자격 증명(client credentials)** 그랜트입니다. `client_id`와 `client_secret`을 이미 가지고 있고, 토큰 엔드포인트가 흐름의 전부입니다.

`ClientCredentialsOAuthProvider`는 사람만 빠진 똑같은 `httpx2.Auth`입니다.

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

달라진 점은 다음과 같습니다.

* `OAuthClientMetadata`도 핸들러도 없습니다. `client_id`와 `client_secret`을 전달하면 프로바이더가 이를 감싸는 최소한의 `client_credentials` 등록을 만들고 동적 등록은 완전히 건너뜁니다.
* `scope`는 공백으로 구분한 문자열로, OAuth의 전송 형식입니다.
* 그 아래는 모두 동일합니다. 같은 `TokenStorage`, 같은 `httpx2.AsyncClient(auth=...)`, 같은 `streamable_http_client`를 씁니다.

기본적으로 시크릿은 토큰 요청에서 HTTP Basic 인증으로 전달됩니다(`client_secret_basic`). 대신 폼 본문에 넣으려면 `token_endpoint_auth_method="client_secret_post"`를 전달하세요. 둘 중 하나만 받는 인가 서버도 있습니다.

!!! tip
    `client_secret`은 환경 변수나 시크릿 매니저에서 읽고, 소스 관리에서는 절대 읽지 마세요.

!!! info
    `mcp.client.auth.extensions.client_credentials`에는 프로바이더가 하나 더 있습니다.
    공유 시크릿 대신 JWT로 인증하는 클라이언트를 위한 **`PrivateKeyJWTOAuthProvider`**입니다
    (`private_key_jwt`, 즉 키 쌍과 워크로드 아이덴티티 방식). 같은 패턴을 따릅니다.
    하나를 생성해 `auth=`에 넣으면 됩니다. 같은 모듈에는 그 어설션을 만드는 두 헬퍼인
    `SignedJWTParameters`와 `static_assertion_provider`도 들어 있습니다.

사람이 없는 상황이 하나 더 있습니다. 클라이언트가 기업에 속해 있고, 어느 MCP 서버에 접근할 수 있는지를 사용자가 아니라 그 기업의 아이덴티티 공급자가 결정하는 경우입니다. 이는 고유한 신뢰 모델을 가진 다른 그랜트이며, 별도 페이지인 **[아이덴티티 어설션](identity-assertion.md)**에서 다룹니다.

## 실패할 때 {#when-it-fails}

OAuth 흐름이 잘못되면 프로바이더는 `mcp.client.auth`의 `OAuthFlowError`를 발생시킵니다. 하위 클래스가 둘 있습니다. `OAuthRegistrationError`는 등록 결과로 쓸 수 있는 클라이언트를 얻지 못했다는 뜻입니다. 인가 서버가 등록을 거부했거나, 등록은 했지만 이 흐름이 쓸 수 없는 자격 증명(예를 들어 구현하지 않은 인증 방식)을 준 경우입니다. `OAuthTokenError`는 토큰을 얻지 못했다는 뜻입니다. 토큰 엔드포인트가 거절했거나, 저장된 클라이언트 레코드에 이 클라이언트가 적용할 수 없는 인증 방식이 담겨 있는 경우로, 후자는 요청을 보내는 대신 토큰 요청을 조립하는 도중에 보고됩니다. `except OAuthFlowError:` 하나로 디스커버리, 등록, 인가, 교환을 모두 잡을 수 있습니다.

모든 것이 흐름 오류인 것은 아닙니다. 네트워크는 여전히 실패할 수 있으며, 그런 경우는 평범한 `httpx2` 예외이고 그대로 통과합니다.

## 요약 {#recap}

* `OAuthClientProvider`는 `httpx2.Auth`입니다. `httpx2.AsyncClient`에 붙이고, 이를 `streamable_http_client(url, http_client=...)`에 전달하면 `Client`는 OAuth가 일어났는지조차 모릅니다.
* 네 가지를 제공합니다. 서버 URL, `OAuthClientMetadata`, `TokenStorage`, 그리고 리다이렉트/콜백 핸들러 쌍입니다.
* `TokenStorage`는 `Protocol`입니다. 비동기 메서드 네 개, 기반 클래스는 없습니다. 토큰뿐 아니라 `client_info`도 영속화하세요.
* 디스커버리, 등록(동적 등록 또는 **Client ID Metadata Document**를 통한 등록), PKCE, `state`와 `iss` 검사, 토큰 갱신은 프로바이더의 일이지 직접 할 일이 아닙니다.
* `ClientCredentialsOAuthProvider`는 사람이 없는 버전입니다. `client_id` + `client_secret`, 핸들러도 브라우저도 없습니다.
* 모든 OAuth 실패는 `OAuthFlowError`이며, `OAuthRegistrationError`와 `OAuthTokenError`가 그 하위 클래스입니다.

이 핸드셰이크의 나머지 절반, 즉 **서버**가 토큰을 요구하도록 만드는 방법은 **[인가](../run/authorization.md)**에서 다룹니다.
