---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
  tool: 1
---
# Prompts {#prompts}

Un **prompt** es una plantilla de mensajes que elige el usuario.

Las herramientas son para el modelo. Un prompt es lo contrario: el usuario elige uno en un menú de su cliente (un comando de barra, un botón), completa sus argumentos y los mensajes renderizados entran en la conversación como si los hubiera escrito él mismo.

Para declarar uno, pon `@mcp.prompt()` en una función que devuelva el texto.

## Tu primer prompt {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

El SDK lee las mismas tres cosas que lee de una herramienta:

* El **nombre** es el nombre de la función: `review_code`.
* La **descripción** que muestra el cliente es el docstring: `Review a piece of code.`
* Los **argumentos** salen de los parámetros. `code` no tiene valor por defecto, así que es obligatorio.

Esto es lo que recibe un cliente de `prompts/list`:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Aquí no hay JSON Schema. Los argumentos de un prompt son una lista plana de **valores de cadena con nombre**: un formulario que rellena una persona, no un payload que construye un modelo.

### Renderizarlo {#rendering-it}

El cliente renderiza la plantilla con `prompts/get`, pasando los argumentos. Tu función se ejecuta y el `str` que devuelves se convierte en **un único mensaje de usuario**:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

Esa es toda la vida de un prompt: se lista por nombre, se renderiza a demanda y se coloca en el chat.

!!! check
    `required` se comprueba antes de que se ejecute tu función. Renderiza `review_code` sin `code` y la
    propia solicitud falla con un error JSON-RPC (código `-32603`):

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    No hay un resultado de error al estilo de las herramientas que devolver a un modelo, porque no hay
    ningún modelo en el circuito: la llamada lanza una excepción. El motivo
    (`Missing required arguments: {'code'}`) queda en el log del servidor.

### Pruébalo {#try-it}

Ejecuta el servidor con el MCP Inspector:

```console
uv run mcp dev server.py
```

Abre la pestaña **Prompts** y selecciona `review_code`. El Inspector dibuja un formulario con un campo obligatorio `code`. Rellénalo, renderízalo y te devuelve exactamente el mensaje de usuario de arriba.

## Más de un mensaje {#more-than-one-message}

Una revisión de código es un mensaje. Una sesión de depuración es una conversación, y un prompt puede sembrarla entera.

Devuelve una lista de mensajes en lugar de un `str`:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` y `AssistantMessage` vienen de `mcp.server.mcpserver.prompts.base`. Dales un `str` y lo envuelven en `TextContent` por ti. El rol es el nombre de la clase.
* `Message` es su base común. Úsala como anotación de retorno.

Renderizar `debug_error` ahora produce tres mensajes, en orden:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Fíjate en el último. Rellenar de antemano un turno `assistant` es la forma de orientar la *siguiente* respuesta del modelo sin que el usuario tenga que escribir esa orientación.

## Títulos y descripciones de argumentos {#titles-and-argument-descriptions}

`review_code` es un nombre de función, no una etiqueta. Dale al cliente algo mejor que poner en el botón y describe cada argumento para que el formulario se explique solo:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` es el nombre legible para personas, exactamente igual que el `title` de una herramienta.
* `Annotated[str, Field(description=...)]` es el mismo patrón que usa **[Herramientas](tools.md)** para describir los parámetros de una herramienta. Aquí la descripción va al argumento en lugar de a un esquema.
* `language` tiene valor por defecto, así que deja de ser obligatorio.

La entrada de `prompts/list` ahora lleva todo lo que un cliente necesita para dibujar un buen formulario:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    Si has leído **[Herramientas](tools.md)**, ya sabes todo lo de esta página. El mismo decorador, el mismo
    docstring como descripción, el mismo `Annotated`/`Field`. Lo único que cambia es quién
    lo dispara (el usuario) y adónde va el resultado (a la conversación).

## Resumen {#recap}

* `@mcp.prompt()` en una función la convierte en un prompt. El nombre sale de la función y la descripción del docstring.
* Los prompts están **controlados por el usuario**: el cliente los lista, el usuario elige uno y completa los argumentos.
* Los argumentos son una lista plana de cadenas con nombre (sin esquema). Un parámetro con valor por defecto es opcional.
* Devuelve un `str` y se convierte en un mensaje de usuario. Devuelve una lista de `UserMessage` / `AssistantMessage` para sembrar una conversación de varios turnos.
* `title=` y `Field(description=...)` son lo que un cliente pone en su interfaz.
* Un argumento obligatorio que falta hace fallar toda la solicitud. No hay un resultado de error por prompt.

El autocompletado en el servidor de los argumentos de un prompt (o de una plantilla de recurso) está en **[Autocompletado](completions.md)**.
