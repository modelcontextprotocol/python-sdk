---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Lifespan {#lifespan}

실제 서버는 대부분 데이터베이스 풀, HTTP 클라이언트, 로드된 모델처럼 살아 있는 동안 내내 유지하는 무언가가 있습니다.

호출할 때마다 새로 만들고 싶지는 않고, 깔끔하게 닫고 싶기는 합니다. 바로 이를 위한 것이 **lifespan**입니다.

## 타입이 지정된 lifespan {#a-typed-lifespan}

lifespan은 서버를 받아 **객체 하나**를 `yield`하는 `@asynccontextmanager`입니다. yield한 객체는 서버가 실행되는 동안 모든 핸들러에서 사용할 수 있습니다.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

아래에서 위로 읽어 보세요.

* `app_lifespan`은 `yield` **앞에서** `Database`에 연결하고, 그 **뒤** `finally`에서 연결을 끊습니다. 이것이 시작과 종료입니다.
* 설정한 것을 담는 평범한 dataclass인 `AppContext`를 yield합니다. 오늘은 필드 하나, 내일은 열 개입니다.
* `MCPServer("Bookshop", lifespan=app_lifespan)`이 연결 작업의 전부입니다.
* 도구 안에서 yield된 객체는 `ctx.request_context.lifespan_context`입니다.

lifespan은 **한 번** 실행됩니다. 서버가 시작될 때(첫 요청 전) 진입하고 서버가 멈출 때 빠져나옵니다. 그 사이의 모든 요청은 같은 `AppContext`를 공유합니다.

!!! info
    FastAPI `lifespan`을 작성해 본 적이 있다면 이미 아는 내용입니다. 같은 데코레이터, 같은 `yield`, 같은 `finally`입니다.

### 모델에게 보이는 것 {#what-the-model-sees}

새로운 것은 없습니다. `ctx`는 **Context** 매개변수이므로 SDK가 주입하며, 입력 스키마에는 절대 들어가지 않습니다.

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

모델이 전달할 수 있는 인자는 `genre`뿐입니다. lifespan은 서버 내부의 일입니다.

`@mcp.resource()`와 `@mcp.prompt()` 함수도 `ctx` 매개변수를 받을 수 있는데, 다음 절에서 설명할 이유로 타입 매개변수 없는 `Context`로 씁니다. `ctx`가 담고 있는 모든 것은 **[Context](context.md)**에서 확인하세요.

### 제대로 된 타입 지정 {#it-really-is-typed}

어노테이션을 다시 보세요. `ctx: Context[AppContext]`입니다.

이 타입 매개변수 하나 덕분에 타입 검사기에게 `ctx.request_context.lifespan_context`는 **곧** `AppContext`입니다. `.db`는 자동 완성되고, `.dbb`는 서버를 실행하기도 전에 오류가 됩니다.

대신 타입 매개변수 없는 `Context`를 쓰면 `lifespan_context`의 타입은 `dict[str, Any]`가 됩니다. 타입 검사기로서는 lifespan이 무엇을 yield했는지 알 방법이 없기 때문입니다. 객체는 런타임에 여전히 존재하지만, 도움은 잃게 됩니다.

!!! warning
    `Context[AppContext]`는 **도구 전용** 표기입니다. `@mcp.resource()`나
    `@mcp.prompt()` 함수에 붙이면 해당 핸들러 호출은 모두 실패합니다. 클라이언트는 오류를 돌려받고,
    서버 로그에 그 이유가 나타납니다.

    ```text
    Context is not available outside of a request
    ```

    리소스와 프롬프트에서는 타입 매개변수 없는 `ctx: Context`를 쓰세요. lifespan이 yield한 객체는
    런타임에 여전히 `ctx.request_context.lifespan_context`에 있습니다. 포기하는 것은 타입 매개변수이지
    객체가 아닙니다.

!!! tip
    lifespan은 항상 있습니다. 전달하지 않으면 SDK의 기본 lifespan이 빈 `dict`를 yield하므로
    `ctx.request_context.lifespan_context`는 `{}`이며, 절대 `None`이 아닙니다. 타입 매개변수 없는
    `Context`가 이를 `dict[str, Any]`로 타입 지정하는 것도 이 기본값 때문입니다.

## 직접 확인하기 {#watch-it-happen}

"시작 코드는 첫 요청 전에 실행된다"는 말은 그냥 믿고 넘어갈 것이 아니라 직접 확인해 볼 만한 문장입니다.

서버를 생명 주기만 남도록 줄여 보세요. `Database`에 `connected` 플래그를 두고, `connect()`와 `disconnect()`에서 이를 뒤집고, 이 값을 보고하는 도구를 추가합니다.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database`가 모듈 수준에 있는 이유는 단 하나, 서버 **바깥**에서 볼 수 있게 하기 위해서입니다.

!!! check
    세 시점, 세 값입니다.

    * 서버가 시작되기 전에는 `database.connected`가 `False`입니다. 모듈을 임포트해도 아무것도 연결되지 않았습니다.
    * 실행 중에 `database_status`를 호출하면 결과는 `"connected"`입니다.
    * 서버를 멈추면 `finally` 블록이 실행되고 `database.connected`는 다시 `False`가 됩니다.

    작업은 정확히 배치한 곳, 즉 `yield` 주변에서 일어났습니다. 임포트 시점도, 요청마다도 아닙니다.

## 요약 {#recap}

* `lifespan=` 매개변수는 서버를 받아 객체 하나를 `yield`하는 `@asynccontextmanager`를 받습니다.
* `yield` 앞의 코드는 시작입니다. 뒤의 `finally`는 종료입니다.
* 요청마다 실행되는 것이 아니라 서버의 전체 수명을 감싸며 한 번 실행됩니다.
* `yield`한 것은 모든 도구, 리소스, 프롬프트에서 `ctx.request_context.lifespan_context`입니다.
* `ctx: Context[AppContext]`는 도구에서 이 접근에 완전한 타입을 부여합니다. 리소스와 프롬프트는 타입 매개변수 없는 `Context`를 받습니다.
* `lifespan=` 매개변수가 없으면 빈 `dict`이며, 절대 `None`이 아닙니다.

호출 도중 멈추고 사용자만 아는 것을 사용자에게 묻는 핸들러는 **[엘리시테이션(elicitation)](elicitation.md)**에서 다룹니다.
