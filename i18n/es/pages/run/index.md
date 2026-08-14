---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# Ejecutar el servidor {#running-your-server}

`mcp.run()` inicia el servidor.

La única decisión que tomas es el **transporte**: cómo se mueven realmente los bytes entre el servidor y su cliente.

## Elige un transporte {#pick-a-transport}

| Transporte | Qué es | Cuándo |
|---|---|---|
| `stdio` | El host lanza tu archivo como subproceso y se comunica a través de su stdin y stdout. | Servidores locales. El valor por defecto. |
| `streamable-http` | Un servidor HTTP real que escucha en un puerto. | Cualquier cosa que despliegues. |
| `sse` | El transporte HTTP antiguo. | No lo uses. |

!!! warning
    SSE quedó reemplazado por Streamable HTTP en la revisión del protocolo 2025-03-26.
    `mcp.run(transport="sse")` sigue funcionando, con sus propias opciones `sse_path=` y `message_path=`,
    pero existe para los clientes que no han migrado. No construyas nada nuevo sobre él.

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` es síncrono. Bloquea durante toda la vida del servidor.
* Sin argumentos, el transporte es `stdio`.
* Está bajo `if __name__ == "__main__":` porque todo lo que carga el servidor (`mcp dev`, `mcp run`, `mcp install`, tus pruebas) **importa** este archivo. La guarda evita que una importación se convierta en un servidor en ejecución.

### stdio {#stdio}

No hay nada que configurar. El host inicia tu archivo como proceso hijo, escribe las solicitudes en su stdin y lee las respuestas de su stdout.

Ejecútalo tú mismo y verás la consecuencia:

```console
python server.py
```

No imprime nada y no termina. Está esperando en stdin a que un host hable primero.

Eso también significa que stdout **es el canal**. Mientras sirve, el SDK mueve el canal a un descriptor privado y desvía a stderr la salida que se *vacía* (flush) hacia stdout (un subproceso que escribe en el stdout heredado, un `print()` con flush), donde no puede corromper el flujo. La salida que se vacía hacia stdout *antes* de que empiece a servir (un script envoltorio que hace echo, un print sin búfer al importar) sigue llegando al canal, igual que un `print()` que queda en el búfer hasta que el intérprete lo vacía al salir. Para la salida que de verdad quieres, el módulo `logging` es la herramienta adecuada: su handler vacía cada registro a stderr en cuanto ocurre. Todos los detalles están en **[Logging](../handlers/logging.md)**.

### Pruébalo {#try-it}

```console
uv run mcp dev server.py
```

El Inspector hace exactamente lo que hace un host real: lanza `server.py` como subproceso y se conecta a él por stdio.

Nunca le diste un puerto. No hay ninguno.

## Streamable HTTP {#streamable-http}

Para poner el mismo servidor en un puerto, nombra el transporte (y sus opciones) en `run()`:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

Esa única línea construye una app de Starlette y la sirve con uvicorn. Los clientes se conectan a `http://127.0.0.1:3001/mcp`.

Cada transporte tiene sus propios argumentos nombrados, todos en `run()`:

* `host` / `port`: dónde escuchar. Por defecto `127.0.0.1` y `8000`.
* `streamable_http_path`: dónde vive el endpoint MCP. Por defecto `/mcp`.
* `json_response=True`: responde a cada POST con un único cuerpo JSON en lugar de un flujo SSE. Ese cuerpo tiene sitio para la respuesta y nada más, así que una herramienta que llama de vuelta al cliente a mitad de solicitud (`ctx.elicit()`, muestreo (sampling)) lanza `NoBackChannelError` en este tramo, y las notificaciones ligadas a la llamada en curso (el progreso de `ctx.report_progress()`, los mensajes de log por llamada) se descartan; el flujo `GET` independiente sigue llevando las que no están relacionadas.
* `stateless_http=True`: un transporte nuevo por solicitud, sin seguimiento de sesión.
* `max_request_body_size`: el cuerpo POST más grande que se acepta, en bytes. Es 4 MiB por defecto; las solicitudes mayores
  reciben HTTP 413 antes del análisis o de la creación de la sesión. Súbelo solo cuando los mensajes MCP legítimos
  superen ese tamaño.
* `event_store`, `retry_interval`, `transport_security`: reanudabilidad y protección contra DNS rebinding. Pueden esperar hasta que despliegues en algún lugar que no sea localhost; **[Desplegar y escalar](deploy.md)** cubre `transport_security`.

!!! warning
    Las opciones de transporte van a `run()`, **no** a `MCPServer(...)`. El constructor describe lo que
    el servidor *es*: nombre, versión, instrucciones. `run()` describe cómo se sirve. Si lo haces
    al revés, Python responde antes de que MCP entre siquiera en juego:

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` es el camino corto. En cuanto necesitas más (el servidor montado dentro de una app existente, dos servidores en un proceso, CORS para clientes de navegador), construyes la app ASGI tú mismo y se la pasas a cualquier host ASGI. Eso es **[Añadir a una app existente](asgi.md)**.

## Ajustes del servidor {#server-settings}

Un par de cosas sobre la ejecución no tienen que ver con el transporte. Son argumentos del constructor:

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: se pasa a `logging.basicConfig()` en el momento en que se construye `MCPServer(...)`. Eso configura el logger **raíz**, así que fija el nivel también para tus propios loggers, no solo para los del SDK. Por defecto `"INFO"`.
* `debug`: se reenvía a la app de Starlette que construyen los transportes HTTP. Por defecto `False`.

Ambos acaban en `mcp.settings`, que puedes leer en tiempo de ejecución.

## El comando `mcp` {#the-mcp-command}

El extra `[cli]` instala una pequeña herramienta de línea de comandos alrededor de todo esto.

`mcp dev` ejecuta el servidor bajo el **MCP Inspector**:

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` añade paquetes al entorno que construye; `--with-editable` instala tu propio paquete en él. Necesita `npx` en tu `PATH`: el Inspector es una app de Node.js.

`mcp run` importa el archivo, encuentra el objeto servidor (un `mcp`, `server` o `app` a nivel de módulo) y llama a `run()` sobre él:

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

El sufijo `:` nombra el objeto cuando no se llama `mcp`, `server` ni `app`.

Tu bloque `if __name__ == "__main__":` nunca se ejecuta aquí: `mcp run` llama a `run()` por su cuenta, y la única opción que reenvía es `--transport`.

`mcp install` registra el servidor en **Claude Desktop**, de modo que la app lo lanza por ti:

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` y `-f .env` guardan variables de entorno en esa entrada. Claude Desktop inicia el servidor en su propio proceso. El entorno de tu shell no está ahí.

Claude Desktop es el único host que `mcp install` conoce. Todos los demás hosts (Claude Code, Cursor, VS Code) aceptan el mismo comando de lanzamiento en su propio archivo de configuración, y **[Conectar con un host real](../get-started/real-host.md)** tiene cada uno.

`mcp version` imprime la versión del SDK instalada.

!!! tip
    `mcp dev` y `mcp run` solo entienden `MCPServer`. Si construyes con el `Server` de bajo nivel,
    lo ejecutas tú mismo. Consulta **[El Server de bajo nivel](../advanced/low-level-server.md)**.

## Resumen {#recap}

* Un **transporte** es cómo llegan los bytes al servidor: `stdio` para un subproceso local, `streamable-http` para un puerto. SSE está reemplazado.
* `mcp.run()` elige el transporte. Sin argumentos es `stdio`, y bloquea.
* Cada opción de transporte (`host`, `port`, `streamable_http_path`, ...) es un argumento de `run()`, nunca de `MCPServer(...)`.
* Mantén `run()` bajo `if __name__ == "__main__":`. Todo lo que carga el servidor importa primero el archivo.
* `log_level=` y `debug=` son argumentos del constructor; acaban en `mcp.settings`.
* `mcp dev` para el Inspector, `mcp run` para ejecutar un archivo, `mcp install` para Claude Desktop, `mcp version` para la versión.
* El transporte nunca cambia lo que el servidor *es*: los tres archivos de esta página exponen la misma herramienta.

Cuando el límite es `run()` mismo (el servidor dentro de una app que ya existe), es **[Añadir a una app existente](asgi.md)**. Un nombre de host real y más de un worker es **[Desplegar y escalar](deploy.md)**. Y si algunos de tus clientes siguen en la versión de la especificación 2025-11-25 o anterior, **[Atender clientes heredados](legacy-clients.md)** es la buena noticia.
