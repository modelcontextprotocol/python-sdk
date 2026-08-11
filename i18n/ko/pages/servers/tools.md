---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# 도구 {#tools}

**도구**는 모델이 호출할 수 있는 함수입니다.

평범한 Python 함수에 `@mcp.tool()` 데코레이터를 붙여 선언합니다. 이것이 API의 전부입니다.

## 첫 번째 도구 {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

방금 작성한 코드를 살펴보세요. 스키마도, JSON도, 프로토콜도 없고 함수 하나만 있습니다. SDK는 이 함수에서 세 가지를 읽어 냅니다.

* 도구의 **이름**은 함수의 이름, 즉 `search_books`입니다.
* 모델이 보는 **설명**은 독스트링, 즉 `Search the catalog by title or author.`입니다.
* 모델이 넘길 수 있는 **인자**는 타입 힌트인 `query: str`, `limit: int`에서 나옵니다.

### 입력 스키마 {#the-input-schema}

SDK는 이 타입 힌트로부터 JSON Schema를 생성해 `tools/list` 과정에서 클라이언트에 보냅니다.

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

두 인자 모두 기본값이 없으므로 `required`에 들어 있습니다. 이 부분은 곧 고칩니다. (`title` 키는 Pydantic이 만들어 내는 부산물입니다. 계약에 해당하는 것은 속성과 그 타입, 그리고 `required`입니다.)

!!! tip
    여기서 타입 힌트는 문서가 아닙니다. 타입 힌트가 바로 **계약**입니다. 클라이언트가 `"limit": "ten"`을 보내면
    함수가 실행되기도 전에 SDK가 거부합니다.

### 모델이 돌려받는 것 {#what-the-model-gets-back}

`{"query": "dune", "limit": 5}`로 도구를 호출하면 결과는 두 부분으로 이루어집니다.

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content`는 **모델**이 읽는 텍스트입니다. `structured_content`는 **클라이언트 애플리케이션**을 위한 타입이 지정된 데이터입니다. 이 값이 들어 있는 이유는 반환 타입을 `-> str`로 선언했기 때문입니다.

`structured_content`는 아직 신경 쓰지 않아도 됩니다. 도구에서 실제 Python 객체를 반환하기만 하면 알맞게 처리됩니다. 이 주제는 **[구조화된 출력](structured-output.md)** 페이지에서 자세히 다룹니다.

### 직접 해 보기 {#try-it}

MCP Inspector로 서버를 실행하세요.

```console
uv run mcp dev server.py
```

출력된 URL을 열고 **Tools** 탭으로 가서 `search_books`를 호출하세요.

Inspector는 필수 항목인 `query` 텍스트 필드와 필수 항목인 `limit` 숫자 필드로 이루어진 폼을 그려 줍니다. 이 폼은 타입 힌트를 보고 만든 것입니다. 다른 모든 MCP 클라이언트도 똑같이 합니다.

## 선택적 인자 {#optional-arguments}

매개변수에 기본값을 주면 더 이상 필수가 아니게 됩니다. 이게 전부입니다. 평범한 Python일 뿐입니다.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

스키마도 그에 맞게 바뀝니다.

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

`limit`은 `required`에서 빠지고 `"default": 10`이 생겼습니다. 이 인자를 생략한 클라이언트는 Python에서 그렇듯 `10`을 받습니다.

## `Field`로 더 풍부한 스키마 만들기 {#richer-schemas-with-field}

타입 힌트만으로도 꽤 많은 것을 할 수 있지만, 때로는 인자를 **설명**하거나 제약하고 싶을 때가 있습니다.

타입을 `Annotated`로 감싸고 Pydantic `Field`를 추가하세요.

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

새로 등장한 것은 세 가지이고, 모두 매개변수에 붙습니다.

* `Field(description=...)`: 모델이 독스트링과 함께 읽는 인자별 설명입니다.
* `Field(ge=1, le=50)`: 숫자 범위입니다. 스키마에는 `"minimum": 1, "maximum": 50`으로 들어갑니다.
* `Literal["fiction", "non-fiction", "poetry"]`: 열거형입니다. 모델은 이 중 하나만 고를 수 있습니다.

!!! check
    제약 조건은 장식이 아닙니다. `limit=999`로 도구를 호출하면 SDK는 **함수가 실행되기 전에**
    도구 오류로 응답합니다.

    ```text
    Input should be less than or equal to 50
    ```

    이 오류는 도구 결과로 모델에게 돌아가고, 모델은 오류를 읽은 뒤 유효한 값으로 다시 시도합니다.
    `le=50`을 한 번 적었을 뿐인데 스스로 교정하는 에이전트를 덤으로 얻은 셈입니다.

!!! info
    FastAPI나 Pydantic을 써 본 적이 있다면 이미 전부 아는 내용입니다. 같은 `Field`, 같은 `Annotated`,
    같은 검증입니다. MCP에만 해당하는 새로 배울 내용은 없습니다.

## 매개변수로 모델 받기 {#a-model-as-a-parameter}

도구가 받는 인자가 두어 개를 넘어가면 Pydantic 모델 하나로 묶으세요.

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

`Book` 스키마는 도구의 입력 스키마 안에 `$defs` 참조로 중첩되고, 모델은 그 자리를 JSON 객체로 채우며, 함수는 이미 검증이 끝난 **진짜 `Book` 인스턴스**를 받습니다. 이 인스턴스에는 `.title`, `.author`, `.year` 속성이 있습니다.

조합은 자유롭습니다. 일반 매개변수 옆에 모델 매개변수를 두어도 되고, 모델을 중첩하거나 모델의 리스트를 받아도 됩니다. 처음부터 끝까지 전부 Pydantic입니다.

## `async def` {#async-def}

도구가 I/O를 한다면(API를 호출하거나, 파일을 읽거나, 데이터베이스를 조회한다면) `async def`로 선언하고 그 안에서 `await`를 쓰세요. SDK가 알아서 await합니다.

일반 `def` 도구도 잘 동작합니다. SDK가 스레드에서 실행하므로 서버를 막는 일이 없습니다.

따로 설정할 것은 아무것도 없습니다.

## 이름, 제목, 애너테이션 {#names-titles-and-annotations}

SDK가 추론하는 것은 모두 데코레이터에서 덮어쓸 수 있습니다.

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title`은 UI에 표시할 사람이 읽기 쉬운 이름입니다. 클라이언트는 `search_books` 대신 *"Search the catalog"*라고 표시합니다.
* `annotations`는 클라이언트를 위한 동작 **힌트**입니다.
  * `read_only_hint=True`: 이 도구는 아무것도 바꾸지 않습니다.
  * `open_world_hint=False`: 열린 웹이 아니라 닫힌 집합(이 카탈로그)을 대상으로 동작합니다.
  * 나머지 둘인 `destructive_hint`와 `idempotent_hint`는 **쓰기**를 하는 도구를 설명합니다. 무언가를
    삭제할 수 있는지, 두 번 호출해도 한 번 호출한 것과 결과가 같은지를 나타냅니다. 명세는 이 둘을 읽기
    전용이 아닌 도구에 대해서만 정의하므로, `search_books`에 붙여도 아무 의미가 없습니다.

잘 만들어진 클라이언트는 이 힌트를 바탕으로 "이 도구를 실행하기 전에 사용자에게 물어봐야 할까?" 같은 판단을 내립니다. 어디까지나 힌트일 뿐 보안 장치가 아닙니다. 클라이언트가 힌트를 지켜 주리라고 기대해서는 안 됩니다.

!!! tip
    이름과 설명을 함수 이름과 독스트링에서 가져오고 싶지 않다면 `@mcp.tool()`에 `name=`과 `description=`을
    넘겨도 됩니다. 대개는 그대로 가져오면 됩니다.

## 요약 {#recap}

* 함수에 `@mcp.tool()` 데코레이터를 붙이면 도구가 됩니다. 이름은 함수에서, 설명은 독스트링에서 가져옵니다.
* 타입 힌트가 **곧** 입력 스키마입니다. 기본값이 있으면 인자는 선택 사항이 됩니다.
* `Annotated[..., Field(...)]` 조합은 설명과 제약 조건을 더하고, `Literal`은 열거형을 더합니다.
* Pydantic 모델 매개변수는 구조화된 "본문"을 받는 방법입니다.
* 잘못된 인자는 알아서 거부되며, 모델이 읽고 스스로 복구할 수 있는 오류가 돌아갑니다.
* I/O에는 `async def`를, 그 밖의 모든 경우에는 일반 `def`를 씁니다.

`return`으로 돌려준 값이 어떻게 되는지는 **[구조화된 출력](structured-output.md)**에서 이어집니다.
