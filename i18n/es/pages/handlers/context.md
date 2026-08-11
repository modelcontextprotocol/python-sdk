---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# El Context {#the-context}

Los argumentos de una herramienta vienen del modelo. Todo lo demás (la solicitud que estás atendiendo, el servidor en el que vives, una forma de responderle al cliente) viene de un solo objeto: el **`Context`**.

No lo construyes ni lo configuras. Lo pides.

## Pídelo {#ask-for-it}

Añade un parámetro anotado con `Context` a cualquier herramienta:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* El SDK construye un `Context` nuevo para cada solicitud y lo pasa.
* El **nombre del parámetro no importa**. `ctx`, `context`, `c`: el SDK lo encuentra por su anotación.
* Los recursos y los prompts también pueden declarar uno, de la misma forma.
* `ctx.request_id` es el id de la solicitud que tu función está atendiendo en este momento.

!!! info
    Si has usado FastAPI, ya has visto esta jugada: declaras un parámetro con el tipo propio del
    framework (`Request` allí, `Context` aquí) y el framework lo proporciona. Nada que registrar,
    nada que configurar: la anotación de tipo es todo el mecanismo.

### Invisible para el modelo {#invisible-to-the-model}

Esta es la parte que hay que interiorizar. Este es el esquema de entrada que `tools/list` informa para `search_books`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Una sola propiedad. `ctx` no es un argumento: nunca aparece en el esquema, al modelo nunca se le habla de él y ningún cliente puede rellenarlo. Es un contrato entre tú y el SDK, que no aparece en lo que se transmite.

### Pruébalo {#try-it}

Ejecuta el servidor con el MCP Inspector:

```console
uv run mcp dev server.py
```

El formulario de `search_books` tiene un único campo `query`. Llámalo con `dune`:

```text
[request 3] Found 3 books matching 'dune'.
```

El número es el de la solicitud que haya tocado. Vuelve a llamar a la herramienta y cambia: cada solicitud recibe su propio `Context`.

## Qué te da {#what-it-gives-you}

El objeto inyectado es pequeño. Además de `request_id`:

* `await ctx.read_resource(uri)`: lee uno de los recursos **propios** del servidor desde dentro de una herramienta. La siguiente sección.
* `await ctx.report_progress(progress, total, message)`: envía el progreso al llamador durante una llamada larga. Todos los detalles están en **[Progreso](progress.md)**.
* `await ctx.elicit(message, schema)` y `await ctx.elicit_url(...)`: pausan la herramienta y le hacen una pregunta al usuario. De eso trata **[Elicitación](elicitation.md)** (elicitation).
* `ctx.session`: el lado del servidor de la conversación con este cliente. Aquí viven las notificaciones que envías al cliente; la última sección lo usa.
* `ctx.headers`: los encabezados de la solicitud que transportó el transporte, o `None` en stdio. Lee un encabezado personalizado con `(ctx.headers or {}).get("x-...")`. Los encabezados son entrada proporcionada por el cliente: valen para una configuración regional o un feature flag, nunca para una identidad.
* `ctx.request_context`: el registro bruto por solicitud. El campo que vas a buscar es `lifespan_context`, el objeto que tu código de arranque entregó con yield (consulta **[Lifespan](lifespan.md)**).

El logging queda fuera de esa lista a propósito. Un servidor registra logs con el módulo `logging` de Python, como cualquier otro programa de Python. **[Logging](logging.md)** es la página breve que explica por qué.

!!! tip
    La inyección solo ocurre en la función que registraste. Una función auxiliar a la que llama tu
    herramienta no recibe su propio `Context`; pásale `ctx` como un argumento normal. No hay un
    "contexto actual" ambiental que obtener desde otro sitio.

## Lee tus propios recursos {#read-your-own-resources}

Los recursos de un servidor no son solo para los clientes. Una herramienta también puede leerlos:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` resuelve la URI a través del mismo registro que atiende `resources/read`, así que una herramienta obtiene lo que obtendría un cliente: un iterable de `ReadResourceContents`, uno por bloque de contenido. Para esta URI hay uno:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` es exactamente lo que devolvió `genres()`. Una única fuente de verdad: el cliente explora el recurso, tus herramientas lo consumen, nadie copia la cadena.
* El único parámetro de `describe_catalog` es el `Context`, así que su esquema de entrada **no tiene ninguna propiedad**. El modelo la llama con `{}`.

## Dile al cliente que la lista cambió {#tell-the-client-the-list-changed}

Lo que ofrece un servidor no queda fijo al importar. Registra una herramienta en tiempo de ejecución y luego díselo al cliente:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` registra una función normal como herramienta: nombre, descripción y esquema se derivan exactamente como lo habría hecho `@mcp.tool()`.
* `await ctx.session.send_tool_list_changed()` envía `notifications/tools/list_changed`. Un cliente que la recibe vuelve a llamar a `tools/list` y ve `recommend_book`.

Los hermanos son `send_resource_list_changed()`, `send_prompt_list_changed()` y `send_resource_updated(uri)` para un cambio en un recurso concreto.

En una conexión 2026-07-28, los clientes reciben notificaciones de cambio solo en un stream `subscriptions/listen` que hayan abierto, así que los métodos `send_*` de arriba no llegan a esos streams. Los métodos de publicación del `Context` entregan a todos los streams suscritos a la vez: `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()` y `await ctx.notify_resource_updated(uri)`. Todos los detalles, incluido cómo escalar horizontalmente entre réplicas, están en **[Suscripciones](subscriptions.md)**.

!!! check
    Antes de que alguien ejecute `enable_recommendations`, la herramienta que prometes no existe.
    Llámala de todos modos y el resultado es un error que el modelo puede leer:

    ```text
    Unknown tool: recommend_book
    ```

    Ejecuta `enable_recommendations` y esa misma llamada funciona. La lista de herramientas es
    realmente dinámica: `tools/list` refleja lo que esté registrado *en este momento*.

## Resumen {#recap}

* Anota un parámetro con `Context` (en una herramienta, un recurso o un prompt) y el SDK lo inyecta. El nombre lo eliges tú.
* Es invisible para el modelo: el esquema de entrada solo contiene tus argumentos reales.
* `ctx.request_id` identifica la solicitud; `ctx.request_context.lifespan_context` es lo que entregó tu arranque con yield.
* `await ctx.read_resource(uri)` permite que una herramienta lea los recursos propios del servidor.
* `ctx.session` es el canal de vuelta al cliente: `send_tool_list_changed()` y sus hermanos le indican que vuelva a obtener una lista que cambiaste.
* Los informes de progreso y la elicitación también empiezan en el `Context`; cada uno tiene su propia página.

Los parámetros que el modelo nunca ve, rellenados por tus propias funciones, son las **[Dependencias](dependencies.md)**.
