---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# El cliente {#the-client}

Un **`Client`** es la forma en que un programa de Python se comunica con un servidor MCP.

Es un solo objeto con un solo ciclo de vida: lo construyes, entras en `async with`, llamas a sus métodos. Cada verbo del protocolo (listar las herramientas, llamar a una, leer un recurso, renderizar un prompt) es un método `async` del objeto que devuelve un resultado tipado.

## Tu primer cliente {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

El servidor del principio solo está ahí para que tengas algo a lo que conectarte. El cliente son las cinco líneas resaltadas.

* `Client(mcp)` recibe **el propio objeto servidor**. Ese es el transporte en memoria: sin subproceso, sin puerto, sin HTTP. Así se conectan todos los ejemplos de esta página y todas las pruebas que escribas.
* `async with` es el **ciclo de vida**. Al entrar se conecta y negocia; al salir se desconecta. No hay un par `connect()` / `close()`, y un `Client` no se puede reutilizar una vez que termina el bloque.
* Dentro del bloque, los datos de la conexión ya están ahí como propiedades simples.

### Qué puedes pasarle a `Client` {#what-you-can-pass-to-client}

`Client` recibe un solo argumento posicional y resuelve el transporte a partir de su tipo:

* Una instancia de `MCPServer` (o del `Server` de bajo nivel): se conecta **en el mismo proceso**.
* Una cadena con una URL (`Client("http://localhost:8000/mcp")`): Streamable HTTP, el camino de producción.
* Un **transporte**: cualquier cosa que puedas usar con `async with ... as (read, write)`, como `stdio_client(...)` envolviendo un subproceso.

Todo lo demás en esta página es idéntico en los tres casos. Los encabezados, los subprocesos, los timeouts y el protocolo `Transport` tienen su propia página: **[Transportes del cliente](transports.md)**.

### Qué hay en un cliente conectado {#whats-on-a-connected-client}

Cuatro propiedades de solo lectura, que se rellenan en cuanto entras en el bloque:

* `client.server_info`: la identidad del servidor, o `None` para un servidor de la generación 2026 que no la informa (los servidores de python-sdk lo hacen por defecto). Aquí `server_info.name` es `"Bookshop"` y `server_info.version` es lo que el servidor informe.
* `client.server_capabilities`: lo que el servidor puede hacer (`tools`, `resources`, `prompts`, `completions`, ...). Una capacidad que el servidor no tiene es `None`.
* `client.protocol_version`: la versión del protocolo que acordaron las dos partes. Aquí es `"2026-07-28"`.
* `client.instructions`: la cadena `instructions=` del servidor, o `None` si no definió una.

Nunca elegiste una versión del protocolo. Por defecto, el `Client` sondea el servidor y recurre al handshake clásico con los más antiguos, así que un mismo cliente funciona contra servidores de cualquier generación. Cuando necesites controlar eso, **[Versiones del protocolo](../protocol-versions.md)** tiene todos los detalles.

!!! tip
    `client.session` es la `ClientSession` subyacente, la vía de escape de bajo nivel.
    No la necesitarás para nada de esta página.

## Listar herramientas {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` devuelve un `ListToolsResult`; las herramientas están en `.tools`. Cada una es la definición completa que un host le entregaría a un modelo:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

y `tool.input_schema` es el JSON Schema que el servidor derivó de las anotaciones de tipo de la función:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Ese esquema es todo lo que una UI necesita para renderizar un formulario de argumentos, y todo lo que un modelo necesita para producir argumentos válidos.

!!! tip
    `title` es opcional, así que una UI que muestra herramientas a una persona tiene que elegir: el `title` si lo hay,
    el `name` si no. `from mcp.shared.metadata_utils import get_display_name` hace exactamente eso,
    para herramientas, recursos, plantillas de recursos y prompts.

## Llamar a una herramienta {#calling-a-tool}

`call_tool(name, arguments)` ejecuta la herramienta y te devuelve un `CallToolResult`.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

El `lookup_book` del servidor devuelve un `Book` de Pydantic. Esto es lo que ve el cliente:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Un solo valor de retorno, tres cosas que leer. Cada una tiene un consumidor distinto.

### `content`: lo que lee el modelo {#content-what-the-model-reads}

`content` es una `list` de **bloques de contenido**, y un bloque de contenido es una unión: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` o `EmbeddedResource`. Una herramienta puede devolver varios, de distintos tipos.

Por eso `main` acota el tipo con `isinstance(block, TextContent)` antes de tocar `block.text`. Fíjate en que no hay ningún `.text` fuera del `isinstance`: el verificador de tipos no lo permite, porque `ImageContent` tiene `.data`, no `.text`. La unión es honesta sobre lo que una herramienta puede enviarte; tu código también debería serlo.

### `structured_content`: lo que lee tu aplicación {#structured_content-what-your-application-reads}

`structured_content` es el valor de retorno de la herramienta en JSON, conforme al `output_schema` que declara la herramienta. Sin analizar cadenas, sin adivinar.

Cuando ambos están presentes dicen lo mismo dos veces a propósito: `content` es para un modelo, `structured_content` es para el código. De dónde sale la mitad estructurada, y cómo controlarla, está en la página **[Salida estructurada](../servers/structured-output.md)**.

### `is_error`: si la herramienta falló {#is_error-whether-the-tool-failed}

Una herramienta que lanza una excepción **no** la lanza en tu cliente. Vuelve como un resultado normal con `is_error=True`.

!!! check
    Pídele `"Solaris"` a `lookup_book` (un título que no está en el catálogo) y la función lanza
    `ValueError`. Aun así, la llamada devuelve un resultado normal:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    El mensaje de la excepción acabó en `content`, donde el **modelo** puede leerlo y volver a intentarlo. Es
    deliberado: un error de herramienta es parte de la conversación, no un fallo fatal. Mira siempre `is_error`
    antes de confiar en `structured_content`.

!!! warning
    `is_error=True` cubre más que tu propio `raise`. Pide una herramienta que el servidor ni siquiera tiene
    (`call_tool("does_not_exist", {})`) y no se lanza nada. Recibes la misma forma de vuelta,
    `is_error=True` con `Unknown tool: does_not_exist` en `content`. Un método de `Client` lanza
    `MCPError` solo cuando el servidor responde con un **error** JSON-RPC en lugar de un resultado, y
    **[Manejo de errores](../servers/handling-errors.md)** explica cuándo un servidor produce cada cosa.

## Recursos {#resources}

Los verbos de recursos vienen en pares: dos formas de listar, una de leer.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` devuelve los recursos **concretos**, los que tienen una URI fija. Aquí: `['catalog://genres']`.
* `list_resource_templates()` devuelve los **parametrizados**. Aquí: `['catalog://genres/{genre}']`. Son dos listas distintas porque una plantilla no se puede leer hasta que la rellenas.
* `read_resource(uri)` recibe una URI como `str` simple y funciona con ambos: pasa `"catalog://genres/poetry"` y el servidor la hace coincidir con la plantilla.

`read_resource` devuelve `contents`, una lista de `TextResourceContents` o `BlobResourceContents`. La misma idea que con el contenido de las herramientas: acota con `isinstance` y luego lee `.text` (o `.blob`).

A un cliente también se le puede avisar cuando cambia un recurso. En conexiones de la generación 2025 eso es `subscribe_resource(uri)` / `unsubscribe_resource(uri)`, un par de métodos que `MCPServer` no implementa, así que con el protocolo 2026-07-28 (donde esos verbos ya no existen) la solicitud responde `-32601`, *Method not found*. El reemplazo de 2026 es un stream `subscriptions/listen`, que `MCPServer` *sí* sirve (allí `server_capabilities.resources.subscribe` es `True`), y cómo consumirlo con `client.listen(...)` es la página **[Suscripciones](subscriptions.md)** de esta sección.

## Prompts {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` te dice qué ofrece el servidor y qué necesita cada prompt:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` lo renderiza. El diccionario de argumentos es `str -> str`: los argumentos de un prompt siempre son cadenas. El resultado es `messages`, una lista de `PromptMessage`, cada uno con un `role` y un bloque `content`:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Un host le entrega esos mensajes directamente al modelo. Esa es toda la funcionalidad.

## Autocompletado {#completions}

Un servidor con un handler de autocompletado puede autocompletar argumentos de prompts y de plantillas de recursos mientras el usuario escribe.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` dice *qué* prompt o plantilla estás rellenando: un `PromptReference` o un `ResourceTemplateReference`.
* `argument` es `{"name": ..., "value": ...}`: el argumento y lo que el usuario ha escrito hasta ahora.

La respuesta está en `result.completion.values`. Escribe `"p"` y el servidor devuelve `['poetry']`. El lado del servidor, y cómo un handler usa los *otros* argumentos ya rellenados para acotar sus sugerencias, es la página **[Autocompletado](../servers/completions.md)**.

## Paginación {#pagination}

Cada método `list_*` acepta un argumento nombrado `cursor=` y cada resultado trae un `next_cursor`. Cuando `next_cursor` es `None`, ya lo tienes todo.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Este bucle es correcto contra cualquier servidor. `MCPServer` devuelve todo en una sola página, así que `next_cursor` es `None` y el bucle se ejecuta una vez; por eso la mayoría del código nunca lo escribe. Los servidores que realmente paginan, y las reglas que siguen los cursores, están en **[Paginación](../advanced/pagination.md)**.

## En las pruebas {#in-tests}

`Client(mcp)`, sin proceso y sin puerto, ya es un banco de pruebas para tu servidor.

Hay una opción del constructor pensada para eso: `Client(mcp, raise_exceptions=True)`. Solo tiene efecto en conexiones en memoria, y **[Pruebas](../get-started/testing.md)** es la página que la explica y construye todo el patrón a su alrededor.

## Resumen {#recap}

* `Client(x)` se conecta en memoria a un objeto servidor, por Streamable HTTP a una cadena con una URL, y por cualquier otra cosa mediante un transporte.
* `async with` es todo el ciclo de vida. Dentro, `server_capabilities` y `protocol_version` ya están rellenas; `server_info` e `instructions` también, cuando el servidor las proporciona.
* `list_tools()` te da el `name`, `title`, `description` e `input_schema` de cada herramienta.
* `call_tool()` devuelve `content` para el modelo, `structured_content` para tu código, e `is_error`. Una herramienta que lanza una excepción es un resultado, no una excepción.
* `content` es una unión de tipos de bloque; acota con `isinstance` antes de leer.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` y `complete` completan los verbos.
* Cada `list_*` acepta `cursor=`; itera hasta que `next_cursor` sea `None`.

Lo que un servidor puede pedirle al *cliente*, y cómo le respondes, está en **[Callbacks del cliente](callbacks.md)**.
