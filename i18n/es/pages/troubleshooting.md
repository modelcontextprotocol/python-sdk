---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Solución de problemas {#troubleshooting}

Cada encabezado de esta página es el texto exacto de un error que produce el SDK, seguido de lo que significa y de la solución en un solo paso. Busca aquí la última línea de tu traceback (o del log del servidor) con la búsqueda en página del navegador y lee solo esa entrada.

Varias entradas se ejecutan contra este mismo servidor. Una herramienta y un recurso con plantilla, cada uno de los cuales lanza una excepción para una ciudad que no conoce:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Los errores que cita esta página son reales: la propia suite de pruebas del SDK reproduce cada uno de ellos.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Esto no es un error de MCP. Es ruido de anyio, y tu error real es la **última línea** de lo que pegaste.

`Client.__aenter__` inicia un grupo de tareas. anyio envuelve en un `ExceptionGroup` todo lo que sale de un grupo de tareas, así que *cualquier* excepción que escape de un bloque `async with Client(...)`, sea la que sea, llega dentro de uno:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

Dos cosas que hacer con eso:

1. **Lee el final.** `MCPError: No forecast for 'Atlantis'.` es el fallo; busca *su* texto en esta página.
2. **Captura dentro del bloque.** El `ExceptionGroup` solo aparece cuando la excepción *sale* del `async with`. Capturado dentro, el mismo fallo es el `MCPError` sin más, sin ningún grupo:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    Un fallo durante la *conexión* (una URL equivocada, un servidor que no está en ejecución, el
    `421` de más abajo en esta página) escapa del propio `async with`, así que no hay un "dentro"
    donde capturarlo. Para esos casos, lee el final del grupo.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` solo construye el objeto. Nada se conecta hasta el `async with`, así que todos los métodos se niegan:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Entra en él. `__aenter__` es la conexión:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` es la desconexión, y por eso no hay ningún `client.close()` que olvidar. **[Pruebas](get-started/testing.md)** se basa exactamente en este patrón.

## `Error executing tool <name>: <message>` y `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Estás leyendo un **resultado**, no una excepción. `call_tool` no lanzó nada, y nunca lo hará para una herramienta que falla.

Llama a `forecast` con una ciudad que el servidor no conoce y la excepción que lanza vuelve con la solicitud marcada como *correcta*:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` tiene la misma forma para un nombre que el servidor nunca registró, y un argumento incorrecto se rechaza igual, contra el esquema de entrada de la herramienta, antes de que tu función llegue a ejecutarse.

La solución está en tu cliente: **comprueba `result.is_error`**. Un `try/except` alrededor de `call_tool` no captura ninguno de estos casos, porque no hay nada que capturar. Es deliberado, y es lo más útil de esta página que puedes interiorizar: el *modelo* eligió la llamada, así que el modelo recibe el mensaje y la oportunidad de intentarlo de nuevo. **[Manejo de errores](servers/handling-errors.md)** tiene todos los detalles, incluida la vía de `MCPError` que *sí* lanza.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

Escribiste `@mcp.tool` en lugar de `@mcp.tool()`. `tool()` es una *fábrica* de decoradores: sin los paréntesis, Python le pasa tu función a su parámetro `name=`.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Añade los paréntesis. `@mcp.resource(...)` y `@mcp.prompt()` dicen lo mismo ante el mismo descuido.

!!! note
    Esto se lanza al **importar** el módulo, antes de que se conecte ningún cliente. Así que un
    host que muestra tu servidor como *no se pudo iniciar* (o *desconectado*), en lugar de
    conectado con cero herramientas, tiene esta forma: ejecuta `python server.py` tú mismo y lee
    el traceback. Un verificador de tipos también lo detecta: una función no es un `name=` válido.

## `Tool already exists: <name>` {#tool-already-exists-name}

Dos registros usaron el mismo nombre de herramienta. Gana el **primero**, el segundo se descarta en silencio, y este aviso en el *log del servidor* es la única señal:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` informa de un solo `forecast`, y es `forecast_today`. Cambia el nombre de uno de ellos. `MCPServer(..., warn_on_duplicate_tools=False)` silencia el aviso sin cambiar el resultado, así que déjalo activado. Los recursos y los prompts tienen la misma regla y la misma línea de log (`Resource already exists:`, `Prompt already exists:`).

## Mi host muestra cero herramientas {#my-host-lists-zero-tools}

No hay ninguna cadena de error para esto, y precisamente por eso es difícil de buscar. El SDK nunca quita una herramienta registrada de `tools/list`, así que ve descartando de dentro hacia fuera:

* **¿Llegó a arrancar el servidor?** `@mcp.tool` sin paréntesis lanza una excepción al importar, y en algunos hosts un servidor caído se parece mucho a uno vacío. Ejecuta `python server.py` tú mismo.
* **¿Está la herramienta en el `mcp` que ejecuta el host?** Un segundo `MCPServer(...)` en otro módulo es un servidor distinto y vacío. Comprueba qué objeto importa realmente el comando del host.
* **¿Dos herramientas compartían nombre?** Entonces una de ellas desapareció. Busca `Tool already exists:` en el log del servidor.
* **¿Está desactualizada la lista del host?** Añadir una herramienta después del arranque solo llega a los clientes que manejan `notifications/tools/list_changed`. Reiniciar el host es la solución expeditiva.
* **¿Algo escribió en `stdout` fuera de la ventana desviada?** Mientras atiende, el SDK desvía a stderr la salida suelta de stdout que se *vacía* (en la medida de lo posible: un entorno que reemplaza los flujos estándar se atiende tal cual), pero la salida vaciada a stdout antes (un script envoltorio que hace eco, un `print()` en tiempo de importación en un proceso sin búfer) o un `print()` en búfer que se drena al salir el intérprete acaba en el flujo del protocolo, y una sola línea de basura puede hacer que el host corte la conexión, lo que algunos hosts muestran como un servidor sin nada dentro. Registra con el módulo `logging` en su lugar. El resto de la lista de comprobaciones del lado del host está en **[Conectar con un host real](get-started/real-host.md)**.

Un nombre de herramienta "inválido" *no* está en esa lista: un nombre no conforme registra un aviso, pero la herramienta se registra y se lista igualmente.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

El servidor rechazó de plano la solicitud HTTP, con un cuerpo que no es JSON-RPC, así que el `Client` de python no tiene nada mejor que mostrarte que este mensaje genérico.

La causa más común, con diferencia, es un servidor Streamable HTTP recién desplegado. `streamable_http_app()` (y `mcp.run("streamable-http")`) sin `transport_security=` activa por defecto la **protección contra DNS rebinding**: solo acepta solicitudes cuya cabecera `Host` sea localhost. Es el valor por defecto correcto en tu portátil y el incorrecto detrás de un nombre de host real:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Despliega eso, apunta un cliente hacia él y la conexión falla en el handshake:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

Las palabras que el servidor envió realmente, `421` e `Invalid Host header`, nunca te llegan: el cuerpo del 421 no tiene `Content-Type: application/json`, así que el cliente no puede analizarlo. Están en el **log del servidor**, que es donde mirar a continuación:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

La solución es `transport_security=`. Añade a la lista de permitidos el nombre de host que sirves realmente:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    Ese es todo el cambio. El mismo cliente ahora se conecta, negocia `2026-07-28` y llama a
    `forecast`.

**[Desplegar y escalar](run/deploy.md)** cubre lo que significa cada campo, el caso del proxy inverso y todo lo demás que cambia al desplegar. Y `421 Misdirected Request` / `Invalid Host header`, justo debajo, es el mismo fallo visto desde el otro lado.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

Esto es `Server returned an error response`, visto desde cualquier cosa que *no* sea el `Client` de python: curl, la pestaña de red de un navegador, el log de acceso de un proxy inverso u otro SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` es la propia frase de motivo de HTTP para ese estado; `Invalid Host header` es el cuerpo de respuesta del SDK; y el `Client` de python muestra el mismo evento como `Server returned an error response`. Las tres son un único rechazo. La comprobación se hace contra la **cabecera `Host` que lleva la solicitud**, no contra la dirección a la que se enlazó el servidor, así que un proxy inverso que reenvía el nombre de host público la dispara exactamente igual que un cliente directo.

La solución es el mismo `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` que se muestra en `Server returned an error response`. Dos de sus detalles merecen mención:

* Una entrada de `allowed_hosts` es una cadena exacta. `"mcp.example.com"` coincide con una cabecera `Host` sin puerto y `"mcp.example.com:*"` coincide con cualquier puerto explícito. Incluye las dos.
* Un `403` con el cuerpo `Invalid Origin header` es la comprobación hermana sobre la cabecera `Origin`. Solo salta con navegadores (nada más envía `Origin`), y `allowed_origins=` es su lista de permitidos.

**[Desplegar y escalar](run/deploy.md)** lo trata a fondo, incluido cuándo desactivar la comprobación es la configuración honesta.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

Tu app MCP está montada dentro de otra app ASGI, y nada inició su **gestor de sesiones**.

`mcp.streamable_http_app()` devuelve una app Starlette cuyo propio lifespan (ciclo de vida del servidor) inicia el gestor, y `uvicorn server:app` ejecuta ese lifespan por ti. Pero Starlette **nunca ejecuta el lifespan de una subaplicación montada**, así que en cuanto la app va dentro de un `Mount`, el gestor nunca arranca y la primera solicitud explota:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

El servidor arranca. La ruta se resuelve. Luego `uvicorn` imprime esto en cada solicitud:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

El cliente ve un 500. La solución es un lifespan en la app **host** que entre en `mcp.session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

**[Añadir a una app existente](run/asgi.md)** es la página para esto, incluidos varios servidores en una sola app y FastAPI. Dos cadenas vecinas de la misma clase:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` El gestor es de un solo uso; entrar dos veces en el lifespan de la misma app lo provoca.
* `mcp.session_manager` solo existe **después** de llamar a `streamable_http_app()`, así que construye primero las rutas y toca el gestor solo dentro del lifespan.

## `MCPError: Session not found` {#mcperror-session-not-found}

El servidor no reconoce el `Mcp-Session-Id` que envió tu cliente, casi siempre porque el servidor **se reinició** (o te enrutaron a otra instancia). Las sesiones viven en la memoria de ese único proceso.

No hay ningún bug del servidor que encontrar. La respuesta HTTP es un `404` cuyo cuerpo *sí* es JSON-RPC, así que, a diferencia del `421` de arriba, el `Client` de python te muestra este tal cual:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

La solución es reconectar: sal del bloque `async with Client(...)` y entra en uno nuevo, que negocia una sesión nueva. Para un cliente de larga duración, eso significa capturar `MCPError` alrededor de tus llamadas y reconectar ante este mensaje en lugar de reintentar dentro de una sesión muerta.

Si ocurre *sin* un reinicio, estás ejecutando más de un worker sin sticky sessions: cada worker mantiene su propia tabla de sesiones, así que una solicitud enrutada al equivocado acaba aquí. **[Desplegar y escalar](run/deploy.md)** y **[Atender clientes heredados](run/legacy-clients.md)** tienen todos los detalles y las dos soluciones (enrutamiento sticky o `stateless_http=True`).

Para quien opera el servidor, la línea de log correspondiente es `Rejected request with unknown or expired session ID: <id>`. Se registra con nivel `INFO`, así que es invisible con el umbral habitual de `WARNING`. Verla en ráfagas justo después de un despliegue es normal; todos los clientes conectados están reconectando.

## `MCPError: Method not found` {#mcperror-method-not-found}

Un lado envió una solicitud JSON-RPC para la que el otro no tiene handler, y `e.error.data` nombra el método. La causa habitual es un **desajuste de generación**: un método que existe en una revisión del protocolo y no en la otra, enviado a un par que habla la equivocada, como un `resources/subscribe` de la generación `2025` que llega a una conexión `2026-07-28`, o un `subscriptions/listen` exclusivo de `2026` enviado por un cliente fijado en `mode="legacy"`. **[Versiones del protocolo](protocol-versions.md)** es el mapa de qué habla cada lado, y la otra causa legítima (una capacidad opcional para la que nunca registraste un handler) está en **[Autocompletado](servers/completions.md)**.

Hay una cosa que **no** produce este error, aunque es una solicitud que el protocolo moderno eliminó: una herramienta que llama a `ctx.elicit()` en una conexión `2026-07-28`. El servidor se niega siquiera a *enviar* esa solicitud, así que lo que obtienes en su lugar es `Cannot send 'elicitation/create': ...`, más abajo en esta página.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Tu servidor quiere preguntarle algo al usuario, y este cliente nunca dijo que se le pudiera preguntar.

Un resolutor de elicitación (elicitation) se niega de entrada cuando el cliente conectado no declaró la elicitación por formulario, y `e.error.data` nombra exactamente lo que falta:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Pasa `elicitation_callback=` a `Client(...)`. Registrar el callback *es* la declaración de la capacidad; no hay un segundo interruptor:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[Callbacks del cliente](client/callbacks.md)** enumera los demás (`sampling_callback`, `list_roots_callback`), cada uno de los cuales es una declaración del mismo modo.

!!! info
    `-32021` es `MISSING_REQUIRED_CLIENT_CAPABILITY`, uno de los tres códigos de error que añade
    la especificación 2026-07-28. Ninguno de ellos es una clase de excepción: todos llegan como
    `MCPError`, y `e.error.code` es donde mirar. `mcp.types` exporta las constantes. Los otros dos
    son `-32020` `HEADER_MISMATCH` (una cabecera HTTP discrepa del cuerpo de la solicitud a la que
    acompaña) y `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (la solicitud nombraba una versión que
    este servidor no habla). Un cliente SDK conforme no puede producir ninguno de los dos, así que
    si ves uno, mira lo que sea que esté reescribiendo solicitudes entre tu cliente y tu servidor.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

La misma carencia que `Client did not declare the form elicitation capability ...`, expresada por las vías que no comprueban de entrada: el servidor necesitaba que se respondiera una elicitación, y el cliente conectado no registró ningún `elicitation_callback`.

Este lo ves desde `ctx.elicit()` en una conexión heredada, y en cualquier conexión desde una pregunta de varias idas y vueltas (multi-round-trip) devuelta (**[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)**) que llega a un cliente sin callback para responderla. La solución es idéntica: pasa `elicitation_callback=` a `Client(...)`. No hay ninguna versión de "al usuario no se le preguntó" que tu herramienta reciba como un `decline`; un cliente al que no se le puede preguntar es una llamada fallida, así que diseña tus herramientas contando con ello.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

Tu handler intentó contactar con el cliente a mitad de solicitud, en una conexión cuya llamada no tiene ningún canal capaz de llevar una solicitud desde el servidor. Hay tres configuraciones de servidor que ponen una llamada en esa situación.

**Una conexión `2026-07-28`: cualquier transporte, siempre.** El protocolo moderno no tiene solicitudes iniciadas por el servidor en absoluto, así que el servidor se niega antes de enviar nada. `ctx.elicit()` dentro de una herramienta es la forma clásica de toparse con esto (en la primera prueba en memoria, ya que `Client(server)` negocia `2026-07-28` sin que se lo pidas), y pasar `elicitation_callback=` no cambia nada, porque ninguna solicitud llega nunca al cliente para que la responda:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**Una conexión heredada en un servidor con `stateless_http=True`.** Sin estado significa que cada solicitud es su propio mundo: sin sesión, sin flujo de servidor a cliente y, por tanto, sin ningún lugar al que enviar un `elicitation/create` (o `sampling/createMessage`, o `roots/list`), ni siquiera en la generación que los tiene:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**Una conexión heredada en un servidor con `json_response=True`.** El `POST` se responde con un único cuerpo JSON, y un único cuerpo solo lleva la respuesta, así que el flujo ligado a la solicitud que necesita un `ctx.elicit()` a mitad de solicitud tampoco existe aquí. La sesión, su `Mcp-Session-Id` y su flujo independiente siguen ahí; solo ha desaparecido el canal ligado a la solicitud.

El mensaje nombra el método que no pudo enviar. `NoBackChannelError` es la clase que lanza el servidor, pero lo que se transmite lleva solo el `MCPError` base, así que la frase de arriba es la última línea de tu traceback, no el nombre de la clase.

Para un cliente `2026-07-28` la solución es la misma en las tres: no vuelvas al cliente a mitad de llamada. Mueve la pregunta a un **resolutor** (o devuelve tú mismo un `InputRequiredResult`) y pasa a formar parte de la *respuesta*, que todas las conexiones pueden llevar:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

La misma pregunta, el mismo `elicitation_callback` en el cliente. La diferencia es interna: un resolutor permite al servidor *devolver* la pregunta desde la llamada en lugar de empujarla, así que nunca fluye nada de servidor a cliente. Eso rescata a todos los clientes `2026-07-28`, sea cual sea la configuración de las tres en que esté el servidor. A un cliente *heredado* no lo rescata la reescritura por sí sola: `2025-11-25` no tiene forma de devolver una pregunta, así que en una conexión heredada el resolutor sigue enviando `elicitation/create` por el canal ligado a la solicitud, y sigue necesitando un servidor que lo conserve: ni `stateless_http=True` ni `json_response=True`. **[Elicitación](handlers/elicitation.md)** cubre los resolutores; **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)** cubre lo que ocurre en lo que se transmite.

!!! check
    La herramienta con `ctx.elicit()` no está mal, es *anterior a 2026*. Conéctate con
    `mode="legacy"` (el handshake clásico de `initialize`, especificación `2025-11-25` y anteriores)
    a un servidor que no tenga ni `stateless_http=True` ni `json_response=True`, y funciona, porque
    ahí el canal de servidor a cliente existe.
    **[Versiones del protocolo](protocol-versions.md)** es la página sobre qué tiene cada versión.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

El servidor no pudo verificar el token `requestState` que tu cliente devolvió como eco, así que rechazó la ronda.

`requestState` es el token opaco de reanudación que una llamada **[de varias idas y vueltas](handlers/multi-round-trip.md)** lleva entre tramos. `MCPServer` lo sella al salir y verifica cada eco, y verifica *cada* `request_state` entrante en `tools/call`, `prompts/get` y `resources/read`, incluso para un handler que nunca emite uno. Así que un token que este proceso no selló se rechaza dondequiera que llegue:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

El mensaje está congelado a propósito: lo que se transmite nunca revela qué comprobación falló. El motivo va al **log del servidor**, y leerlo es todo el diagnóstico:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Los motivos que verás realmente:

* **`unknown key`** es el que importa. La clave de sellado por defecto se genera al arrancar el proceso, así que un reintento que cae en un **worker distinto**, en otra instancia detrás de un balanceador de carga o en el mismo servidor **después de un reinicio** se selló con una clave que este proceso nunca tuvo. No es un atacante; es el valor por defecto encontrándose con más de un proceso.
* **`audience`**: el token lo selló una instancia con un *nombre de servidor distinto*. El nombre es el claim de audiencia por defecto del sello, así que una flota debe compartir el nombre (o fijar un `RequestStateSecurity(audience=...)` explícito) además de las claves.
* **`expired`**: la ronda tardó más que el `ttl` del sello, que es de 600 segundos y por ronda, no por llamada.
* **`malformed`** / **`codec error`**: el token se alteró en tránsito, o nunca fue un token sellado.
* **`request binding`**: el token volvió con otra herramienta, otros argumentos u otro método.

La solución multiproceso es un argumento (las *mismas* `keys` en todas las instancias) más una cosa que no es un argumento en absoluto: el mismo *nombre* de servidor (o un `audience=` compartido explícito).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` sella; todas las claves de la lista verifican, que es lo que hace posible la rotación sin tiempo de inactividad. **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md#protecting-requeststate)** explica qué protege el sello y la secuencia de rotación, y **[Desplegar y escalar](run/deploy.md)** recorre todo el fallo de dos workers y su solución en dos partes.

!!! tip
    `keys=[...]` rechaza una clave débil de inmediato, con un mensaje inusualmente útil:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Haz lo que dice.

## ¿Sigues sin resolverlo? {#still-stuck}

* Si un mensaje que produjo el SDK no está en esta página, eso es un bug de documentación que vale la pena reportar por sí solo.
* Busca en el [gestor de incidencias](https://github.com/modelcontextprotocol/python-sdk/issues); la mayoría de las cadenas de error que aparecen ahí ya son el informe de alguien.
* ¿No encontraste nada? [Abre una incidencia](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) con el traceback completo, o pregunta en [#python-sdk-dev en el Discord de MCP Contributors](https://discord.gg/6CSzBmMkjX).

## Resumen {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` nunca es el error. Lee la **última línea**; capturar `MCPError` *dentro* del bloque `async with Client(...)` evita el envoltorio por completo.
* `call_tool` no lanza nada para una herramienta que falla. `Error executing tool ...` y `Unknown tool: ...` son resultados: comprueba `result.is_error`.
* `Client must be used within an async context manager` -> usa `async with`. `Use @tool() instead of @tool` -> añade los paréntesis.
* `Tool already exists:` en el log del servidor es la única señal de que dos herramientas con el mismo nombre se fundieron en una.
* Un 421, tres formas de escribirlo: `Server returned an error response` (el `Client` de python), `421 Misdirected Request` / `Invalid Host header` (todo lo demás), `Invalid Host header: <host>` (el log del servidor). Solución: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> una app montada cuyo lifespan de la app host nunca entró en `mcp.session_manager.run()`.
* `Session not found` -> el servidor se reinició; reconecta.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` necesita un canal de servidor a cliente: una conexión `2026-07-28` nunca lo tiene, `stateless_http=True` quita el heredado y `json_response=True` quita el ligado a la solicitud. Usa un resolutor (un cliente heredado necesita además un servidor que conserve el canal). Su vecino `Method not found` es una solicitud de un método que la revisión del protocolo del otro lado no tiene.
* `Client did not declare the form elicitation capability ...` y `Elicitation not supported` -> al cliente le falta `elicitation_callback=`.
* `Invalid or expired requestState` nunca dice por qué en lo que se transmite. El log del servidor sí; `unknown key` significa compartir `RequestStateSecurity(keys=[...])` entre los workers.
