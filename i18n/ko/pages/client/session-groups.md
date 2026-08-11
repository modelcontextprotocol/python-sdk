---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# 세션 그룹 {#session-groups}

`Client`는 하나의 서버에 연결합니다. 실제 애플리케이션은 여러 서버(검색 서버, 데이터베이스 서버, 내부 API)가 필요한 경우가 많고, 결국 서버마다 연결과 도구 목록을 따로 관리하게 됩니다.

**`ClientSessionGroup`**은 여러 연결을 담고, 각 연결이 제공하는 모든 것을 하나의 뷰로 합쳐 주는 단일 객체입니다.

## 서버 두 개 {#two-servers}

평범한 서버 두 개로 시작합니다. 서로 아무 관련이 없으므로 둘 다 자연스럽게 도구 이름을 `search`라고 지었습니다.

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## 그룹 하나 {#one-group}

`ClientSessionGroup`을 만들고 서버마다 **`connect_to_server`**를 한 번씩 호출하세요.

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server`는 서버 객체가 아니라 트랜스포트 매개변수를 받습니다. 서브프로세스를 띄우려면 `StdioServerParameters`(`mcp`에서 가져옴), 이미 URL에서 수신 대기 중인 서버라면 `StreamableHttpParameters` / `SseServerParameters`(`mcp.client.session_group`에서 가져옴)를 사용합니다.
* `group.tools`는 연결된 모든 서버의 도구를 담은 `dict[str, Tool]`입니다. `group.resources`와 `group.prompts`도 같은 형태입니다.
* `group.call_tool(name, arguments)`는 이름을 조회해 그 이름을 소유한 세션을 찾고 호출을 전달합니다. 어느 서버인지 지정할 일이 없습니다.

!!! check
    `client.py`를 두 서버와 같은 곳에 두고 실행하세요. 두 번째 `connect_to_server`가 거부합니다.

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    이것은 `MCPError`이며, 두 번째 서버의 어떤 것도 등록되기 전에 발생합니다. 이름은 그룹 **전체**에서
    고유해야 하고, 직접 제어하지 않는 두 서버는 언젠가 충돌하기 마련입니다.

## `component_name_hook` {#component_name_hook}

이 문제는 서버가 아니라 그룹에서 해결합니다. `(name, server_info)`를 받는 함수를 전달하면 그룹이 등록하는 모든 이름에 대해 그 함수를 실행합니다.

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

다시 실행하세요. 이제 `print(sorted(group.tools))`가 둘 다 보여 줍니다.

```text
['Library.search', 'Web.search']
```

* **키**는 직접 정한 것입니다. `by_server`가 `server_info.name`, 즉 각 `MCPServer(...)`를 생성할 때 지정한 이름으로 키를 만들었습니다.
* 안에 든 `Tool`은 그대로입니다. `group.tools["Web.search"].name`은 여전히 `"search"`이며, `call_tool`이 전송할 때 쓰는 이름도 바로 이것입니다. 접두사는 프로세스 밖으로 나가지 않습니다.
* 도구만 해당하는 것이 아닙니다. 라이브러리의 `hours` 리소스는 `Library.hours`로 등록됩니다.

!!! tip
    훅은 충돌이 있을 때만이 아니라 **모든** 서버의 **모든** 이름에 대해 실행됩니다. 충돌 시에만 접두사를
    붙이는 모드는 없습니다. 방식을 하나 정하고 어디에나 적용되도록 하세요.

## 서버 추가와 제거 {#adding-and-removing-servers}

`connect_to_server`는 자신이 연 `ClientSession`을 반환합니다. 나중에 그 서버를 빼고 싶다면 이 값을 보관해 두세요. `await group.disconnect_from_server(session)`이 그 서버의 도구, 리소스, 프롬프트를 그룹에서 제거합니다.

이미 연결된 `ClientSession`을 갖고 있다면(`Client.session`이 그런 예입니다) 새 트랜스포트를 여는 대신 `await group.connect_with_session(server_info, session)`에 넘기세요. 같은 방식으로 합쳐집니다. 그룹은 자신이 열지 않은 세션을 절대 닫지 않습니다. `server_info`는 구성 요소 접두사에 쓰일 서버 이름을 지정합니다. 2026년대 연결에서는 `client.server_info`가 `None`일 수 있으므로(신원 정보는 선택 사항입니다), 그런 경우에는 직접 만든 `Implementation(name=..., version=...)`을 전달하세요.

## 고전 핸드셰이크 {#the-classic-handshake}

`ClientSessionGroup`은 `Client`가 아니라 `ClientSession` 위에 만들어졌습니다. `connect_to_server`는 매번 고전적인 `initialize` 핸드셰이크를 실행합니다. **[프로토콜 버전](../protocol-versions.md)**에서 설명하는 `server/discover` 탐색은 보내지 않습니다. 모든 MCP 서버가 이 핸드셰이크를 이해하므로 호환성에서 잃는 것은 없습니다. 다만 더 나은 경로를 지원하는 서버에도 그룹은 더 오래되고 느린 경로를 택한다는 뜻일 뿐입니다.

## 요약 {#recap}

* `ClientSessionGroup`은 여러 서버 연결을 담고 도구, 리소스, 프롬프트를 각각 하나의 `dict`로 합칩니다.
* 서버마다 `connect_to_server(params)`를 호출합니다. `Client`가 받는 서버 객체나 URL이 아니라 트랜스포트 매개변수를 받습니다.
* `group.call_tool(name, arguments)`는 소유한 서버로 알아서 라우팅합니다.
* 이름은 그룹 전체에서 고유해야 합니다. `search` 도구를 가진 두 서버는 그대로는 공존할 수 없습니다.
* `component_name_hook=`은 등록되는 모든 이름을 다시 씁니다. 딕셔너리 키는 바뀌지만 전송되는 이름은 바뀌지 않습니다.
* `connect_with_session`은 이미 가진 세션을 추가하고, `disconnect_from_server`는 세션을 제거합니다.

그룹이 사용하는 핸드셰이크(그리고 `Client`가 선호하는 더 빠른 핸드셰이크)에 관한 자세한 내용은 **[프로토콜 버전](../protocol-versions.md)**에서 확인하세요.
