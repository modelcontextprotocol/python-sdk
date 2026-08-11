---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# Novedades de la v2 {#whats-new-in-v2}

En la v2 pasaron dos cosas a la vez. Se **reconstruyó el SDK**: un motor nuevo bajo el cliente y el servidor, un `Client` de primera clase y una serie de renombramientos con los que un código v1 se topa en su primer import. Y **el protocolo avanzó**: la v2 habla la revisión 2026-07-28 de MCP, que elimina el handshake de conexión, la sesión y toda solicitud iniciada por el servidor, sin dejar varados a los clientes que ya tienes.

Esta página es el recorrido por ambas mitades, una sección por titular, cada una terminando en la página que se ocupa del tema. No es el manual de portado. Ese es la **[Guía de migración](migration.md)**: cada cambio incompatible, con el código de antes y después.

!!! note "La v2 es la línea estable"
    `pip install mcp` instala la 2.x, e **[Instalación](get-started/installation.md)** tiene la
    línea de instalación para copiar y pegar. Si algo en la v2 se rompe, te sorprende o te frena,
    [cuéntanoslo](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

## El SDK: de la v1 a la v2 {#the-sdk-v1-to-v2}

### `FastMCP` ahora es `MCPServer` {#fastmcp-is-now-mcpserver}

La clase de servidor de alto nivel cambió de nombre, y su módulo con ella. Es lo primero con lo que se topa todo servidor v1, porque la ruta de import antigua desapareció en lugar de quedar obsoleta:

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

Para un servidor construido con decoradores, eso es además casi todo el portado. `@mcp.tool()`, `@mcp.resource()` y `@mcp.prompt()` aceptan lo mismo que aceptaban en la v1 (`@mcp.resource()` añade un argumento nombrado opcional `security=`), y el esquema de entrada sigue saliendo de tus anotaciones de tipo. En los bordes: todo lo que estaba bajo `mcp.server.fastmcp.*` vive ahora bajo `mcp.server.mcpserver.*`, `ctx.fastmcp` es `ctx.mcp_server`, `get_context()` desapareció (declara un parámetro `ctx: Context` en su lugar) y la excepción base `FastMCPError` es `MCPServerError`. La **[Guía de migración](migration.md#fastmcp-renamed-to-mcpserver)** tiene la tabla de imports.

### `Resolve`: la nueva forma de pedir datos al usuario {#resolve-the-new-way-to-ask-the-user-for-input}

No todo lo que una herramienta necesita debería venir del modelo. Novedad de la v2: un parámetro de herramienta anotado con `Resolve(fn)` lo rellena una función que escribes tú, sin que el modelo lo vea, y esa función puede devolver `Elicit(...)` para poner una pregunta delante del usuario. Es la forma preferida de obtener cualquier cosa del cliente en mitad de una llamada: el SDK transporta la pregunta por el mecanismo que la conexión admita (una solicitud de elicitación (elicitation) en vivo para un cliente heredado, una solicitud de varias idas y vueltas (multi-round-trip) en 2026-07-28), así que un solo cuerpo de herramienta sirve para ambas generaciones. **[Dependencias](handlers/dependencies.md)** es la página.

!!! note
    Las otras dos formas siguen ahí para cuando las necesites: `ctx.elicit()` sigue funcionando
    para clientes en conexiones heredadas (**[Elicitación](handlers/elicitation.md)**), y un handler
    puede devolver él mismo un `InputRequiredResult` y dirigir las rondas a mano, que es también
    como viajan las solicitudes de muestreo (sampling) y de roots en 2026-07-28
    (**[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)**).

### Un `Client` de primera clase {#a-first-class-client}

La v1 te entregaba tres capas anidadas: un gestor de contexto de transporte que producía flujos en crudo, una `ClientSession` envolviéndolos y un `await session.initialize()` llamado a mano. La v2 tiene un solo objeto:

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` acepta un objeto servidor (en memoria, sin transporte: la historia de las pruebas), una URL (Streamable HTTP) o cualquier gestor de contexto de transporte como `stdio_client(...)`. Entrar en `async with` conecta y negocia la versión del protocolo, sea cual sea la generación que hable el servidor; `client.server_capabilities` y `client.protocol_version` simplemente están ahí después, y `client.server_info` también cuando el servidor se identifica (ahora es `Implementation | None`, porque la identidad en la generación 2026 es opcional). Los callbacks de muestreo y elicitación que registraste en la v1 siguen funcionando (sus cuerpos ven el mismo renombramiento de atributos a snake_case que todo lo demás en esta página), ahora también responden a las solicitudes dentro de resultados al estilo 2026 (más abajo) y se ejecutan concurrentemente en lugar de una a una. `ClientSession` sigue debajo para quien quiera la superficie de bajo nivel, y `client.session` te la entrega; también cambió (corre sobre el nuevo motor de despacho, y algunas de sus propias firmas cambiaron), así que lee la **[Guía de migración](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)** antes de bajar a ese nivel.

**[El Client](client/index.md)** lo presenta, **[Transportes del cliente](client/transports.md)** cubre las tres formas de conexión, **[Callbacks del cliente](client/callbacks.md)** cubre los callbacks en sí y **[Pruebas](get-started/testing.md)** muestra el patrón en memoria que sustituye al helper `create_connected_server_and_client_session()` de la v1.

### El `Server` de bajo nivel se reconstruyó, no se renombró {#the-low-level-server-was-rebuilt-not-renamed}

Si trabajas en la capa JSON-RPC, esta es la parte de la v2 donde "todo es distinto". Aquí está el mismo servidor de una sola herramienta de las dos maneras; haz clic en los marcadores para ver qué se movió.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. Los handlers se registran con decoradores (llamados, con paréntesis), en cualquier momento después de que exista el servidor.
2. Devuelves una `list[Tool]` sin más y el SDK la envuelve en un `ListToolsResult`.
3. Los campos son camelCase en Python, y el esquema **se aplica**: el SDK valida con jsonschema los argumentos de `call_tool` contra él antes de que se ejecute tu función, por eso `arguments["query"]` más abajo es seguro.
4. Un solo handler `call_tool` atiende todas las herramientas, y recibe el nombre de la herramienta y los argumentos ya validados, desempaquetados y nunca `None`.
5. Lanzar una excepción es como una herramienta v1 señala un fallo: cualquier excepción se captura y se devuelve como `CallToolResult(isError=True)` con `str(e)` como texto, así que el modelo que llama lee este mensaje y puede reintentar.
6. El contexto viene de una ContextVar ambiental, a la que se llega a través del objeto servidor en mitad de la solicitud.
7. Los bloques de contenido sueltos se envuelven en un `CallToolResult` por ti.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Ahora los campos son snake_case, y el esquema **se anuncia pero nunca se aplica**: nada comprueba los argumentos antes de que se ejecute tu handler.
2. Todos los handlers tienen la misma forma: `async (ctx, params) -> result`. El contexto es el primer argumento (`ctx.session`, `ctx.request_id` y `ctx.protocol_version` viven en él); aquí es adonde fue a parar `server.request_context`.
3. Construyes tú el `ListToolsResult` completo. Devolver una lista suelta es ahora un `TypeError` del lado del servidor, no algo que el SDK envuelva.
4. Entran params tipados (`params.name`, `params.arguments`), sale un resultado completo. Nada se desempaqueta, envuelve ni convierte por ti.
5. La misma comprobación, distinto verbo. Un `ValueError` aquí llegaría al modelo como un `-32603` opaco (ver más abajo), así que un error de protocolo deliberado se lanza como `MCPError`: pasa con su código y su mensaje intactos, y `-32602` con este texto es la propia respuesta de la especificación para una herramienta desconocida.
6. `params.arguments` puede ser `None`; la v1 lo dejaba en `{}` por defecto antes de que tu código lo viera. Sin validación delante del handler, esta línea es imprescindible.
7. Una excepción inesperada lanzada aquí se convierte en un error de protocolo **saneado**, `-32603` `"Internal server error"`: el modelo nunca ve el mensaje. Para un fallo que el modelo deba leer y al que deba reaccionar, devuelve `CallToolResult(is_error=True, ...)`.
8. Los handlers son argumentos del constructor, así que la superficie del servidor está completa en el momento en que existe; `add_request_handler()` es la vía de escape tras la construcción, y la puerta a los métodos personalizados.

El ejemplo es el patrón. De forma más general: todos los handlers tienen la misma forma, con params tipados de entrada y un tipo de resultado completo de salida; la antigua comprobación con jsonschema de los argumentos de las herramientas desapareció; una excepción es un error de protocolo, nunca un resultado de herramienta con `is_error=True`; y la ContextVar ambiental `server.request_context` desapareció. Los métodos personalizados con espacio de nombres de proveedor son de primera clase mediante `add_request_handler(method, params_type, handler)`, que valida los params entrantes contra tu modelo antes de que se ejecute tu handler. Y una lista `middleware` (marcada deliberadamente como provisional) envuelve cada mensaje entrante, sustituyendo a los métodos privados `_handle_*` que la gente solía sobrescribir.

Por debajo, el bucle de recepción `BaseSession` de la v1 se reemplazó por un motor de despacho que ahora comparten el cliente y el servidor, y es lo que hace ciertas varias cosas de esta página a la vez: un solo objeto `Server` sirve ambas generaciones del protocolo, `Client(server)` despacha en proceso sin enmarcado JSON-RPC, y una solicitud de cliente que agota su tiempo de espera ahora cancela de verdad el handler del lado del servidor.

**[El Server de bajo nivel](advanced/low-level-server.md)** es la página; la **[Guía de migración](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** recorre cada gancho eliminado. Si nunca bajaste por debajo de `MCPServer`, nada de esto te afecta.

### Los tipos del protocolo se movieron a `mcp-types`, y todos los campos son snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

Los tipos del protocolo viven ahora en su propia distribución, `mcp-types`. No depende de nada más que pydantic y typing-extensions, así que una pasarela, un proxy o un generador de código pueden consumir las formas que MCP transmite sin instalar una pila HTTP: un proyecto así instala `mcp-types` e importa `mcp_types`. El propio `mcp` depende de ese paquete en una versión exacta y lo reexpone, así que el código que depende del SDK sigue escribiendo `import mcp.types as types` y `from mcp.types import Tool` (un alias permanente, cada nombre es el mismo objeto) y declara solo su única dependencia real, `mcp`. La regla práctica: importa a través del paquete del que realmente dependas.

En esos tipos, cada atributo de Python es ahora snake_case: `result.is_error`, `tool.input_schema`, `listing.next_cursor`. El JSON que realmente se transmite es camelCase, exactamente como antes; solo cambió la grafía de los atributos. Dos valores por defecto más estrictos lo acompañan: los campos desconocidos se ignoran en lugar de reenviarse de vuelta (pon los extras en `_meta`), y ambos lados validan el tráfico contra la versión del protocolo que negociaron. Consulta la **[Guía de migración](migration.md#field-names-changed-from-camelcase-to-snake_case)** para ver la tabla de renombramientos.

### La configuración del transporte se movió a `run()` {#transport-configuration-moved-to-run}

`MCPServer(...)` trata de lo que tu servidor *es*: su nombre, sus instrucciones, su lifespan (ciclo de vida del servidor), su autenticación. Cómo se *sirve* pertenece ahora a `run()` y a los constructores de la app, que es adonde fueron `host`, `port`, `stateless_http`, `json_response`, las rutas de los endpoints y `transport_security` (`MCPServer("x", port=9000)` es un `TypeError`). Las sobrecargas están tipadas por transporte, así que tu editor te dice qué opciones acepta `stdio` y cuáles `streamable-http`. Una eliminación que conviene conocer: `mount_path` desapareció; montar la app ASGI es la forma admitida de servir bajo un prefijo.

**[Ejecutar tu servidor](run/index.md)** cubre las opciones; **[Añadir a una app existente](run/asgi.md)** cubre el montaje.

### Comportamiento que cambia sin un error de import {#behavior-that-changes-without-an-import-error}

Los renombramientos se anuncian solos. Estos no:

* **Las funciones síncronas se ejecutan en un hilo de trabajo.** Una herramienta `def` (o recurso, prompt o resolutor) ya no bloquea el bucle de eventos; la contrapartida es que su cuerpo ya no se ejecuta *en* el hilo del bucle de eventos, lo que importa para código afín a un hilo. Los handlers `async def` no cambian. **[Guía de migración](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**.
* **`MCPError` (el `McpError` de la v1) lanzado dentro de una herramienta es ahora un error de protocolo.** El modelo nunca lo ve. Cualquier otra excepción sigue convirtiéndose en un resultado `is_error=True` que el modelo puede leer y al que puede reaccionar. **[Manejo de errores](servers/handling-errors.md)** explica la división.
* **Los resultados se validan antes de salir.** Un `Tool` construido a mano cuyo `input_schema` sea `{}` ahora falla en `tools/list` (la especificación exige `"type": "object"`). Los servidores construidos sobre `@mcp.tool()` nunca ven esto; el SDK escribe sus esquemas.
* **Tu cliente valida lo que recibe.** `list_tools()` y `call_tool()` comprueban la respuesta del servidor contra la versión del protocolo negociada, así que un servidor no del todo válido que el análisis permisivo de la v1 toleraba ahora lanza `pydantic.ValidationError`. Si te conectas a servidores que no controlas, cuenta con ser tú quien los descubra; la **[Guía de migración](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)** tiene los detalles.
* **Las plantillas de URI son ahora RFC 6570 de verdad.** `{+path}`, `{?query}` y compañía funcionan, la coincidencia es exacta en lugar de laxa por regex, y el path traversal en los valores extraídos se rechaza por defecto. Las plantillas más estrictas fallan al decorar, no en la primera solicitud. **[Plantillas de URI](servers/uri-templates.md)**.
* **El lifespan de Streamable HTTP se ejecuta una vez**, al arrancar, y su estado lo comparten todas las sesiones y solicitudes. En la v1 se ejecutaba una vez por sesión, y una vez por solicitud con `stateless_http=True`. Los pools y cachés construidos en un lifespan se vuelven drásticamente más baratos; cualquier cosa que adquiriera ahí un recurso por conexión pertenece ahora al cuerpo del handler. **[Lifespan](handlers/lifespan.md)**.
* **`mcp dev` y `mcp install` fijan el entorno que lanzan** a la versión del SDK que tienes instalada. Ambos comandos ejecutan tu servidor en un entorno nuevo `uv run --with ...`, que antes resolvía `mcp` a la versión estable más reciente en lugar de la versión contra la que estás desarrollando. **[Guía de migración](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**.
* **El cliente HTTP es ahora `httpx2`, no `httpx`.** El cambio de dependencia altera lo que tu código captura y pasa (`httpx2.AsyncClient`, `httpx2.ConnectError`), y cambia cómo se verifican los certificados TLS: `httpx2` valida mediante `truststore` contra el almacén de confianza del sistema operativo en lugar de la lista de CA incluida en certifi. La mayoría de los entornos ni se enteran; un contenedor mínimo sin almacén de CA del sistema, o una CA privada que solo conocía el paquete de certifi, empieza a fallar en el handshake TLS. Define `SSL_CERT_FILE`/`SSL_CERT_DIR` o pasa `verify=ssl_context` a tu cliente. **[Guía de migración](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**.

### Eliminado sin más {#removed-outright}

Cada uno de estos es una sección de la **[Guía de migración](migration.md)**:

* El **transporte WebSocket**, en ambos lados, y el extra `mcp[ws]`. Nunca formó parte de la especificación de MCP.
* La API **experimental Tasks** (`mcp.*.experimental`). 2026-07-28 saca las tareas del protocolo principal y las lleva a una extensión oficial ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)), que este SDK todavía no implementa.
* `mcp.shared.version`, `mcp.shared.progress` y `mcp.shared.session` (con el stub `RequestResponder` que importaban las anotaciones de `message_handler` de la v1) como rutas de import. (`mcp.types` *no* se elimina: permanece como alias permanente del paquete independiente `mcp_types`.)
* La grafía obsoleta `streamablehttp_client`, y el callback `get_session_id` de `streamable_http_client` (que ahora produce exactamente dos flujos).
* `McpError`, renombrado **`MCPError`** con un constructor directo `(code, message, data)`.
* `MCPServer.get_context()`, `mount_path=` y, en el `Server` de bajo nivel, los métodos decoradores, la ContextVar y los diccionarios de handlers.

## El protocolo: de 2025-11-25 a 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

La v2 implementa la revisión 2026-07-28, y sirve **ambas** revisiones a la vez: la misma `streamable_http_app()` (y el mismo servidor stdio) responde al `initialize` de un cliente de la generación 2025 y a las solicitudes de un cliente de la generación 2026 sin nada que configurar, ninguna bandera que activar ni un despliegue aparte. Servir la revisión nueva no deja varado a un cliente en la antigua. Lo que sigue es lo que cambia la revisión nueva en sí.

### Sin handshake, sin sesión {#no-handshake-no-session}

Un cliente 2026-07-28 no abre una conexión, negocia y luego habla. Cada solicitud lleva su versión de protocolo, la información del cliente y las capacidades del cliente en `_meta`, y la única llamada de descubrimiento, `server/discover`, es una solicitud normal como cualquier otra. `Client` hace lo correcto por defecto: sondea `server/discover` una vez y recurre al handshake `initialize` si el servidor es más antiguo.

Sobre Streamable HTTP no hay `Mcp-Session-Id` en el camino 2026, y ese es el titular operativo: **nada ata una solicitud moderna a un worker**, así que cualquier réplica detrás de un balanceador de carga round-robin normal puede responderla. Dos matices honestos. Tus clientes de la generación 2025 (hoy, eso es la mayoría) siguen abriendo sesiones y siguen necesitando la afinidad que necesitaran en la v1; para ellos no cambia nada. Y lo único que un reintento de *varias idas y vueltas* tiene que llevar entre workers es su `request_state` sellado, cuya clave por defecto se genera por proceso, así que un despliegue escalado horizontalmente pasa `RequestStateSecurity(keys=[...])`. (`stateless_http=True` no tiene relación: solo afecta a cómo se sirve a los clientes de la generación 2025, y el tráfico 2026 nunca lo lee; si ya lo tenías activado en la v1, no cambia nada.)

**[Versiones del protocolo](protocol-versions.md)** es el lado del cliente de esto, **[Desplegar y escalar](run/deploy.md)** es la lista de comprobación del operador (la lista de hosts permitidos, la clave de `request_state`, las notificaciones entre réplicas) y **[Atender clientes heredados](run/legacy-clients.md)** es la historia de ambas generaciones a la vez.

### El servidor no puede llamar al cliente: solicitudes de varias idas y vueltas {#the-server-cannot-call-the-client-multi-round-trip-requests}

Toda solicitud iniciada por el servidor desaparece en 2026-07-28: elicitación por push, muestreo, `roots/list`. En una conexión 2026 no hay canal para ellas, así que `ctx.elicit()` y `ctx.session.create_message()` fallan ahí con `NoBackChannelError`, porque no hay canal de retorno (back-channel) (siguen funcionando para clientes heredados).

El reemplazo le da la vuelta a la llamada. Una herramienta que necesita algo del usuario *devuelve* la pregunta (`InputRequiredResult`), el cliente la responde con los mismos callbacks que siempre tuvo, y la llamada se reintenta con las respuestas adjuntas. `Client` dirige ese bucle por ti. En el servidor rara vez construyes tú el resultado, porque lo hace una **[dependencia](handlers/dependencies.md)**: anota un parámetro con `Resolve(ask_quantity)`, donde `ask_quantity` es una función ordinaria que escribes tú, y el SDK pregunta por el mecanismo que la conexión admita, una solicitud de elicitación en vivo en una sesión heredada o una solicitud de varias idas y vueltas en 2026. Un solo cuerpo de herramienta, ambas generaciones:

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

Ese archivo es la propuesta en un solo lugar: un servidor, una herramienta respaldada por `Resolve`, y un cliente heredado más un cliente moderno recibiendo ambos su respuesta, en memoria. **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)** explica el mecanismo (incluido `request_state`, que el SDK sella y verifica por ti); **[Elicitación](handlers/elicitation.md)** cubre cómo preguntar.

!!! warning "Este es el único lugar donde un servidor v1 portado cambia de comportamiento"
    Tus propias pruebas se lo encuentran primero: `Client(mcp)` negocia 2026-07-28 contra tu
    servidor v2 por defecto, así que una herramienta que llama a `ctx.elicit()` falla en una prueba
    que pasaba en la v1. Mueve la pregunta a un parámetro `Resolve(...)` (portátil entre
    generaciones), o fija el cliente de pruebas a `mode="legacy"` si de verdad quieres el
    comportamiento push.

### Roots, muestreo y logging del protocolo quedan obsoletos; `ping` se elimina {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) declara obsoletas tres *capacidades* enteras, en todas las versiones del protocolo: roots, muestreo y logging a nivel MCP (`ctx.info()` y compañía). Es un eje distinto del canal de retorno ausente de arriba; obsoleto es solo un aviso, todo sigue funcionando contra sesiones de la generación 2025 y nada cambia en lo que se transmite. Lo que notas es `MCPDeprecationWarning`, que es un `UserWarning`, así que se imprime por defecto; cuenta con que tu primer `ctx.info(...)` tras la actualización lo diga.

`ping` es más estricto: eliminado del protocolo, no obsoleto. Dos de los métodos independientes de las funcionalidades obsoletas se eliminan en 2026-07-28 del mismo modo, `logging/setLevel` y el `notifications/roots/list_changed` del cliente, y las notificaciones de progreso son ahora solo de servidor a cliente.

**[Funcionalidades obsoletas](deprecated.md)** tiene la tabla completa, el reemplazo de cada una y el filtro de una línea si necesitas un log silencioso mientras atiendes clientes heredados.

### Las notificaciones de cambio se convierten en un solo flujo {#change-notifications-become-one-stream}

En 2026-07-28 el flujo HTTP GET independiente y `resources/subscribe` se sustituyen por `subscriptions/listen`: el cliente abre un único flujo de larga duración y nombra los tipos de notificación que quiere. `MCPServer` lo sirve por defecto; publicas con `await ctx.notify_resource_updated(uri)` (y `notify_tools_changed()`, etc.), un middleware puede rechazar una solicitud de escucha por llamante, y los despliegues con varias réplicas conectan un `SubscriptionBus` compartido. En el cliente, `async with client.listen(...)` abre el flujo: el filtro entra como argumentos nombrados, vuelven eventos de cambio tipados, y `sub.honored` es el subconjunto que el servidor aceptó entregar.

**[Suscripciones](handlers/subscriptions.md)** cubre la publicación y el servicio, **[su gemela en Clientes](client/subscriptions.md)** el extremo que observa, y **[Desplegar y escalar](run/deploy.md)** el bus.

### El resto, rápido {#the-rest-quickly}

* **La identidad es opcional, metadatos por mensaje.** La clave `clientInfo` de `_meta` del lado de la solicitud es opcional (el par obligatorio es `protocolVersion` + `clientCapabilities`), y `serverInfo` salió del cuerpo del resultado de `server/discover`: los servidores la estampan en el `_meta` de cada resultado de la generación 2026 en su lugar ([spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). El SDK siempre la estampa; `client.server_info` es `None` cuando un servidor no se identifica (por ejemplo, un middleware quitó la clave). **[El Server de bajo nivel](advanced/low-level-server.md)** muestra la marca en lo que se transmite.
* **Las solicitudes se pueden enrutar sin analizar cuerpos.** Las solicitudes HTTP modernas llevan `Mcp-Method` (y, para las tres llamadas de tipo herramienta, `Mcp-Name`); una propiedad del esquema de entrada de una herramienta anotada con `x-mcp-header` se refleja en una cabecera `Mcp-Param-*` y el servidor la contrasta ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). Las pasarelas y los limitadores de tasa pueden enrutar solo con cabeceras; la **[Guía de migración](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)** tiene las reglas.
* **Los resultados llevan indicaciones de caché.** Los resultados de listado y lectura declaran `ttlMs` y `cacheScope` ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)); los fijas por método con `cache_hints=`, y `Client` los respeta con una caché de respuestas integrada. Un servidor que no envía indicaciones (todo servidor anterior a 2026) ve un tráfico idéntico, sin caché. **[Indicaciones de caché](client/caching.md)**.
* **Las extensiones son de primera clase.** Servidores y clientes declaran paquetes de capacidades opcionales bajo identificadores DNS inversos ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)); la extensión integrada `Apps` (MCP Apps) es la referencia. **[Extensiones](advanced/extensions.md)** y **[MCP Apps](advanced/apps.md)**.
* **Los códigos de error se estandarizaron.** Un recurso inexistente es `-32602` con la URI en `error.data`, y los nuevos códigos reservados por la especificación aparecen como `-32020` (cabecera no coincidente), `-32021` (falta una capacidad obligatoria) y `-32022` (versión de protocolo no admitida). **[Solución de problemas](troubleshooting.md)** está indexada por los mensajes exactos.
* **La autorización se volvió más difícil de usar mal.** El cliente valida el `iss` devuelto con el código de autorización ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207); tu `callback_handler` devuelve ahora un `AuthorizationCodeResult`), envía `application_type` cuando se registra y nunca reutiliza credenciales contra un servidor de autorización distinto. Novedad en el rincón empresarial: el flujo de aserción de identidad de [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990). La **[Guía de migración](migration.md)** enumera cada cambio de OAuth; **[OAuth para clientes](client/oauth-clients.md)** y **[Aserción de identidad](client/identity-assertion.md)** son las páginas.
* **Todo servidor es trazable.** OpenTelemetry viene activado por defecto como middleware: cada solicitud obtiene un span de servidor, sin coste hasta que el proceso configura un exportador. Cuando ambos extremos ejecutan el SDK, el cliente también propaga el contexto de traza W3C en `_meta`, así que las trazas se unen. **[OpenTelemetry](run/opentelemetry.md)**.

## ¿Actualizas desde la v1? {#upgrading-from-v1}

* La **[Guía de migración](migration.md)** es la lista completa y exacta de lo que hay que cambiar; esta página era el porqué.
* **La v1.x no se va a ningún lado.** Pasa a mantenimiento, sigue recibiendo correcciones críticas y parches de seguridad, y nada de la publicación de la especificación 2026-07-28 la rompe; su documentación vive en [/v1/](https://py.sdk.modelcontextprotocol.io/v1/). Si publicas una biblioteca que depende de `mcp` y no estás listo para migrar, mantén un límite superior (por ejemplo `mcp>=1.28,<2`) para que una resolución sin fijar se quede en la 1.x.
* ¿Algo tosco, confuso o roto? **[Envía comentarios sobre la v2](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**; se lee todo.
