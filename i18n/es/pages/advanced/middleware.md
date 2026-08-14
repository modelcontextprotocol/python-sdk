---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

Un **middleware** es una función asíncrona que envuelve cada mensaje que recibe el servidor.

Lo escribes como `async (ctx, call_next)` y lo añades a `server.middleware`. Esa es toda la API.

!!! warning
    La lista de middleware está marcada como **provisional** en el código fuente: su firma y su
    semántica pueden cambiar en una versión menor 2.x. Úsala para *observar* (medir tiempos,
    registrar, trazar) y para *rechazar* mensajes; no la conviertas en los cimientos del servidor.

`MCPServer` recibe la lista en el constructor (`MCPServer(name, middleware=[...])`) y la expone como
`mcp.middleware`; el `Server` de bajo nivel expone la misma lista como `server.middleware`. El ejemplo
de abajo usa el `Server` de bajo nivel; si `Server(name, on_call_tool=...)` es nuevo para ti, lee
primero **[El Server de bajo nivel](low-level-server.md)**.

## Un middleware que mide tiempos {#a-timing-middleware}

Un servidor, una herramienta y un middleware que registra cuánto tardó cada mensaje:

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` es el mismo `ServerRequestContext` que reciben tus handlers. `ctx.method` es la cadena
  del método sin procesar; `ctx.params` son los parámetros sin procesar, **antes** de cualquier
  validación.
* `call_next(ctx)` ejecuta el resto de la cadena: la validación, la búsqueda del handler y tu
  handler. Devuelve lo que devolvió y la respuesta queda intacta.
* El `try`/`finally` es deliberado: un handler que lanza una excepción también se cronometra,
  porque el fallo llega a tu middleware como la excepción que sale de `call_next`.
* `server.middleware.append(...)` lo registra. La lista se ejecuta de fuera hacia dentro, así que
  `middleware[0]` es el más cercano al canal.

### Pruébalo {#try-it}

Conecta un cliente, lista las herramientas, llama a una. El log tiene **tres** líneas:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

Hiciste dos llamadas y obtuviste tres líneas. La primera es `server/discover`: la solicitud que
envió el cliente para establecer la conexión, antes de que pidieras nada.

Ese es el punto. El middleware envuelve **cada** mensaje entrante:

* El establecimiento de la conexión: `server/discover`, o `initialize` y `notifications/initialized`
  en una sesión heredada.
* Cada solicitud y cada notificación. Para una notificación, `ctx.request_id is None`,
  `call_next(ctx)` devuelve `None` y lo que devuelvas se descarta.
* Incluso un método para el que el servidor no tiene handler: `call_next` lanza el
  `MCPError(-32601, "Method not found")` *a través de* tu middleware de camino al cliente.

## Qué puedes hacer dentro de uno {#what-you-can-do-inside-one}

En orden creciente de cuánto deberías dudar:

* **Observar.** Cronométralo, cuéntalo, regístralo. El ejemplo de arriba.
* **Rechazar.** Lanza un `MCPError` *en lugar de* llamar a `call_next(ctx)` y ese único mensaje se
  responde con un error JSON-RPC. La conexión sigue activa; el siguiente mensaje pasa. Así es
  como un servidor restringe `subscriptions/listen` por llamante:
  **[Decidir quién puede observar](../handlers/subscriptions.md#deciding-who-may-watch)** en la
  página de Suscripciones lo recorre paso a paso.
* **Reescribir.** `ctx` es una dataclass: `await call_next(dataclasses.replace(ctx, params=...))`
  entrega al resto de la cadena unos parámetros distintos de los que envió el cliente. Nunca hagas
  esto con `initialize`: el resultado que recibe el cliente se construye a partir de tus parámetros
  reescritos, pero el servidor fija el estado de la conexión a partir de los parámetros originales
  que llegaron por el canal. Los dos lados pueden terminar el handshake en desacuerdo sobre lo que
  negociaron.
* **Responder.** Devuelve un resultado sin llamar a `call_next(ctx)` y llega al cliente como tu
  respuesta. `call_next` te entrega la forma final que se transmite, y la canalización nunca
  retoca lo que devuelves, así que todo el sobre es tuyo: en una conexión de la generación 2026
  eso incluye la marca `_meta` de `serverInfo`, que el SDK añade a los resultados de los handlers
  pero no a los tuyos.

!!! check
    `initialize` es una de las cosas que el middleware envuelve, y es el *único* punto de enganche
    que tienes para ello. Intenta apropiártelo con `add_request_handler` y el SDK se niega:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` se maneja en línea: el servidor no lee más mensajes entrantes hasta que tu cadena
    de middleware devuelve. Esperar con await una solicitud del servidor al cliente
    (`ctx.session.send_request(...)`, una elicitación) mientras se maneja `initialize` **bloquea
    la conexión por completo**: la respuesta que esperas nunca se podrá leer. Las notificaciones
    que se envían sin esperar respuesta no dan problemas.

## El único middleware que viene activado por defecto {#the-one-middleware-that-ships-on-by-default}

El SDK incluye exactamente un middleware, y ya está en la lista del servidor: el que emite un
span de OpenTelemetry por cada mensaje. No lo añades y, la mayor parte del tiempo, ni piensas en
él. No hace nada hasta que instalas un exportador, y tiene su propia página:
**[OpenTelemetry](../run/opentelemetry.md)**.

!!! info
    Si has escrito middleware ASGI, ya conoces esta forma. El `(scope, receive, send)` de
    Starlette se convirtió en `(ctx, call_next)`, y se ejecuta *después* del transporte, sobre el
    mensaje ya decodificado en lugar de la solicitud HTTP sin procesar. Los dos se combinan: el
    middleware de Starlette sobre `streamable_http_app()` ve HTTP; este ve MCP.

## Resumen {#recap}

* Un middleware es `async (ctx, call_next) -> result`, se pasa como `MCPServer(middleware=[...])` (o
  se añade a `mcp.middleware`), y se añade a `server.middleware` en el `Server` de bajo nivel.
* Envuelve **cada** mensaje entrante (`server/discover`, `initialize`, solicitudes, notificaciones,
  métodos desconocidos) y se ejecuta de fuera hacia dentro.
* `ctx.request_id is None` es la forma de distinguir una notificación de una solicitud.
* Lanza una excepción en lugar de llamar a `call_next` para rechazar un mensaje; la conexión sobrevive.
* El trazado con OpenTelemetry del propio SDK también es un middleware, ya incluido en la lista. Consulta
  **[OpenTelemetry](../run/opentelemetry.md)**.
* Toda la superficie es provisional. Observa con ella; no construyas sobre ella.

Eso es todo lo que envuelve una solicitud. **[Autorización](../run/authorization.md)** es lo que decide si la solicitud
llega a ejecutarse siquiera.
