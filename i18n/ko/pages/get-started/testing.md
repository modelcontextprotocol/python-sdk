---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# 테스트 {#testing}

Python SDK는 **인메모리 트랜스포트**를 갖춘 `Client` 클래스를 제공합니다. 서버 객체를 넘기면 그 서버에 직접 연결합니다.

서브프로세스도 없습니다. 포트도 없습니다. 트랜스포트도 전혀 없습니다. FastAPI의 `TestClient`와 같은 발상입니다.

## 기본 사용법 {#basic-usage}

도구가 하나뿐인 간단한 서버가 있다고 해 보겠습니다.

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

아래 테스트를 실행하려면 (개발용) 의존성 두 개가 더 필요합니다.

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    이 문서는 [`pytest`](https://docs.pytest.org/en/stable/)를 이미 알고 있다고 가정합니다.

    아래 테스트에서는 [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/)으로
    결과 객체 전체를 한 줄에 검증합니다. 테스트의 출력을 코드에 보이는 `snapshot(...)` 리터럴
    형태로 기록해 주는 라이브러리입니다. 쓰고 싶지 않다면 import를 빼고, 여느 테스트에서 하듯
    관심 있는 필드(`result.content[0].text == "3"`)를 직접 검증하세요.

이제 테스트 코드입니다.

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. `trio`를 사용한다면 대신 `"trio"`를 반환하세요. 자세한 내용은 [anyio 문서](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on)를 참고하세요.
2. 이 픽스처는 연결을 마친 클라이언트를 yield합니다. `client`를 받는 모든 테스트는 같은 서버로 이어지는 새 인메모리 연결을 받습니다.

다 됐습니다. 이제 더 많은 시나리오를 다루도록 테스트를 확장할 수 있습니다.

## `raise_exceptions=True`를 쓰는 이유 {#why-raise_exceptionstrue}

잘못될 수 있는 일은 서로 다른 두 가지이고, 이 플래그는 그중 하나에만 관여합니다.

**작성한 도구** 안에서 발생한 예외는 프로토콜 실패가 아닙니다. `is_error=True`인 정상적인 결과가
되고, 모델이 그 메시지를 읽습니다. `raise_exceptions`는 이 점을 바꾸지 않습니다. 플래그가 있든
없든 `call_tool`은 똑같은 `is_error=True` 결과를 반환합니다. 이 주제를 통째로 다루는 페이지가
따로 있습니다. **[오류 처리](../servers/handling-errors.md)**를 참고하세요.

도구 본문 **바깥**에서 일어난 실패는 다릅니다. `Client(mcp)`가 제공하는 연결에서는 클라이언트가
보기 전에 서버가 이 실패를 일반적인 `"Internal server error"`로 정제합니다. 예상치 못한 크래시의
세부 내용을 원격 호출자에게 흘려서는 절대 안 됩니다. 하지만 테스트에서는 바로 이것이 원하지
**않는** 동작이며, `raise_exceptions=True`가 바꾸는 것도 바로 이 부분입니다. 테스트는 정제된
메시지 대신 실제 메시지를 보게 됩니다.

테스트에서는 켜 두세요. 프로덕션 코드에서는 아무 의미가 없습니다.

## 기본값은 인프로세스 연결 {#in-process-by-default}

!!! note
    `Client(mcp)`는 인프로세스로 연결하며 기본적으로 **세대 중립적**(era-neutral)입니다. 서버를
    조사해 알맞은 프로토콜 경로를 고릅니다. 테스트가 레거시 전용 동작, 즉 샘플링이나
    엘리시테이션(elicitation) 푸시, `message_handler` 같은 것을 검증한다면 `mode="legacy"`로
    고정하고, 그 경우에는 `raise_exceptions=True`를 빼세요. 레거시 연결은 애초에 정제를 하지
    않으며, 이 플래그는 실패를 테스트가 아니라 서버 태스크 안에서 다시 발생시키기 때문입니다.

이 문서의 예제가 실제로 동작한다고 약속할 수 있는 것도 바로 그 한 줄 덕분입니다. 모든 예제
파일은 SDK 자체의 테스트 스위트에서 실행되며, 거의 전부가 정확히 이 클라이언트를 거칩니다.
SDK가 스스로를 검증하는 데 쓰는 바로 그 도구를 사용하고 있는 것입니다.

이제 동작하고 테스트까지 거친 서버가 생겼습니다. 이 서버를 실제 애플리케이션(Claude Desktop,
IDE)에 넣는 방법은 **[실제 호스트에 연결하기](real-host.md)**에서, 그 밖에 서버를 구동하는 모든
방법은 **[서버 실행하기](../run/index.md)**에서 다룹니다.
