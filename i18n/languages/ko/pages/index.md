# MCP Python SDK {#mcp-python-sdk}

!!! info "현재 안정 릴리스 라인인 v2 문서"
    v2가 처음이거나 v1에서 넘어왔다면 **[v2에서 달라진 점](whats-new.md)**에서 변경 사항을 5분 만에 둘러볼 수 있고, **[마이그레이션 가이드](migration.md)**가 모든 호환성 파괴 변경을 다룹니다.
    아직 v1.x를 쓰고 있다면 문서는 [v1.x 문서](https://py.sdk.modelcontextprotocol.io/v1/)에 있습니다.
    부족하거나 헷갈리는 부분이 있다면 [알려주세요](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

**Model Context Protocol(MCP)**은 애플리케이션이 표준화된 방식으로 LLM에 컨텍스트를 제공하게 해 주며, 컨텍스트를 **제공하는** 일과 LLM 상호작용 자체를 분리합니다.

이것이 그 공식 Python SDK입니다. 이를 사용하면 다음과 같은 일을 할 수 있습니다.

* 모든 MCP 호스트에 도구, 리소스, 프롬프트를 노출하는 **MCP 서버를 구축**합니다.
* 모든 MCP 서버에 연결하는 **MCP 클라이언트를 구축**합니다.
* 표준 트랜스포트를 모두 사용합니다. stdio, Streamable HTTP, SSE.

## 요구 사항 {#requirements}

Python 3.10 이상.

## 설치 {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` 엑스트라를 설치하면 `mcp` 명령을 쓸 수 있으며, 개발할 때 필요합니다.
각 의존성이 어떤 역할을 하는지는 [설치](get-started/installation.md)에서 확인하세요.

## 예제 {#example}

### 만들기 {#create-it}

`server.py` 파일을 만드세요.

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

이것으로 완전한 MCP 서버가 완성됩니다.

**도구** 하나(`add`)와 템플릿 **리소스** 하나(`greeting://{name}`)를 노출합니다.

### 실행하기 {#run-it}

```console
uv run mcp dev server.py
```

이 명령은 서버를 실행하고, 서버를 이리저리 시험해 볼 수 있는 대화형 UI인 [MCP Inspector](https://github.com/modelcontextprotocol/inspector)를 엽니다. 출력된 URL을 여세요.

!!! note
    Inspector는 Node.js 앱이므로 `mcp dev`를 쓰려면 `PATH`에 `npx`가 있어야 합니다.

### 사용해 보기 {#try-it}

Inspector에서 **Tools**로 이동해 `a=1`, `b=2`로 `add`를 호출하세요.

`3`이 돌아옵니다.

Inspector는 타입 힌트를 보고 그 폼(`a`용 필수 정수 필드와 `b`용 필수 정수 필드)을 만들었습니다. Claude를 비롯한 다른 모든 MCP 호스트도 마찬가지입니다.

이제 **Resources**로 이동해 `greeting://World`를 읽어 보세요.

```text
Hello, World!
```

### 정리 {#recap}

작성하지 **않은** 것을 다시 살펴보세요.

* JSON Schema가 없습니다. `a: int, b: int` **자체가** 스키마입니다.
* 요청 파싱도, 직렬화도, 검증 코드도 없습니다.
* 프로토콜 처리 코드는 아예 없습니다.

타입 힌트와 docstring이 있는 Python 함수 두 개를 작성했을 뿐입니다. 나머지는 SDK가 처리합니다.

## 다음 단계 {#where-to-go-next}

* **[시작하기](get-started/index.md)**는 설치부터 동작하고 테스트까지 마친 서버까지 안내합니다.
* MCP 서버를 **사용하는** 애플리케이션을 만든다면 **[클라이언트](client/index.md)**부터 시작하세요.
* 이미 FastAPI나 Starlette 앱이 있다면 **[기존 앱에 추가하기](run/asgi.md)**에서 그 안에 MCP 서버를 마운트하는 방법을 확인하세요.
* 정확한 오류 메시지를 찾고 있다면 **[문제 해결](troubleshooting.md)**이 메시지 원문을 그대로 기준으로 정리되어 있습니다.
* v2에서 무엇이 바뀌었는지 궁금하다면 **[v2에서 달라진 점](whats-new.md)**에서 5분 만에 둘러볼 수 있습니다.
* v1에서 마이그레이션한다면 **[마이그레이션 가이드](migration.md)**부터 시작하세요.
* 정확한 시그니처를 찾고 있다면 **[API 레퍼런스](api/mcp/index.md)**가 소스에서 생성되어 있습니다.
* LLM과 함께 읽고 있다면, 이 문서는 [llms.txt](https://llmstxt.org/) 형식으로도 제공됩니다.
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt)는 페이지 색인이고,
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt)는 모든 페이지를 하나의 파일에 담고 있습니다.
