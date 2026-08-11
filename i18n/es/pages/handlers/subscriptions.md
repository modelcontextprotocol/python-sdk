---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# Suscripciones {#subscriptions}

El catálogo de un servidor no es fijo. Las herramientas aparecen en tiempo de ejecución, y el contenido detrás del URI de un recurso cambia.

Las **suscripciones** son la forma en que un cliente se entera. El cliente envía una solicitud `subscriptions/listen`, y la respuesta a esa solicitud *es* el flujo: queda abierto y transporta las notificaciones de cambio que el cliente pidió.

## Publícalo desde la herramienta {#publish-it-from-the-tool}

Tu parte es una sola línea: publicar el cambio.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` llega a cada flujo abierto que se suscribió a ese URI. A nadie más.
* `await ctx.notify_tools_changed()` llega a cada flujo que pidió los cambios en la lista de herramientas. Un cliente que lo recibe vuelve a llamar a `tools/list`, y ahora ve `sprint_report`.
* Los métodos hermanos son `notify_prompts_changed()` y `notify_resources_changed()`.
* Sin suscriptores, sin trabajo. Publicar en un servidor inactivo no hace nada, así que nunca compruebas si alguien está escuchando. Declaras qué cambió.

`MCPServer` atiende `subscriptions/listen` por ti. Las obligaciones del canal (el acuse de recibo como primera trama, el filtrado por flujo, el id de suscripción en cada trama) son trabajo del SDK.

!!! check
    En el canal, un flujo cuyo filtro nombró `board://sprint` se ve así después de que se ejecuta `complete_task`:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    Fíjate en lo que la actualización *no* lleva: el tablero. Cada trama lleva el id JSON-RPC de la solicitud listen bajo `_meta`, y ese id es el id de suscripción. Lo genera el cliente: el `Client` de Python usa cadenas como `"listen-1"`; otros clientes pueden usar enteros.

## Solo lo que se pidió {#only-what-was-asked-for}

El filtro es un contrato. Un flujo que solicitó los cambios en la lista de herramientas y un URI de recurso recibe esos dos tipos y nada más. Publica un cambio de prompt y ese flujo se queda en silencio.

`MCPServer` compara los URI de recurso como cadenas exactas, así que un flujo que nombró `board://sprint` no se entera de nada sobre `board://sprint/tasks/1`. La especificación permite que un servidor informe de un cambio en un subrecurso de un URI suscrito; `MCPServer` nunca lo hace, pero los clientes están construidos para esperarlo.

Dos cosas que el flujo *no* es:

* **No es un registro de repetición.** Un flujo caído se pierde, y los eventos publicados mientras nadie estaba conectado no se encolan. Los clientes vuelven a escuchar y vuelven a consultar.
* **No es la vía de 2025.** A los clientes que llamaron a `resources/subscribe` los atiende `ctx.session.send_resource_updated(uri)`. Los métodos `notify_*` llegan solo a los flujos de `subscriptions/listen`.

## Decidir quién puede observar {#deciding-who-may-watch}

Por defecto se acepta cada tipo y URI solicitado: cualquier llamador puede observar cualquier URI que publiques. Nada consulta tu handler de lectura, porque nadie está leyendo: un llamador al que tu handler `files://{name}` rechazaría puede igualmente abrir un flujo sobre `files://payroll.csv` y enterarse de que cambió, y cuándo. Nunca conoce el contenido, y no puede sondear qué existe, porque un URI desconocido también se acepta y simplemente nunca se dispara. Acotado pero real, así que contrólalo antes de publicar URI por usuario desde un servidor multiinquilino.

El control es un middleware. Ve la solicitud `subscriptions/listen` antes de que el SDK la acuse y la rechaza cuando el llamador pide algo que no puede leer:

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` es la solicitud en bruto, así que el propio middleware la valida como `SubscriptionsListenRequestParams` y lee el filtro que pidió el cliente.
* El rechazo es un `MCPError` lanzado antes de `call_next(ctx)`: el cliente recibe ese error y ningún flujo, y la conexión sigue. Mantén el mensaje uniforme, sin nombrar ningún URI, para que un rechazo nunca confirme qué URI están protegidos.
* Un único `can_access(user, uri)` responde ambas preguntas. El handler del recurso lo consulta en `resources/read`; el middleware lo consulta en `subscriptions/listen`. Cambia la tabla por una base de datos o por tu sistema RBAC y ambos siguen coordinados.
* La decisión vale durante toda la vida del flujo. No hay nueva comprobación por evento, así que si el acceso de un llamador puede caducar a mitad del flujo (un token que expira), termina la conexión de ese llamador cuando ocurra.

El contrato completo del middleware, incluido qué más envuelve y por qué está marcado como provisional, está en **[Middleware](../advanced/middleware.md)**.

## El lado del cliente {#the-client-end}

Aquí tienes un cliente al otro lado de ese flujo, siguiendo el tablero:

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Entrar en `client.listen(...)` envía la solicitud y espera tu acuse de recibo, así que el flujo está activo cuando empieza el bloque, y cada evento tipado es una señal para volver a consultar, nunca un payload. Ese es todo el contrato en una pantalla. Todo lo demás sobre el lado del cliente vive en su propia página: observar junto a un flujo principal, finales de flujo y volver a escuchar. Consulta **[Suscripciones](../client/subscriptions.md)** en *Clientes*.

## Escalar más allá de un proceso {#scaling-past-one-process}

Las publicaciones viajan desde tu handler hasta los flujos abiertos a través de un `SubscriptionBus`. El valor por defecto es en memoria: un proceso, con todos los flujos dentro. Esa es la respuesta correcta hasta que ejecutas réplicas detrás de un balanceador de carga, porque entonces el flujo de un cliente queda fijado a una réplica, y una publicación en otra réplica tiene que llegar hasta él.

Esa pieza te toca implementarla a ti: dos métodos sobre tu backend de pub/sub.

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

`encode` es tuyo, y también lo es la tarea lectora de cada réplica que decodifica los mensajes que llegan y llama a cada listener registrado. Los listeners son síncronos, no deben lanzar excepciones y se ejecutan en el bucle de eventos del servidor.

El bus transporta valores `ServerEvent` tipados, cuatro dataclasses pequeñas, nunca JSON-RPC. El marcado, el filtrado y los ciclos de vida de los flujos se quedan en el SDK, así que una implementación del bus no puede romper el protocolo. Solo puede mover eventos entre procesos.

Para publicar desde fuera de una solicitud, construye el bus tú mismo para conservar la referencia. `MCPServer` crea uno internamente cuando no pasas nada, y no lo expone.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## La composición de bajo nivel {#the-low-level-composition}

Abajo, en el `Server` de bajo nivel, no hay nada preconectado, y las mismas piezas se ensamblan en tres líneas:

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* El bus es tuyo, así que publicas en él directamente: `await bus.publish(ResourceUpdated(uri=...))`. Ponlo donde tus handlers puedan alcanzarlo: el ámbito del módulo aquí, el lifespan en una app más grande.
* `ListenHandler(bus)` es el mismo handler que registra `MCPServer`, y `on_subscriptions_listen=` es una ranura de handler común y corriente. Pon tu propio callable en esa ranura para otra semántica, y las obligaciones de la especificación pasan a ti: acusar recibo primero, marcar cada trama con el id de suscripción, no entregar nada fuera del filtro.
* `ListenHandler.close()` termina cada flujo abierto de forma ordenada. Cada uno recibe el resultado de la solicitud listen como trama final, que es la forma que tiene la especificación de decir que el servidor terminó la suscripción a propósito. Devuelve antes de que esos flujos acaben de vaciarse, así que dales un momento antes de desmontar el transporte. Sin él, los flujos terminan cuando el cliente se desconecta.

## Resumen {#recap}

* Un cliente se apunta con una solicitud `subscriptions/listen`, y la respuesta es el flujo. Atenderla viene integrado.
* Publicas con `ctx.notify_*`, y el SDK hace el trabajo de marcado, filtrado y ciclo de vida.
* Los eventos son señales, no payloads. Ambos extremos vuelven a consultar.
* El lado del cliente es `async with client.listen(...)`: **[Suscripciones](../client/subscriptions.md)** en *Clientes* tiene todos los detalles.
* En el `Server` de bajo nivel ensamblas tú mismo las mismas piezas: un bus, `ListenHandler(bus)`, la ranura `on_subscriptions_listen`.
* Escalar horizontalmente significa implementar `SubscriptionBus`, dos métodos, y pasarlo como `MCPServer(subscriptions=...)`.

Ejecutar el servidor que atiende todo esto, detrás de una réplica o de veinte, es **[Desplegar y escalar](../run/deploy.md)**.
