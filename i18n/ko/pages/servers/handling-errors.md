---
translation:
  sections: [e33d441f12d50535, 7099694c603e0f5f, c1df4cf9673433e6, c9cd294541422e6e, 6cec073617bfd037, efa92b8f99e908c8, 6a22a29e27fb4601]
  tool: 1
---
# 오류 처리 {#handling-errors}

도구가 실패하는 방식은 두 가지이며, SDK는 이 둘을 매우 다르게 다룹니다.

일반적인 예외를 발생시키면 **모델**이 보게 됩니다. `MCPError`를 발생시키면 **프로토콜**이 보게 됩니다.

이 페이지는 둘 중 무엇을 선택할지에 관한 내용입니다.

## 모델이 고칠 수 있는 오류 {#an-error-the-model-can-fix}

무언가를 조회하는 도구를 하나 두고, 조회가 실패하게 해 봅시다.

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

이 두 줄에는 MCP와 관련된 것이 전혀 없습니다. `get_author`는 여느 Python 함수가 그러듯 평범한 `ValueError`를 발생시킵니다.

카탈로그에 없는 제목으로 호출하고 결과를 살펴보세요.

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* 요청은 **성공했습니다**. 결과가 있고, 호출한 쪽에서는 아무 예외도 발생하지 않았습니다.
* `is_error`가 `True`이고, 예외 메시지(앞에 도구 이름이 붙음)가 `content`에, 즉 모델이 읽는 바로 그 자리에 들어 있습니다.
* `structured_content`는 `None`입니다. 실패한 호출에는 구조화할 반환 값이 없습니다.

이것이 **도구 오류**이며, 도구가 발생시키는 **모든** 예외의 기본 동작입니다. 그리고 거의 언제나 원하는 동작이기도 합니다.

도구를 호출하는 쪽은 모델입니다. 인자를 고른 것도 모델입니다. 그래서 도구 오류는 대화의 한 차례가 됩니다. 모델은 *"No book titled 'Nothing' in the catalog."*를 읽고, 제목을 잘못 추측했다는 것을 깨닫고, 더 나은 제목으로 다시 호출합니다. `raise` 한 줄을 썼을 뿐인데 스스로 교정하는 에이전트를 얻은 셈입니다.

!!! tip
    도구에서 오류 메시지를 `return`으로 돌려주지 마세요. 반환된 문자열은 `is_error=False`이므로,
    모델에게(그리고 모든 클라이언트 UI에게) 도구가 제대로 작동했고 그 문자열이 답인 것처럼 보입니다.
    `raise`를 쓰세요. 플래그가 신호입니다.

## 모델이 고칠 수 없는 오류 {#an-error-the-model-cannot-fix}

이제 `ValueError`를 `MCPError`로 바꿔 봅시다.

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError`는 SDK의 **프로토콜 오류**입니다. 도구 래퍼가 잡지 **않는** 유일한 예외로, 그대로 전파되어 `tools/call` 요청 전체가 결과 대신 JSON-RPC 오류로 실패합니다.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **결과가 없습니다**. `content`도, `is_error`도 없으므로 모델이 읽을 것이 아무것도 없습니다.
* 대신 **호스트** 애플리케이션이 오류를 받습니다. 도구가 아예 존재하지 않을 때와 같은 방식입니다.
* `code`, `message`, `data`는 그대로 도착합니다. `INVALID_PARAMS`는 `-32602`입니다. `mcp.types`는 이 코드와 나머지 JSON-RPC 오류 코드(`INVALID_REQUEST`, `INTERNAL_ERROR`, ...)를 상수로 내보내므로 매직 넘버를 직접 입력할 일이 없습니다.

!!! check
    같은 조회, 같은 실패지만, 이번에는 클라이언트 쪽에서 호출이 반환되는 대신 예외를 **발생시킵니다**.

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    첫 번째 버전은 모델에게 반응할 수 있는 문장을 건넸습니다. 이 버전은 아무것도 건네지 않습니다.
    `get_author`의 경우 이는 명백히 더 나쁜 선택이며, 바로 그 점이 다음 절의 주제입니다.

## 무엇을 발생시킬 것인가 {#which-one-to-raise}

두 경로는 서로 다른 두 질문에 답합니다.

* **실행**이 실패했을 때는 **아무 예외나 발생시키세요**. 도구가 하려던 일이 되지 않은 경우입니다. 호출을 선택한 것은 모델이므로, 모델이 그 결과를 보고 회복할 기회를 얻어야 합니다. 철자가 틀린 제목, 시간 초과된 상위 API, 존재하지 않는 행은 모두 도구 오류입니다.
* **요청 자체**를 거부해야 할 때는 **`MCPError`를 발생시키세요**. 도구가 의존하는 기능이 클라이언트에 없거나, 서버가 누구에게도 응답할 수 있는 상태가 아니거나, 호출한 쪽이 필수 단계를 건너뛴 경우입니다. 모델이 재시도해도 이 중 어느 것도 해결되지 않으므로, 메시지를 모델에게 건네서 얻을 것이 없습니다.

판단 기준은 질문 하나입니다. **더 똑똑한 모델이었다면 이 상황을 피할 수 있었을까?** 예 -> 일반 예외. 아니요 -> `MCPError`.

이 기준으로 보면 `get_author`의 두 번째 버전은 잘못된 선택을 했습니다. 더 나은 제목이면 해결되므로, 모델이 메시지를 볼 자격이 있었습니다. 그 버전은 메커니즘을 보여 주기 위한 것이지, 권장하기 위한 것이 아닙니다.

!!! info
    `MCPError`는 `from mcp import MCPError`로 가져오며 `code`, `message`, 그리고 선택적인
    `data` 페이로드를 받습니다. 여기에 넣은 내용이 그대로 클라이언트가 받는 내용입니다. SDK는 발생한
    `MCPError`를 정제하지 않고 그대로 전달합니다.

## 존재하지 않는 리소스 {#a-resource-that-doesnt-exist}

리소스도 같은 선을 긋고, 흔한 경우를 위해 이름 붙은 예외를 하나 제공합니다.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}`은 **템플릿**입니다. **어떤** 제목과도 일치하므로 "URI의 형식이 올바른가"와 "책이 존재하는가"는 서로 다른 질문이고, 두 번째 질문에는 작성한 함수만 답할 수 있습니다.

답할 수 없을 때는 `ResourceNotFoundError`를 발생시키세요. SDK는 이를 명세가 존재하지 않는 리소스에 지정한 프로토콜 오류로 바꿉니다. `-32602`에 요청된 URI가 `data`에 담기므로, 클라이언트는 **어느** 읽기가 실패했는지 알 수 있습니다.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

여기에는 `is_error=True`인 절반짜리 결과가 없다는 점에 주목하세요. 리소스 읽기는 내용을 반환하거나 실패하거나 둘 중 하나입니다. 리소스에는 프로토콜 경로만 있습니다. 템플릿을 비롯해 리소스에 관한 나머지 모든 내용은 **[리소스](resources.md)**에서 다룹니다.

## 직접 발생시킬 일이 없는 오류 {#errors-you-never-raise}

잘못된 인자는 함수에 도달하지 않습니다.

`get_author`에 문자열이 아닌 `title`을 보내면 SDK는 함수를 호출하기 **전에** 입력 스키마와 대조해 거부하며, 모델이 읽고 교정할 수 있는 같은 종류의 `is_error=True` 도구 오류로 돌려줍니다. **[도구](tools.md)**에서 `Field(le=50)` 제약으로 같은 거부가 일어나는 것을 보여 줍니다.

이는 작성하지 않아도 되는 `raise` 문이 한 부류 통째로 있다는 뜻입니다. 타입 힌트를 직접 다시 검증하지 마세요.

!!! info
    이 페이지의 모든 내용은 **클라이언트**가 보는 것이며, 테스트를 작성할 때 쓸 인메모리 `Client`도
    정확히 같은 것을 봅니다. `raise_exceptions=True`조차 도구 오류를 트레이스백으로 되돌리지 않습니다.
    그 플래그가 동작할 수 있는 시점에는 예외가 이미 `is_error=True` 결과가 되어 있기 때문입니다.
    결과에 대해 단언하세요. 이 패턴은 **[테스트](../get-started/testing.md)**에서 다룹니다.

## 요약 {#recap}

* 도구에서 **아무 예외**나 발생시키면 -> 호출은 `is_error=True`와 함께 메시지를 `content`에 담아 반환합니다. 모델이 읽고 재시도할 수 있습니다. 이것이 기본 동작입니다.
* **`MCPError`**를 발생시키면 -> 호출 자체가 JSON-RPC 오류로 실패합니다. 모델은 아무것도 보지 못하고, 호스트가 처리합니다. `code`, `message`, `data`는 그대로 유지됩니다.
* 판단 기준이 되는 질문은 **더 똑똑한 모델이었다면 이 상황을 피할 수 있었을까?**입니다. 예 -> 예외. 아니요 -> `MCPError`.
* 리소스 핸들러에서 `ResourceNotFoundError`를 발생시키면 -> 프로토콜의 `-32602`가 되며, URI가 `data`에 담깁니다.
* 잘못된 인자는 함수가 실행되기 전에 스키마와 대조해 거부되므로, 이를 위해 `raise`를 쓰지 않습니다.
* `from mcp import MCPError`를 쓰고, 오류 코드 상수는 `mcp.types`에서 가져옵니다.

오류 처리까지 마쳤습니다. 이것으로 서버가 **노출하는** 모든 것을 다뤘습니다. 모든 핸들러가 실행 중에 무엇을 읽을 수 있고 클라이언트에게 무엇을 되돌려 할 수 있는지는 다음 절인 **[핸들러 내부](../handlers/index.md)**에서 다룹니다.

가장 자주 마주칠 SDK 오류의 정확한 문구, 각각의 의미, 그리고 각각에 대한 한 번의 조치로 끝나는 해결책은 **[문제 해결](../troubleshooting.md)**에서 확인하세요.
