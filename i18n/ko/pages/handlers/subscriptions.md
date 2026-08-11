---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# 구독 {#subscriptions}

서버의 카탈로그는 고정되어 있지 않습니다. 도구는 런타임에 나타나고, 리소스 URI 뒤의 콘텐츠는 바뀝니다.

**구독**은 클라이언트가 이런 변화를 알게 되는 방법입니다. 클라이언트가 `subscriptions/listen` 요청을 한 번 보내면, 그 요청에 대한 응답이 **곧** 스트림입니다. 응답은 열린 채로 유지되며 클라이언트가 요청한 변경 알림을 실어 나릅니다.

## 도구에서 게시하기 {#publish-it-from-the-tool}

서버 쪽에서 할 일은 한 줄, 변경을 게시하는 것뿐입니다.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")`는 해당 URI를 구독한 열린 스트림 모두에 도달합니다. 그 외에는 아무에게도 가지 않습니다.
* `await ctx.notify_tools_changed()`는 도구 목록 변경을 요청한 모든 스트림에 도달합니다. 이를 받은 클라이언트는 `tools/list`를 다시 호출하고, 이제 `sprint_report`를 보게 됩니다.
* 형제 메서드로 `notify_prompts_changed()`와 `notify_resources_changed()`가 있습니다.
* 구독자가 없으면 할 일도 없습니다. 유휴 상태의 서버에 게시하는 것은 아무 동작도 하지 않으므로, 누가 듣고 있는지 확인할 필요가 전혀 없습니다. 무엇이 바뀌었는지만 알리면 됩니다.

`MCPServer`가 `subscriptions/listen`을 대신 처리합니다. 와이어 수준의 의무(첫 프레임으로 보내는 확인 응답, 스트림별 필터링, 모든 프레임에 붙는 구독 id)는 SDK의 몫입니다.

!!! check
    와이어 위에서, 필터에 `board://sprint`를 지정한 스트림은 `complete_task`가 실행된 뒤 다음과 같이 보입니다.

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    업데이트에 **담기지 않은** 것에 주목하세요. 보드 자체가 없습니다. 모든 프레임은 `_meta` 아래에 listen 요청의 JSON-RPC id를 담으며, 그 id가 구독 id입니다. 이 id는 클라이언트가 발급합니다. Python `Client`는 `"listen-1"` 같은 문자열을 쓰고, 다른 클라이언트는 정수를 쓰기도 합니다.

## 요청한 것만 {#only-what-was-asked-for}

필터는 계약입니다. 도구 목록 변경과 리소스 URI 하나를 요청한 스트림은 그 두 종류만 받고 다른 것은 받지 않습니다. 프롬프트 변경을 게시해도 그 스트림은 조용합니다.

`MCPServer`는 리소스 URI를 정확한 문자열로 비교하므로, `board://sprint`를 지정한 스트림은 `board://sprint/tasks/1`에 관해서는 아무것도 듣지 못합니다. 명세는 구독한 URI의 하위 리소스 변경을 서버가 보고하는 것을 허용합니다. `MCPServer`는 절대 그렇게 하지 않지만, 클라이언트는 이를 예상하도록 만들어져 있습니다.

스트림이 **아닌** 것 두 가지가 있습니다.

* **재생 로그가 아닙니다.** 끊어진 스트림은 사라지며, 아무도 연결되어 있지 않은 동안 게시된 이벤트는 대기열에 쌓이지 않습니다. 클라이언트는 다시 listen하고 다시 가져옵니다.
* **2025 방식이 아닙니다.** `resources/subscribe`를 호출한 클라이언트는 `ctx.session.send_resource_updated(uri)`로 처리됩니다. `notify_*` 메서드는 `subscriptions/listen` 스트림에만 도달합니다.

## 누가 지켜볼 수 있는지 정하기 {#deciding-who-may-watch}

기본적으로 요청된 모든 종류와 URI가 받아들여집니다. 어떤 호출자든 게시하는 모든 URI를 지켜볼 수 있습니다. 아무도 읽지 않으므로 read 핸들러는 전혀 참조되지 않습니다. `files://{name}` 핸들러가 거절할 호출자라도 `files://payroll.csv`에 스트림을 열어 그것이 바뀌었다는 사실과 언제 바뀌었는지를 알 수 있습니다. 내용은 절대 알 수 없고, 무엇이 존재하는지 탐색할 수도 없습니다. 알 수 없는 URI도 받아들여지며 단지 이벤트가 발생하지 않을 뿐이기 때문입니다. 좁지만 실재하는 문제이므로, 멀티테넌트 서버에서 사용자별 URI를 게시하기 전에 관문을 두세요.

관문은 미들웨어입니다. SDK가 확인 응답을 보내기 전에 `subscriptions/listen` 요청을 보고, 호출자가 읽어서는 안 되는 것을 하나라도 요청하면 거부합니다.

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params`는 원시 요청이므로, 미들웨어가 직접 `SubscriptionsListenRequestParams`로 검증하고 클라이언트가 요청한 필터를 읽습니다.
* 거부는 `call_next(ctx)` 전에 `MCPError`를 발생시키는 것입니다. 클라이언트는 그 오류를 받고 스트림은 받지 못하며, 연결은 계속 유지됩니다. 메시지는 URI를 명시하지 않고 일관되게 유지하여, 거부가 어떤 URI가 보호되는지를 확인해 주는 일이 없도록 하세요.
* 하나의 `can_access(user, uri)`가 두 질문 모두에 답합니다. 리소스 핸들러는 `resources/read`에서, 미들웨어는 `subscriptions/listen`에서 이를 묻습니다. 테이블을 데이터베이스나 RBAC 시스템으로 바꿔도 둘은 계속 보조를 맞춥니다.
* 이 결정은 스트림의 수명 동안 유지됩니다. 이벤트마다 다시 확인하지 않으므로, 호출자의 접근 권한이 스트림 도중에 만료될 수 있다면(만료되는 토큰) 그 시점에 해당 호출자의 연결을 끊으세요.

미들웨어가 그 밖에 무엇을 감싸는지, 왜 잠정적(provisional)으로 표시되어 있는지를 포함한 전체 미들웨어 계약은 **[미들웨어](../advanced/middleware.md)**에 있습니다.

## 클라이언트 쪽 {#the-client-end}

다음은 그 스트림의 반대편에서 보드를 따라가는 클라이언트입니다.

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

`client.listen(...)`에 진입하면 요청을 보내고 서버의 확인 응답을 기다리므로, 블록이 시작될 때 스트림은 이미 살아 있고, 타입이 지정된 각 이벤트는 다시 가져오라는 신호일 뿐 절대 페이로드가 아닙니다. 이것이 한 화면에 담긴 계약의 전부입니다. 주 흐름과 나란히 지켜보기, 스트림 종료, 다시 listen하기 등 클라이언트 쪽의 나머지 내용은 별도 페이지에 있습니다. **클라이언트** 아래의 **[구독](../client/subscriptions.md)**을 참고하세요.

## 단일 프로세스를 넘어 확장하기 {#scaling-past-one-process}

게시된 이벤트는 핸들러에서 열린 스트림까지 `SubscriptionBus`를 거쳐 이동합니다. 기본은 인메모리입니다. 프로세스 하나, 그 안의 모든 스트림입니다. 로드 밸런서 뒤에서 레플리카를 실행하기 전까지는 이것이 정답입니다. 그 이후에는 클라이언트의 스트림이 한 레플리카에 고정되고, 다른 레플리카에서 게시한 이벤트가 그 스트림에 도달해야 하기 때문입니다.

그 이음매는 직접 구현할 부분입니다. 사용하는 pub/sub 백엔드 위에 메서드 두 개를 만들면 됩니다.

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode`는 직접 작성하며, 도착하는 메시지를 디코드해 등록된 모든 리스너를 호출하는 각 레플리카의 리더 태스크도 마찬가지입니다. 리스너는 동기 함수이고, 예외를 발생시켜서는 안 되며, 서버의 이벤트 루프에서 실행됩니다.

버스는 타입이 지정된 `ServerEvent` 값, 즉 작은 데이터클래스 네 개를 실어 나르며 JSON-RPC는 절대 나르지 않습니다. 스탬핑, 필터링, 스트림 생명 주기는 SDK에 남아 있으므로 버스 구현이 프로토콜을 깨뜨릴 수는 없습니다. 프로세스 사이에서 이벤트를 옮길 수 있을 뿐입니다.

요청 바깥에서 게시하려면 참조를 보유할 수 있도록 버스를 직접 생성하세요. `MCPServer`는 아무것도 전달하지 않으면 내부적으로 하나를 만들며, 이를 노출하지 않습니다.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## 저수준 구성 {#the-low-level-composition}

저수준 `Server`에는 미리 연결된 것이 아무것도 없으며, 같은 부품이 세 줄로 조립됩니다.

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* 버스를 직접 소유하므로 버스에 직접 게시합니다. `await bus.publish(ResourceUpdated(uri=...))`. 핸들러가 닿을 수 있는 곳에 두세요. 여기서는 모듈 스코프이고, 더 큰 앱에서는 lifespan입니다.
* `ListenHandler(bus)`는 `MCPServer`가 등록하는 것과 같은 핸들러이고, `on_subscriptions_listen=`은 평범한 핸들러 슬롯입니다. 다른 의미 체계를 원하면 그 슬롯에 직접 만든 callable을 넣으세요. 그러면 명세상의 의무가 작성자에게 넘어옵니다. 먼저 확인 응답을 보내고, 모든 프레임에 구독 id를 찍고, 필터 밖의 것은 아무것도 전달하지 않아야 합니다.
* `ListenHandler.close()`는 열린 스트림을 모두 정상적으로 종료합니다. 각 스트림은 마지막 프레임으로 listen 요청의 결과를 받으며, 이는 서버가 의도적으로 구독을 끝냈음을 나타내는 명세상의 방식입니다. 이 메서드는 스트림이 플러시를 마치기 전에 반환하므로, 트랜스포트를 해체하기 전에 잠깐 여유를 주세요. 이를 호출하지 않으면 스트림은 클라이언트가 연결을 끊을 때 끝납니다.

## 요약 {#recap}

* 클라이언트는 `subscriptions/listen` 요청 하나로 참여하고, 그 응답이 스트림입니다. 이를 처리하는 기능은 내장되어 있습니다.
* `ctx.notify_*`로 게시하면 스탬핑, 필터링, 생명 주기 작업은 SDK가 처리합니다.
* 이벤트는 페이로드가 아니라 신호입니다. 양쪽 모두 다시 가져옵니다.
* 클라이언트 쪽은 `async with client.listen(...)`입니다. 자세한 내용은 **클라이언트** 아래의 **[구독](../client/subscriptions.md)**에서 확인하세요.
* 저수준 `Server`에서는 같은 부품을 직접 조립합니다. 버스, `ListenHandler(bus)`, `on_subscriptions_listen` 슬롯입니다.
* 스케일 아웃은 메서드 두 개짜리 `SubscriptionBus`를 구현하고 `MCPServer(subscriptions=...)`로 전달하는 것을 뜻합니다.

레플리카 하나 뒤에서든 스무 개 뒤에서든, 이 모든 것을 처리하는 서버를 실행하는 방법은 **[배포와 확장](../run/deploy.md)**에서 확인하세요.
