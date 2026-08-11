---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# 클라이언트 {#the-client}

**`Client`**는 Python 프로그램이 MCP 서버와 통신하는 수단입니다.

하나의 객체에 하나의 생명 주기가 있습니다. 객체를 만들고, `async with`에 들어가고, 메서드를 호출하면 됩니다. 모든 프로토콜 동작(도구 목록 조회, 도구 호출, 리소스 읽기, 프롬프트 렌더링)은 타입이 지정된 결과를 돌려주는 `async` 메서드로 제공됩니다.

## 첫 번째 클라이언트 {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

맨 위의 서버는 연결할 대상을 마련하기 위해 있을 뿐입니다. 클라이언트는 강조 표시된 다섯 줄입니다.

* `Client(mcp)`에는 **서버 객체 자체**를 넘깁니다. 이것이 인메모리 트랜스포트입니다. 서브프로세스도, 포트도, HTTP도 없습니다. 이 페이지의 모든 예제와 앞으로 작성할 모든 테스트가 이 방식으로 연결합니다.
* `async with`가 **생명 주기**입니다. 들어가면 연결하고 협상하며, 나오면 연결을 끊습니다. `connect()` / `close()` 쌍은 없으며, 블록이 끝난 뒤에는 `Client`를 재사용할 수 없습니다.
* 블록 안에서는 연결 정보가 이미 평범한 프로퍼티로 준비되어 있습니다.

### `Client`에 전달할 수 있는 것 {#what-you-can-pass-to-client}

`Client`는 위치 인자 하나를 받고, 그 타입으로 트랜스포트를 결정합니다.

* `MCPServer`(또는 저수준 `Server`) 인스턴스: **프로세스 내부**에서 연결합니다.
* URL 문자열(`Client("http://localhost:8000/mcp")`): 프로덕션 경로인 Streamable HTTP입니다.
* **트랜스포트**: `async with ... as (read, write)`로 사용할 수 있는 모든 것, 예를 들어 서브프로세스를 감싸는 `stdio_client(...)`입니다.

이 페이지의 나머지 내용은 세 가지 모두에서 동일합니다. 헤더, 서브프로세스, 타임아웃, `Transport` 프로토콜은 별도의 페이지인 **[클라이언트 트랜스포트](transports.md)**에서 다룹니다.

### 연결된 클라이언트에 있는 것 {#whats-on-a-connected-client}

블록에 들어가는 순간 채워지는 읽기 전용 프로퍼티 네 개가 있습니다.

* `client.server_info`: 서버의 신원 정보입니다. 이를 보고하지 않는 2026년 시대의 서버라면 `None`입니다(python-sdk 서버는 기본적으로 보고합니다). 여기서 `server_info.name`은 `"Bookshop"`이고, `server_info.version`은 서버가 보고하는 값입니다.
* `client.server_capabilities`: 서버가 할 수 있는 것(`tools`, `resources`, `prompts`, `completions`, ...)입니다. 서버에 없는 기능은 `None`입니다.
* `client.protocol_version`: 양쪽이 합의한 프로토콜 버전입니다. 여기서는 `"2026-07-28"`입니다.
* `client.instructions`: 서버의 `instructions=` 문자열이며, 설정하지 않았다면 `None`입니다.

프로토콜 버전을 직접 고른 적은 없습니다. 기본적으로 `Client`는 서버를 탐색하고, 오래된 서버에서는 전통적인 핸드셰이크로 대체하므로, 하나의 클라이언트가 어느 시대의 서버와도 동작합니다. 이를 제어해야 할 때 자세한 내용은 **[프로토콜 버전](../protocol-versions.md)**에서 확인하세요.

!!! tip
    `client.session`은 내부의 `ClientSession`으로, 저수준 탈출구입니다.
    이 페이지의 어떤 내용에도 필요하지 않습니다.

## 도구 목록 조회 {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()`는 `ListToolsResult`를 반환하며, 도구는 `.tools`에 들어 있습니다. 각 도구는 호스트가 모델에 건네는 완전한 정의입니다.

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

그리고 `tool.input_schema`는 서버가 함수의 타입 힌트에서 도출한 JSON Schema입니다.

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

이 스키마는 UI가 인자 입력 폼을 렌더링하는 데 필요한 전부이자, 모델이 유효한 인자를 만들어 내는 데 필요한 전부입니다.

!!! tip
    `title`은 선택 사항이므로, 사람에게 도구를 보여 주는 UI는 무엇을 표시할지 골라야 합니다. `title`이 있으면 쓰고,
    없으면 `name`을 씁니다. `from mcp.shared.metadata_utils import get_display_name`이 정확히 그 일을 하며,
    도구, 리소스, 리소스 템플릿, 프롬프트 모두에 쓸 수 있습니다.

## 도구 호출 {#calling-a-tool}

`call_tool(name, arguments)`는 도구를 실행하고 `CallToolResult`를 돌려줍니다.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

서버의 `lookup_book`은 Pydantic `Book`을 반환합니다. 클라이언트가 보는 것은 다음과 같습니다.

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

반환값은 하나이고, 읽을 것은 세 가지입니다. 각각 소비하는 쪽이 다릅니다.

### `content`: 모델이 읽는 것 {#content-what-the-model-reads}

`content`는 **콘텐츠 블록**의 `list`이며, 콘텐츠 블록은 `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink`, `EmbeddedResource`의 유니온입니다. 도구는 서로 다른 종류의 블록을 여러 개 반환할 수 있습니다.

그래서 `main`은 `block.text`를 건드리기 전에 `isinstance(block, TextContent)`로 타입을 좁힙니다. `isinstance` 바깥에는 `.text`가 없다는 점에 주목하세요. `ImageContent`에는 `.text`가 아니라 `.data`가 있기 때문에 타입 검사기가 허용하지 않습니다. 유니온은 도구가 보낼 수 있는 것을 정직하게 드러내며, 코드도 그래야 합니다.

### `structured_content`: 애플리케이션이 읽는 것 {#structured_content-what-your-application-reads}

`structured_content`는 도구의 반환값을 JSON으로 표현한 것으로, 도구가 선언한 `output_schema`와 일치합니다. 문자열 파싱도, 추측도 필요 없습니다.

둘 다 있을 때는 의도적으로 같은 내용을 두 번 말합니다. `content`는 모델을 위한 것이고, `structured_content`는 코드를 위한 것입니다. 구조화된 쪽이 어디서 오고 어떻게 제어하는지는 **[구조화된 출력](../servers/structured-output.md)** 페이지에서 다룹니다.

### `is_error`: 도구의 실패 여부 {#is_error-whether-the-tool-failed}

예외를 발생시키는 도구라도 클라이언트에서 예외를 발생시키지 **않습니다**. `is_error=True`인 평범한 결과로 돌아옵니다.

!!! check
    `lookup_book`에 `"Solaris"`(카탈로그에 없는 제목)를 요청하면 함수가
    `ValueError`를 발생시킵니다. 그래도 호출은 정상적으로 반환됩니다.

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    예외 메시지는 **모델**이 읽고 다시 시도할 수 있는 `content`에 담겼습니다. 이는
    의도된 것입니다. 도구 오류는 충돌이 아니라 대화의 일부입니다. `structured_content`를
    믿기 전에 항상 `is_error`를 확인하세요.

!!! warning
    `is_error=True`는 직접 작성한 `raise`보다 더 많은 경우를 포괄합니다. 서버에 아예 없는 도구를 요청해도
    (`call_tool("does_not_exist", {})`) 아무 예외도 발생하지 않습니다. 같은 형태로,
    `content`에 `Unknown tool: does_not_exist`가 담긴 `is_error=True`가 돌아옵니다. `Client` 메서드는
    서버가 결과 대신 JSON-RPC **오류**로 응답할 때만 `MCPError`를 발생시키며,
    서버가 언제 어느 쪽을 내보내는지는 **[오류 처리](../servers/handling-errors.md)**에서 다룹니다.

## 리소스 {#resources}

리소스 동작은 짝을 이룹니다. 목록을 조회하는 방법이 둘, 읽는 방법이 하나입니다.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()`는 **구체적인** 리소스, 즉 URI가 고정된 리소스를 반환합니다. 여기서는 `['catalog://genres']`입니다.
* `list_resource_templates()`는 **매개변수화된** 리소스를 반환합니다. 여기서는 `['catalog://genres/{genre}']`입니다. 템플릿은 값을 채우기 전에는 읽을 수 없으므로 두 목록은 서로 다릅니다.
* `read_resource(uri)`는 평범한 `str` URI를 받으며 둘 다에 동작합니다. `"catalog://genres/poetry"`를 전달하면 서버가 템플릿에 매칭합니다.

`read_resource`는 `TextResourceContents` 또는 `BlobResourceContents`의 리스트인 `contents`를 반환합니다. 도구 콘텐츠와 같은 방식입니다. `isinstance`로 좁힌 다음 `.text`(또는 `.blob`)를 읽으세요.

클라이언트는 리소스가 변경될 때 알림을 받을 수도 있습니다. 2025년 시대의 연결에서는 `subscribe_resource(uri)` / `unsubscribe_resource(uri)`이며, `MCPServer`가 구현하지 않는 메서드 쌍이므로 2026-07-28 와이어(이 동작이 더 이상 존재하지 않는)에서는 요청이 `-32601`, *Method not found*로 응답합니다. 2026년의 대체 수단은 `subscriptions/listen` 스트림으로, `MCPServer`가 **실제로** 제공합니다(여기서 `server_capabilities.resources.subscribe`는 `True`입니다). 이를 `client.listen(...)`으로 소비하는 방법은 이 섹션의 **[구독](subscriptions.md)** 페이지에서 다룹니다.

## 프롬프트 {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()`는 서버가 무엇을 제공하는지, 각 프롬프트에 무엇이 필요한지 알려 줍니다.

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)`가 프롬프트를 렌더링합니다. 인자 딕셔너리는 `str -> str`입니다. 프롬프트 인자는 항상 문자열입니다. 결과는 `PromptMessage`의 리스트인 `messages`이며, 각 메시지에는 `role`과 `content` 블록이 있습니다.

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

호스트는 이 메시지를 곧바로 모델에 건넵니다. 이 기능은 이것이 전부입니다.

## 자동 완성 {#completions}

자동 완성 핸들러가 있는 서버는 사용자가 입력하는 동안 프롬프트와 리소스 템플릿 인자를 자동 완성할 수 있습니다.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref`는 **어느** 프롬프트 또는 템플릿을 채우고 있는지 지정합니다. `PromptReference` 또는 `ResourceTemplateReference`입니다.
* `argument`는 `{"name": ..., "value": ...}`로, 인자와 사용자가 지금까지 입력한 값입니다.

답은 `result.completion.values`에 있습니다. `"p"`를 입력하면 서버가 `['poetry']`를 돌려줍니다. 서버 쪽 구현과, 핸들러가 이미 채워진 **다른** 인자를 사용해 제안을 좁히는 방법은 **[자동 완성](../servers/completions.md)** 페이지에서 다룹니다.

## 페이지네이션 {#pagination}

모든 `list_*` 메서드는 `cursor=` 키워드를 받고, 모든 결과에는 `next_cursor`가 있습니다. `next_cursor`가 `None`이면 전부 받은 것입니다.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

이 루프는 어떤 서버에 대해서도 올바릅니다. `MCPServer`는 모든 것을 한 페이지에 반환하므로 `next_cursor`는 `None`이고 루프는 한 번만 돌며, 그래서 대부분의 코드는 이 루프를 작성하지 않습니다. 실제로 페이지를 나누는 서버와 커서가 따르는 규칙은 **[페이지네이션](../advanced/pagination.md)**에서 다룹니다.

## 테스트에서 {#in-tests}

프로세스도 포트도 없는 `Client(mcp)`는 그 자체로 이미 서버의 테스트 하네스입니다.

이를 위해 만들어진 생성자 플래그가 하나 있습니다. `Client(mcp, raise_exceptions=True)`입니다. 인메모리 연결에서만 효과가 있으며, 이를 설명하고 전체 패턴을 구축하는 페이지는 **[테스트](../get-started/testing.md)**입니다.

## 요약 {#recap}

* `Client(x)`는 서버 객체에는 인메모리로, URL 문자열에는 Streamable HTTP로, 그 밖의 것에는 트랜스포트를 통해 연결합니다.
* `async with`가 생명 주기의 전부입니다. 그 안에서는 `server_capabilities`와 `protocol_version`이 이미 채워져 있으며, 서버가 제공하는 경우 `server_info`와 `instructions`도 마찬가지입니다.
* `list_tools()`는 각 도구의 `name`, `title`, `description`, `input_schema`를 제공합니다.
* `call_tool()`은 모델을 위한 `content`, 코드를 위한 `structured_content`, 그리고 `is_error`를 반환합니다. 예외를 발생시키는 도구는 예외가 아니라 결과입니다.
* `content`는 블록 타입의 유니온입니다. 읽기 전에 `isinstance`로 좁히세요.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt`, `complete`가 나머지 동작을 이룹니다.
* 모든 `list_*`는 `cursor=`를 받습니다. `next_cursor`가 `None`이 될 때까지 루프를 도세요.

서버가 **클라이언트**에 요청할 수 있는 것과 이에 응답하는 방법은 **[클라이언트 콜백](callbacks.md)**에서 다룹니다.
