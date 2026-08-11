---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# 페이지네이션 {#pagination}

대부분의 서버에는 필요 없는 기능입니다.

`MCPServer`는 모든 `list_*` 요청에 가진 것을 전부 한 페이지에 담아 `next_cursor=None`으로 응답합니다. 도구, 리소스, 프롬프트가 수십 개 정도라면 이것이 올바른 동작이며, 설정할 것은 아무것도 없습니다.

페이지네이션은 리소스 목록이 사실상 데이터베이스인 서버를 위한 것입니다. 한 번의 응답으로 직렬화하기에는 무리인 수천 개의 행이 있는 경우입니다. 프로토콜의 해법은 **커서**입니다. 서버는 페이지 하나와 불투명한 토큰을 함께 반환하고, 클라이언트는 그 토큰을 다시 보내 다음 페이지를 받습니다.

`@mcp.resource()`에는 이를 위한 훅이 없습니다. 페이지를 나누려면 **[저수준 Server](low-level-server.md)**에서 목록 핸들러를 직접 작성해야 합니다.

## 페이지를 나누는 서버 {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* 저수준 `Server`에서 핸들러는 데코레이터가 아니라 생성자 인자입니다. `on_list_resources`가 모든 `resources/list` 요청에 응답하며, 연결 작업은 이것이 전부입니다.
* 페이지를 나누는 핸들러는 모두 `params: PaginatedRequestParams | None` 타입을 받으며, 예제는 두 경우를 모두 처리합니다. 다만 실제 연결에서는 SDK가 `None`을 넘기는 일이 없습니다(`params` 멤버가 없는 요청은 기본값이 채워진 모델로 핸들러에 도달합니다). 따라서 의미 있는 신호는 `params.cursor is None`이며, 이는 **처음부터 시작하라**는 뜻입니다.
* 커서가 **무엇인지**는 직접 정합니다. 여기서는 문자열로 표현한 오프셋입니다. 타임스탬프, 기본 키, base64 덩어리 등 내보낼 때 만들어 낼 수 있고 돌아왔을 때 알아볼 수 있는 것이면 무엇이든 됩니다.
* `next_cursor=None`은 "이것이 마지막 페이지였다"고 알리는 방법입니다. 개수도, 총계도, `has_more`도 없습니다. `None`이 신호의 전부입니다.

!!! tip
    `PAGE_SIZE`를 10으로 둔 것은 예제를 읽기 쉽게 하기 위해서입니다. 실제 값은 엔드포인트마다 정하세요.
    한 줄짜리 리소스 목록이라면 500개 페이지도 감당할 수 있지만, 덩치 큰 프롬프트 템플릿 목록은 그럴 수 없습니다.
    클라이언트는 여기에 관여할 수 없으며, 이는 의도된 설계입니다.

### 직접 해 보기 {#try-it}

`Client(server)`는 `MCPServer`에 연결할 때와 똑같이 저수준 `Server`에 인메모리로 연결합니다.

인자 없이 `list_resources()`를 호출하세요. `book-1`부터 `book-10`까지 리소스 10개가 돌아오고, `next_cursor`는 문자열 `"10"`입니다.

이를 `list_resources(cursor="10")`으로 다시 넘기면 첫 번째 리소스는 `book-11`이고, 새 `next_cursor`는 `"20"`입니다.

열 번째 페이지는 `next_cursor`가 `None`으로 설정되어 돌아옵니다. 끝입니다.

## 클라이언트 루프 {#the-client-loop}

`Client`의 모든 `list_*` 메서드(`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`)는 `cursor=` 키워드를 받습니다. 페이지로 나뉜 목록을 전부 가져오는 것은 `while True` 하나면 됩니다.

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor`는 `None`으로 시작하므로 첫 요청에는 커서가 실리지 않습니다.
* `next_cursor`를 확인하기 **전에** 결과를 덧붙이세요. 마지막 페이지에도 리소스가 있습니다.
* `next_cursor is None`이 종료 조건입니다. 그 외의 값은 손대지 않고 그대로 `cursor=`에 다시 넣습니다.

이 파일의 `main()`을 실행하면 `100 resources`가 출력됩니다. 열 개씩 열 페이지가, 페이지가 열 개라는 사실조차 모르는 루프에 의해 하나로 이어 붙여진 결과입니다.

이 루프는 **[클라이언트](../client/index.md)**에서 모든 `list_*` 동사에 대해 보여 주는 것과 같은 루프이며, 페이지를 나누지 않는 서버에 대해서도 비용이 들지 않습니다. 첫 응답에서 `next_cursor`가 `None`이므로 루프는 한 번만 돕니다.

## 세 가지 규칙 {#the-three-rules}

**커서는 불투명합니다.** 클라이언트는 커서를 파싱하거나, 만들거나, 추측해서는 안 됩니다. 커서를 얻는 유일하게 정당한 출처는 이전 페이지의 `next_cursor`를 그대로 쓰는 것입니다.

**페이지 크기는 서버가 정합니다.** 프로토콜에 `limit=`은 없습니다. 다른 페이지 크기가 필요하면 서버를 바꿔야 합니다.

**페이징을 무시하는 클라이언트도 여전히 동작합니다.** `list_resources()`를 한 번 호출하고, 처음 열 개를 받고, 버린 `next_cursor`는 알아채지 못합니다. 아무것도 깨지지 않습니다. 덜 보일 뿐입니다.

!!! check
    불투명하다는 것은 말 그대로 불투명하다는 뜻입니다. 커서를 지어내면(`list_resources(cursor="page-2")`)
    프로토콜이 해 줄 수 있는 것은 아무것도 없습니다. 이 서버는 `int("page-2")`를 시도하고, 핸들러는 예외를
    일으키며, 클라이언트에게 돌아오는 것은 다음과 같습니다.

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    서버에서 받지 않은 커서는 기능 요청이 아니라 버그입니다.

## 요약 {#recap}

* `MCPServer`는 모든 것을 한 페이지로 반환합니다. 페이지네이션은 선택 사항이며, 저수준 `Server`에서 선택합니다.
* `on_list_resources`(그리고 `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`)는 `PaginatedRequestParams | None`을 받으며, 첫 페이지에서는 `params.cursor`가 `None`입니다.
* 페이지와 함께 `next_cursor`를 반환합니다. 나중에 알아볼 수 있는 문자열이면 무엇이든 되고, 남은 것이 없으면 `None`입니다.
* 클라이언트 루프는 `cursor=`를 전달하고, 누적하고, `next_cursor is None`이 될 때까지 반복합니다.
* 커서는 불투명하고, 페이지 크기는 서버가 정하며, 페이징을 하지 않는 클라이언트도 첫 페이지는 받습니다.

직접 작성하는 `Server` API의 나머지(`on_call_tool`, `input_schema` 딕셔너리, `_meta`)는 **[저수준 Server](low-level-server.md)**에서 확인하세요.
