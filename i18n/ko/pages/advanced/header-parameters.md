---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# 헤더 매개변수 {#header-parameters}

대부분의 서버에는 필요 없는 내용입니다.

서버 앞에 놓인 게이트웨이나 로드 밸런서는 본문을 파싱하지 않고 읽을 수 있는 정보만으로 라우팅할 수 있습니다. 도구 인수에 `x-mcp-header`를 표시하면 `2026-07-28` **[프로토콜 버전](../protocol-versions.md)**을 사용하는 클라이언트가 그 값을 HTTP 헤더로도 보냅니다.

## 인수 표시하기 {#mark-an-argument}

표시는 인수의 JSON Schema에 추가하는 키 하나입니다. `MCPServer`에서는 `Field`가 이 키를 넣어 줍니다.

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* `2026-07-28` 버전의 Streamable HTTP에서는 클라이언트가 본문과 함께 `Mcp-Param-Region` 헤더를 보내며, 서버는 둘이 일치하지 않는 호출을 거부합니다.
* 도구 목록을 조회하지 않은 클라이언트는 표시를 본 적이 없으므로 헤더를 보내지 않고, 호출은 거부됩니다. 이 SDK의 `Client`는 이때 도구 목록을 조회한 뒤 호출을 한 번 다시 보내므로, 목록을 먼저 조회해도 왕복 한 번을 아낄 뿐입니다.
* 그 밖의 모든 연결은 이 애너테이션을 무시합니다.

함수는 바뀌지 않습니다. `region`은 여전히 인수로 전달됩니다.

## 표시할 수 있는 대상 {#what-can-be-marked}

`str`, `int`, `bool` 인수입니다. 그 밖의 타입은 도구를 등록할 때 `InvalidSignature`로 거부됩니다.

단일 타입이 없는 `str | None`도 여기에 포함됩니다. 선택적 인수는 Pydantic의 `WithJsonSchema`로 스키마를 직접 명시해야 합니다.

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## 저수준 `Server`에서 {#on-the-low-level-server}

여기서는 `input_schema`를 직접 작성하므로 키를 그대로 넣으면 됩니다.

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* 애너테이션을 대신 검사해 주는 것은 없습니다. 잘못된 애너테이션도 그대로 제공되며, `2026-07-28` 클라이언트는 해당 도구를 목록에서 제외합니다.

### 이름으로 찾는 스키마 {#schemas-by-name}

헤더를 검사하려면 SDK는 호출을 디스패치하기 전에 도구의 입력 스키마가 필요합니다. `get_tool_input_schema`가 없으면 SDK는 표시된 도구가 있든 없든 인수가 있는 모든 호출마다 `on_list_tools` 핸들러를 실행해 스키마를 얻습니다.

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* 이미 가지고 있는 정보로 응답하도록 이 함수를 전달하세요.
* 검사할 것이 없는 도구에는 `None`을 반환하세요.

## 요약 {#recap}

* 도구 인수에 `x-mcp-header`를 표시하면 `2026-07-28` 클라이언트가 그 인수를 `Mcp-Param-*` HTTP 헤더로도 한 번 더 보냅니다.
* 서버는 헤더와 본문이 일치하지 않는 호출을 거부합니다.
* `str`, `int`, `bool` 인수만 표시할 수 있습니다. 그 밖의 경우 `MCPServer`는 `InvalidSignature`를 발생시킵니다.
* 저수준 `Server`는 아무것도 검사하지 않으며, 클라이언트는 애너테이션이 잘못된 도구를 목록에서 제외합니다.
* `get_tool_input_schema`가 있으면 저수준 `Server`가 호출마다 `on_list_tools`를 실행하지 않습니다.

직접 작성하는 `Server` API의 나머지 내용은 **[저수준 Server](low-level-server.md)**에서 다룹니다.
