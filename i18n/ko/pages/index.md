---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "현재 안정 릴리스 계열인 v2를 다루는 문서"
    v2를 처음 접하거나 v1에서 넘어왔다면 **[v2에서 달라진 점](whats-new.md)**에서 바뀐 내용을 5분 만에 둘러볼 수 있고, **[마이그레이션 가이드](migration.md)**에서 호환성을 깨는 변경 사항을 빠짐없이 확인할 수 있습니다.
    아직 v1.x를 사용 중이라면 해당 버전의 문서는 [v1.x 문서](https://py.sdk.modelcontextprotocol.io/v1/)에서 볼 수 있습니다.
    매끄럽지 않거나 헷갈리는 부분이 있다면 [알려 주세요](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

**Model Context Protocol(MCP)**은 애플리케이션이 표준화된 방식으로 LLM에 컨텍스트를 제공할 수 있게 해 주며, 컨텍스트를 **제공하는** 일을 LLM과의 상호작용 자체와 분리합니다.

이 라이브러리가 바로 MCP의 공식 Python SDK입니다. 이 SDK로 다음과 같은 일을 할 수 있습니다.

* 어떤 MCP 호스트에든 도구, 리소스, 프롬프트를 노출하는 **MCP 서버를 만듭니다**.
* 어떤 MCP 서버에든 연결하는 **MCP 클라이언트를 만듭니다**.
* 모든 표준 트랜스포트(stdio, Streamable HTTP, SSE)로 통신합니다.

## 요구 사항 {#requirements}

Python 3.10 이상이 필요합니다.

## 설치 {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` extra는 `mcp` 명령을 제공하며, 개발할 때 이 명령을 쓰게 됩니다.
각 의존성의 용도는 [설치](get-started/installation.md)에서 확인하세요.

## 예제 {#example}

### 만들기 {#create-it}

`server.py` 파일을 만드세요.

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

이것으로 완전한 MCP 서버가 완성됩니다.

이 서버는 **도구** 하나(`add`)와 템플릿 **리소스** 하나(`greeting://{name}`)를 노출합니다.

### 실행하기 {#run-it}

```console
uv run mcp dev server.py
```

이 명령은 서버를 시작하고, 서버를 이것저것 눌러 볼 수 있는 대화형 UI인 [MCP Inspector](https://github.com/modelcontextprotocol/inspector)를 엽니다. 출력되는 URL을 여세요.

!!! note
    Inspector는 Node.js 앱이므로 `mcp dev`를 쓰려면 `PATH`에 `npx`가 있어야 합니다.

### 직접 해 보기 {#try-it}

Inspector에서 **Tools**로 이동해 `a=1`, `b=2` 값으로 `add`를 호출하세요.

`3`이 돌아옵니다.

Inspector는 타입 힌트를 바탕으로 그 입력 폼(`a`에 해당하는 필수 정수 필드 하나, `b`에 해당하는 필드 하나)을 만들었습니다. Claude도, 다른 모든 MCP 호스트도 똑같이 합니다.

이제 **Resources**로 이동해 `greeting://World`를 읽어 보세요.

```text
Hello, World!
```

### 요약 {#recap}

작성하지 **않은** 것이 무엇인지 다시 살펴보세요.

* JSON Schema가 없습니다. `a: int, b: int`가 **바로** 스키마입니다.
* 요청 파싱도, 직렬화도, 유효성 검사 코드도 없습니다.
* 프로토콜 처리는 전혀 없습니다.

타입 힌트와 독스트링이 달린 Python 함수 두 개를 작성했을 뿐입니다. SDK가 나머지를 처리합니다.

## 다음으로 살펴볼 곳 {#where-to-go-next}

* **[시작하기](get-started/index.md)**는 설치에서 출발해 제대로 동작하고 테스트까지 마친 서버에 이르기까지 안내합니다.
* MCP 서버를 **사용하는** 애플리케이션을 만들고 있다면 **[클라이언트](client/index.md)**부터 시작하세요.
* 이미 FastAPI나 Starlette 앱이 있다면 **[기존 앱에 추가하기](run/asgi.md)**를 참고하세요. 그 앱 안에 MCP 서버를 마운트하는 방법을 다룹니다.
* 특정 오류 메시지를 추적하고 있다면 **[문제 해결](troubleshooting.md)**을 보세요. 오류 메시지 원문을 기준으로 정리되어 있습니다.
* v2에서 무엇이 바뀌었는지 궁금하다면 **[v2에서 달라진 점](whats-new.md)**에서 5분 만에 둘러볼 수 있습니다.
* v1에서 마이그레이션한다면 **[마이그레이션 가이드](migration.md)**부터 시작하세요.
* 정확한 시그니처를 찾고 있다면 소스 코드에서 생성된 **[API 레퍼런스](api/mcp/index.md)**를 보세요.
* LLM으로 이 문서를 읽고 있다면 [llms.txt](https://llmstxt.org/) 형식으로도 게시되어 있으니 참고하세요.
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) 파일은 페이지 색인이고,
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) 파일은 모든 페이지를 한 파일에 담고 있습니다.
