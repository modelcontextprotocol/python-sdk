---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# 클라이언트 트랜스포트 {#client-transports}

모든 `Client`는 **트랜스포트**를 통해 서버와 통신합니다. 메시지를 실제로 실어 나르는 것이 바로 트랜스포트입니다.

트랜스포트를 따로 설정할 일은 없습니다. `Client`는 위치 인자 하나만 받으며, 그 타입을 보고 어떤 트랜스포트를 쓸지 판단합니다.

각 트랜스포트의 **서버** 쪽(`mcp.run()`이 하는 일과 배포 대상)은 **[서버 실행하기](../run/index.md)**에서 다룹니다.

## 인메모리 {#in-memory}

서버 객체 자체를 전달하세요.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

서브프로세스도, 포트도, 네트워크를 오가는 바이트도 없습니다. 클라이언트와 서버는 같은 프로세스 안의 두 객체일 뿐이지만, 호출은 여전히 실제 프로토콜 계층을 거칩니다. `search_books`는 HTTP를 통할 때와 똑같이 나열되고, 검증되고, 호출됩니다.

덕분에 이 방식은 동시에 두 가지 역할을 합니다.

* **테스트 도구.** 이 문서의 모든 예제는 이 방식으로 실행되며, **[테스트](../get-started/testing.md)** 페이지는 전체 패턴을 이 방식 위에 구축합니다.
* **임베딩 API.** 서버를 직접 생성하는 애플리케이션은 도구를 호출하기 위해 네트워크를 거칠 필요가 없습니다.

## Streamable HTTP {#streamable-http}

URL 문자열을 전달하면 **Streamable HTTP**를 얻습니다. 배포 시 사용하는 트랜스포트입니다.

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

이것이 프로덕션 클라이언트의 전부입니다. `Client`가 URL을 `streamable_http_client(...)`로 감싸 주며, 그 아래에는 MCP에 맞게 설정된 `httpx2.AsyncClient`가 있습니다. `follow_redirects=True`, connect/write/pool에 30초 타임아웃, 그리고 서버가 응답 스트림을 열어 둘 수 있으므로 read에는 300초 타임아웃이 적용됩니다.

!!! check
    생성만 한 `Client`는 **연결되지 않은** 상태입니다. 생성은 트랜스포트를 고를 뿐이고,
    실제로 여는 것은 `async with`입니다. 진입하기 전에 연결을 사용하려 하면 SDK가 이를 알려 줍니다.

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    `Client("http://...")`를 작성한 시점에는 아무것도 리졸브되거나, 가져오거나, 생성되지 않았습니다. 그 줄은 비용이 들지 않습니다.

### 직접 만든 `httpx2.AsyncClient` 사용하기 {#bring-your-own-httpx2asyncclient}

`Authorization` 헤더, 쿠키, 프록시, mTLS, 다른 타임아웃이 필요해지는 순간, `httpx2.AsyncClient`를 직접 만들어 `streamable_http_client`에 넘기세요.

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

눈여겨볼 점이 두 가지 있습니다.

* `httpx2.AsyncClient`의 소유자는 작성한 코드이므로, 진입과 종료도 **직접** 해야 합니다. SDK는 자신이 만들지 않은 클라이언트를 절대 닫지 않습니다.
* `streamable_http_client(url, http_client=...)`는 트랜스포트를 반환하고, `Client(transport)`는 이를 다른 것과 마찬가지로 받아들입니다.

TLS 관련 참고 사항이 하나 있습니다. `httpx2`는 번들된 CA 목록이 아니라
([`truststore`](https://pypi.org/project/truststore/)를 통해) 운영체제의 신뢰 저장소를 기준으로
인증서를 검증합니다. 사용 가능한 시스템 CA 저장소가 없는 환경(일부 최소 컨테이너)에서는 표준
`SSL_CERT_FILE`/`SSL_CERT_DIR` 환경 변수를 설정하거나 `httpx2.AsyncClient`에 명시적으로
`verify=ssl_context`를 전달하세요(배경 설명은
[`httpx2`로 대체된 `httpx`와 `httpx-sse`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)에 있습니다).

!!! warning
    `streamable_http_client`는 예전에 `headers=`와 `timeout=`을 직접 받았습니다. 이제는 받지 않습니다.
    매개변수는 `url`, `http_client`, `terminate_on_close`뿐입니다. 습관적으로 `headers=`를 쓰면
    다음 오류가 납니다.

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    HTTP와 관련된 모든 것은 이제 전달하는 `httpx2.AsyncClient` 하나에 담깁니다.

!!! info
    `httpx2`는 익숙한 `httpx` API를 그대로 유지하므로, `httpx`를 안다면 여기서 인증, 프록시,
    이벤트 훅, 재시도, 연결 제한을 다루는 방법도 이미 아는 셈입니다. SDK는 그 위에 아무것도
    더하지 않고 아무것도 빼지 않습니다. OAuth가 연결되는 지점도 여기입니다.
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. 전체 흐름은 **[OAuth 클라이언트](oauth-clients.md)**에서 다룹니다.

## stdio {#stdio}

**stdio** 서버는 서브프로세스입니다. 클라이언트가 이를 실행하고, stdin에 JSON-RPC를 쓰고, stdout에서 JSON-RPC를 읽습니다. 데스크톱 호스트가 사용자 컴퓨터에서 서버를 실행하는 방식이 바로 이것입니다. 호스트는 **곧** 이 코드에 UI를 더한 것이며, **[실제 호스트에 연결하기](../get-started/real-host.md)**는 같은 관계를 호스트 쪽에서 설정 파일로 바라본 것입니다.

`StdioServerParameters`로 프로세스를 기술하고, `stdio_client`로 트랜스포트로 바꾼 다음, **그것**을 `Client`에 넘기세요.

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client`는 매개변수 객체를 단독으로 받지 않습니다. `StdioServerParameters`는 설정이고, `stdio_client(server)`는 그 설정으로 프로세스를 띄우는 방법을 아는 트랜스포트입니다. 항상 감싸서 전달하세요.

`async with` 블록을 벗어나면 서브프로세스도 함께 종료됩니다. stdin을 닫고, 기다리고, 남아 있으면 강제 종료합니다. 직접 정리할 일은 없습니다.

!!! warning
    자식 프로세스는 환경 변수를 상속하지 **않습니다**. 직접 작성하지 않았을 수도 있는 프로세스로
    민감한 정보가 새어 나가지 않도록 최소한의 허용 목록(POSIX에서는 `HOME`, `LOGNAME`, `PATH`,
    `SHELL`, `TERM`, `USER`)만 전달됩니다.

    API 키가 필요한 서버는 거기서 키를 찾지 못합니다. `env=`로 명시적으로 전달하세요. 해당
    변수는 허용 목록 위에 병합됩니다. 위 예제에서 `BOOKSHOP_API_KEY`가 하는 일이 바로 이것입니다.

## SSE {#sse}

`mcp.client.sse`의 `sse_client(url)`은 Streamable HTTP로 대체된 이전 HTTP 트랜스포트입니다. 아직 이 방식을 쓰는 서버와 통신하려면 `Client(sse_client("http://localhost:8000/sse"))`처럼 같은 방식으로 감싸서 사용하되, 새로운 것을 이 위에 만들지는 마세요.

## `Transport` 프로토콜 {#the-transport-protocol}

`Client`에게 위의 모든 것은 같은 것입니다.

**트랜스포트**란 `(read, write)` 메시지 스트림 쌍을 내어주는 비동기 컨텍스트 매니저라면 무엇이든 해당합니다. 정식으로는 `mcp.client`의 `Transport` 프로토콜입니다. `Client`는 인자를 타입으로 구분합니다. 서버 객체는 프로세스 내에서 연결하고, `str`은 `streamable_http_client(url)`이 되며, 그 밖의 것은 트랜스포트로 직접 진입합니다. 마지막 규칙 덕분에 `stdio_client(...)`, `streamable_http_client(...)`, `sse_client(...)`가 모두 같은 자리에 들어가고, 직접 만든 트랜스포트도 쓸 수 있습니다.

## 요약 {#recap}

* `Client(mcp)`(서버 객체)는 인메모리로 연결합니다. 테스트와 임베딩에 사용하세요.
* `Client("http://.../mcp")`(URL)는 프로덕션 트랜스포트인 Streamable HTTP로 연결합니다.
* 헤더, 인증, 프록시, 타임아웃은 `streamable_http_client(url, http_client=...)`에 전달하는 `httpx2.AsyncClient`에 설정합니다. `headers=` 키워드는 없습니다.
* stdio는 `Client(stdio_client(StdioServerParameters(...)))`이며, 매개변수 객체만 단독으로 쓰는 일은 절대 없습니다.
* 서브프로세스는 현재 환경이 아니라 허용 목록에 있는 환경 변수만 받습니다. `env=`로 여기에 추가합니다.
* 트랜스포트는 `async with x as (read, write)`로 쓸 수 있는 것이면 무엇이든 됩니다. `Client`는 서버 객체나 URL이 아닌 것은 모두 그 프로토콜에 그대로 넘깁니다.
* `Client`를 생성하면 트랜스포트가 정해집니다. `async with`가 이를 엽니다.

트랜스포트가 열리면 양쪽은 프로토콜 버전에 합의해야 합니다. 보통은 신경 쓸 일이 없지만, 필요할 때는 **[프로토콜 버전](../protocol-versions.md)** 페이지를 확인하세요.
