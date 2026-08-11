---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# 진행 상황 {#progress}

30초가 걸리면서 그 30초 동안 아무 말도 하지 않는 도구는 고장 난 것처럼 보입니다.

**진행 상황 알림**이 이 문제를 해결합니다. 도구는 얼마나 진행되었는지 보고하고, 클라이언트는 그 정보로 무엇을 그릴지 결정합니다. 진행 막대일 수도, 스피너일 수도, 로그 한 줄일 수도 있습니다.

## 도구에서 보고하기 {#report-it-from-the-tool}

**`Context`** 매개변수를 받고 `report_progress`를 호출하세요.

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

인자는 세 개이며, 각 인자의 의미는 직접 정합니다.

* `progress`: 얼마나 진행했는지입니다. 사양은 보고할 때마다 이 값이 **증가**해야 한다고 요구합니다. 같은 값을 반복하거나 뒤로 돌아가면 안 됩니다.
* `total`: 알고 있다면, 전체가 얼마나 되는지입니다. 선택 사항입니다.
* `message`: **이** 단계를 설명하는, 사람이 읽을 수 있는 한 줄입니다. 선택 사항입니다.

`ctx`는 타입 힌트 덕분에 주입되며 모델에는 전혀 보이지 않습니다. `import_catalog`의 입력 스키마에는 `urls` 속성 하나만 있습니다. **[Context](context.md)** 페이지는 이 객체를 본격적으로 다루며, 진행 상황 보고는 이 객체가 제공하는 기능 중 하나입니다.

## 클라이언트에서 수신하기 {#listen-for-it-from-the-client}

클라이언트는 **호출 단위로** 수신을 선택합니다. `call_tool`에 `progress_callback=` 인자를 전달하면 됩니다.

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

콜백은 서버가 보고한 값 그대로, 즉 `progress`, `total`, `message`를 받는 `async` 함수입니다.

!!! info
    `Client(mcp)`는 서버 객체에 메모리 안에서 직접 연결하며, **[테스트](../get-started/testing.md)**
    페이지의 기반이 되는 것과 같은 클라이언트입니다. `progress_callback`은 `Client`가 어떤 트랜스포트를
    쓰든 같은 매개변수입니다. 다만 곧 보게 될 **타이밍**은 인메모리 연결의 타이밍입니다. 인메모리 연결은
    콜백을 인라인으로 실행하므로 모든 보고가 `call_tool`이 반환되기 전에 도착합니다. 실제 트랜스포트에서는
    알림과 결과가 경쟁하므로, 느린 콜백은 `call_tool`이 반환된 뒤에도 여전히 실행 중일 수 있습니다.

### 직접 해 보기 {#try-it}

`client.py`를 `server.py` 옆에 두고 실행하세요.

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

서버의 `await ctx.report_progress(...)` 하나하나가 클라이언트에서 `show` 호출 하나가 되었고, 순서도 그대로이며, 두 줄 모두 `call_tool`이 반환되기 **전에** 출력되었습니다. 진행 상황은 결과에 묶여 오지 않고, 도구가 아직 작업하는 동안 스트리밍됩니다.

!!! warning
    `progress_callback`은 `Client`가 아니라 **호출**에 속합니다. 이를 위한 생성자 인자는 없습니다.
    호출마다 원하는 콜백이 다르기 때문입니다. 어떤 호출은 다운로드 막대를 움직이고, 다음 호출은
    로그 한 줄을 남깁니다.

!!! check
    이제 `progress_callback=show` 부분을 지우고 다시 실행하세요.

    ```text
    {'result': 'Imported 2 records.'}
    ```

    오류도 경고도 없고 결과는 같습니다. `report_progress`는 **호출자가 진행 상황을 요청하지 않았으면
    아무 일도 하지 않으므로**, 조건 없이 보고하면 되고 누가 듣고 있는지 신경 쓸 필요가 없습니다.

## 전체 양을 모를 때 {#when-you-dont-know-the-total}

`total`은 분모를 알 때 쓰는 값입니다. 모르는 경우도 많습니다. 피드를 비우거나, 커서를 따라가거나, 길이 헤더가 없는 무언가를 내려받을 때가 그렇습니다.

그럴 때는 생략하세요.

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

콜백은 `total=None` 값을 받습니다. 클라이언트는 여전히 **활동**("3 imported so far...")은 보여 줄 수 있지만 백분율은 보여 줄 수 없습니다. 더 보기 좋은 막대를 위해 전체 양을 지어내지 마세요.

!!! tip
    `progress`가 꼭 특정한 무언가를 세어야 하는 것은 아닙니다. 바이트, 행, 페이지 중 사용자가
    알아볼 단위를 고르고, 지킬 수 있는 `total`만 약속하세요.

## 요약 {#recap}

* `Context`를 받는 도구라면 어디서든 `await ctx.report_progress(progress, total=None, message=None)` 형태로 호출합니다.
* 클라이언트는 `call_tool`에 `progress_callback=` 인자를 전달합니다. 호출마다 지정하며, `Client`에는 지정하지 않습니다.
* 콜백은 `async (progress, total, message) -> None` 형태이며 도구가 아직 실행 중인 동안 호출됩니다.
* 호출에 콜백이 없으면 `report_progress`는 아무 일도 하지 않습니다. 조건 없이 보고하세요.
* `total`을 모르면 생략하세요. 콜백은 `None`을 받습니다.

진행 상황은 실행 중인 도구가 **사용자**에게 보여 주는 것입니다. 서버를 운영하는 **운영자**를 위해 도구가 남기는 로그 줄은 별개의 채널이며, **[로깅](logging.md)**에서 다룹니다.
