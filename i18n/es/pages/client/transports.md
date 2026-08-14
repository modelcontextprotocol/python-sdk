---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# Transportes del cliente {#client-transports}

Cada `Client` habla con su servidor a través de un **transporte**: lo que realmente lleva los mensajes.

Nunca configuras uno por separado. `Client` recibe un único argumento posicional y deduce el transporte a partir de su tipo.

El lado del *servidor* de cada uno (lo que hace `mcp.run()` y lo que despliegas) está en **[Ejecutar el servidor](../run/index.md)**.

## En memoria {#in-memory}

Pasa el propio objeto del servidor:

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

Sin subproceso, sin puerto, sin bytes por ningún canal. El cliente y el servidor son dos objetos en el mismo proceso, y aun así la llamada pasa por la capa real del protocolo: `search_books` se lista, se valida y se invoca exactamente igual que por HTTP.

Eso lo convierte en dos cosas a la vez:

* **Un arnés de pruebas.** Todos los ejemplos de esta documentación se ejercitan así, y la página **[Pruebas](../get-started/testing.md)** construye todo el patrón en torno a ello.
* **Una API de integración.** Una aplicación que construye el servidor no necesita un salto de red para llamar a sus herramientas.

## Streamable HTTP {#streamable-http}

Pasa una cadena con una URL y obtienes **Streamable HTTP**, el transporte con el que despliegas:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

Ese es todo el cliente de producción. `Client` envuelve la URL en `streamable_http_client(...)` por ti, encima de un `httpx2.AsyncClient` configurado como MCP necesita: `follow_redirects=True`, un timeout de 30 segundos para connect/write/pool y un timeout de lectura de 300 segundos, porque el servidor puede mantener abierto un flujo de respuesta.

!!! check
    Un `Client` que has construido **no** está conectado. La construcción solo elige el transporte;
    `async with` es lo que lo abre. Intenta usar la conexión antes de entrar y el SDK te lo dice:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    No se resolvió, se obtuvo ni se lanzó nada cuando escribiste `Client("http://...")`. Esa línea es gratis.

### Trae tu propio `httpx2.AsyncClient` {#bring-your-own-httpx2asyncclient}

En cuanto necesites un encabezado `Authorization`, una cookie, un proxy, mTLS o un timeout distinto, construye tú mismo el `httpx2.AsyncClient` y entrégaselo a `streamable_http_client`:

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

Dos cosas que notar:

* El `httpx2.AsyncClient` es tuyo, así que **tú** entras y sales de él. El SDK nunca cierra un cliente que no creó.
* `streamable_http_client(url, http_client=...)` devuelve un transporte, y `Client(transport)` lo acepta como cualquier otra cosa.

Una nota sobre TLS: `httpx2` verifica los certificados contra el almacén de confianza del sistema operativo (mediante
[`truststore`](https://pypi.org/project/truststore/)), no contra una lista de CA incluida. En un entorno sin
un almacén de CA del sistema utilizable (algunos contenedores mínimos), configura las variables de entorno
estándar `SSL_CERT_FILE`/`SSL_CERT_DIR` o pasa un `verify=ssl_context` explícito a tu `httpx2.AsyncClient`
(el contexto está en
[`httpx` y `httpx-sse` sustituidos por `httpx2`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

!!! warning
    `streamable_http_client` antes aceptaba `headers=` y `timeout=` directamente. Ya no:
    sus únicos parámetros son `url`, `http_client` y `terminate_on_close`. Usa `headers=` por
    costumbre y obtienes:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    Todo lo que tiene forma de HTTP vive ahora en el único `httpx2.AsyncClient` que pasas.

!!! info
    `httpx2` conserva la API conocida de `httpx`, así que si conoces `httpx` ya sabes cómo hacer la autenticación,
    los proxies, los event hooks, los reintentos y los límites de conexión aquí. El SDK no añade nada encima ni quita
    nada. También es donde se conecta OAuth:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. Todo ese flujo está en **[Clientes OAuth](oauth-clients.md)**.

## stdio {#stdio}

Un servidor **stdio** es un subproceso. El cliente lo lanza, escribe JSON-RPC en su stdin y lee JSON-RPC de su stdout. Así es como un host de escritorio ejecuta un servidor en tu máquina: un host *es* este código más una interfaz de usuario, y **[Conectar a un host real](../get-started/real-host.md)** es la misma relación vista desde el lado del host, como archivo de configuración.

Describe el proceso con `StdioServerParameters`, conviértelo en un transporte con `stdio_client` y entrega *eso* a `Client`:

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` no acepta el objeto de parámetros por sí solo. `StdioServerParameters` es configuración; `stdio_client(server)` es el transporte que sabe lanzar un proceso a partir de ella. Envuélvelo siempre.

Salir del bloque `async with` también cierra el subproceso: cierra stdin, espera y lo mata si se queda. Nunca lo limpias tú.

!!! warning
    El proceso hijo **no** hereda tu entorno. Recibe una lista de permitidos mínima (`HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` y `USER` en POSIX) para que nada sensible se filtre a un proceso que quizá
    no hayas escrito tú.

    Un servidor que necesita una clave de API no la encontrará ahí. Pásala explícitamente con `env=`; esas
    variables se fusionan encima de la lista de permitidos. Eso es lo que hace `BOOKSHOP_API_KEY` arriba.

## SSE {#sse}

`sse_client(url)`, de `mcp.client.sse`, es el transporte HTTP al que reemplazó Streamable HTTP. Envuélvelo igual, `Client(sse_client("http://localhost:8000/sse"))`, para hablar con un servidor que todavía lo usa, y no construyas nada nuevo sobre él.

## El protocolo `Transport` {#the-transport-protocol}

Para `Client`, todo lo anterior es lo mismo.

Un **transporte** es cualquier gestor de contexto asíncrono que produce un par `(read, write)` de flujos de mensajes: formalmente, el protocolo `Transport` de `mcp.client`. `Client` resuelve su argumento por tipo: un objeto de servidor se conecta dentro del proceso, un `str` se convierte en `streamable_http_client(url)` y cualquier otra cosa se entra directamente como transporte. Esa última regla es la razón por la que `stdio_client(...)`, `streamable_http_client(...)` y `sse_client(...)` encajan todos en el mismo hueco, y por la que puedes escribir el tuyo.

## Resumen {#recap}

* `Client(mcp)` (el objeto del servidor) se conecta en memoria. Úsalo para pruebas y para integración.
* `Client("http://.../mcp")` (una URL) se conecta por Streamable HTTP, el transporte de producción.
* Los encabezados, la autenticación, los proxies y los timeouts van en un `httpx2.AsyncClient` que pasas a `streamable_http_client(url, http_client=...)`. No existe el argumento nombrado `headers=`.
* stdio es `Client(stdio_client(StdioServerParameters(...)))`, nunca el objeto de parámetros solo.
* El subproceso recibe un entorno con lista de permitidos, no el tuyo; `env=` se añade a él.
* Un transporte es cualquier cosa con la que puedas hacer `async with x as (read, write)`. `Client` entrega directamente a ese protocolo todo lo que no sea un objeto de servidor ni una URL.
* Construir un `Client` elige el transporte. `async with` lo abre.

Una vez abierto el transporte, los dos lados tienen que acordar una versión del protocolo. Normalmente nunca piensas en ello; cuando lo hagas, **[Versiones del protocolo](../protocol-versions.md)** es la página.
