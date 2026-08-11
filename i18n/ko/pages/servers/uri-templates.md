---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# URI 템플릿과 경로 안전성 {#uri-templates-and-path-safety}

이 페이지는 [`@mcp.resource`](resources.md)가 받아들이는 URI 템플릿 문법과, 추출된 값에 SDK가 적용하는 경로 안전성 정책을 다루는 레퍼런스입니다. 리소스가 무엇이고 언제 사용하는지에 관한 소개는 **[리소스](resources.md)**에서 먼저 살펴보세요. 이 페이지는 리소스를 선언하는 데 이미 익숙하고, 전체 연산자 집합이나 보안 설정, 저수준 연결 방법을 알고 싶은 경우를 가정합니다.

템플릿 문법은 [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)을 따릅니다. SDK는 들어오는 `resources/read` URI를 매칭하기 위해 선택한 부분 집합을 지원하며, 여기에 더해 서비스하려는 디렉터리 바깥으로 해석될 수 있는 값을 거부하는 보안 계층을 제공합니다. 프로토콜 수준의 세부 사항(메시지 형식, 생명 주기, 페이지네이션)은 [MCP 리소스 명세](https://modelcontextprotocol.io/specification/latest/server/resources)를 참고하세요.

## 전체 연산자 집합 {#the-full-operator-set}

단순 플레이스홀더인 `{user_id}`는 **[리소스](resources.md)**에서 소개한 형태입니다. 연산자 형태는 네 가지가 더 있으며, 나란히 비교할 수 있도록 하나의 서버에 모아 두었습니다.

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

강조 표시된 데코레이터는 각각 URI를 다른 방식으로 분해합니다. 아래 섹션에서 위에서부터 차례로 살펴봅니다.

### 단순 확장: `{name}` {#simple-expansion-name}

`books://{isbn}`은 평범하고 일상적인 형태입니다. 플레이스홀더는 `isbn` 매개변수에 대응하므로, 클라이언트가 `books://978-0441172719`를 읽으면 `get_book("978-0441172719")`이 호출됩니다.

단순한 `{name}`은 첫 번째 `/`에서 멈춥니다. `books://978/extra`는 매칭되지 않습니다. `978` 뒤의 슬래시에서 캡처가 끝나고 `/extra`가 남기 때문입니다.

### 타입 변환 {#type-conversion}

추출된 값은 문자열로 들어오지만, 더 구체적인 타입을 선언하면 SDK가 변환합니다. `orders://{order_id}`는 매개변수가 `order_id: int`인 함수로 전달되므로, `orders://12345`를 읽으면 `get_order("12345")`가 아니라 `get_order(12345)`가 호출됩니다. 핸들러는 형 변환 없이 바로 산술 연산(`order_id + 1`)을 수행합니다.

### 여러 세그먼트에 걸친 경로: `{+name}` {#multi-segment-paths-name}

슬래시가 포함된 값을 캡처하려면 `{+name}`을 사용하세요. `manuals://{+path}`의 경우 다음과 같습니다.

* `manuals://returns.md`는 `path = "returns.md"`를 줍니다.
* `manuals://printing/setup.md`는 `path = "printing/setup.md"`를 줍니다.

값이 계층 구조를 가질 때는 언제든 `{+name}`을 사용하세요. 파일시스템 경로, 중첩된 객체 키, 프록시하는 URL 경로가 여기에 해당합니다.

### 쿼리 매개변수: `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}`는 `limit`과 `sort`를 `?` 뒤에 둡니다. 경로는 **어떤** 책인지를 식별하고, 쿼리는 **어떻게** 읽을지를 조정합니다.

쿼리 매개변수는 느슨하게 매칭됩니다. 순서는 상관없고, 추가된 항목은 무시되며, 생략된 매개변수는 함수의 기본값으로 처리됩니다. 따라서 `reviews://978-0441172719`는 `limit=10, sort="newest"`를 사용하고, `reviews://978-0441172719?sort=top`은 `sort`만 덮어씁니다.

### 경로 세그먼트를 리스트로: `{/name*}` {#path-segments-as-a-list-name}

각 경로 세그먼트를 슬래시가 포함된 하나의 문자열이 아니라 별개의 리스트 항목으로 받고 싶다면 `{/name*}`을 사용하세요. `shelves://browse{/path*}`의 경우, 클라이언트가 `shelves://browse/fiction/sci-fi`를 읽으면 `browse_shelf(["fiction", "sci-fi"])`가 호출됩니다.

### 템플릿 레퍼런스 {#template-reference}

가장 흔한 패턴은 다음과 같습니다.

| 패턴         | 예시 입력             | 얻는 값                 |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | **매칭 안 됨**(`/`에서 멈춤) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### 파서가 거부하는 것 {#what-the-parser-rejects}

몇 가지 템플릿 형태는 첫 요청에서 실패하는 대신 미리 잡아냅니다. `@mcp.resource`는 데코레이터가 실행될 때 템플릿을 파싱하므로, 아래 경우는 실행 중인 서버에 도달하지 않습니다.

`UriTemplate.parse()`는 다음 경우에 `InvalidUriTemplate`을 발생시킵니다.

* **두 변수 사이에 아무것도 없는 경우.** `manuals://{+path}{ext}`는 거부됩니다. 매칭 과정에서 `path`가 어디서 끝나고 `ext`가 어디서 시작하는지 알 수 없기 때문입니다. 사이에 리터럴을 두거나(`manuals://{+path}/{ext}`), 자체 구분자를 제공하는 연산자를 사용하세요. `manuals://{+path}{.ext}`는 `{.ext}`가 직접 `.`을 제공하므로 허용됩니다.
* **여러 세그먼트에 걸친 변수가 둘 이상인 경우.** 템플릿 하나에 `{+var}`, `{#var}`, 또는 전개 변수(`{/var*}`, `{.var*}`, `{;var*}`)는 최대 하나만 허용됩니다. 둘이면 본질적으로 모호합니다. 어느 쪽이 추가 세그먼트를 흡수해야 하는지 결정할 원칙적인 방법이 없습니다.
* **일반적인 문법 오류.** 닫히지 않은 중괄호, 두 번 사용된 변수 이름, 또는 `{var:3}` 접두사 수정자나 `{?vars*}` 쿼리 전개처럼 SDK가 지원하지 않는 RFC 6570 기능이 여기에 해당합니다.

이에 더해 `@mcp.resource`는 핸들러 매개변수가 템플릿 끝의 `{?...}`/`{&...}` 구간에 있는 쿼리 변수에 바인딩되어 있으면서 Python 기본값이 없는 경우 `ValueError`를 발생시킵니다. 이 변수들은 느슨하게 매칭되므로(클라이언트가 어느 것이든 생략할 수 있습니다), 기본값이 없는 매개변수는 이를 생략한 첫 요청에서 불투명한 내부 오류로만 드러나게 됩니다. 위 서버의 `reviews://{isbn}{?limit,sort}`는 올바른 형태입니다. `limit`과 `sort` 모두 기본값을 갖고 있습니다.

## 보안 {#security}

템플릿 매개변수는 클라이언트에서 옵니다. 이 값이 검증 없이 파일시스템이나 데이터베이스 연산으로 흘러가면, `../../etc/passwd` 같은 값이 서비스하려던 디렉터리 바깥으로 해석될 수 있습니다.

### SDK가 기본으로 검사하는 것 {#what-the-sdk-checks-by-default}

핸들러가 실행되기 전에 SDK는 다음에 해당하는 매개변수를 거부합니다.

* `..` 구성 요소를 통해 시작 디렉터리를 벗어나는 경우
* 절대 경로(`/etc/passwd`, `C:\Windows`)나 Windows 드라이브 상대 경로(`C:foo`)처럼 보이는 경우. 드라이브 상대 경로 값과 `x:y` 같은 네임스페이스 식별자는 문자열로는 구별할 수 없으므로, 한 글자 뒤에 콜론이 오는 값은 기본적으로 모두 거부됩니다. 그런 값을 정당하게 받는 매개변수라면 검사에서 제외하세요.
* 널 바이트(`\x00`)를 포함하는 경우

`..` 검사는 부분 문자열 스캔이 아니라 구성 요소 기반입니다. `v1.0..v2.0`이나 `HEAD~3..HEAD` 같은 값은 `..`가 독립된 경로 세그먼트가 아니므로 통과합니다.

이 검사는 디코딩된 값에 적용되므로, URI에서 어떻게 인코딩되었든 경로 탐색 시도를 잡아냅니다(`../etc`, `..%2Fetc`, `%2E%2E/etc`, `..%5Cetc`, `%00` 모두 잡힙니다).

!!! check
    위 서버에서 `manuals://../etc/passwd`를 읽으면 요청은 즉시 거부됩니다. 템플릿 매칭은 첫 번째 실패에서 멈추므로, 이후의(더 관대할 수도 있는) 템플릿을 대체 수단으로 시도하지 않습니다. 클라이언트는 어떤 템플릿에도 매칭되지 않는 URI와 동일한 `-32602` "Unknown resource" 오류를 받고, `read_manual`은 실행되지 않습니다.

### 파일시스템 핸들러: safe_join 사용 {#filesystem-handlers-use-safe_join}

내장 검사는 흔한 경우를 막아 주지만 샌드박스 경계까지는 알 수 없습니다. 파일시스템에 접근할 때는 `safe_join`으로 경로를 해석하고 기준 디렉터리 안에 머무르는지 확인하세요.

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join`은 단순 문자열 검사로는 놓칠 수 있는 심볼릭 링크 탈출, `..` 시퀀스, 절대 경로 트릭을 잡아냅니다. 해석된 경로가 `DOCS_ROOT`를 벗어나면 `PathEscapeError`를 발생시키고, 이는 클라이언트에 `ResourceError`로 전달됩니다.

### 기본값이 방해가 될 때 {#when-the-defaults-get-in-the-way}

검사가 정당한 값을 막는 경우도 있습니다. 카탈로그 가져오기 도구는 의도적으로 절대 경로를 받을 수 있고, 어떤 매개변수는 핸들러가 파일시스템을 건드리지 않고 안전하게 해석하는 `../sibling` 같은 상대 참조일 수 있습니다. 해당 매개변수를 검사에서 제외하거나, 서버 전체의 정책을 완화하세요.

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* 데코레이터의 `security=ResourceSecurity(exempt_params={"source"})`는 해당 리소스의 해당 매개변수 하나에 대해서만 검사를 건너뜁니다. 서버의 나머지 부분은 기본 정책을 유지합니다.
* `MCPServer` 생성자의 `resource_security=`는 모든 리소스의 기본값을 설정합니다. 여기서 `relaxed`는 `..` 검사를 완전히 끕니다.

설정 가능한 검사는 다음과 같습니다.

| 설정                    | 기본값  | 동작                                |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | 시작 디렉터리를 벗어나는 `..` 시퀀스를 거부합니다 |
| `reject_absolute_paths` | `True`  | `/foo`, `C:\foo`, UNC 경로, 드라이브 상대 경로 `C:foo`를 거부합니다(`x:y`도 잡힙니다) |
| `reject_null_bytes`     | `True`  | `\x00`을 포함하는 값을 거부합니다   |
| `exempt_params`         | 비어 있음 | 검사를 건너뛸 매개변수 이름        |

이 검사는 휴리스틱 사전 필터입니다. 파일시스템 접근에서는 `safe_join`이 여전히 격리 경계입니다.

!!! tip
    핸들러가 요청을 처리할 수 없다면(파일이 없거나, id를 알 수 없는 경우) 예외를 발생시키세요. SDK가 이를 오류 응답으로 바꿉니다. 프로토콜 오류와 도구 오류의 차이는 **[오류 처리](handling-errors.md)**에서 확인하세요.

## 저수준 Server의 리소스 {#resources-on-the-low-level-server}

저수준 `Server` 위에서 구축하는 경우(**[저수준 Server](../advanced/low-level-server.md)** 참고), `resources/list`와 `resources/read` 프로토콜 메서드의 핸들러를 직접 등록합니다. 데코레이터는 없으며, 프로토콜 타입을 직접 반환합니다.

### 정적 리소스 {#static-resources}

고정 URI의 경우 레지스트리를 두고 정확히 일치하는지에 따라 분기하세요.

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

list 핸들러는 클라이언트에게 사용 가능한 것을 알려 주고, read 핸들러는 콘텐츠를 제공합니다. 먼저 레지스트리를 확인하고, 템플릿이 있다면 템플릿(아래)으로 넘기고, 그 외에는 예외를 발생시키세요.

### 템플릿 {#templates}

`MCPServer`가 사용하는 템플릿 엔진은 `mcp.shared.uri_template`에 있으며 독립적으로 동작합니다. 동일한 파싱과 매칭을 얻되, 라우팅과 보안 정책은 직접 연결합니다.

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

강조 표시된 줄에서는 세 가지 일이 일어납니다.

* **한 번 파싱하고, 요청마다 매칭합니다.** `UriTemplate.parse()`가 템플릿을 만들고, `template.match(uri)`는 추출된 변수를 `dict`로 반환하거나 URI가 맞지 않으면 `None`을 반환합니다. URL 디코딩은 `match()` 안에서 일어나며, 디코딩된 값은 경로 안전성 검증 없이 그대로 반환됩니다. 값은 문자열로 나오므로 직접 변환하세요(`int(matched["id"])`, `Path(matched["path"])`).
* **안전성 검사를 직접 적용합니다.** `MCPServer`가 기본으로 실행하는 `..` 검사와 절대 경로 검사는 `mcp.shared.path_security`에 있습니다. `read_manual_safely`는 `MANUALS`를 건드리기 전에 이를 호출합니다. 매개변수가 파일시스템 경로가 아니라면(ISBN, 검색 쿼리 등) 해당 값의 검사는 건너뛰세요. 정책은 설정 객체가 아니라 핸들러마다 직접 제어합니다.
* **같은 출처에서 템플릿을 나열합니다.** 클라이언트는 `resources/templates/list`를 통해 템플릿을 발견합니다. `str(template)`은 원래 템플릿 문자열을 돌려주므로, 목록과 매처가 하나의 단일 출처를 공유합니다.

## 요약 {#recap}

* `{name}`은 세그먼트 하나를 매칭하고, `{+name}`은 슬래시를 유지하며, `{?a,b}`는 쿼리 문자열에서 값을 가져오고, `{/name*}`은 세그먼트를 리스트로 나눕니다.
* 사이에 아무것도 없는 두 변수, 또는 여러 세그먼트에 걸친 두 번째 변수는 파싱 시점에 거부됩니다. 끝의 `{?...}`/`{&...}` 쿼리 변수에 바인딩된 매개변수는 Python 기본값을 선언해야 합니다.
* 매개변수에 타입을 표기하면(`order_id: int`) SDK가 변환합니다.
* 기본 보안 정책은 핸들러가 실행되기 전에 `..`, 절대 경로, 널 바이트를 거부합니다. 리소스별로는 `security=ResourceSecurity(...)`로, 서버 전체로는 `resource_security=`로 재정의하세요.
* 파일시스템 접근에서는 `safe_join`이 격리 경계입니다.
* 저수준 `Server`에서는 `UriTemplate.parse()`로 파싱하고, `.match()`로 매칭하며, `mcp.shared.path_security`를 직접 적용하세요.
