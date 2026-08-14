---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# Registro de logs {#logging}

Registra logs desde una herramienta igual que desde cualquier otra función de Python: con la biblioteca estándar.

MCP tiene una **capacidad de logging** a nivel de protocolo: un servidor podía enviar sus mensajes de log al cliente como notificaciones, mediante métodos del objeto `Context`. La revisión 2026-07-28 de la especificación **declara obsoleta esa capacidad y no la sustituye**, así que esta documentación no la enseña. La lista completa de lo que está obsoleto y qué hacer en su lugar está en **[Funcionalidades obsoletas](../deprecated.md)**.

Lo que haces en su lugar es lo que haces en cualquier otro programa de Python: usar la biblioteca estándar.

## Una herramienta que registra logs {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` te da un logger con el nombre de tu módulo. Créalo una vez, al principio.
* Dentro de la herramienta llamas a `logger.info(...)` como en cualquier otra función. Nada que inyectar, nada que esperar con `await`, nada específico de MCP.

!!! check
    Llama a la herramienta y mira el resultado completo:

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    La línea de log no aparece por ningún lado. El logging es para **ti**, la persona que opera el
    servidor. El modelo nunca lo ve. Si el modelo debe leer algo, devuélvelo con `return`.

## A dónde va {#where-it-goes}

Para un servidor **stdio**, esta pregunta importa más de lo habitual. El host lanzó el servidor como subproceso y lee los mensajes MCP desde su **stdout**. La salida de error estándar es tuya.

La biblioteca estándar ya hace lo correcto: la salida de log va a `sys.stderr` por defecto. Tus líneas `logger.info(...)` acaban en la terminal (o donde sea que el host recoja el stderr del subproceso), y el flujo del protocolo se mantiene limpio.

!!! tip
    No uses `print()` en un servidor stdio. `print` escribe en **stdout**, y stdout pertenece al
    protocolo. Mientras atiende solicitudes, el SDK desvía a stderr el stdout que realmente se *vacía*
    (flush), así que no puede corromper el canal. Pero un `print()` en un proceso con búfer por bloques
    suele quedarse sin vaciar en el búfer de `sys.stdout` hasta que el intérprete lo drena al salir,
    directamente sobre el flujo del protocolo. Incluso cuando se desvía, la línea llega en bruto entre la
    salida de log, sin nivel, sin nombre de logger y sin forma de filtrarla.

    `logger.debug("got here")` cuesta la misma línea de esfuerzo y va al lugar correcto.

## El nivel {#the-level}

No tienes que llamar a `logging.basicConfig()` tú mismo. Construir un `MCPServer` ya lo hizo, con un handler apuntado a la salida de error estándar, al nivel que pasas como `log_level=`, así que `MCPServer("Bookshop", log_level="DEBUG")` es todo lo que hace falta para ver tus líneas `logger.debug(...)`.

El valor por defecto es `"INFO"`.

`logging.basicConfig()` nunca reemplaza handlers que ya existen. Si configuras el logging tú mismo antes de crear el servidor, tu configuración gana.

## Pruébalo {#try-it}

Ejecuta el servidor con el MCP Inspector:

```console
uv run mcp dev server.py
```

Llama a `search_books` desde la pestaña **Tools**. El Inspector te muestra el resultado: solo el valor devuelto. La línea

```text
Searching for 'dune'
```

fue a la salida de error estándar: a la terminal, no al canal.

!!! info
    Si lo que realmente quieres es *trazabilidad* (cada solicitud, cuánto tardó, si falló), no quieres
    líneas de log, quieres spans. El servidor ya los emite: el SDK traza cada mensaje con OpenTelemetry
    por defecto. Consulta **[OpenTelemetry](../run/opentelemetry.md)**.

## Resumen {#recap}

* La capacidad de logging del protocolo MCP queda obsoleta en la especificación 2026-07-28 y no se sustituye. No construyas sobre ella.
* `logger = logging.getLogger(__name__)` a nivel de módulo, `logger.info(...)` en la herramienta. Ese es todo el patrón.
* La salida de log nunca llega al modelo. Solo lo hace el valor que devuelves con `return`.
* La salida de error estándar es tuya; stdout pertenece al protocolo. El SDK desvía a stderr el stdout extraviado que se vacía mientras atiende solicitudes, pero un `print()` sin vaciar todavía puede drenarse sobre el canal al salir, y las líneas desviadas llegan sin etiquetar; usa `logging`, cuyo handler vacía cada registro.
* `MCPServer(..., log_level="DEBUG")` fija el nivel, y una configuración de logging que hayas hecho antes se respeta.

Avisar a los clientes conectados de que algo cambió en el servidor (la lista de herramientas, un recurso) es cosa de **[Suscripciones](subscriptions.md)**.
