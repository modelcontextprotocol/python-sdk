---
translation:
  sections: [3d1663c18edc824c, d4fd37009a13f03d, af9f398a5a8b679a, 470c2dd144294d69, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# Atender clientes heredados {#serving-legacy-clients}

MCP tiene dos generaciones de protocolo: la generación del handshake `initialize`, hasta la versión de la especificación `2025-11-25`, y la generación moderna, `2026-07-28`. **[Versiones del protocolo](../protocol-versions.md)** es la página dedicada a esa división.

Esta página trata del lado del servidor de esa división, y la respuesta cabe en una frase: **el `streamable_http_app()` que ya despliegas atiende a ambas.**

El SDK enruta cada solicitud según su encabezado `MCP-Protocol-Version`. Una solicitud que indica `2026-07-28` va al handler moderno. Una solicitud que indica una versión de la generación del handshake, o que no trae ningún encabezado (que es como llega el `initialize` de un cliente anterior a 2026), va al transporte que esos clientes esperan: handshake `initialize`, sesiones y todo lo demás. Ocurre por solicitud, antes de tu código, en una sola app.

Así que un cliente heredado (legacy) no es algo *para* lo que construyes. Es algo que se conecta *al* servidor que ya escribiste. No configuras nada.

!!! note
    Nada, literalmente. No hay una opción `legacy=`, ni una lista de versiones permitidas, ni forma
    de rechazar o desactivar una generación: ni en `streamable_http_app()`, ni en `run()`, ni en el
    gestor de sesiones. Ambas generaciones están siempre activas. Lo más parecido a un interruptor
    por generación en esa firma es `stateless_http`, y ocupa la mayor parte de esta página.

## Un handler, ambas generaciones {#one-handler-both-eras}

Aquí tienes una herramienta que necesita preguntarle algo al usuario, y clientes de ambas generaciones que la llaman:

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` necesita una cosa que el modelo no proporcionó: cuántos ejemplares. `Annotated[..., Resolve(ask_quantity)]` es la forma en que una herramienta lo declara (**[Dependencias](../handlers/dependencies.md)** tiene todos los detalles). Nada en `reserve` nombra una versión, comprueba una capacidad ni se bifurca.

Los dos clientes están abiertos **al mismo tiempo**, sobre el mismo objeto `mcp`. `mode="legacy"` ejecuta el handshake `initialize`: exactamente la conexión que abre un cliente anterior a 2026. El otro toma el valor por defecto y queda en `2026-07-28`.

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

Mismo servidor, mismo handler, misma respuesta. Esa es toda la funcionalidad.

Vale la pena detenerse en el *cómo*, porque a los dos clientes se les hizo la misma pregunta por dos canales completamente distintos. La conexión `2026-07-28` no tiene un canal por el que el servidor pueda enviar una solicitud, así que `Resolve` devolvió la pregunta dentro del resultado de la herramienta y el cliente reintentó la llamada con la respuesta (**[Solicitudes de varias idas y vueltas](../handlers/multi-round-trip.md)**). La conexión `2025-11-25` no tiene nada de eso; ahí, `Resolve` envió una solicitud `elicitation/create` en vivo a mitad de la llamada y esperó. No escribiste ninguna de las dos cosas. `Resolve` lee la versión negociada de la conexión y elige; el cuerpo de tu herramienta ve un `AcceptedElicitation` en ambos casos.

!!! tip
    Esa portabilidad entre generaciones es la *razón* por la que `Resolve` es la API sobre la que
    conviene construir. Su hermano mayor, `ctx.elicit()` (**[Elicitación](../handlers/elicitation.md)**),
    solo envía `elicitation/create`, así que solo funciona en una conexión heredada. En una
    `2026-07-28` la llamada falla. Si una herramienta todavía lo usa, la solución es la que ves
    arriba, no una comprobación de versión.

## Lo que te cuesta una sesión heredada {#what-a-legacy-session-costs-you}

El enrutamiento es gratis. La sesión no.

Una conexión `2026-07-28` **no tiene sesión**: cada solicitud es independiente, y el handler moderno nunca emite un `Mcp-Session-Id`. Una conexión heredada es lo contrario. En el momento en que un cliente anterior a 2026 envía `initialize`, el SDK genera un `Mcp-Session-Id`, lo devuelve en un encabezado de respuesta y mantiene detrás de él un registro vivo que las solicitudes posteriores del cliente deben encontrar: la versión negociada, los streams abiertos, una tarea en segundo plano que mueve la sesión.

Ese registro es **un simple `dict` dentro del proceso**. No hay un almacén de sesiones distribuido ni forma de conectar uno.

Con un solo worker eso no se nota. Con dos, es todo el problema: una solicitud que trae un `Mcp-Session-Id` y cae en un worker que no lo generó no encuentra nada en ese dict, y la respuesta es un `404` (`Session not found`), no el resultado de la herramienta. Así que en cuanto ejecutas más de un worker, **los clientes heredados necesitan enrutamiento sticky (afinidad de sesión)**: cada solicitud de una sesión tiene que llegar al proceso que la inició. Los clientes modernos nunca lo necesitan; no tienen una sesión a la que mantenerse pegados. **[Desplegar y escalar](deploy.md)** cubre la afinidad y todo lo demás sobre ejecutar más de uno de estos.

!!! warning
    `event_store=` parece la solución y no lo es. Es **reanudabilidad** (reenviar los eventos SSE
    perdidos a un cliente que se reconecta a la *misma* sesión), no un almacén de sesiones. Nunca
    hace que una sesión sea alcanzable desde otro proceso.

## El único ajuste: `stateless_http` {#the-one-knob-stateless_http}

Si la afinidad es un costo que te niegas a pagar, hay exactamente una cosa que puedes cambiar.

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

Es el servidor del principio de la página más un argumento nombrado. `stateless_http=True` hace que el tramo heredado construya en su lugar una sesión desechable, por solicitud: no se emite ningún `Mcp-Session-Id`, no se recuerda nada entre solicitudes, así que cualquier worker puede atender cualquier solicitud y el balanceador de carga puede hacer lo que quiera.

Dos cosas sobre él importan más que lo que hace.

**Solo afecta al tramo heredado.** Las solicitudes se enrutan según el encabezado de versión *antes* de que se lea `stateless_http`, así que la ruta moderna nunca lo ve. Una conexión `2026-07-28` ya no tiene sesión y es exactamente igual con cualquiera de los dos valores.

**Cuesta los dos canales de servidor a cliente en ese tramo.** Una sesión que vive lo que dura un `POST` no tiene un stream por el que el servidor pueda enviar una solicitud ni un stream independiente por el que enviar notificaciones. Cada solicitud iniciada por el servidor lanza `NoBackChannelError`: `ctx.elicit()`, las llamadas retiradas de muestreo (sampling) y roots (**[Funcionalidades obsoletas](../deprecated.md)**) y, sí, `Resolve` cuando le hace su pregunta a un cliente *heredado*. Las notificaciones ni siquiera reciben un error; se descartan en silencio.

!!! note
    `json_response=True` no es ese ajuste, pero asume la mitad del mismo costo en *cada* sesión
    heredada: un `POST` respondido con un único cuerpo JSON no tiene stream para el canal ligado a
    la solicitud, así que un `ctx.elicit()` a mitad de solicitud lanza el mismo `NoBackChannelError`
    y las notificaciones ligadas a la solicitud se descartan. El stream independiente de la sesión no
    se toca: las notificaciones no relacionadas siguen llegando.

!!! check
    Haz lo incorrecto. `reserve` es exactamente la herramienta que acaba de atender a ambos clientes.
    Despliégala con `stateless_http=True`, conecta los mismos dos clientes por HTTP y llámala desde
    cada uno.

    El cliente moderno sigue recibiendo `Reserved 2 of 'Dune'.` El tramo moderno no cambió.

    La llamada del cliente heredado no vuelve como un resultado `is_error` que el modelo pueda leer.
    La solicitud entera falla, como un error de protocolo de nivel superior:

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` no te salvó. En una conexión `2025-11-25` *tiene* que enviar `elicitation/create`,
    y el canal que necesita es justo lo que `stateless_http=True` entregó. El código portable entre
    generaciones no es código libre de canal de retorno (back-channel).

Así que es una concesión real, y solo existe en el tramo heredado: **con sesión y afinidad, o sin estado y en una sola dirección.** Si tus herramientas nunca llaman de vuelta al cliente, `stateless_http=True` es gratis y deberías usarlo. Si lo hacen, conserva las sesiones y mantén el enrutamiento con afinidad.

## Dónde se bifurca realmente tu código {#where-your-code-actually-forks}

Casi en ningún sitio.

Herramientas, recursos, prompts, salida estructurada, progreso, errores: a ninguno le importa qué generación hizo la llamada. El handshake `initialize`, el `Mcp-Session-Id`, el stream independiente, el `DELETE` que termina una sesión: el SDK se encarga de todo, y un handler nunca ve nada de eso. La entrada interactiva es *el* lugar donde las generaciones difieren de verdad en lo que se transmite, y `Resolve` existe para que no sea tu problema: acabas de ver a una sola herramienta atender a ambas.

Queda exactamente una cosa, y son las **notificaciones de cambio**, porque las dos generaciones escuchan por conductos distintos:

* Un cliente `2026-07-28` abre un stream `subscriptions/listen` y lee el bus de suscripciones. `ctx.notify_resource_updated()` (y `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`) publican ahí, y *solo* ahí. **[Suscripciones](../handlers/subscriptions.md)** es esa página.
* Un cliente heredado lee el stream independiente que su sesión mantiene abierto. `ctx.session.send_resource_updated()` (y `send_tool_list_changed()` y compañía) escriben en la *conexión* que trajo la solicitud: para una sesión heredada, ese es su stream independiente. Una conexión moderna no tiene dónde ponerlo: por HTTP no existe ese canal, y por stdio los cuatro tipos de notificación de cambio viajan solo por streams `subscriptions/listen`, así que en una conexión moderna la notificación se descarta en silencio.

Por HTTP, ninguna de las dos llamadas alcanza a los clientes de la otra generación. Para avisar a todos, llama a ambas:

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

Dos líneas, sin `if`, sin comprobación de versión, y listo. Esa es la lista completa de cosas que un handler hace distinto porque existe un cliente heredado.

## Resumen {#recap}

* Un solo `streamable_http_app()` atiende a ambas generaciones del protocolo. El SDK enruta cada solicitud según su encabezado `MCP-Protocol-Version`; no hay nada que configurar ni ningún ajuste de generación que buscar.
* Un cliente heredado te cuesta una sesión: un registro `Mcp-Session-Id` dentro del proceso sin ningún almacén distribuido detrás. Más de un worker significa **enrutamiento sticky**, o el worker equivocado responde `404 Session not found`. **[Desplegar y escalar](deploy.md)** tiene todos los detalles sobre varios workers.
* `stateless_http=True` es el único ajuste, y es **solo para el tramo heredado**. Compra balanceo de carga gratis para los clientes heredados al precio de los dos canales de servidor a cliente en ese tramo: las solicitudes iniciadas por el servidor lanzan `NoBackChannelError` (un error de nivel superior en el cliente, no un resultado `is_error`), y las notificaciones se descartan.
* Una conexión `2026-07-28` no tiene sesión en ningún caso. `stateless_http` nunca la toca.
* El código de tu handler se bifurca por generación en exactamente un lugar: las notificaciones de cambio. `ctx.notify_*` llega a los clientes de `subscriptions/listen`; `ctx.session.send_*` llega a las sesiones heredadas. Llama a ambas.
* Todo lo demás (incluido pedirle datos al usuario, mediante `Resolve`) es portable entre generaciones por construcción. Escribe la versión moderna una sola vez.
