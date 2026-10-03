---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# 리소스 {#resources}

**리소스**는 애플리케이션이 읽도록 노출하는 데이터입니다.

도구와 리소스를 가르는 기준이 바로 이것입니다. 도구는 **모델**이 호출하기로 결정하는 것입니다. 리소스는 **애플리케이션**이 불러오기로 결정해서(설정 파일, 레코드, 문서 등) 모델에게 컨텍스트로 제시하는 것입니다.

평범한 Python 함수에 `@mcp.resource(uri)`를 붙이면 리소스를 선언할 수 있습니다.

## 첫 번째 리소스 {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

도구와 같은 모양이지만 한 가지가 더 있습니다. 바로 **URI**입니다. 리소스는 이름이 아니라 주소로 지정합니다. 클라이언트는 `config://app`을 요청하지, `get_config`를 요청하는 일은 없습니다.

나머지는 SDK가 여전히 함수에서 읽어 냅니다.

* **이름**은 함수 이름인 `get_config`입니다.
* 클라이언트가 보는 **설명**은 독스트링입니다.
* **내용**은 반환하는 값 그대로입니다.

`resources/list` 때 클라이언트는 다음을 받습니다.

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

그리고 클라이언트가 `config://app`을 읽으면 함수가 실행되고 반환값이 텍스트로 돌아옵니다.

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    목록 조회는 비용이 거의 들지 않습니다. 함수는 `resources/list` 때는 호출되지 **않고**,
    `resources/read` 때만, 그것도 요청된 URI에 한해서만 호출됩니다. 리소스를 천 개 노출해도
    비용은 누군가 실제로 여는 리소스만큼만 듭니다.

### 직접 해 보기 {#try-it}

MCP Inspector로 서버를 실행하세요.

```console
uv run mcp dev server.py
```

출력되는 URL을 열고 **Resources** 탭으로 이동하세요. `config://app`이 설명과 함께 목록에 있습니다. 클릭하면 Inspector가 읽어 들이며, 앞서 작성한 설정 두 줄이 보입니다.

## 리소스 템플릿 {#resource-templates}

레코드마다 URI를 하나씩 두는 방식은 확장되지 않습니다. URI에 **플레이스홀더**를 넣고 함수에 그에 대응하는 매개변수를 두세요.

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

URI에는 `{user_id}` 자리를, 함수에는 `user_id: str` 매개변수를 둡니다. 계약은 이것이 전부입니다.

이제 이것은 **리소스 템플릿**이며, 있는 곳도 바뀝니다. `resources/list`에서 빠지고 대신 `resources/templates/list`에 주소가 아닌 패턴으로 나타납니다.

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

클라이언트는 플레이스홀더를 채워 `users://42/profile`, `users://ada/profile` 같은 구체적인 URI를 읽습니다. 함수 하나가 이 모든 URI에 응답하며, 일치한 값은 `user_id`로 전달됩니다.

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

결과의 `uri`에 주목하세요. 템플릿이 아니라 클라이언트가 요청한 **구체적인** URI입니다.

!!! check
    플레이스홀더와 매개변수는 서로 일치해야 합니다. URI는 여전히 `{user_id}`인데 함수 매개변수
    이름을 `user`로 바꾸면, 어떤 클라이언트도 접근하기 전인 **임포트 시점에** 데코레이터가
    거부합니다.

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    불일치는 버그일 수밖에 없으므로, SDK는 불일치가 있는 채로는 서버를 아예 시작할 수 없게 만듭니다.

플레이스홀더 문법은 [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)을 따릅니다. 여러 세그먼트에 걸친 값에는 `{+path}`, 선택적 쿼리 매개변수에는 `{?q,lang}` 등을 쓸 수 있습니다. SDK는 추출된 값에 기본적으로 경로 안전성 검사도 적용합니다. 전체 레퍼런스는 **[URI 템플릿과 경로 안전성](uri-templates.md)**에서 확인하세요.

`get_user_profile`은 `Context`로 어노테이션한 매개변수도 받을 수 있습니다. SDK는 이 매개변수를 URI 매개변수로 취급하는 일 없이 주입해 주며, 무엇을 제공하는지는 **[Context](../handlers/context.md)** 페이지에서 다룹니다.

## 반환하는 값 {#what-you-return}

`str`만 반환할 수 있는 것은 아닙니다. 리소스마다 `mime_type`을 지정하고 알맞은 값을 반환하세요.

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme`는 `str`을 반환하므로 그대로 전송됩니다. 가장 흔한 경우입니다.
* `catalog_stats`는 `dict`를 반환하므로 SDK가 대신 **JSON 텍스트**로 직렬화합니다.

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover`는 `bytes`를 반환하므로 클라이언트는 `TextResourceContents` 대신 `BlobResourceContents`를 받으며, 반환한 바이트는 base64로 인코딩되어 `blob` 필드에 담깁니다.

JSON으로 직렬화할 수 있는 다른 모든 것(리스트, Pydantic 모델, 데이터클래스)에도 같은 규칙이 적용됩니다. `str`도 `bytes`도 아니면 JSON이 됩니다.

`mime_type`은 직접 선언하는 값이며 기본값은 `text/plain`입니다. SDK는 반환값을 들여다보고 이를 추측하는 일이 결코 없으므로, 따로 표시하지 않은 `dict` 리소스는 클라이언트에 여전히 일반 텍스트로 알려집니다.

!!! tip
    이름, 제목, 설명을 함수에서 끌어내고 싶지 않다면 `@mcp.resource()`는 `name=`, `title=`,
    `description=`도 받습니다. 그리고 작성할 함수가 아예 없는 경우에는
    `mcp.server.mcpserver.resources`에 미리 만들어진 `Resource` 클래스(`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`)가 있으며,
    `mcp.add_resource(...)`로 등록하면 됩니다.

클라이언트는 리소스를 **구독**해서 리소스가 바뀔 때 알림을 받을 수도 있습니다. 이것은 클라이언트 쪽 이야기이며 **[클라이언트](../client/index.md)**에서 다룹니다.

## 요약 {#recap}

* 함수에 `@mcp.resource(uri)`를 붙이면 리소스가 됩니다. URI는 주소, 반환값은 내용, 독스트링은 설명입니다.
* URI에 `{placeholder}` 자리가 있으면 **템플릿**이 됩니다. `resources/templates/list`에 나열되며 함수 하나가 일치하는 모든 URI를 처리합니다.
* 플레이스홀더 이름은 함수의 매개변수 이름과 같아야 합니다. 틀리면 프로덕션이 아니라 임포트 시점에 알게 됩니다.
* 함수는 리소스를 나열할 때가 아니라 **읽을** 때 실행됩니다.
* `str`은 텍스트가 되고, `bytes`는 base64 blob이 되며, 그 밖의 것은 모두 JSON 텍스트가 됩니다. 레이블은 `mime_type=` 인자로 붙입니다.
* 도구는 모델이 행동하기 위한 것이고, 리소스는 애플리케이션이 읽기 위한 것입니다.

세 번째 프리미티브, 즉 사람이 메뉴에서 고르는 것은 **[프롬프트](prompts.md)**입니다.
