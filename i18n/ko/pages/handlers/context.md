---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Context {#the-context}

도구의 인자는 모델이 채웁니다. 그 밖의 모든 것(지금 처리 중인 요청, 도구가 속한 서버, 클라이언트에 되돌려 말을 건넬 수단)은 단 하나의 객체, **`Context`**에서 옵니다.

직접 생성하지도, 설정하지도 않습니다. 달라고 하기만 하면 됩니다.

## Context 받기 {#ask-for-it}

아무 도구에나 `Context`로 어노테이션한 매개변수를 추가하세요.

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* SDK는 요청마다 새 `Context`를 만들어 전달합니다.
* 매개변수 **이름은 중요하지 않습니다**. `ctx`, `context`, `c` 무엇이든 SDK는 어노테이션으로 찾아냅니다.
* 리소스와 프롬프트도 같은 방식으로 선언할 수 있습니다.
* `ctx.request_id`는 함수가 바로 지금 처리하고 있는 요청의 ID입니다.

!!! info
    FastAPI를 써 봤다면 익숙한 방식입니다. 프레임워크 고유의 타입(FastAPI에서는 `Request`, 여기서는 `Context`)으로 매개변수를 선언하면 프레임워크가 값을 채워 줍니다. 등록할 것도, 설정할 것도 없습니다. 타입 어노테이션이 메커니즘의 전부입니다.

### 모델에게 보이지 않는 매개변수 {#invisible-to-the-model}

꼭 새겨 둘 부분입니다. 다음은 `tools/list`가 보고하는 `search_books`의 입력 스키마입니다.

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

속성은 하나뿐입니다. `ctx`는 인자가 아닙니다. 스키마에 나타나지 않고, 모델은 그 존재를 전혀 듣지 못하며, 어떤 클라이언트도 값을 채울 수 없습니다. 개발자와 SDK 사이의 약속일 뿐, 와이어 위에서는 보이지 않습니다.

### 직접 해 보기 {#try-it}

MCP Inspector로 서버를 실행하세요.

```console
uv run mcp dev server.py
```

`search_books` 폼에는 `query` 필드 하나만 있습니다. `dune`으로 호출해 보세요.

```text
[request 3] Found 3 books matching 'dune'.
```

숫자는 이 호출이 우연히 몇 번째 요청이었는지에 따라 정해집니다. 도구를 다시 호출하면 숫자가 바뀝니다. 요청마다 고유한 `Context`를 받기 때문입니다.

## Context가 제공하는 것 {#what-it-gives-you}

주입되는 객체는 작습니다. `request_id` 외에 다음이 있습니다.

* `await ctx.read_resource(uri)`: 도구 안에서 서버 **자신의** 리소스를 읽습니다. 다음 절에서 다룹니다.
* `await ctx.report_progress(progress, total, message)`: 오래 걸리는 호출 중에 호출자에게 진행 상황을 스트리밍합니다. 자세한 내용은 **[진행 상황](progress.md)**에서 확인하세요.
* `await ctx.elicit(message, schema)`와 `await ctx.elicit_url(...)`: 도구를 잠시 멈추고 사용자에게 질문합니다. **[엘리시테이션(elicitation)](elicitation.md)**에서 다룹니다.
* `ctx.session`: 이 클라이언트와 나누는 대화의 서버 쪽 끝입니다. 클라이언트로 보내는 알림이 여기에 있으며, 마지막 절에서 사용합니다.
* `ctx.headers`: 트랜스포트가 실어 온 요청 헤더이며, stdio에서는 `None`입니다. 사용자 정의 헤더는 `(ctx.headers or {}).get("x-...")`로 읽습니다. 헤더는 클라이언트가 제공하는 입력이므로 로캘이나 기능 플래그에는 괜찮지만, 신원으로는 절대 쓰면 안 됩니다.
* `ctx.request_context`: 요청별 원시 레코드입니다. 주로 찾게 될 필드는 `lifespan_context`로, 시작 코드가 yield한 객체입니다(**[Lifespan](lifespan.md)** 참고).

로깅은 일부러 이 목록에 넣지 않았습니다. 서버는 다른 Python 프로그램과 마찬가지로 Python의 `logging` 모듈로 로그를 남깁니다. 그 이유는 짧은 페이지 **[로깅](logging.md)**에서 설명합니다.

!!! tip
    주입은 등록한 함수에만 일어납니다. 도구가 호출하는 헬퍼 함수는 자체 `Context`를 받지 않으므로 `ctx`를 일반 인자로 넘겨주세요. 다른 곳에서 가져다 쓸 수 있는 전역 "현재 컨텍스트" 같은 것은 없습니다.

## 서버 자신의 리소스 읽기 {#read-your-own-resources}

서버의 리소스는 클라이언트만을 위한 것이 아닙니다. 도구도 읽을 수 있습니다.

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource`는 `resources/read`를 처리하는 것과 같은 레지스트리를 통해 URI를 해석하므로, 도구는 클라이언트가 받는 것과 똑같은 결과를 받습니다. 콘텐츠 블록마다 하나씩 담긴 `ReadResourceContents`의 이터러블입니다. 이 URI에는 하나가 있습니다.

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content`는 `genres()`가 반환한 값 그대로입니다. 진실의 원천은 하나입니다. 클라이언트는 리소스를 둘러보고, 도구는 리소스를 사용하며, 누구도 문자열을 복사하지 않습니다.
* `describe_catalog`의 유일한 매개변수는 `Context`이므로 입력 스키마에는 **속성이 아예 없습니다**. 모델이 호출할 때 넘기는 인자는 `{}`입니다.

## 목록이 바뀌었음을 클라이언트에 알리기 {#tell-the-client-the-list-changed}

서버가 제공하는 것은 임포트 시점에 고정되지 않습니다. 런타임에 도구를 등록한 다음 클라이언트에 알리세요.

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)`은 평범한 함수를 도구로 등록합니다. 이름, 설명, 스키마는 `@mcp.tool()`을 썼을 때와 똑같이 도출됩니다.
* `await ctx.session.send_tool_list_changed()`는 `notifications/tools/list_changed`를 보냅니다. 이를 받은 클라이언트는 `tools/list`를 다시 호출하고 `recommend_book`을 보게 됩니다.

형제 메서드로는 `send_resource_list_changed()`, `send_prompt_list_changed()`, 그리고 특정 리소스 하나의 변경을 알리는 `send_resource_updated(uri)`가 있습니다.

2026-07-28 연결에서 클라이언트는 직접 연 `subscriptions/listen` 스트림에서만 변경 알림을 받으므로, 위의 `send_*` 메서드는 그 스트림에 닿지 않습니다. `Context`의 발행 메서드는 구독 중인 모든 스트림에 한 번에 전달합니다. `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()`, `await ctx.notify_resource_updated(uri)`입니다. 여러 복제본으로 확장하는 방법까지 포함한 자세한 내용은 **[구독](subscriptions.md)**에서 확인하세요.

!!! check
    누군가 `enable_recommendations`를 실행하기 전까지는 약속한 도구가 존재하지 않습니다. 그래도 호출하면 모델이 읽을 수 있는 오류가 결과로 돌아옵니다.

    ```text
    Unknown tool: recommend_book
    ```

    `enable_recommendations`를 실행하면 똑같은 호출이 성공합니다. 도구 목록은 진짜로 동적입니다. `tools/list`는 **바로 지금** 등록되어 있는 것을 반영합니다.

## 요약 {#recap}

* (도구, 리소스, 프롬프트에서) 매개변수에 `Context` 어노테이션을 달면 SDK가 주입합니다. 이름은 마음대로 정하면 됩니다.
* 모델에게는 보이지 않습니다. 입력 스키마에는 언제나 실제 인자만 들어갑니다.
* `ctx.request_id`는 요청을 식별하고, `ctx.request_context.lifespan_context`는 시작 코드가 yield한 객체입니다.
* `await ctx.read_resource(uri)`로 도구가 서버 자신의 리소스를 읽을 수 있습니다.
* `ctx.session`은 클라이언트로 되돌아가는 채널입니다. `send_tool_list_changed()`와 형제 메서드는 바뀐 목록을 다시 가져오라고 클라이언트에 알립니다.
* 진행 상황 보고와 엘리시테이션도 `Context`에서 시작하며, 각각 별도 페이지가 있습니다.

모델은 전혀 보지 못하고 직접 작성한 함수가 채우는 매개변수는 **[의존성](dependencies.md)**입니다.
