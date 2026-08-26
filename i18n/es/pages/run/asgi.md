---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# Añadir a una app existente {#add-to-an-existing-app}

`mcp.run("streamable-http")` arranca un servidor web por ti. A veces no es lo que quieres: el servidor MCP es una pieza de una aplicación web más grande, o ya tienes un despliegue ASGI.

Para eso, `mcp.streamable_http_app()` devuelve una **aplicación Starlette**.

Una app Starlette es una app ASGI, así que cualquier cosa que aloje ASGI (uvicorn, Hypercorn, otra Starlette, FastAPI) puede alojar el servidor MCP.

## La app {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` es una aplicación ASGI corriente. Pásala a cualquier servidor ASGI:

```console
uvicorn server:app
```

El endpoint MCP está en `/mcp`, así que un cliente se conecta a `http://127.0.0.1:8000/mcp`.

La app ya trae dos cosas:

* Una ruta, `/mcp`: el endpoint Streamable HTTP.
* Un **lifespan** (ciclo de vida del servidor) que arranca `mcp.session_manager`, el objeto que se encarga del trabajo en segundo plano de cada sesión activa.

Ejecuta la app por sí sola (`uvicorn server:app`) y nunca tendrás que pensar en ninguna de las dos.

!!! tip
    `streamable_http_app()` acepta los mismos argumentos nombrados que `mcp.run("streamable-http", ...)`,
    menos `port`: el puerto es cosa de lo que sirva la app. `host` se sigue aceptando, pero aquí
    no enlaza nada; **[Desplegar y escalar](deploy.md)** explica qué controla realmente.
    **[Ejecutar el servidor](index.md)** cubre las opciones en sí.

`mcp.sse_app()` hace lo mismo para el transporte SSE, ya reemplazado.

## Solo localhost, hasta que digas lo contrario {#localhost-only-until-you-say-otherwise}

Por defecto, la app responde **solo** a las solicitudes dirigidas a localhost. `streamable_http_app()`
no puede saber detrás de qué nombre de host se va a servir, así que activa la protección contra DNS
rebinding con la lista de permitidos más segura posible; en tu máquina eso es justo lo correcto.
Desplegada detrás de un nombre de host real, significa que **toda solicitud se rechaza con
`421 Misdirected Request`** hasta que le pases a `transport_security=` una lista de permitidos con
lo que realmente sirves. Nada de lo que construiste llega siquiera a consultarse antes. Esa lista
de permitidos, y todo lo demás que hay entre una app que funciona y un nombre de host real, está en
**[Desplegar y escalar](deploy.md)**.

## Montarla {#mounting-it}

En cuanto el servidor MCP es *parte* de una aplicación más grande, metes la app dentro de un `Mount`. Y en cuanto haces eso, el lifespan pasa a ser tu problema:

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` junto con el path por defecto `/mcp` mantiene el endpoint en `/mcp`. Starlette prueba las rutas en orden y `Mount("/")` coincide con **cualquier** path, así que tus propias rutas van *antes* que él en la lista. Todo lo que quede después es inalcanzable.
* La función `lifespan` entra en `mcp.session_manager.run()` durante toda la vida de la app **anfitriona**. Esta es la línea que todo el mundo olvida.
* `mcp.session_manager` solo existe *después* de llamar a `streamable_http_app()`. Por eso las rutas se construyen en el ámbito del módulo y el gestor solo se toca dentro del lifespan.

La ruta `Host` de Starlette funciona igual: cambia `Mount("/", ...)` por `Host("mcp.example.com", ...)` para enrutar por nombre de host en lugar de por path. La regla del lifespan no cambia, y la de la seguridad del transporte tampoco. Una ruta `Host("mcp.example.com", ...)` solo recibe solicitudes dirigidas a ese nombre de host, pero la lista de permitidos de Host del propio transporte (**[Desplegar y escalar](deploy.md)**) sigue ejecutándose primero. Sin `"mcp.example.com"` en ella, esa ruta responde a todas con un `421`.

!!! warning "La app anfitriona es dueña del lifespan"
    `streamable_http_app()` conecta `session_manager.run()` al lifespan de la Starlette que
    devuelve, pero **el lifespan de una subaplicación montada nunca se ejecuta**. Monta la app y
    ese lifespan integrado es código muerto. La app que esté en la cima de tu pila ASGI, sea cual
    sea, debe entrar en `mcp.session_manager.run()` en su propio lifespan.

!!! check
    Borra la línea `lifespan=lifespan` y arranca el servidor. Arranca. La ruta se resuelve.
    Luego la primera solicitud a `/mcp` falla con:

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    Nada arranca el gestor de sesiones salvo su `run()`.

## Dos servidores, una app {#two-servers-one-app}

Cada `MCPServer` es su propia app con su propio gestor de sesiones. Monta tantos como quieras; entra en todos los gestores desde el lifespan de la app anfitriona, que es uno solo:

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` entra en ambos gestores; arrancan juntos y se cierran en orden inverso.
* Los endpoints son `/notes/mcp` y `/tasks/mcp`: el prefijo de montaje más el path por defecto.

## Cambiar el path {#changing-the-path}

Ese `/mcp` final es `streamable_http_path`. Ponlo en `"/"` y el prefijo de montaje pasa a ser el path público completo:

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

Ahora los clientes se conectan a `/notes`, no a `/notes/mcp`.

## CORS para clientes de navegador {#cors-for-browser-clients}

Un cliente basado en navegador necesita dos permisos de tu parte: **enviar** sus encabezados de solicitud MCP y **leer** el que MCP devuelve. Ambos son configuración CORS de la app anfitriona, y la lista de permitidos de seguridad del transporte de arriba tiene que concordar con ella:

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` es la mitad que todo el mundo olvida. Un navegador hace un **preflight** de cada solicitud MCP, porque `Content-Type: application/json` y los encabezados de solicitud `Mcp-*` no están en la lista segura de CORS, y un encabezado que el preflight no concede es una solicitud que el navegador nunca envía. (`allow_headers=["*"]` también funciona: Starlette responde a un preflight con lo que sea que haya pedido.)
* `expose_headers=["Mcp-Session-Id"]` es la mitad de lectura. Streamable HTTP devuelve el ID de sesión en ese encabezado de respuesta, y los navegadores ocultan los encabezados de respuesta a JavaScript salvo que CORS los exponga por nombre. Sin él, el cliente nunca puede hacer su segunda solicitud.
* `allow_origins` es decisión tuya, no de MCP. Sé preciso y refléjalo en `allowed_origins=` arriba: el navegador hace cumplir CORS, pero el servidor comprueba `Origin` por su cuenta, y un origen en el que el transporte no confía recibe un `403` incluso tras un preflight limpio.
* `allow_methods` enumera los tres métodos que usa Streamable HTTP: `POST` para enviar mensajes, `GET` para abrir el flujo de servidor a cliente, `DELETE` para terminar la sesión.

## Rutas personalizadas {#custom-routes}

`@mcp.custom_route()` registra un endpoint HTTP simple en la misma app, para las cosas que todo servicio desplegado necesita y que no tienen nada que ver con MCP: una comprobación de estado, un callback de OAuth.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* El handler es Starlette puro: una función `async` de `Request` a `Response`.
* `streamable_http_app()` recoge todas las rutas personalizadas. `app.routes` es ahora `/mcp` y `/health`.
* `GET /health` responde `{"status": "ok"}` sin rastro de MCP.

!!! warning
    Las rutas personalizadas **nunca se autentican**, aunque el resto del servidor sí. Es
    deliberado: las comprobaciones de estado y los callbacks de OAuth tienen que ser accesibles
    antes de que exista ningún token. No pongas nada privado detrás de una.

## Resumen {#recap}

* `mcp.streamable_http_app()` devuelve una app Starlette con una ruta, `/mcp`. Cualquier servidor ASGI puede ejecutarla.
* Por defecto, la app responde solo a las solicitudes dirigidas a localhost, y detrás de un nombre de host real lo rechaza todo con un `421` hasta que le pases a `transport_security=` una lista de permitidos. **[Desplegar y escalar](deploy.md)** se ocupa de eso y del resto del camino a producción.
* `Mount` (o `Host`) la mete dentro de una app Starlette o FastAPI más grande.
* **Montar desactiva el lifespan integrado.** El lifespan de la app anfitriona debe entrar en `mcp.session_manager.run()`, o la primera solicitud falla.
* Varios servidores en una app significa varios montajes y un solo lifespan que entra en todos los gestores de sesiones.
* `streamable_http_path="/"` mueve el endpoint al propio prefijo de montaje.
* Los clientes de navegador necesitan CORS: `allow_headers` para los encabezados de solicitud `Mcp-*`, `expose_headers=["Mcp-Session-Id"]` para la respuesta.
* `@mcp.custom_route()` añade endpoints HTTP simples, sin autenticación, junto a `/mcp`.

Una vez que el servidor es accesible en una URL real, **[El cliente](../client/index.md)** se conecta a él con esa URL en lugar de con un objeto servidor.
