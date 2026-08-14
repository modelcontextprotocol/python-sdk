---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# El Server de bajo nivel {#the-low-level-server}

`@mcp.tool()` es una capa. Debajo hay una segunda clase de servidor, `Server`, que habla MCP en crudo: le pasas los objetos del protocolo y los transmite tal cual, sin tocarlos.

`MCPServer` está construido encima. Bajas de nivel cuando la capa de conveniencia estorba:

* Necesitas emitir un esquema **exacto** (cargado de un archivo, generado a partir de una base de datos), no uno derivado de una firma de Python.
* Necesitas control total del resultado: `_meta`, `is_error`, cada clave de `structured_content`.
* Necesitas atender un método que MCP no define.

Para todo lo demás, quédate en `MCPServer`.

## La misma herramienta, a mano {#the-same-tool-by-hand}

Esta es la herramienta `search_books` que **[Herramientas](../servers/tools.md)** escribe en nueve líneas de `@mcp.tool()`, sin el azúcar sintáctico:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Cambiaron tres cosas, y son toda la API de bajo nivel:

* **Los handlers son parámetros del constructor.** `on_list_tools=` y `on_call_tool=` van en `Server(...)`. Aquí abajo no hay decoradores, y todos los handlers tienen la misma forma: `async (ctx, params) -> result`.
* **Tú escribes el esquema de entrada.** `Tool.input_schema` es un simple `dict` de JSON Schema. Nadie lo deriva de las anotaciones de tipo, porque no hay anotaciones de tipo de las que derivarlo.
* **Tú construyes el resultado.** `CallToolResult(content=[TextContent(...)])`, a mano. Nada se envuelve, se convierte ni se infiere de una anotación de retorno.

`params` es la solicitud ya analizada: `CallToolRequestParams` te da `.name` y `.arguments`. `ctx` es un `ServerRequestContext`: `ctx.session` para responder al cliente, `ctx.lifespan_context`, `ctx.request_id` y `ctx.meta`, el `_meta` entrante de la solicitud.

!!! info
    Si has usado FastAPI, ya conoces esta relación. `MCPServer` es la capa de decoradores y anotaciones de tipo; `Server` es el Starlette de debajo. No son rivales: `MCPServer` construye un `Server` y registra en él handlers exactamente como estos.

### Pruébalo {#try-it}

Aquí no hay Inspector: `mcp dev` y `mcp run` solo aceptan un `MCPServer`. Al `Client` en memoria le da igual; acepta un `Server` de bajo nivel exactamente igual que acepta un `MCPServer`:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

El mismo texto que produjo la versión con `@mcp.tool()`. Dos diferencias honestas:

* `result.structured_content` es `None`. El servidor de alto nivel envuelve un `-> str` en `{"result": ...}` por ti; aquí nadie construye lo que no construiste.
* `list_tools` devuelve el esquema que escribiste **tú**, carácter por carácter. La versión de alto nivel tenía `"title": "Query"` en cada propiedad y un `"title": "search_booksArguments"` en la raíz: artefactos de Pydantic. Aquí abajo, si se transmite, es porque lo pusiste ahí.

## Nada se comprueba por ti {#nothing-is-checked-for-you}

`MCPServer` rechaza un argumento incorrecto antes de que tu función llegue a ejecutarse, validando la llamada contra el esquema que generó (**[Herramientas](../servers/tools.md)**).

`Server` no hace eso. Tu `input_schema` se *anuncia* al cliente; nunca se *aplica* a `params.arguments`.

!!! check
    Llama a `search_books` sin `limit` y tu `args["limit"]` lanza `KeyError`. El cliente ve:

    ```text
    MCPError: Internal server error
    ```

    Un error de JSON-RPC, código `-32603`, con un mensaje deliberadamente genérico: el SDK no filtra tu traceback a un llamador remoto. El modelo nunca se entera de qué hizo mal, así que no puede reintentar. (En una prueba, `raise_exceptions=True` muestra la excepción real en su lugar; consulta **[Pruebas](../get-started/testing.md)**.)

Eso se generaliza. Una excepción lanzada desde un handler de bajo nivel es **siempre** un error de protocolo, nunca un resultado de herramienta con `is_error=True`. Si quieres que el modelo lea el fallo y se recupere, valida `params.arguments` por tu cuenta y devuelve `CallToolResult(content=[TextContent(...)], is_error=True)`. Los dos tipos de fallo son el tema de **[Manejo de errores](../servers/handling-errors.md)**.

## Dos herramientas, un handler {#two-tools-one-handler}

`on_call_tool` es el único punto de entrada para todas las herramientas del servidor. Enrutas según `params.name`:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` anuncia las dos. `call_tool` despacha según el nombre.
* La rama `else` importa: `Server` reenvía sin problema un `tools/call` para un nombre que nunca listaste directamente a tu handler. Lanzar una excepción ahí convierte la llamada en el mismo `-32603` de antes.

## Salida estructurada, a mano {#structured-output-by-hand}

Declara `output_schema` en el `Tool` y pon `structured_content` en el resultado. Ambos son cosa tuya:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Llámala y el resultado lleva ambas representaciones:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

El bloque `_meta` es el sello de identidad del servidor: el SDK lo añade a cada resultado de la generación 2026, con la `version` del constructor (un servidor que no establece ninguna informa una cadena vacía). Un servidor que no deba identificarse puede quitar la clave con un middleware, que es dueño de los resultados que devuelve.

El servidor nunca compara los dos campos. El `Client` de este SDK sí: devuelve un `structured_content` que no cumpla el `output_schema` que declaraste y `call_tool` lanza un `RuntimeError` que empieza por `Invalid structured content returned by tool search_books` y sigue citando el fallo de `jsonschema`. Prometer un esquema es barato; cumplirlo depende de ti. Toda la escalera de tipos de retorno y esquemas está en **[Salida estructurada](../servers/structured-output.md)**.

## `_meta`: para la aplicación, no para el modelo {#\_meta-for-the-application-not-the-model}

`content` es la parte de la respuesta que lee el modelo. `structured_content` es la misma respuesta como datos tipados. `_meta` es el tercer canal: datos que viajan con el resultado para la **aplicación cliente**, sin formar parte de la respuesta en absoluto.

Úsalo para ID de registros, ID de trazas, cualquier cosa que tu interfaz necesite y tu prompt no:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* Lo construyes como `_meta=`, el nombre que se transmite. El cliente lo lee de vuelta como `result.meta`.
* Pon tus claves en un espacio de nombres (`bookshop/record_ids`). Las claves `io.modelcontextprotocol/*` están reservadas por el protocolo.

!!! warning
    `_meta` es una convención entre tú y la aplicación cliente, no una garantía sobre lo que llega
    al modelo. El host decide qué muestra. Nunca pongas un secreto en ninguna parte de un resultado de herramienta.

## Las capacidades siguen a tus handlers {#capabilities-follow-your-handlers}

Un `Server` anuncia exactamente las familias de métodos para las que le diste handlers. El `Bookshop` de arriba pasa `on_list_tools` y `on_call_tool` y nada más, así que un cliente que se conecta a él ve:

```json
{"tools": {"listChanged": false}}
```

Ni `resources` ni `prompts`: no hay nada que los respalde. Pasa `on_list_prompts` y aparece `prompts`; pasa `on_completion` y aparece `completions`.

`MCPServer` siempre anuncia herramientas, recursos y prompts, hayas registrado alguno o no, porque sus gestores siempre existen. Aquí abajo la declaración *es* la llamada al constructor.

## El genérico del lifespan {#the-lifespan-generic}

`Server` es genérico en el tipo que produce su lifespan. Anótalo una vez y el objeto queda tipado en todos los sitios donde aparece:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* El lifespan es un `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`; `@asynccontextmanager` sobre un generador `async` te da exactamente eso.
* Lo que produzca con `yield` se convierte en `ctx.lifespan_context`, y como los handlers están anotados como `ServerRequestContext[Catalog]`, `.search(...)` se autocompleta y pasa la comprobación de tipos.
* Se entra en él una vez cuando el servidor arranca y se sale una vez cuando se detiene. El arranque, la finalización y la versión de `MCPServer` de la misma idea están en **[Lifespan](../handlers/lifespan.md)**.

Sin un `lifespan=`, `ctx.lifespan_context` es un `dict` vacío.

## Un método propio {#a-method-of-your-own}

El constructor cubre los métodos que MCP define. `add_request_handler` cubre todo lo demás:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* El primer argumento es la cadena del método. Las notificaciones tienen un gemelo, `add_notification_handler`.
* `params_type` es el modelo contra el que se validan los `params` entrantes **antes** de que se ejecute tu handler, así que los métodos personalizados *sí* reciben la validación que las herramientas no. Hereda de `RequestParams` para que el campo `_meta` se analice como el de cualquier otro método.
* El handler devuelve un `BaseModel`, un `dict` o `None`. El SDK lo serializa en el resultado JSON-RPC.

Una advertencia honesta: el `Client` de alto nivel solo tiene verbos para los métodos que MCP define, así que no hay `client.reindex()`. Un método de proveedor es para un par que ya sabe que existe: un cliente que también distribuyes, u otro servicio tuyo que hable JSON-RPC.

Un método que no puedes reclamar:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

El handshake pertenece al runner. `server/discover`, `ping` y todos los demás métodos integrados son tuyos para reemplazarlos.

!!! tip
    `Server.middleware`, mencionado en ese error, envuelve **todos** los mensajes entrantes, incluido `initialize`. Si lo que quieres es observar o reescribir el tráfico en vez de responder a un método nuevo, empieza en **[Middleware](middleware.md)**.

## Los otros handlers {#the-other-handlers}

Cada uno de estos es una idea para la que ya tienes el vocabulario; cada uno tiene su propia página.

* `on_call_tool`, `on_get_prompt` y `on_read_resource` pueden devolver un `InputRequiredResult` en lugar de su resultado normal para pausar la llamada y pedir datos al cliente; consulta **[Solicitudes de varias idas y vueltas (multi-round-trip)](../handlers/multi-round-trip.md)**. Fiel a este nivel, nada se instala por ti: donde `MCPServer` sella `requestState` por defecto, aquí el `request_state` que estableces se transmite exactamente como lo escribiste hasta que optas por `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))`: una línea (ambos nombres se importan de `mcp.server.request_state`) para el mismo sellado y verificación que realiza `MCPServer` (**[Proteger `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt` y `on_completion` tienen la misma forma `(ctx, params) -> result` para las demás primitivas.
* `on_subscriptions_listen` sirve el stream `subscriptions/listen` de 2026-07-28. Pasa un `ListenHandler` construido sobre un `SubscriptionBus` y publica eventos en el bus desde tus otros handlers; consulta **[Suscripciones](../handlers/subscriptions.md)** para la composición completa.
* `server.streamable_http_app()` devuelve la misma app de Starlette que la de `MCPServer`; despliégala como **[Ejecutar tu servidor](../run/index.md)** despliega cualquier otra app ASGI. Aquí abajo no hay `server.run(transport=...)`: `server.run(read_stream, write_stream, server.create_initialization_options())` conduce una conexión sobre un par de streams, y esa única línea es todo lo que hay.

## Resumen {#recap}

* El `Server` de bajo nivel recibe sus handlers como **parámetros del constructor** `on_*`; cada handler es `async (ctx, params) -> result`.
* Tú escribes el dict `input_schema` y tú construyes el `CallToolResult`. Nada se deriva, se envuelve ni se valida por ti.
* Una excepción en un handler es un error de protocolo `-32603`. Un error de herramienta que el modelo pueda leer es un `CallToolResult` con `is_error=True` que devuelves **tú**.
* El `_meta` del resultado va dirigido a la aplicación cliente, no al modelo.
* `Server[T]` es genérico en lo que produce su lifespan; `ctx.lifespan_context` es un `T` tipado.
* `add_request_handler(method, params_type, handler)` sirve cualquier método. `initialize` está reservado.
* Las capacidades que anuncia un `Server` se derivan de los handlers que registraste.

`Client(server)` trató a ambos servidores de forma idéntica porque *son* el mismo protocolo, que es justamente la idea. La siguiente capa hacia abajo no es una clase: es **[Middleware](middleware.md)**.
