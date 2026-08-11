---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
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
    **[도구](tools.md)**를 읽었다면 이 페이지의 내용은 이미 모두 알고 있는 셈입니다. 같은 데코레이터,
    설명이 되는 같은 docstring, 같은 `Annotated`/`Field`입니다. 달라지는 것은 누가 실행하는지(사용자)와
    결과가 어디로 가는지(대화 속으로)뿐입니다.

## 요약 {#recap}

* 함수에 `@mcp.prompt()`를 붙이면 프롬프트가 됩니다. 이름은 함수에서, 설명은 docstring에서 옵니다.
* 프롬프트는 **사용자가 제어**합니다. 클라이언트가 나열하고, 사용자가 하나를 골라 인수를 채웁니다.
* 인수는 이름이 붙은 문자열의 평평한 목록입니다(스키마 없음). 기본값이 있는 매개변수는 선택 사항입니다.
* `str`을 반환하면 사용자 메시지 하나가 됩니다. `UserMessage` / `AssistantMessage`의 목록을 반환하면 여러 턴의 대화 시작점을 마련할 수 있습니다.
* `title=`과 `Field(description=...)`은 클라이언트가 UI에 표시하는 내용입니다.
* 필수 인수가 빠지면 요청 전체가 실패합니다. 프롬프트별 오류 결과는 없습니다.

프롬프트(또는 리소스 템플릿) 인수의 서버 측 자동 완성은 **[자동 완성](completions.md)**에서 다룹니다.
