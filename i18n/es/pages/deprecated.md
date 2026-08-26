---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# Funcionalidades obsoletas {#deprecated-features}

La especificación 2026-07-28 retira cinco cosas. El SDK sigue implementando todas y cada una, y todas llevan ahora un **aviso de obsolescencia**. Una función auxiliar del SDK queda obsoleta por su cuenta y aparece [al final](#deprecated-sdk-helpers).

La tabla siguiente nombra cada funcionalidad obsoleta, explica por qué desaparece e indica el reemplazo sobre el que construir.

## Qué queda obsoleto {#what-is-deprecated}

| Obsoleto | Por qué | Qué hacer en su lugar |
|---|---|---|
| **Roots** (directorios raíz): `ctx.session.list_roots()`, `client.send_roots_list_changed()`, el `list_roots_callback=` que pasas a `Client(...)` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) retira la capacidad. | Recibe las rutas como argumentos de herramienta normales o URI de recurso, o incrusta una `ListRootsRequest` en un `InputRequiredResult` (consulta **[Solicitudes de varias idas y vueltas (multi-round-trip)](handlers/multi-round-trip.md)**). |
| **Muestreo (sampling) iniciado por el servidor**: `ctx.session.create_message()`, el `sampling_callback=` que pasas a `Client(...)` | SEP-2577 retira la capacidad. | Devuelve `InputRequiredResult` y deja que el cliente reintente la llamada (consulta **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)**). |
| **Registro de logs del protocolo**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 retira la capacidad. Nada dentro del protocolo la reemplaza. | El `import logging` de siempre hacia stderr (consulta **[Registro de logs](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | **Eliminado** del protocolo, no solo obsoleto. No hay método `ping` en 2026-07-28. | Nada. Solo funciona contra una conexión `mode="legacy"`. |
| **Progreso de cliente a servidor**: `client.send_progress_notification()` | 2026-07-28 hace que el progreso sea solo de servidor a cliente. | Nada que enviar. Tu *servidor* informa del progreso con `ctx.report_progress()` (consulta **[Progreso](handlers/progress.md)**). |

De esa tabla se desprenden tres cosas:

* Roots, muestreo y registro de logs van juntos. Una sola propuesta, **SEP-2577**, deja obsoletas las tres capacidades a la vez.
* El muestreo y los roots comparten un problema más profundo: son lugares donde un **servidor** envía una **solicitud** al **cliente**. Esa dirección entera es lo que 2026-07-28 reemplaza con las **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)**. Lo que desaparece son los métodos RPC independientes (`sampling/createMessage`, `roots/list` y el `elicitation/create` de estilo push); los tipos de payload `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` sobreviven, incrustados en `InputRequiredResult.input_requests`, y en el cliente llegan a los mismos callbacks.
* `ping` es la excepción. El protocolo no lo deja obsoleto: lo elimina. El método del SDK sigue avisando (su mensaje dice *removed*, no *deprecated*) y llamarlo en una conexión moderna responde con *"Method not found"*.

## Obsoleto es solo un aviso {#deprecated-is-advisory}

Hoy no se rompe nada.

Todos los métodos anteriores siguen funcionando contra cualquier sesión que haya negociado **2025-11-25 o anterior**. Fija `mode="legacy"` en el cliente y obtienes exactamente el comportamiento anterior a 2026. No hay cambios en lo que se transmite y la negociación de capacidades no cambia.

Lo que cambia es que recibes un aviso visible la primera vez que se ejecuta cada uno:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` hereda de `UserWarning`, **no** de `DeprecationWarning`. Es deliberado: el filtro por defecto de Python solo muestra `DeprecationWarning` en código que se ejecuta directamente como `__main__`, y así es como las bibliotecas dejan cosas obsoletas sin que nadie se entere durante dos años. Este aparece en todas partes, sin ninguna opción `-W`.

!!! warning
    "Solo un aviso" deja de ser cierto en el canal. El muestreo y los roots son *solicitudes*
    de servidor a cliente, y una sesión 2026-07-28 no tiene ningún canal que las transporte.
    Llama a `ctx.session.create_message()` dentro de una herramienta en una conexión moderna y
    el aviso se dispara igual, y después el envío falla con un error:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Dos señales, en ese orden. El `MCPDeprecationWarning` se dispara en el momento en que llamas
    al método, en cualquier conexión. El error es lo que vuelve cuando a continuación el SDK
    intenta enviar. Estas dos funcionalidades solo funcionan de extremo a extremo en una conexión
    `mode="legacy"` cuyo cliente registró el callback correspondiente.

## `ping` en una sesión heredada {#ping-on-a-legacy-session}

Un **ping** es una solicitud vacía que cualquiera de los dos lados puede enviar para comprobar que el otro sigue respondiendo. La especificación 2026-07-28 lo elimina ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): cada solicitud que envía un cliente moderno ya demuestra que el servidor está ahí, y un servidor moderno no tiene canal por el que enviar uno. Ambos métodos del SDK siguen funcionando en una sesión de la generación del handshake. Desde el cliente:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

Y desde el servidor, dentro de cualquier handler:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` avisa con `MCPDeprecationWarning` en cada llamada. En una conexión por defecto (`2026-07-28`), el servidor responde `MCPError: Method not found` en su lugar.
* `ctx.session.send_ping()` no lleva ningún aviso. En una conexión moderna lanza el mismo error de falta de canal de retorno (back-channel) que cualquier otra solicitud iniciada por el servidor.
* Ninguno de los dos lados registra nada para responder a un ping.

## Notificaciones de cambio de roots {#roots-change-notifications}

Un cliente de la generación 2025 que declaró la capacidad roots puede avisar al servidor de que sus carpetas del espacio de trabajo cambiaron enviando `notifications/roots/list_changed`; el servidor responde solicitando `roots/list` de nuevo. La especificación 2026-07-28 elimina la notificación junto con el resto del flujo de roots de estilo push. En el cliente, pasar `list_roots_callback=` (**[Callbacks del cliente](client/callbacks.md)**) es lo que declara `"roots": {"listChanged": true}`, y una llamada cumple esa promesa:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

En el servidor, el `Server` de bajo nivel acepta el handler que la recibe:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` es la lista que devuelve tu `list_roots_callback`. `client.send_roots_list_changed()` avisa, y necesita un cliente `mode="legacy"`: en una conexión moderna la notificación se descarta en silencio. Mantén la sesión abierta después, porque el `roots/list` posterior del servidor llega por ella.
* `MCPServer` no tiene ningún hook para la notificación. En el `Server` de bajo nivel, `on_roots_list_changed=` registra el handler (también obsoleto, y avisa en la construcción). La notificación no lleva payload, así que el handler llama a `ctx.session.list_roots()` para obtener la lista nueva.

## Silenciar el aviso {#silencing-the-warning}

No lo hagas en código nuevo.

Pero un servidor que mantienes y que de verdad atiende a clientes anteriores a 2026 tiene todo el derecho a un log tranquilo. Filtra la categoría antes de que se ejecute la primera llamada obsoleta:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

Esa es toda la API. No hay un interruptor por método, y tampoco lo quieres: la gracia de tener una sola categoría es que una línea la silencia y una línea la trae de vuelta.

!!! check
    Aplica el filtro al revés y obtienes una prueba de regresión gratis. Añade
    `"error::mcp.MCPDeprecationWarning"` al ajuste `filterwarnings` de tu configuración de
    pytest y la llamada obsoleta **lanza una excepción** en lugar de avisar. Una herramienta
    llamada `old_log` que todavía llama a `ctx.info()` deja de pasar: la llamada vuelve con
    `is_error=True` y `Error executing tool old_log`, y el log capturado del servidor señala
    al culpable:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Una línea de configuración de pytest, y una llamada obsoleta nunca podrá volver a colarse
    en tu código sin que falle una prueba.

## Funciones auxiliares del SDK obsoletas {#deprecated-sdk-helpers}

No son cambios de la especificación, solo detalles internos del SDK con un reemplazo mejor. Avisan con el mismo `MCPDeprecationWarning` y se eliminarán en 3.0.

| Obsoleto | Qué hacer en su lugar |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` y después `FuncMetadata.call_fn()`. Solo lo llamaba el código que maneja `FuncMetadata` directamente (una subclase propia de `Tool`, por ejemplo). |

## Resumen {#recap}

* La especificación 2026-07-28 deja obsoletos los **roots**, el **muestreo** iniciado por el servidor y el **registro de logs** del protocolo (todo en [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), restringe el **progreso** a la dirección servidor a cliente y elimina **`ping`**.
* La columna de reemplazos te indica el camino: **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)** para el muestreo y los roots, **[Registro de logs](handlers/logging.md)** para los logs, **[Progreso](handlers/progress.md)** para el progreso. `ping` no necesita nada en absoluto.
* Obsoleto es solo un aviso: no hay cambios en lo que se transmite, todo sigue funcionando contra sesiones anteriores a 2026 y recibes un `MCPDeprecationWarning` visible (un `UserWarning`, así que está activo por defecto).
* El muestreo y los roots necesitan además un canal de retorno que una sesión 2026-07-28 no tiene. En una conexión moderna avisan y después lanzan una excepción.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` silencia toda la categoría; `"error::mcp.MCPDeprecationWarning"` en pytest la convierte en un fallo de prueba.
* Una función auxiliar del SDK, `FuncMetadata.call_fn_with_arg_validation()`, queda obsoleta por separado y se eliminará en 3.0.
* El código nuevo no debería construirse sobre nada de esto.

Todas las demás páginas de esta documentación enseñan la API actual.
