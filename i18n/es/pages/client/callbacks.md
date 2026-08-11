---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# Callbacks del cliente {#client-callbacks}

Casi todas las solicitudes en MCP van en una sola dirección: del cliente al servidor.

Un servidor también puede pedirle cosas al **cliente**: hacerle una pregunta al usuario, muestrear el modelo del usuario, listar las carpetas del espacio de trabajo del usuario. Respondes a esas solicitudes pasando **callbacks** a `Client(...)`.

## Un servidor que pregunta {#a-server-that-asks}

Aquí tienes un servidor cuya herramienta no puede terminar por sí sola:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` envía una solicitud `elicitation/create` **al cliente** y espera.
* La herramienta no devuelve nada hasta que alguien (una persona en un formulario, o tu código) proporciona un `name`.

Esa es la mitad del servidor, y la página **[Elicitación](../handlers/elicitation.md)** se ocupa de ella. Esta página es el otro extremo de la conexión.

## El callback de elicitación {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* Un callback de elicitación (elicitation) es `async (context, params) -> ElicitResult`.
* `params.message` es la pregunta. `params.requested_schema` es el JSON Schema de la respuesta que quiere el servidor. Un cliente real genera un formulario a partir de él; este lo rellena automáticamente.
* Devuelves `ElicitResult(action="accept", content={...})`, o `action="decline"`, o `action="cancel"`. La única otra opción es `ErrorData(...)`, que rechaza la solicitud y hace fallar toda la llamada.
* `context` es un `ClientRequestContext`: la `session` activa, el `request_id` del servidor y cualquier `meta` que haya adjuntado.

!!! tip
    `params` es una unión de los dos modos de elicitación. Aquí `params.mode` es `"form"`; una solicitud
    `"url"` lleva `params.url` en lugar de un esquema. Un solo callback maneja ambos; bifurca según `params.mode`.
    **[Elicitación](../handlers/elicitation.md)** muestra el patrón completo.

### Pruébalo {#try-it}

Llama a `issue_card` y observa ambos extremos.

Tu callback recibe la pregunta del servidor, ya analizada:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

Responde, `ctx.elicit(...)` se reanuda dentro de la herramienta y la herramienta termina:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

Un `tools/call` tuyo, un `elicitation/create` de vuelta desde el servidor, respondido por tu función, todo dentro de una sola llamada a herramienta.

!!! info
    `mode="legacy"` en la llamada a `Client(...)` hace trabajo real. Por defecto, `Client(...)` negocia la ruta
    moderna del protocolo, y esa ruta no tiene canal de retorno (back-channel) para las solicitudes del servidor al cliente: `ctx.elicit`
    falla antes de que tu callback llegue a ejecutarse. No lo decide el transporte; lo decide el protocolo
    negociado, tanto en memoria como a través de una URL. Fija `mode="legacy"` siempre que tu cliente tenga
    que responder a una; todas las pruebas detrás de esta página lo hacen. **[Versiones del protocolo](../protocol-versions.md)** tiene todos los detalles.

    En una sesión 2026-07-28 el callback no está muerto, se alimenta de otra forma: cuando una herramienta devuelve un
    `InputRequiredResult` que lleva un `ElicitRequest`, `Client` despacha esa entrada al mismo
    `elicitation_callback` y reintenta la llamada por ti. Ese flujo está en **[Solicitudes de varias idas y vueltas](../handlers/multi-round-trip.md)**.

## Un callback es una capacidad {#a-callback-is-a-capability}

Nunca le dijiste al servidor que tu cliente puede responder solicitudes de elicitación. Lo hizo el SDK.

Cuando un cliente se conecta declara sus `capabilities`, la imagen especular de las del servidor. No escribes ese objeto. **Registrar un callback es la declaración.**

| lo que pasas | lo que declara el cliente |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| ninguno de ellos | `{}` |

Las subcapacidades de muestreo (sampling) son el único refinamiento: pasa `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` junto con `sampling_callback` cuando tu muestreador maneja los parámetros `tools` / `tool_choice`. Los servidores deben ver `sampling.tools` declarado antes de poder enviarlos.

`logging_callback` y `message_handler` no están en la tabla. Manejan notificaciones, y las notificaciones no necesitan ninguna capacidad.

El servidor lee la declaración con `ctx.session.check_client_capability(...)`. Añade una herramienta que lo haga:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

Conéctate solo con `elicitation_callback` y llámala:

```python
result.structured_content  # {'result': ['elicitation']}
```

Pasa los tres callbacks y obtienes `['elicitation', 'sampling', 'roots']`. No pases ninguno y obtienes `[]`.

!!! check
    Ahora haz lo incorrecto: conéctate **sin** `elicitation_callback` y llama a `issue_card` de todos modos.

    La solicitud `elicitation/create` del servidor sigue llegando a tu cliente, y el SDK la responde por
    ti, con un error, porque nunca dijiste que pudieras manejarla. Ese error hunde toda la llamada.
    `call_tool` no devuelve un resultado `is_error`; lanza:

    ```text
    MCPError: Elicitation not supported
    ```

    Eso es un error de protocolo (`-32600`, *invalid request*), no un error de herramienta: no hay nada que
    el modelo pueda leer y reintentar. Por eso vale la pena tener `client_features`: un servidor bien educado
    comprueba antes de preguntar.

## El par obsoleto {#the-deprecated-pair}

`sampling_callback` responde a `sampling/createMessage`: el servidor pidiéndole a *tu* modelo que complete algo. `list_roots_callback` responde a `roots/list`: el servidor preguntando en qué directorios puede trabajar.

Ambos funcionan. Ambos siguen la regla anterior. Y ambos atienden RPC que **la especificación 2026-07-28 elimina**: un servidor moderno no llama de vuelta a tu cliente a mitad de una solicitud, te devuelve la solicitud como parte del resultado de la herramienta (**[Solicitudes de varias idas y vueltas](../handlers/multi-round-trip.md)**). Los callbacks en sí no están muertos. Cuando un `InputRequiredResult` lleva un `CreateMessageRequest` o un `ListRootsRequest`, el bucle automático de `Client` lo despacha al mismo `sampling_callback` o `list_roots_callback` que registraste aquí. La lista completa está en **[Funcionalidades obsoletas](../deprecated.md)**.

Sigues necesitando los callbacks para hablar con servidores que no han migrado. Las firmas:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* Un callback de muestreo recibe los `CreateMessageRequestParams` completos (`messages`, `model_preferences`, `max_tokens`) y devuelve un `CreateMessageResult`. *Tú* ejecutas el modelo, como prefieras; el SDK solo transporta la solicitud.
* Un callback de roots no recibe ningún parámetro y devuelve un `ListRootsResult`.
* Cualquiera de los dos puede devolver `ErrorData(...)` en su lugar, para rechazar.

Pásalos a `Client(...)` exactamente igual que `elicitation_callback`.

## Los callbacks de notificaciones {#the-notification-callbacks}

Dos más. Ninguno declara nada.

`logging_callback` recibe el `notifications/message` que envía un servidor, como `LoggingMessageNotificationParams` (`level`, `logger`, `data`). El logging del protocolo está a su vez obsoleto según la especificación 2026-07-28 (**[Logging](../handlers/logging.md)** explica qué hacer en su lugar), así que este callback existe para los servidores que todavía lo emiten. En una conexión de la generación 2026 el callback por sí solo no te da nada, porque los servidores 2026 envían mensajes de log solo a las solicitudes que lo piden: pasa `log_level="info"` (u otro nivel) a `Client(...)` para marcar esa preferencia en cada solicitud y recibir ese nivel y los superiores. Los servidores anteriores a 2026 lo ignoran y mantienen su comportamiento de `logging/setLevel`.

`message_handler` es el comodín: toda notificación del servidor que la sesión expone le llega (además de a su callback específico), y en un transporte basado en flujos también toda `Exception` a nivel de transporte. Dos nunca llegan: `notifications/cancelled` la aplica el SDK en lugar de exponerla, y la confirmación de suscripción de un flujo `listen()` activo la consume ese flujo. Anota el parámetro con `IncomingMessage` (`ServerNotification | Exception`, exportado desde `mcp.client`). El único patrón que vale la pena conocer es `if isinstance(message, Exception): raise message`, para que una conexión rota falle de forma visible en lugar de desvanecerse.

## Resumen {#recap}

* Un servidor puede enviar solicitudes al cliente. Las respondes con callbacks pasados a `Client(...)`.
* El callback de elicitación es el vigente: `async (context, params) -> ElicitResult`, una sola función para los modos formulario y URL.
* **Registrar un callback es declarar la capacidad.** Sin él, el SDK rechaza la solicitud del servidor en tu nombre y toda la llamada falla con `MCPError`.
* Un servidor lo averigua antes de preguntar con `ctx.session.check_client_capability(...)`.
* `sampling_callback` y `list_roots_callback` funcionan igual pero atienden funcionalidades obsoletas; los servidores modernos usan solicitudes de varias idas y vueltas en su lugar.
* `logging_callback` y `message_handler` reciben notificaciones. No declaran nada.

El primer argumento de `Client(...)` es un objeto de transporte. **[Transportes del cliente](transports.md)** cubre todos los tipos.
