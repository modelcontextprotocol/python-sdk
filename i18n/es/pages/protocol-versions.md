---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# Versiones del protocolo {#protocol-versions}

MCP tiene dos generaciones.

Los servidores publicados antes de 2026-07-28 abren cada conexión con el **handshake `initialize`**: el cliente propone una versión, el servidor responde con la suya, el cliente confirma, todo antes de la primera solicitud útil. Los servidores en **2026-07-28** eliminan el handshake. El cliente envía un único sondeo **`server/discover`** y el servidor le responde con todo en un solo resultado.

Casi nunca tienes que preocuparte por esto, porque `Client` negocia por ti. Esta página trata del único argumento del constructor que lo controla, `mode=`, y de las tres ocasiones en que lo cambias.

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

No pasaste `mode`, así que obtuviste el valor por defecto: `"auto"`. Al entrar en `async with` se envía un único sondeo `server/discover` con la versión más reciente que habla este SDK. Después:

* Un **servidor moderno** lo responde. El cliente adopta el resultado. Una ida y vuelta, y listo.
* Un **servidor más antiguo** nunca ha oído hablar de `server/discover` y devuelve un error. El cliente recurre al handshake clásico `initialize` y se queda con lo que este negocie.

En cualquier caso terminas conectado, y `client.protocol_version` te dice cuál fue:

```text
2026-07-28
```

Esa es toda la funcionalidad. Un solo `Client`, servidores de cualquier generación, sin ramificaciones en tu código.

!!! info
    `MCPServer` responde a `server/discover` en todos los transportes (en memoria, stdio, Streamable
    HTTP), así que contra tu propio servidor `auto` siempre llega a `2026-07-28`. El mecanismo de
    respaldo solo se activa contra un servidor real anterior a 2026, que es exactamente cuando quieres que lo haga.

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` nunca sondea. Ejecuta el handshake `initialize`, la misma conexión que abre un cliente anterior a 2026.

```text
2025-11-25
```

El mismo servidor. Habla `2026-07-28` sin ningún problema; le dijiste al cliente que no preguntara.

Esto lo quieres para las funcionalidades de tipo **push**.

Una solicitud iniciada por el servidor es el servidor llamándote *a ti*: `ctx.elicit(...)` poniendo un formulario delante de tu usuario, el muestreo (sampling) pidiéndole a tu modelo una respuesta en mitad de una llamada a una herramienta. Ese canal solo existe en una sesión de la generación del handshake.

En 2026-07-28 ya no existe. El servidor *devuelve* sus preguntas y tú repites la llamada con las respuestas (**[Solicitudes de varias idas y vueltas (multi-round-trip)](handlers/multi-round-trip.md)**).

`mode="auto"` solo te da un handshake cuando el servidor es demasiado antiguo para cualquier otra cosa. `mode="legacy"` lo garantiza. Úsalo siempre que le pases a `Client(...)` un `sampling_callback`, un `elicitation_callback` que quieras que se ejecute como solicitud, o un `message_handler`. **[Callbacks del cliente](client/callbacks.md)** los repasa uno por uno.

## Fijar una versión {#pinning-a-version}

`mode` también acepta una cadena con una versión moderna del protocolo. Hoy ese conjunto es exactamente `["2026-07-28"]`.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

Una versión fijada no envía **nada**. Ni sondeo ni handshake. El cliente adopta `2026-07-28` localmente y la conexión está activa en el instante en que `async with` devuelve el control.

Fijar una versión es una promesa que haces *tú*: ya sabes que el servidor habla esa versión. El cliente no lo comprueba.

!!! check
    Fijar una versión no es un descubrimiento. Imprime `client.server_info` y el precio salta a la vista:

    ```text
    None
    ```

    El cliente nunca le preguntó al servidor quién es, así que `server_info` es `None`. Con `client.server_capabilities`
    pasa lo mismo: todas las capacidades son `None`. Las llamadas a herramientas siguen funcionando (el protocolo no necesita nada de eso);
    el código que lee `server_capabilities` para decidir qué ofrecer, no.

    La siguiente sección es la solución.

Solo se pueden fijar versiones modernas. Una cadena de la generación del handshake se rechaza al construir el cliente, antes de cualquier E/S, y el error te dice qué escribir en su lugar:

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## Reconectar con `prior_discover` {#reconnecting-with-prior_discover}

El sondeo es barato, pero sigue siendo una ida y vuelta que pagas en cada reconexión, y la respuesta casi nunca cambia.

Así que guárdala. Tras una conexión `auto`, `client.session.discover_result` contiene el `DiscoverResult` exacto que envió el servidor: sus `supported_versions`, sus `capabilities`, sus `instructions` y la identidad que el servidor grabó en el `_meta` del resultado. Devuélveselo como `prior_discover=` la próxima vez:

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

La segunda conexión hizo **cero** idas y vueltas de negociación y aun así sabe exactamente con quién está hablando. Ese es el modo fijado bien hecho: `mode=` nombra la versión, `prior_discover=` aporta la identidad. ✨

`DiscoverResult` es un modelo de Pydantic. `saved.model_dump_json()` va a un archivo o a una caché; `DiscoverResult.model_validate_json(...)` lo recupera en el siguiente proceso.

!!! tip
    `prior_discover=` solo tiene efecto cuando `mode` es una versión fijada. Con `"auto"` el cliente
    sondea el servidor de todos modos, y con `"legacy"` se ignora.

## Los cuatro modos {#the-four-modes}

| Escribes | Tráfico de negociación | Obtienes |
| --- | --- | --- |
| `Client(target)` | un sondeo `server/discover`; el handshake `initialize` si falla | la versión más reciente que hablan ambos lados, sea cual sea la generación |
| `Client(target, mode="legacy")` | el handshake `initialize` | una versión de la generación del handshake; las solicitudes iniciadas por el servidor funcionan |
| `Client(target, mode="2026-07-28")` | ninguno | esa versión, fijada, con `server_info` como `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | ninguno | esa versión, fijada, *y* la identidad que guardaste la última vez |

## Resumen {#recap}

* MCP tiene una generación del handshake (hasta `2025-11-25`, el handshake `initialize`) y una generación moderna (`2026-07-28`, `server/discover`). `Client` hace de puente entre ambas.
* `mode="auto"` es el valor por defecto: sondea y, si falla, recurre al handshake. Déjalo como está a menos que una de las otras tres filas te describa.
* `client.protocol_version` es siempre la respuesta a "¿qué obtuve?".
* `mode="legacy"` fuerza el handshake. Es lo que necesitas para las solicitudes iniciadas por el servidor: muestreo, elicitación (elicitation) de tipo push, `message_handler`.
* Fijar una versión (`mode="2026-07-28"`) no envía ningún tráfico de negociación, a costa de que `client.server_info` sea `None`.
* `prior_discover=` compensa ese precio: guarda `client.session.discover_result`, reconecta con él y obtén ambas cosas.

Una conexión moderna no tiene canal push, así que ¿cómo te hace una pregunta un servidor de 2026 en mitad de una llamada? La devuelve: **[Solicitudes de varias idas y vueltas](handlers/multi-round-trip.md)**.
