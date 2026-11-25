---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# 설치 {#installation}

Python SDK는 PyPI에 [`mcp`](https://pypi.org/project/mcp/)라는 이름으로 올라와 있습니다. **Python 3.10 이상**이 필요합니다.

이 문서는 현재 안정 릴리스 계열인 **v2**를 설명합니다.

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "v1에서 옮겨 오는 경우"
    v2는 호환성이 깨지는 변경이 포함된 메이저 버전이며, **[마이그레이션 가이드](../migration.md)**에서
    그 변경을 하나도 빠짐없이 다룹니다. 작성한 **패키지**가 `mcp`에 의존하는데 아직 마이그레이션할 준비가 되지 않았다면,
    버전을 고정하지 않은 의존성 해석이 1.x 계열에 머무르도록 `<2` 상한을 유지하세요(예: `mcp>=1.28,<2`).

## 설치되는 항목 {#what-gets-installed}

SDK를 사용하는 데 이런 내용을 알 필요는 전혀 없지만, 각 의존성이 어떤 용도인지 궁금하다면 다음을 참고하세요.

* `mcp-types`: 모든 프로토콜 타입(요청, 결과, 콘텐츠 블록)을 담은 별도 패키지로, SDK와 항상 같은 버전으로 맞춰 릴리스됩니다. `mcp`에 의존하는 코드는 이 패키지를 `mcp.types` 별칭을 통해 임포트합니다(이 문서에 나오는 모든 `from mcp.types import ...`가 그렇습니다). `mcp_types`를 직접 임포트하는 것은 SDK 없이 `mcp-types`만 설치하는 프로젝트에서만 하세요.
* [`anyio`](https://anyio.readthedocs.io/): 비동기 런타임입니다. SDK 전체가 anyio를 기반으로 작성되어 있으므로 `asyncio`와 `trio` 중 어느 쪽에서든 실행됩니다.
* [`pydantic`](https://docs.pydantic.dev/): 모든 `mcp.types` 모델이 이 위에 만들어져 있으며, 스키마 생성과 검증도 전부 담당합니다.
* [`httpx2`](https://pypi.org/project/httpx2/): Streamable HTTP와 SSE **클라이언트** 트랜스포트의 기반이 되는 HTTP 클라이언트로, server-sent events 지원이 내장되어 있습니다.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/), [`python-multipart`](https://pypi.org/project/python-multipart/): HTTP **서버** 트랜스포트를 구성합니다.
* [`jsonschema`](https://pypi.org/project/jsonschema/): 도구의 구조화된 출력이 선언된 출력 스키마에 맞는지 검증합니다.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): 인가에 쓰이는 OAuth 토큰 처리를 담당합니다.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): 가벼운 API만 들어 있으므로, OpenTelemetry SDK와 익스포터를 직접 설치하지 않는 한 SDK의 트레이싱 미들웨어에는 아무 비용도 들지 않습니다.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/)와 [`typing-inspection`](https://pypi.org/project/typing-inspection/): Python 3.10에서 최신 타이핑 기능을 쓸 수 있게 해 줍니다.
* [`pywin32`](https://pypi.org/project/pywin32/): Windows 전용으로, `stdio` 하위 프로세스 관리에 사용됩니다.

## 선택적 추가 기능 {#optional-extras}

* `mcp[cli]`는 `mcp` 명령줄 도구(`mcp dev`, `mcp run`, `mcp install`)에 필요한 [`typer`](https://typer.tiangolo.com/)와 [`python-dotenv`](https://pypi.org/project/python-dotenv/)를 추가합니다. 개발하는 동안에는 있는 편이 좋지만, 배포된 서버에는 필요하지 않을 수도 있습니다.
* `mcp[rich]`는 서버 로그를 더 보기 좋게 만들어 주는 [`rich`](https://rich.readthedocs.io/)를 추가합니다.
