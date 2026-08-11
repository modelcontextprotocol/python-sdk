---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# Extensiones {#extensions}

Una **extensión** es un paquete opcional de comportamiento MCP detrás de un único identificador.

En un servidor puede aportar herramientas, recursos y nuevos métodos de solicitud, y puede envolver
`tools/call`. En un cliente puede reclamar formas de resultado adicionales de `tools/call` y observar
notificaciones de proveedor. Cada lado se anuncia bajo su propio `capabilities.extensions`, y nada
cambia para quien no lo haya pedido. Ese es el contrato ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)), y
tiene una regla de oro: **las extensiones están desactivadas por defecto**.

## Usar una extensión {#using-an-extension}

Pasa las instancias al construir:

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

Listo. El servidor ahora anuncia `io.modelcontextprotocol/ui` bajo
`capabilities.extensions` y sirve todo lo que aporta la extensión.

`Apps` es la extensión de referencia incorporada y tiene su propia página: **[MCP Apps](apps.md)**.

!!! note
    Las extensiones se fijan al construir. No hay un `add_extension` que llamar después:
    el mapa de capacidades de un servidor no debería cambiar mientras haya clientes conectados a él.

El mapa de capacidades viaja en `server/discover`, que es una ruta de **2026-07-28**. Un
handshake `initialize` heredado no tiene dónde ponerlo, así que un cliente heredado simplemente
no ve la extensión. Diseña pensando en eso: una extensión *amplía* un servidor, no debe ser la
única forma de usarlo.

## Escribir la tuya {#writing-your-own}

Crea una subclase de `Extension` y sobrescribe solo lo que necesites. Cada método tiene un valor por defecto.

### El identificador {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

El identificador es una cadena `vendor-prefix/name` que sigue la gramática de claves `_meta`
de la especificación: etiquetas separadas por puntos (cada una empieza con una letra y termina
con una letra o un dígito), una barra y luego el nombre. Se valida **cuando se define la clase**,
así que un error tipográfico no espera a que arranque un servidor:

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

Usa como prefijo un dominio que controles. `io.modelcontextprotocol/*` es para extensiones
especificadas por el propio proyecto MCP.

### Aportar herramientas {#contributing-tools}

La extensión útil más pequeña es una herramienta y un mapa de ajustes:

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` devuelve objetos `ToolBinding`. El servidor registra cada uno exactamente como si
  hubieras llamado tú a `mcp.add_tool(...)`: la misma generación de esquema, la misma inyección
  de `Context`, todo igual.
* `settings()` es el valor anunciado en `capabilities.extensions["com.example/stamps"]`.
  Devuelve `{}` (el valor por defecto) para anunciar la extensión sin ajustes.
* La extensión nunca recibe el servidor. Declara sus aportaciones como datos;
  `MCPServer` las consume. No hay un `self.server` que mutar.

Y `main()` es la prueba, un cliente en memoria directamente contra `mcp`:

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### Servir tus propios métodos {#serving-your-own-methods}

Una extensión puede registrar **nuevos métodos de solicitud**: sus propios verbos, servidos junto a los
de la especificación:

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` es una subclase de `RequestParams`, así que el sobre `_meta` de 2026 se analiza
  de forma uniforme y tu handler recibe parámetros validados, nunca un diccionario en bruto. Acota lo
  que controla el cliente: `Field(ge=1, le=100)` rechaza un `limit` absurdo antes de que
  tu código reserve nada para él.
* `require_client_extension(ctx, EXTENSION_ID)` es el filtro: un cliente que no declaró
  la extensión recibe el error `-32021` (falta una capacidad de cliente requerida),
  con el payload legible por máquina `requiredCapabilities` que pide la especificación.
* `protocol_versions=frozenset({"2026-07-28"})` fija el método a una única versión del protocolo.
  En cualquier otra versión el cliente recibe `METHOD_NOT_FOUND`, exactamente como si el método
  no existiera ahí. Para ese cliente, no existe.

Los métodos son **estrictamente aditivos**. El SDK lo hace cumplir al construir, no en
tiempo de ejecución:

* Un `MethodBinding` para un método definido por la especificación (`tools/list`, `completion/complete`, ...)
  lanza `ValueError` cuando se construye el binding. Los verbos principales pertenecen al servidor.
* Dos extensiones que vinculan el mismo método lanzan una excepción cuando se registra la segunda.
  Que gane la última escritura es como los plugins se corrompen entre sí; aquí no hacemos eso.
* Un conjunto `protocol_versions` vacío también lanza una excepción: un método que nunca puede
  servirse es un bug, no una configuración.

### El lado del cliente {#the-client-side}

El `main()` del mismo archivo es toda la historia del cliente, sus dos mitades:

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` declara la extensión. Las
  declaraciones se convierten en `ClientCapabilities.extensions`: en una conexión 2026-07-28
  el mapa viaja en el sobre `_meta` de cada solicitud, así que el servidor lo ve en
  **cada** solicitud; en una conexión heredada viaja en el handshake `initialize`.
  Al código del servidor le da igual cuál: `require_client_extension(ctx, ...)` y
  `ctx.session.check_client_capability(...)` leen la fuente correcta en ambas rutas.
* Los métodos de proveedor bajan una capa hasta `client.session.send_request(...)`; `Client`
  solo incorpora métodos de primera clase para los verbos de la especificación. `send_request`
  acepta cualquier subclase de `Request`, así que la solicitud de proveedor pasa tal cual.

### Interceptar `tools/call` {#intercepting-toolscall}

El único hook que intercepta. Sobrescribe `intercept_tool_call` para observar, cortocircuitar
o vetar una llamada a herramienta:

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` es el `CallToolRequestParams` validado: obtienes `params.name` y
  `params.arguments` sin tocar JSON en bruto. También es lo que decide qué llamada a
  herramienta se ejecuta: pasar un contexto reescrito a través de `call_next` cambia lo que
  el handler observa en `ctx`, no la invocación de la herramienta. Reescribir solicitudes a
  nivel del canal es cosa de [Middleware](middleware.md).
* `call_next(ctx)` ejecuta el resto de la cadena y devuelve el resultado del handler.
  Devuélvelo sin cambios (observar), devuelve otra cosa (reemplazar) o lanza un
  `MCPError` (rechazar). Lo que devuelvas se serializa como cualquier resultado de
  handler, incluido el sello de identidad `serverInfo` de la generación 2026, así que un
  interceptor que cortocircuita nunca produce una respuesta anónima o fuera de esquema.
* Con varias extensiones, los interceptores se anidan en orden de registro: la primera
  extensión en `extensions=[...]` es la más externa.
* La implementación por defecto deja pasar todo, y un servidor cuyas extensiones nunca
  sobrescriben este hook mantiene intacto el handler `tools/call` sin más. No
  pagas por lo que no usas.

El hook envuelve `tools/call` y nada más. Para lo que afecta a cada mensaje, usa
[Middleware](middleware.md). Para eso está.

## Usar una extensión de cliente {#using-a-client-extension}

Una **extensión de cliente** es el mismo contrato desde el lado que consume: un paquete de
comportamiento del lado del cliente detrás de un único identificador. Pasa las instancias a
`Client(extensions=[...])` y llama a las herramientas con normalidad:

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` devuelve un `CallToolResult` normal, como cualquier otra llamada. Lo que
cambió la extensión: el servidor ahora puede responder a `buy` con una **forma de resultado**
`receipt` en lugar de un resultado final, y `Receipts` la termina (aquí canjeando el
recibo con una llamada de seguimiento) antes de que `call_tool` devuelva. Nada del punto
de llamada se mueve.

Quita la extensión y nada de esto existe: el filtro del servidor rechaza a un cliente
que no la declaró (error -32021), y una forma reclamada procedente de un servidor que
se salta el filtro falla la validación, exactamente como exige la especificación para un
`resultType` no reconocido. Desactivada por defecto, en ambos extremos del canal.

Para anunciar un identificador **sin** comportamiento del lado del cliente (el servidor filtra
según la capacidad, el cliente no hace nada, como en el cliente de búsqueda de arriba), usa
`advertise()`:

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## Escribir una extensión de cliente {#writing-a-client-extension}

Crea una subclase de `ClientExtension` y sobrescribe solo lo que necesites. Tres tipos de
aportación, cada uno con un valor por defecto: `settings()`, `claims()` y `notifications()`.

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* El identificador sigue la misma gramática que el del servidor y se valida cuando se
  define la clase.
* `claims()` devuelve objetos `ResultClaim`: una etiqueta del canal, el modelo que la analiza y el
  resolutor que la termina. El modelo debe fijar la etiqueta con
  `result_type: Literal["receipt"]` y no debe ser subclase de los tipos de resultado principales
  del verbo; ambas cosas se hacen cumplir cuando se construye el claim. Los campos de proveedor como
  `receipt_token` viajan por el canal tal cual: una forma sustituida llega al cliente
  literalmente.
* El resolutor recibe el modelo analizado y un `ClaimContext`; `ctx.session` es el
  mismo identificador público que `client.session`, así que los seguimientos son llamadas de
  sesión normales. Devuelve el `CallToolResult` normal del verbo.
* `settings()` es el valor anunciado en `ClientCapabilities.extensions[identifier]`,
  leído una vez al construir el `Client`.

`notifications()` declara las notificaciones de servidor de proveedor que se van a observar:

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

El handler recibe los parámetros validados de uno en uno, en orden de despacho. Observa; no puede vetar
ni responder.

Dos reglas discretas. Los claims solo están activos en conexiones 2026-07-28, y el anuncio de
capacidades los sigue: en una conexión heredada los claims se disuelven y el identificador sale
del anuncio con ellos, así que el cliente nunca anuncia una extensión cuyas formas
rechazaría. Y cuando quieras la forma reclamada tú mismo en lugar del resolutor,
llama a `client.session.call_tool(..., allow_claimed=True)`; sin esa bandera, una
forma reclamada que llega a un llamador del nivel de sesión lanza `UnexpectedClaimedResult`.

### Verbos de extensión {#extension-verbs}

Los métodos de solicitud propios de una extensión no necesitan registro del lado del cliente. Un tipo
de solicitud de proveedor es una subclase de `mcp.types.Request` y pasa por `client.session.send_request`,
como en [Servir tus propios métodos](#serving-your-own-methods). Un añadido: cuando una
clave de los parámetros debe viajar en el header `Mcp-Name` (las especificaciones de extensión, como
tasks, lo exigen para sus verbos), el tipo de solicitud declara `name_param`:

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

La sesión replica `params["jobId"]` en `Mcp-Name` en cada ruta de envío, y un
valor ausente falla de forma visible en lugar de omitir en silencio un header obligatorio.

## Lo que una extensión no puede hacer {#what-an-extension-cannot-do}

La superficie de aportación es **cerrada** a propósito. En el servidor: ajustes, herramientas,
recursos, métodos y un interceptor de `tools/call`. En el cliente: ajustes, claims de
resultado y bindings de notificación. Una extensión no puede:

* **Meterse en el host.** Declara datos; no guarda ninguna referencia al servidor ni al cliente.
* **Reemplazar el comportamiento principal.** Los métodos de la especificación y las etiquetas de
  resultado principales se rechazan al construir (el runner reserva `initialize` directamente); un
  binding de notificación eclipsado por el vocabulario principal se silencia con un aviso en su lugar.
* **Registrarse tarde.** Una vez que `MCPServer(...)` o `Client(...)` devuelven, el conjunto
  de extensiones es el que es.

Si estás peleando contra estos muros, no estás escribiendo una extensión. Estás escribiendo
un fork. Los muros son la funcionalidad: quien lee `extensions=[Apps(), Stamps()]`
sabe *todo* lo que esas dos pueden haber tocado.
