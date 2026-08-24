---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# 프롬프트 {#prompts}

**프롬프트**는 사용자가 고르는 메시지 템플릿입니다.

도구는 모델을 위한 것입니다. 프롬프트는 그 반대입니다. 사용자가 클라이언트의 메뉴(슬래시 명령, 버튼)에서 하나를 고르고 인수를 채우면, 렌더링된 메시지가 마치 사용자가 직접 입력한 것처럼 대화에 들어갑니다.

텍스트를 반환하는 함수에 `@mcp.prompt()`를 붙이면 프롬프트가 선언됩니다.

## 첫 번째 프롬프트 {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK는 도구에서 읽는 것과 똑같은 세 가지를 읽습니다.

* **이름**은 함수 이름인 `review_code`입니다.
* 클라이언트가 보여 주는 **설명**은 docstring인 `Review a piece of code.`입니다.
* **인수**는 매개변수에서 나옵니다. `code`에는 기본값이 없으므로 필수입니다.

클라이언트가 `prompts/list`에서 돌려받는 내용은 다음과 같습니다.

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

여기에는 JSON Schema가 없습니다. 프롬프트 인수는 **이름이 붙은 문자열 값**의 평평한 목록입니다. 모델이 구성하는 페이로드가 아니라 사람이 채우는 양식입니다.

### 렌더링 {#rendering-it}

클라이언트는 인수를 전달하며 `prompts/get`으로 템플릿을 렌더링합니다. 함수가 실행되고, 반환한 `str`은 **사용자 메시지 하나**가 됩니다.

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

프롬프트의 생애는 이것이 전부입니다. 이름으로 나열되고, 필요할 때 렌더링되어, 채팅에 들어갑니다.

!!! check
    `required`는 함수가 실행되기 전에 강제됩니다. `code` 없이 `review_code`를 렌더링하면
    요청 자체가 JSON-RPC 오류(코드 `-32603`)로 실패합니다.

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    이 과정에는 모델이 관여하지 않으므로 모델에게 돌려줄 도구 방식의 오류 결과는 없습니다.
    호출이 예외를 발생시킵니다. 이유(`Missing required arguments: {'code'}`)는 서버 로그에 남습니다.

### 직접 해 보기 {#try-it}

MCP Inspector로 서버를 실행하세요.

```console
uv run mcp dev server.py
```

**Prompts** 탭을 열고 `review_code`를 선택하세요. Inspector가 필수 `code` 필드 하나가 있는 양식을 그립니다. 필드를 채우고 렌더링하면 위의 사용자 메시지가 그대로 돌아옵니다.

## 여러 개의 메시지 {#more-than-one-message}

코드 리뷰는 메시지 하나입니다. 디버깅 세션은 대화이며, 프롬프트로 대화 전체의 시작점을 마련할 수 있습니다.

`str` 대신 메시지 목록을 반환하세요.

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage`와 `AssistantMessage`는 `mcp.server.mcpserver.prompts.base`에 있습니다. `str`을 넘기면 알아서 `TextContent`로 감싸 줍니다. 역할은 클래스 이름입니다.
* `Message`는 둘의 공통 기반 클래스입니다. 반환 어노테이션으로 사용하세요.

이제 `debug_error`를 렌더링하면 메시지 세 개가 순서대로 만들어집니다.

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

마지막 메시지를 눈여겨보세요. `assistant` 턴을 미리 채워 두면 사용자가 직접 방향을 입력하지 않아도 모델의 **다음** 응답을 원하는 방향으로 이끌 수 있습니다.

## 제목과 인수 설명 {#titles-and-argument-descriptions}

`review_code`는 레이블이 아니라 함수 이름입니다. 클라이언트가 버튼에 표시할 더 나은 이름을 주고, 양식이 스스로를 설명하도록 각 인수에 설명을 붙이세요.

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"`는 도구의 `title`과 똑같이 사람이 읽기 위한 이름입니다.
* `Annotated[str, Field(description=...)]`은 **[도구](tools.md)**에서 도구의 매개변수를 설명할 때 쓰는 것과 같은 패턴입니다. 여기서는 설명이 스키마가 아니라 인수에 붙습니다.
* `language`에는 기본값이 있으므로 더 이상 필수가 아닙니다.

이제 `prompts/list` 항목에는 클라이언트가 좋은 양식을 그리는 데 필요한 모든 것이 담깁니다.

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    **[도구](tools.md)**를 읽었다면 여기까지의 내용은 이미 모두 알고 있는 셈입니다. 같은 데코레이터,
    설명이 되는 같은 docstring, 같은 `Annotated`/`Field`입니다. 달라지는 것은 누가 실행하는지(사용자)와
    결과가 어디로 가는지(대화 속으로)뿐입니다.

## 텍스트 그 이상 {#more-than-text}

`UserMessage`와 `AssistantMessage`는 `str`을 받는 자리라면 어디든 콘텐츠 블록이나 `Image` / `Audio` 헬퍼도 받습니다. 프롬프트에서 자주 나오는 경우는 두 가지입니다. 문서를 첨부하는 경우와 그림을 첨부하는 경우입니다.

### 파일 임베딩 {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* 스타일 가이드는 `style://python`에 있는 리소스이며(**[리소스](resources.md)**에서 다룹니다), `server.py` 옆의 `style-guide.md`에서 읽어 옵니다. 아무 Markdown 파일이나 그 자리에 두세요.
* `EmbeddedResource(resource=TextResourceContents(...))`(둘 다 `mcp.types`에 있습니다)는 URI와 MIME 타입과 함께 파일을 첫 번째 메시지로 담고, 이 파일을 참조하는 요청이 일반 텍스트로 뒤따릅니다.
* 가이드를 f-string에 붙여 넣는 대신 임베딩하면 클라이언트가 첨부 파일로 보여 주고 나중에 `style://python`을 다시 열 수 있으며, 모델은 파일을 원문 그대로 받습니다. 바이너리 파일에는 base64 `blob`을 담은 `BlobResourceContents`를 사용하세요.

렌더링하면 첫 번째 메시지의 `content`는 `resource` 블록입니다.

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### 이미지 첨부 {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image`는 **[이미지, 오디오, 아이콘](media.md)**의 헬퍼입니다. 프롬프트가 렌더링될 때 `UserMessage`가 이를 `ImageContent` 블록(파일은 base64로 인코딩되고, MIME 타입은 `.png`에서 추측)으로 변환합니다. `Audio`도 같은 방식으로 `AudioContent`가 됩니다.
* `architecture.png`라는 이름의 PNG를 아무거나 `server.py` 옆에 두세요. 프롬프트 인수는 문자열이므로 그림은 항상 서버에서 나옵니다. `component`는 문구만 제공합니다.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## 런타임에 목록 바꾸기 {#changing-the-list-at-runtime}

클라이언트가 연결된 상태에서도 프롬프트를 추가할 수 있습니다. 예를 들어 사용자가 지시 사항을 자신만의 메뉴 항목으로 저장하게 할 수 있습니다. 프롬프트를 등록한 다음 알림을 보내세요.

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))`는 `@mcp.prompt()`와 똑같이 함수를 등록하고, `mcp.remove_prompt(name)`은 그 반대입니다. `add_prompt`는 같은 이름의 기존 항목을 덮어쓰지 않고 유지하므로, 저장이 교체가 되도록 이 도구는 먼저 이전 항목을 제거합니다. `prompts/list`에는 변경 사항이 즉시 반영됩니다.
* `await ctx.notify_prompts_changed()`는 `subscriptions/listen` 스트림을 듣고 있는 모든 `2026-07-28` 클라이언트에게 `notifications/prompts/list_changed`를 보냅니다(**[구독](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()`는 호출한 클라이언트가 2026 이전 버전일 때 그 클라이언트에게 보냅니다(**[레거시 클라이언트 지원](../run/legacy-clients.md)**). 둘 다 호출하세요. 알릴 대상이 없으면 각각 아무 일도 하지 않습니다.
* 알림을 받은 클라이언트는 `prompts/list`를 다시 호출합니다. Python `Client`에서는 `async with client.listen(prompts_list_changed=True) as sub:`이며, `PromptsListChanged` 이벤트를 내놓습니다.

## 요약 {#recap}

* 함수에 `@mcp.prompt()`를 붙이면 프롬프트가 됩니다. 이름은 함수에서, 설명은 docstring에서 옵니다.
* 프롬프트는 **사용자가 제어**합니다. 클라이언트가 나열하고, 사용자가 하나를 골라 인수를 채웁니다.
* 인수는 이름이 붙은 문자열의 평평한 목록입니다(스키마 없음). 기본값이 있는 매개변수는 선택 사항입니다.
* `str`을 반환하면 사용자 메시지 하나가 됩니다. `UserMessage` / `AssistantMessage`의 목록을 반환하면 여러 턴의 대화 시작점을 마련할 수 있습니다.
* `title=`과 `Field(description=...)`은 클라이언트가 UI에 표시하는 내용입니다.
* 필수 인수가 빠지면 요청 전체가 실패합니다. 프롬프트별 오류 결과는 없습니다.
* `EmbeddedResource`나 `Image`를 `UserMessage`로 감싸면 문서나 그림을 첨부할 수 있습니다.
* 런타임에 프롬프트를 추가하거나 제거하려면 `mcp.add_prompt(...)` / `mcp.remove_prompt(...)`를 쓰고, 이어서 `await ctx.notify_prompts_changed()`와 `await ctx.session.send_prompt_list_changed()`를 호출하세요.

프롬프트(또는 리소스 템플릿) 인수의 서버 측 자동 완성은 **[자동 완성](completions.md)**에서 다룹니다.
