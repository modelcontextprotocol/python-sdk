---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# Solicitudes de varias idas y vueltas {#multi-round-trip-requests}

A veces una herramienta no puede terminar en una sola ida y vuelta. Necesita algo que solo tiene el usuario: una elección, una confirmación, una credencial.

Antes de 2026-07-28 el servidor lo conseguía con una llamada **de vuelta**: abría su propia solicitud al cliente (una elicitación (elicitation), una llamada de muestreo (sampling)) mientras atendía la original. La especificación 2026-07-28 retira ese canal de retorno (back-channel).

En su lugar, el servidor **devuelve** un resultado.

## Devuelve, no llames de vuelta {#return-dont-call-back}

El servidor responde a `tools/call` con un **`InputRequiredResult`** en lugar de un `CallToolResult`. Dos de sus campos hacen el trabajo:

* **`input_requests`**: lo que el servidor aún necesita, como un dict cuyas claves son nombres que eligió el servidor. Cada valor es un `ElicitRequest`, un `CreateMessageRequest` o un `ListRootsRequest`.
* **`request_state`**: un token opaco. El cliente lo devuelve tal cual en el reintento. Tu servidor es lo único que lo lee.

El cliente satisface cada solicitud y luego llama a la **misma herramienta otra vez**, con sus respuestas en `input_responses` y el token en `request_state`. El servidor ya tiene lo que le faltaba y devuelve un `CallToolResult` normal.

Ese es todo el protocolo. Cada tramo es una solicitud ordinaria del cliente al servidor. Nunca fluye nada en sentido contrario.

## El lado del servidor {#the-server-side}

En `@mcp.tool()` rara vez construyes esto a mano: declara una dependencia que pregunta al usuario (`Elicit`), muestrea el LLM del cliente (`Sample`) o lista sus roots (directorios raíz) (`ListRoots`), y el SDK devuelve el `InputRequiredResult` por ti; esa forma es la página **[Dependencias](dependencies.md)**. Las dos formas no se mezclan: una llamada tiene un solo canal `input_responses`/`request_state`, así que una herramienta que usa parámetros `Resolve(...)` no puede además devolver `InputRequiredResult` desde su cuerpo. Un retorno `InputRequiredResult` declarado se rechaza al registrar (`InvalidSignature`), y uno no declarado hace fallar la llamada en tiempo de ejecución. La forma manual es el `Server` de **bajo nivel**, cuyo handler `on_call_tool` puede devolver cualquiera de los dos tipos de resultado:

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` tiene el tipo `-> CallToolResult | InputRequiredResult`. Devolver el segundo es toda la API del lado del servidor.
* En la primera llamada `params.input_responses` es `None`, así que la guarda se activa y el handler pregunta en lugar de responder.
* En el reintento, el `ElicitResult` que envió el cliente está bajo la **misma clave** (`"region"`) que el servidor usó en `input_requests`.

Todo lo demás en ese archivo (el `input_schema` explícito, el `CallToolResult` construido a mano) es el `Server` de bajo nivel ordinario, que se explica en **[El Server de bajo nivel](../advanced/low-level-server.md)**. Esta página solo añade el segundo tipo de retorno.

## Más allá de las herramientas {#beyond-tools}

`tools/call` no es especial: en 2026-07-28 un servidor puede responder a `prompts/get` y `resources/read` de la misma manera. En `MCPServer`, una función `@mcp.prompt()` (o una función de **plantilla** `@mcp.resource()`) devuelve ella misma el `InputRequiredResult` y lee las respuestas del reintento desde el contexto:

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* La primera ronda devuelve el `InputRequiredResult`. En el reintento, `ctx.input_responses` contiene las respuestas bajo las mismas claves y la función devuelve su resultado ordinario: mensajes de prompt aquí, contenido de recurso para un recurso de plantilla.
* Un `request_state` que fijes se sella antes de transmitirse y se verifica cuando vuelve, como todo lo demás en el servidor; **[Proteger `requestState`](#protecting-requeststate)** más abajo explica qué te da el sello y cuándo necesitas configurar claves.
* Una función `@mcp.tool()` puede devolver el resultado directamente de la misma manera, cuando la forma con dependencias no encaja.
* Las funciones `@mcp.resource()` estáticas no participan: no reciben `Context`, así que nunca podrían leer el reintento. Solo los recursos de plantilla pueden preguntar.
* Las reglas sobre la generación del protocolo de más abajo se aplican sin cambios: devolver un `InputRequiredResult` en una sesión anterior a 2026 es el mismo `-32603` que describe la advertencia.

## El lado del cliente {#the-client-side}

`Client` ejecuta el bucle por ti.

Registra los callbacks que el servidor podría pedir (`elicitation_callback`, `sampling_callback`, `list_roots_callback`) y llama a la herramienta. Cuando llega un `InputRequiredResult`, `Client` despacha cada entrada de `input_requests` al callback correspondiente, reintenta con las respuestas y el `request_state` devuelto, y sigue hasta que vuelve un `CallToolResult`:

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* Ese `elicitation_callback` es el mismo al que habría llegado el `elicitation/create` por canal de retorno de un servidor anterior a 2026. Lo mismo vale para `sampling_callback` con `sampling/createMessage` y `list_roots_callback` con `roots/list`: en 2026-07-28 las RPC independientes de servidor a cliente desaparecen, pero los mismos payloads `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` viajan dentro de `input_requests` y se despachan a los mismos tres callbacks. Un solo conjunto de callbacks sirve a ambas generaciones.
* `call_tool` devuelve un `CallToolResult` sin más. Las rondas intermedias son invisibles para quien llama.
* `get_prompt` y `read_resource` ejecutan el mismo bucle.

!!! check
    Si omites el callback, el bucle falla en la primera ronda: el callback sustituto del SDK
    responde a toda elicitación con un error, y `call_tool` lanza `MCPError` con el mensaje
    *"Elicitation not supported"*.

El bucle está acotado. `Client(..., input_required_max_rounds=10)` es el tope por defecto; un servidor que sigue devolviendo `InputRequiredResult` más allá de él hace que `call_tool` lance una excepción. Si una ronda trae solo `request_state` y ningún `input_requests`, `Client` duerme brevemente (50 ms que se duplican hasta un techo de 250 ms) antes de reintentar, así que a un servidor que solo está diciendo *"todavía no he terminado"* no se le sondea sin parar.

### Controlar el bucle tú mismo {#driving-the-loop-yourself}

El bucle automático basta para un cliente de un solo proceso. Hazte cargo del bucle, en cambio, cuando:

* Tu cliente es **distribuido**: el proceso que muestra la pregunta al usuario no es el proceso que llamó a `call_tool`, así que un worker distinto emite el reintento. `request_state` es el token persistible que llevas a través de esa frontera, mediante tu propio almacenamiento, e `input_responses` es lo que el otro lado envía de vuelta con él.
* Quieres **inspeccionar** cada ronda: registrar o auditar cada entrada de `input_requests`, rechazar ciertos tipos de solicitud o aplicar tu propio backoff entre tramos.
* Quieres un límite de **tiempo real** en lugar de un límite por número de rondas: envuelve tu propio bucle en `anyio.fail_after(...)` en lugar de depender de `input_required_max_rounds`.

Baja a la sesión subyacente, donde `allow_input_required=True` te entrega la unión directamente:

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` amplía el tipo de retorno a `CallToolResult | InputRequiredResult`. El `isinstance` es lo que lo vuelve a estrechar.
* `request_state` está ahora en tus manos. Guárdalo entre tramos y la conversación puede reanudarse desde un proceso nuevo.
* Por cada entrada de `input_requests` pones un `InputResponse` bajo la **misma clave** en `input_responses`. `fulfil` es donde va tu UI; esta fija la respuesta en el código.
* Mismo nombre de herramienta, mismos `arguments`, en cada tramo. El reintento es la llamada original realizada de nuevo, no un método nuevo.

## Proteger `requestState` {#protecting-requeststate}

Todo lo anterior trata `request_state` como un eco, y en lo que se transmite no es más que eso. Pero el cliente lo conserva entre tramos (guardarlo entre procesos es justo lo que aprobó la sección anterior), así que lo que vuelve es **entrada proporcionada por el cliente**: puede estar modificada, caducada o tomada de otra llamada completamente distinta. La especificación exige que los servidores protejan la integridad de este estado y rechacen la ronda cuando la verificación falla, siempre que el estado pueda influir en la autorización, el acceso a recursos o la lógica de negocio.

`MCPServer` lo protege por defecto. Todo servidor sella el `requestState` saliente y verifica cada eco (tanto el estado de los resolutores como el construido a mano) con una clave generada al arrancar el proceso. No configuras nada, escribes texto plano y lees texto plano; lo único que se transmite es un token cifrado opaco.

La clave por defecto vive y muere con el proceso, que es lo único que debes saber antes de desplegar más allá de un solo proceso:

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **El valor por defecto (sin configuración)** sirve para un solo proceso: stdio, o exactamente un worker HTTP. Un reintento que cae en otro worker, en otra instancia detrás de un balanceador de carga o en el mismo servidor tras un reinicio está sellado con una clave que ese proceso no tiene: el cliente recibe el rechazo fijo de más abajo y debe empezar el flujo de nuevo.
* **`keys=[...]`** es obligatorio siempre que un reintento pueda llegar a una **instancia distinta** (`uvicorn` con varios workers, HTTP con balanceo de carga) o deba sobrevivir a reinicios: cada instancia verifica lo que emitió cualquier instancia hermana. La misma maquinaria, tu secreto en lugar de uno generado.
* Para tu propia criptografía, como un KMS o un servicio de tokens existente, pasa `RequestStateSecurity(codec=...)` en lugar de `keys`; **[Trae tu propia criptografía](#bring-your-own-crypto)** más abajo explica el contrato.

### Qué lleva el sello {#what-the-seal-carries}

Por defecto o configurado, el `requestState` que se transmite es un token cifrado y autenticado. Tu código nunca lo ve: los handlers y los resolutores escriben texto plano y leen texto plano (`ctx.request_state`); el SDK sella a la salida y verifica a la entrada. Más allá de la integridad, cada token está vinculado a:

* **Una ventana de tiempo.** Cada ronda vuelve a sellar con una caducidad nueva, así que `RequestStateSecurity(ttl=...)` (600 segundos por defecto) acota el tiempo de reflexión por ronda, no el flujo completo.
* **El principal autenticado.** Cuando la solicitud trae un token de acceso OAuth que el SDK validó, el estado queda vinculado al cliente, el emisor y el sujeto del token: el estado emitido para un usuario falla con otro, incluso cuando ambos usuarios comparten un mismo cliente OAuth. Un verificador que no aporta sujeto degrada el vínculo a la sola identidad del cliente, que con ID de cliente basados en URL comparten todos los usuarios de ese software cliente. Cuando la autenticación termina fuera del SDK (un proxy delante), o el transporte no está autenticado, no hay principal al que vincular y esta comprobación queda inerte, salvo que `RequestStateSecurity(bind_principal=...)` aporte uno a partir de tu propia señal de identidad. Sean cuales sean los componentes que aporta tu verificador de tokens, debe aportarlos de forma coherente: un verificador que incluye el sujeto en algunas solicitudes y lo omite en otras cambia el principal a mitad del flujo, y las rondas en curso se rechazan.
* **La solicitud de origen.** El método, el nombre de la herramienta o del prompt (o la URI del recurso) y un resumen criptográfico de los argumentos. Un token reproducido contra otra herramienta, otros argumentos u otro método falla.
* **La pregunta exacta que se hizo.** Cada respuesta de un resolutor queda fijada a la pregunta tal como se mostró al cliente, tanto en la ronda en que llega por primera vez como cuando una respuesta registrada se reutiliza más tarde. Vuelve a desplegar con un mensaje reformulado o un esquema cambiado y el servidor vuelve a preguntar en lugar de consumir una respuesta obsoleta. La misma fijación funciona en el otro sentido: deriva los mensajes de los argumentos de la herramienta, no de datos propios de cada llamada. Un mensaje construido a partir de una marca de tiempo o de una cotización en vivo se muestra distinto en cada ronda, así que toda respuesta registrada parece obsoleta y el servidor vuelve a preguntar hasta que el límite de rondas del cliente termina la llamada.

Todo eso es trabajo del SDK, no tuyo, ni del códec si traes el tuyo.

### Rotación de claves {#rotating-keys}

`keys[0]` sella el estado nuevo; todas las claves de la lista verifican. La rotación sin tiempo de inactividad tiene tres fases, cada una desplegada por completo antes de la siguiente:

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

Nunca promuevas primero la clave emisora: emitir con una clave que alguna instancia aún no puede verificar pierde rondas en curso a mitad del despliegue.

Las claves tienen como ámbito un solo servicio. El sobre sellado lleva también el nombre del servidor como claim de audiencia, así que un token emitido por otro servicio que casualmente comparte un secreto se rechaza de todos modos. El claim es tan distintivo como lo sea el nombre, así que un servidor con una política explícita debe tener un nombre real o fijar `RequestStateSecurity(audience=...)`: uno sin nombre lanza una excepción al construirse. `audience=` también sirve para topologías deliberadas de varios servicios donde un servicio debe aceptar estado que emitió otro. (El valor por defecto sin configuración queda exento: su clave nunca sale del proceso, así que el claim de audiencia no tiene nada que añadir.)

### Trae tu propia criptografía {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` acepta cualquier cosa con `seal(bytes) -> str` y `unseal(str) -> bytes` que lance `InvalidRequestState` para cualquier token que no haya emitido. La forma clásica es el cifrado de sobre contra un KMS, donde desenvuelves una clave de datos una vez al arrancar y mantienes local la criptografía por token:

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

El TTL, el vínculo con el principal y el vínculo con la solicitud **no** son trabajo del códec: el SDK los graba en el payload antes de `seal` y los vuelve a verificar después de `unseal`, para todo códec. Las únicas obligaciones de un códec son la integridad (manipulado significa lanzar una excepción) y, a ser posible, la confidencialidad.

### Cuando falla la verificación {#when-verification-fails}

Todo fallo entrante, ya sea por manipulación, caducidad, reproducción contra otra solicitud u otro principal, o por estar sellado con una clave que este servidor no conoce, recibe la misma respuesta:

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

Un único mensaje fijo para todas las causas, de modo que lo que se transmite nunca revela qué comprobación falló; el motivo real va al log del servidor. Se comprueba todo `requestState` entrante en `tools/call`, `prompts/get` y `resources/read`, incluido uno que llegue para un handler que nunca emite estado. El rechazo más común en la práctica no es un atacante: es la clave por defecto, local al proceso, que se topa con un reintento anterior a un reinicio o procedente de otra instancia; el cliente reinicia el flujo, y `keys=[...]` es la solución cuando eso importa.

### Estado construido a mano {#hand-built-state}

Un `request_state` que fijas tú mismo (al devolver `InputRequiredResult` desde una función de herramienta, de prompt o de plantilla de recurso) lo sella y verifica la misma maquinaria que el estado de los resolutores, sin ningún cambio de código: escribe texto plano, lee texto plano, y se aplican todos los vínculos anteriores.

Lo único que el SDK no puede fijar por ti, incluso configurado, es la identidad de la pregunta: no sabe a cuál de *tus* preguntas pertenece una respuesta de tu estado. Si guardas respuestas con la pregunta como clave, incluye tu propio identificador de pregunta en el estado y compruébalo en el reintento.

El `Server` de bajo nivel es el nivel sin pilas incluidas: a diferencia de `MCPServer`, no se sella nada hasta que añades tú mismo esa frontera, y tu `request_state` se transmite exactamente como lo escribiste hasta que lo haces. La activación de una sola línea se muestra en **[El Server de bajo nivel](../advanced/low-level-server.md#the-other-handlers)**.

## Un resultado de 2026-07-28 {#a-2026-07-28-result}

`InputRequiredResult` solo existe en la versión del protocolo **2026-07-28**. El `Client(server)` en memoria la negocia por ti; a través del canal, `mode="auto"` la descubre. Tras conectar, `client.protocol_version` te dice qué obtuviste.

!!! warning
    Una sesión anterior a 2026 no tiene dónde poner un `InputRequiredResult`. Devuelve uno desde tu
    handler en una conexión `mode="legacy"` y el ejecutor no puede serializarlo a la versión negociada;
    el cliente recibe un error `-32603` *"Handler returned an invalid result"*. Un servidor que atiende
    ambas generaciones debe comprobar `ctx.protocol_version` antes de recurrir a él.

!!! info
    **La elicitación en modo URL** usa exactamente este mecanismo en una conexión 2026. La entrada en
    `input_requests` es un `ElicitRequest` cuyos params son `ElicitRequestURLParams`; el usuario
    termina el flujo fuera de banda y tu cliente reintenta la llamada. El mismo bucle, ninguna API
    nueva. La mitad del servidor de alto nivel está en **[Elicitación](elicitation.md)**.

## Resumen {#recap}

* En 2026-07-28 un servidor que necesita datos a mitad de una llamada **devuelve** un `InputRequiredResult`. Nunca abre una solicitud al cliente.
* `input_requests` es lo que necesita. `request_state` es un token opaco de reanudación que solo lee el servidor.
* `Client` ejecuta el bucle de reintentos por ti: registra `elicitation_callback` / `sampling_callback` / `list_roots_callback` y `call_tool` devuelve un `CallToolResult` sin más. `input_required_max_rounds` (10 por defecto) lo acota.
* Para inspeccionar o persistir rondas, usa `client.session.call_tool(..., allow_input_required=True)` y hazte cargo tú mismo del bucle `while isinstance(result, InputRequiredResult)`.
* En `@mcp.tool()`, una dependencia que pregunta al usuario produce este resultado por ti (**[Dependencias](dependencies.md)**); el `Server` de **bajo nivel** es la forma manual.
* Los prompts y los recursos también participan: una función `@mcp.prompt()` o `@mcp.resource()` de plantilla devuelve ella misma el `InputRequiredResult` y lee `ctx.input_responses` en el reintento.
* `requestState` vuelve como entrada proporcionada por el cliente, así que `MCPServer` lo sella por defecto (tanto el estado de los resolutores como el construido a mano) con una clave local al proceso; los despliegues de varias instancias pasan `RequestStateSecurity(keys=[...])` (o un códec propio) para que cada instancia pueda verificar lo que emitió una instancia hermana. El sello vincula cada token a una ventana de tiempo, a la solicitud de origen y al principal autenticado cuando la solicitud trae autenticación que el SDK validó o `bind_principal=` aporta tu propia señal de identidad (**[Proteger `requestState`](#protecting-requeststate)**).

Este es el mecanismo que sustituye al muestreo iniciado por el servidor y al resto del canal de retorno de tipo push; consulta **[Funcionalidades obsoletas](../deprecated.md)**.
