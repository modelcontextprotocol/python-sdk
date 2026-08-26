---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# 시작하기 {#get-started}

MCP가 처음이거나 이 SDK가 처음이라면 여기서 시작하세요. 이곳의 페이지는 아무것도 없는 상태에서 시작해,
테스트까지 마친 동작하는 서버를 완성하도록 안내합니다. [SDK 설치](installation.md),
[첫 번째 서버](first-steps.md) 만들기, [실제 호스트에 연결하기](real-host.md), 그리고 인메모리 클라이언트로
[테스트하기](testing.md) 순서로 진행합니다.

## 코드 실행하기 {#run-the-code}

모든 코드 블록은 그대로 복사해서 바로 사용할 수 있습니다. 하나하나가 완전하게 동작하는 파일입니다.

따라 하려면 코드 블록을 `server.py`에 붙여 넣고 MCP Inspector에서 여세요.

```console
uv run mcp dev server.py
```

코드를 직접 작성(또는 복사)하고, 수정하고, 로컬에서 실행해 보기를 **강력히 권장합니다**. 평소 쓰는 편집기에서 직접 다뤄 봐야 핵심이 제대로 와닿습니다. 작성할 코드가 얼마나 적은지, 자동 완성은 어떤지, 실행하기도 전에 타입 검사가 실수를 잡아내는 모습까지 확인할 수 있습니다.

## 추측할 필요 없는 예제 {#you-will-not-be-guessing}

이 문서의 모든 예제는 SDK 저장소의 [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) 아래에 있는 완전한 파일이며, 하나도 빠짐없이 SDK의 테스트 스위트가 **인메모리 클라이언트**를 통해 실행합니다.

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

서브프로세스도, 포트도, 트랜스포트도 없습니다. `Client(mcp)`가 서버 객체에 직접 연결합니다.

SDK 변경으로 이 문서의 예제가 하나라도 깨지면, 페이지에 문제가 드러나기 전에 CI가 먼저 실패합니다. 여기서 읽는 코드가 곧 실제로 실행되는 코드입니다.

이 방식은 [테스트](testing.md)에서 직접 사용해 봅니다. 작성한 서버를 테스트하는 방법도 바로 이것입니다.

## 다음 단계 {#where-to-go-next}

서버를 실행하고 나면 나머지 문서는 강좌가 아니라 레퍼런스입니다.
모든 페이지가 독립적으로 읽히므로 필요한 곳으로 바로 이동하세요.

* 서버가 노출하는 것(도구, 리소스, 프롬프트)은 **[서버](../servers/index.md)**에서 다룹니다.
* 등록한 함수 안에서 사용할 수 있는 것은 **[핸들러 내부](../handlers/index.md)**에서 다룹니다.
* 클라이언트 앞에 내놓는 방법(stdio, HTTP, 기존 FastAPI 앱)은 **[서버 실행하기](../run/index.md)**에서 다룹니다.
* 반대편, 즉 MCP 서버를 **사용하는** 애플리케이션을 만드는 방법은 **[클라이언트](../client/index.md)**에서 다룹니다.
