---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# 자동 완성 {#completions}

서버 위에 UI를 만드는 클라이언트는 사용자가 입력하는 동안 인수 값을 자동 완성하고 싶어 합니다. 언어 이름, 리포지토리 이름, 파일 경로 같은 것들입니다.

**자동 완성(completions)**은 서버가 이런 제안을 제공하는 방법입니다.

## 자동 완성할 만한 것 {#something-worth-completing}

자동 완성은 정확히 두 가지에만 적용됩니다. **프롬프트**의 인수와 **리소스 템플릿**의 매개변수입니다. 그러니 각각 하나씩 가진 서버로 시작하세요.

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

아직 자동 완성과 관련된 것은 아무것도 없습니다.

* `review_code`는 `language`를 받습니다. 서버가 어떤 철자를 허용하는지 사용자가 추측해야 해서는 안 됩니다.
* `github_repo`는 `owner`와 `repo`를 받습니다. 둘 다 자유 입력 칸으로 두면 좋은 폼이 아닙니다.

## 자동 완성 핸들러 {#the-completion-handler}

`@mcp.completion()`으로 데코레이트한 함수를 **하나** 추가하세요.

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* 핸들러는 서버당 하나입니다. 모든 자동 완성 요청이 여기로 들어오며, 무엇을 자동 완성하는지에 따라 분기합니다.
* 반드시 `async def`여야 합니다. SDK가 이 함수를 await합니다.
* 인수 세 개를 받습니다.
  * `ref`: **어떤** 프롬프트 또는 리소스 템플릿인지를 `PromptReference` 또는 `ResourceTemplateReference`로 나타냅니다. 둘을 구분할 때는 `isinstance`를 사용합니다.
  * `argument`: `argument.name`은 자동 완성 중인 인수이고, `argument.value`는 사용자가 지금까지 입력한 내용입니다.
  * `context`: 이미 확정된 인수입니다. 지금은 무시하세요.
* `Completion(values=[...])`을 반환하거나, 제안할 것이 없으면 `None`을 반환합니다.

!!! tip
    `argument.value`는 사용자가 입력한 접두사입니다. SDK는 대신 필터링해 주지 **않습니다**.
    `values`에 넣은 것이 그대로 UI에 표시됩니다. `startswith`는 직접 작성해야 합니다.

### 직접 해 보기 {#try-it}

**[테스트](../get-started/testing.md)**의 인메모리 `Client`로 실행해 보세요.
`ref=PromptReference(name="review_code")`와
`argument={"name": "language", "value": "py"}`로 `client.complete()`를 호출하세요.

```python
result.completion.values  # ['python']
```

* `ref`는 핸들러가 받는 것과 같은 참조 타입입니다.
* `argument`는 `name`과 `value`라는 키 두 개만 가진 평범한 dict입니다.

빈 `value`를 보내면 전체 목록이 돌아옵니다. `lang.startswith("")`는 모든 언어에서 참이기 때문입니다.

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

`code`(핸들러가 인식하지 못하는 인수)를 물어보면 `None`을 반환하고, SDK는 이를 빈 목록으로 바꿉니다.

```python
result.completion.values  # []
```

`None`은 **"제안 없음"**을 뜻할 뿐, 결코 오류가 아닙니다. UI는 일반 텍스트 입력 칸으로 대체합니다.

## 선언한 적 없는 기능 {#a-capability-you-never-declared}

핸들러를 등록하는 것이 곧 선언입니다. 클라이언트를 연결하고 확인해 보세요.

```python
client.server_capabilities.completions  # CompletionsCapability()
```

어디에도 `completions`를 나열하지 않았습니다. SDK가 핸들러를 보고 기능을 대신 선언했습니다. 모든 **선택적** 기능은 이런 식으로 동작합니다. 핸들러가 곧 선언입니다. (세 가지 프리미티브는 선택적이지 않습니다. `MCPServer`는 핸들러가 있든 없든 항상 이 세 가지를 선언합니다.)

!!! check
    첫 번째 `server.py`(핸들러가 없는 버전)로 돌아가서 그래도 요청해 보세요. 호출은
    JSON-RPC 오류와 함께 실패합니다.

    ```text
    Method not found
    ```

    그리고 `client.server_capabilities.completions`는 `None`입니다. 이것이 바로 기능의 의의입니다.
    제대로 동작하는 클라이언트는 기능을 확인하고, 서버가 응답할 수 없는 요청은 아예 보내지 않습니다.

## 의존하는 인수 {#dependent-arguments}

`github://repos/{owner}/{repo}`에는 매개변수가 두 개 있고, `repo`에 유용한 값은 먼저 어떤 `owner`를 골랐는지에 따라 달라집니다.

`context`는 바로 이를 위한 것입니다. 사용자가 **이미 확정한** 인수를 담고 있습니다.

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* 새 분기는 템플릿의 `repo` 매개변수에 대해 실행됩니다.
* `context.arguments`는 지금까지 선택된 값(여기서는 `owner`)을 담은 `dict[str, str] | None`입니다.
* 아직 `owner`가 없으면 의미 있는 제안도 없으므로, 핸들러는 `None`을 반환합니다.

클라이언트는 확정된 값을 `context_arguments=`로 보냅니다. 이번에는 `ref`가
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`입니다. 빈 `value`로 `repo`를
요청하면서 `context_arguments={"owner": "modelcontextprotocol"}`를 전달하세요.

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

`context_arguments=`를 빼면 같은 호출이 `[]`를 반환합니다. 핸들러는 owner를 알기 전까지는 어떤 리포지토리를 제안해야 할지 알 수 없습니다.

!!! info
    `Completion`은 `total=`과 `has_more=`도 받습니다. `values`가 더 긴 목록의 일부일 때 설정하면
    UI가 **"외 200개"**처럼 표시할 수 있습니다. 대부분의 핸들러에는 필요하지 않습니다.

## 요약 {#recap}

* 자동 완성은 **프롬프트 인수**와 **리소스 템플릿 매개변수**에 대한 제안입니다. 그 외에는 없습니다.
* `@mcp.completion()`은 하나뿐인 핸들러를 등록합니다. 형태는 `async def (ref, argument, context) -> Completion | None`입니다.
* `isinstance(ref, ...)`와 `argument.name`으로 분기하세요. `argument.value`로 필터링하는 것은 직접 해야 합니다.
* `None`은 빈 목록이 됩니다. 결코 오류가 아닙니다.
* `context.arguments`는 이미 확정된 값을 담고 있으며, 클라이언트는 이를 `context_arguments=`로 제공합니다.
* `completions` 기능은 핸들러를 등록하는 순간 나타납니다. 핸들러가 없으면 요청은 `Method not found`가 됩니다.

제안은 사용자가 프롬프트나 템플릿을 아직 **채우고 있는** 동안 도움이 됩니다. 도구 호출 **도중에** 사용자에게 질문하려면 **[엘리시테이션(elicitation)](../handlers/elicitation.md)**이 필요합니다. 도구가 텍스트 외에 반환할 수 있는 모든 것은 **[이미지, 오디오, 아이콘](media.md)**에서 확인하세요.
