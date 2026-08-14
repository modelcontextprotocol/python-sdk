---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# Desplegar y escalar {#deploy-scale}

El servidor funciona. Ahora necesita un nombre de host real y más de un worker detrás.

Casi nada de eso es asunto de MCP. Tú pones el servidor ASGI, el gestor de procesos y el balanceador de carga. Lo que tiene esta página es la lista corta de cosas que *sí* son asunto de MCP: un ajuste que condiciona cualquier despliegue y los dos puntos donde "más de un worker" cambia lo que hace el SDK.

## Antes que nada: la lista de hosts permitidos {#before-anything-else-the-host-allowlist}

`streamable_http_app()` no puede saber detrás de qué nombre de host se va a servir, así que supone la respuesta más segura: localhost. Sin `transport_security=`, la app activa la **protección contra DNS rebinding** y acepta una solicitud solo si su encabezado `Host` es `127.0.0.1:<port>`, `localhost:<port>` o `[::1]:<port>`. El encabezado `Origin`, cuando lo hay, tiene que ser la forma `http://` del mismo. En tu máquina eso es exactamente lo correcto: impide que una página web maliciosa maneje tu servidor local a través de un nombre DNS que volvió a apuntar a `127.0.0.1`.

Desplegada detrás de un nombre de host real, esa misma configuración por defecto rechaza **todas las solicitudes** hasta que indiques lo contrario. La comprobación se ejecuta antes que cualquier cosa con forma de MCP, así que nada de lo que construiste llega siquiera a consultarse:

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

`transport_security=` es la solución. Permite lo que realmente sirves:

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* Las entradas de `allowed_hosts` son cadenas exactas: `"mcp.example.com"` coincide con un encabezado `Host` sin puerto y `"mcp.example.com:*"` coincide con cualquier puerto. Incluye ambas.
* `allowed_origins` solo importa para los navegadores, porque nada más envía `Origin`. Es el gemelo del lado del servidor de la configuración CORS de **[Añadir a una app existente](asgi.md)**.
* Detrás de un proxy inverso que ya controla el encabezado `Host`, desactivar la comprobación es la configuración honesta: `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.
* Pasar un `host=` que no sea localhost (por ejemplo `host="mcp.example.com"`) **no** añade ese nombre de host a la lista permitida. Solo evita que el valor por defecto de localhost arme la protección, lo que deja cualquier Host y Origin aceptados. Di lo que quieres decir con `transport_security=`.

!!! check
    Borra el argumento `transport_security=security` y despliega la app de todos modos. Arranca, `/mcp`
    enruta, y cada solicitud (incluso desde un simple `curl`) vuelve así:

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    No encontrarás esas palabras del lado del cliente. Un `421` es una respuesta HTTP en texto plano, no un
    error JSON-RPC, así que el cliente MCP lanza un error de transporte genérico; el nombre de host que
    no le gustó aparece solo en el log del **servidor**, como una única advertencia. Un servidor recién
    desplegado que rechaza todas las conexiones es una lista de hosts permitidos hasta que se demuestre lo contrario.
    **[Solución de problemas](../troubleshooting.md)** también empieza por aquí.

## Workers, y quién tiene que ser sticky {#workers-and-who-has-to-be-sticky}

Una vez que el nombre de host responde, pon más de un worker detrás. No hay ningún ajuste del SDK para eso; una app Starlette se escala como cualquier app ASGI, entregando el objeto a algo que sepa hacer fork:

```console
uvicorn server:app --workers 4
```

Cuatro procesos, un socket. Y ahora la pregunta que todo despliegue tiene que responder: **¿una solicitud tiene que llegar al worker que vio la anterior?**

Para un cliente que habla el protocolo **2026-07-28**, no. Una solicitud moderna es un único POST autocontenido: sin handshake `initialize` antes, sin `Mcp-Session-Id` en la respuesta, nada *a lo que* una segunda solicitud pueda volver. Enrútala a cualquier worker.

Eso no es un modo que activas. `stateless_http=True` parece que debería serlo, pero el transporte enruta según el encabezado de solicitud `MCP-Protocol-Version`, entrega una solicitud moderna al handler moderno y **devuelve**. La línea que lee `stateless_http` viene *después* de ese retorno. No es que el flag se ignore en la ruta 2026-07-28; es que nunca se alcanza. `stateless_http` es un ajuste solo para el tramo **heredado**, y la ruta moderna no tiene sesión por construcción.

Para un cliente heredado en la versión de especificación 2025-11-25 o anterior, la respuesta depende de ese flag:

| Versión de protocolo del cliente | Sesión | Lo que debe hacer el balanceador de carga |
| --- | --- | --- |
| **2026-07-28** | Ninguna. `Mcp-Session-Id` nunca se establece. | Nada. Cualquier worker atiende cualquier solicitud. |
| **2025-11-25 y anteriores** (por defecto) | `Mcp-Session-Id`, guardado en la memoria de un worker. | **Sesiones sticky.** Una solicitud siguiente que llega a otro worker recibe un `404` *"Session not found"*. |
| **2025-11-25 y anteriores**, con `stateless_http=True` | Ninguna. | Nada. El costo es el canal de retorno (back-channel) del servidor al cliente (muestreo (sampling), elicitación (elicitation) por push, `roots/list`) y la capacidad de reanudar. |

Las sesiones sticky y lo que cuesta el tramo heredado tienen su propia página, **[Atender clientes heredados](legacy-clients.md)**; las dos generaciones en sí están en **[Versiones del protocolo](../protocol-versions.md)**. Lo que importa aquí es la forma de la respuesta: *en 2026-07-28 ya eres stateless, sin nada que configurar.*

El resto de esta página son las dos cosas que ser stateless **no** te resuelve.

## `requestState` entre workers {#requeststate-across-workers}

Una herramienta **[de varias idas y vueltas (multi-round-trip)](../handlers/multi-round-trip.md)** necesita algo que el cliente tiene que ir a buscar (una confirmación, una elección, una credencial), así que devuelve una pregunta en lugar de una respuesta y termina en el reintento. Entre las dos rondas el cliente guarda un token opaco `request_state` que acuñó el servidor. En el reintento el servidor tiene que volver a abrir ese token.

*¿Sellado con qué clave?* Por defecto, una que el servidor generó con `os.urandom(32)` al construirse. Con `--workers 4` eso son cuatro construcciones, en cuatro procesos: cuatro claves distintas, nunca escritas en ningún lado, nunca compartidas, perdidas al reiniciar.

Aquí tienes una herramienta que pregunta antes de actuar, en un servidor que no configura nada:

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

La primera ronda llega al worker A. El worker A sella `refund:120` con **su** clave y devuelve el token. El cliente le pone la pregunta delante a una persona, recibe un sí y reintenta. El reintento es una solicitud HTTP completamente nueva.

!!! check
    Deja que ese reintento llegue al worker B. B intenta abrir un token que no acuñó, no puede, y rechaza la
    ronda entera. Nunca se llama a `refund`; el cliente recibe un error JSON-RPC:

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    Ese mensaje está **congelado**. Expirado, manipulado, reutilizado contra otros argumentos o (la causa
    más común con diferencia en un despliegue real) sellado por un worker hermano: al cliente se le dice
    lo mismo cada vez, así que lo que se transmite nunca revela qué comprobación falló. El motivo real es un
    `WARNING` en el log del servidor:

    ```text
    requestState rejected on tools/call: unknown key
    ```

    Una herramienta de varias idas y vueltas que funcionaba con un worker y empezó a fallar *a veces* con
    dos es esto. Las dos rondas siguen teniendo que llegar al mismo proceso, así que falla exactamente tan
    a menudo como tu balanceador de carga las separa.

Las dos rondas son dos solicitudes HTTP independientes, y varias cosas ordinarias las separan: un proxy que balancea por solicitud, una conexión que se cayó entre medias, un despliegue o un reinicio, un cliente que persistió `request_state` y está reanudando desde un proceso completamente distinto (**[Dirigir el bucle tú mismo](../handlers/multi-round-trip.md#driving-the-loop-yourself)**). Cualquiera de ellas es "un worker distinto".

La solución es un argumento. Tiene **dos** mitades.

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** es la mitad que todo el mundo encuentra. Dale a cada instancia el mismo secreto (al menos 32 bytes) y cada instancia puede abrir lo que acuñó cualquier hermana. `keys[0]` sella y todas las claves de la lista abren, que es el anillo de rotación; **[Rotar claves](../handlers/multi-round-trip.md#rotating-keys)** explica cómo girarlo sin tiempo de inactividad.
* **El nombre del servidor** es la mitad que casi nadie encuentra, y la razón por la que los reintentos entre instancias siguen fallando después de compartir la clave. Cada token sellado lleva el `name` del servidor como **claim de audiencia**, comprobado de forma estricta al volver a entrar. Dos instancias construidas a partir del mismo código tienen el mismo nombre y nunca lo notan. Nómbralas distinto (`MCPServer(f"billing-{POD}")` parece buena higiene de observabilidad) y cada reintento entre instancias se rechaza exactamente como arriba, con clave compartida o sin ella. El log dice `audience` en lugar de `unknown key`; el cliente no puede notar la diferencia.

Acuña el secreto una vez y entrega el mismo valor a cada instancia. Este es el comando que el propio mensaje de error del SDK te dice que ejecutes si le pasas menos de 32 bytes:

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "Las mismas claves, *y* el mismo nombre"
    Un despliegue de varias instancias debe compartir ambos. Si los nombres por instancia son imprescindibles
    para ti, dale a la flota una única audiencia explícita: `RequestStateSecurity(keys=[...], audience="billing")`.
    Cada instancia acuña y acepta entonces bajo `"billing"` sin importar cómo se llame.

Todo lo demás sobre el sello está en **[Proteger `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**: qué vincula, el `ttl` por ronda (600 segundos por defecto), traer tu propio códec, por qué el valor por defecto sin configurar es exactamente lo correcto en `stdio`. Toda la aportación de esta página es una lista de comprobación de dos puntos: *las mismas claves, el mismo nombre.*

!!! info
    Estás en esta ruta aunque nunca hayas escrito `InputRequiredResult`. Una herramienta cuyos parámetros
    usan `Resolve(...)` (**[Dependencias](../handlers/dependencies.md)**) es una herramienta de varias idas y vueltas,
    y el SDK acuña y sella su `request_state` por ella. La misma clave por defecto, el mismo fallo entre
    workers, la misma solución.

## Notificaciones de cambio entre réplicas {#change-notifications-across-replicas}

El stream `subscriptions/listen` de un cliente es una única respuesta de larga duración, así que queda fijado a una réplica durante toda su vida. Un `ctx.notify_resource_updated(...)` publicado en una réplica **distinta** tiene que llegarle.

La unión entre las dos es el `SubscriptionBus`. El bus que le des a un servidor es al que va cada publicación y el que escucha cada stream abierto, así que entrega el mismo bus a cada réplica:

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

A nada del fan-out le importa a qué objeto servidor está conectado un stream. Dos servidores que comparten un `InMemorySubscriptionBus` ya se comportan así: abre un stream de escucha en uno, ejecuta `edit_note` en el otro, y el stream se entera. Ese bus en memoria solo abarca objetos servidor dentro de un mismo proceso, lo que lo convierte en el modelo, no en el despliegue:

* Entre procesos reales, **el SDK no trae ningún bus que pueda ayudarte.** `SubscriptionBus` es un `Protocol` de dos métodos (`publish` y `subscribe`) que implementas sobre tu propio backend pub/sub (Redis, NATS, lo que ya ejecutes) y pasas como `MCPServer(subscriptions=...)`. **[Suscripciones](../handlers/subscriptions.md#scaling-past-one-process)** tiene el esbozo y el contrato.
* El bus transporta cuatro eventos tipados pequeños, nunca JSON-RPC. El acuse de recibo, el filtrado y el ciclo de vida de los streams se quedan en el SDK, así que tu bus no puede romper el protocolo; solo puede mover eventos entre procesos.
* Los streams **no** se pueden reanudar y los eventos **no** se vuelven a reproducir. Perder una réplica descarta sus streams; los clientes vuelven a escuchar y vuelven a obtener los datos. No hay almacén de eventos que compartir ni nada más que configurar. Este es el único lugar donde escalar horizontalmente es de verdad solo más de lo mismo.

## Lo que el SDK no te da {#what-the-sdk-does-not-give-you}

Un `MCPServer` es una implementación del protocolo, no un servidor de aplicaciones. Los ajustes de despliegue que vas a buscar a continuación faltan a propósito:

* **Sin `workers=`.** `mcp.run("streamable-http")` arranca exactamente un proceso uvicorn, y eso es todo lo que arrancará jamás. Multiproceso es `streamable_http_app()` entregado a lo que ya uses para desplegar ASGI: `uvicorn --workers`, gunicorn, el gestor de procesos de tu plataforma. Esta página deliberadamente no es un tutorial de ninguno de ellos; su documentación es mejor de lo que sería una copia aquí.
* **Sin ruta de health check.** `@mcp.custom_route("/health", methods=["GET"])` es toda la respuesta, y nunca se autentica aunque el resto del servidor sí. Eso es lo correcto para una sonda de vida, incorrecto para cualquier cosa privada. **[Añadir a una app existente](asgi.md#custom-routes)** muestra una.
* **Sin objeto de configuración de producción.** No hay ningún lugar en `MCPServer` donde anotar timeouts, TLS, apagado ordenado o límites de conexión, porque ninguno de esos es su trabajo. Pertenecen a tu servidor ASGI, y los configuras allí. **[Ejecutar tu servidor](index.md)** cubre el puñado de ajustes que el constructor *sí* acepta.
* **Sin `EventStore` incluido, y en 2026-07-28 sin uso para uno.** La capacidad de reanudar es una funcionalidad del tramo heredado con estado; un intercambio moderno es un POST, una respuesta y nada que reanudar.

## Resumen {#recap}

* Por defecto, la app responde solo a las solicitudes dirigidas a localhost. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` es la puerta de salida a producción: hasta que lo pases, cada solicitud detrás de un nombre de host real es un `421` y el motivo solo está en el log del servidor.
* En 2026-07-28 no hay sesión ni nada sobre lo que un balanceador de carga pueda ser sticky. `stateless_http=True` es un ajuste solo para lo heredado porque una solicitud moderna se enruta y se responde antes de que ese flag llegue a leerse.
* La clave por defecto de `requestState` es `os.urandom(32)`, acuñada por proceso. Un reintento de varias idas y vueltas que llega a otro worker falla con `-32602` *"Invalid or expired requestState"*.
* La solución es `RequestStateSecurity(keys=[...])` **y** el mismo nombre de servidor en cada instancia. El nombre es el claim de audiencia por defecto del token. Las mismas claves, el mismo nombre.
* Las notificaciones de cambio cruzan réplicas a través de un `SubscriptionBus` compartido. La única implementación del SDK es dentro del proceso; el `Protocol` de dos métodos sobre tu propio pub/sub te toca escribirlo a ti.
* No hay `workers=`, ni ruta de health check, ni objeto de configuración de producción. Trae tu propio servidor ASGI.

Lo otro que un nombre de host real necesita delante es un token: **[Autorización](authorization.md)**.
