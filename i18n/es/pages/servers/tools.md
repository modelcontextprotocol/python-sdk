---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# Herramientas {#tools}

Una **herramienta** es una función a la que el modelo puede llamar.

Declaras una poniendo `@mcp.tool()` sobre una función de Python normal. Esa es toda la API.

## Tu primera herramienta {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

Mira lo que escribiste. No hay esquemas, ni JSON, ni protocolo: solo una función. El SDK lee tres cosas de ella:

* El **nombre** de la herramienta es el nombre de la función: `search_books`.
* La **descripción** que ve el modelo es el docstring: `Search the catalog by title or author.`
* Los **argumentos** que el modelo puede pasar salen de las anotaciones de tipo: `query: str` y `limit: int`.

### El esquema de entrada {#the-input-schema}

A partir de esas anotaciones de tipo, el SDK genera un JSON Schema y lo envía al cliente durante `tools/list`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

Ambos argumentos están en `required` porque ninguno tiene valor por defecto. Lo arreglarás en un momento. (Las claves `title` son artefactos de Pydantic; las propiedades, sus tipos y `required` son el contrato.)

!!! tip
    Aquí las anotaciones de tipo no son documentación. Son **el contrato**. Si un cliente envía `"limit": "ten"`,
    el SDK lo rechaza antes de que tu función llegue a ejecutarse.

### Lo que recibe el modelo {#what-the-model-gets-back}

Llama a la herramienta con `{"query": "dune", "limit": 5}` y el resultado tiene dos partes:

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` es el texto que lee el **modelo**. `structured_content` son datos tipados para la **aplicación cliente**. Está ahí porque declaraste el tipo de retorno como `-> str`.

No te preocupes todavía por `structured_content`. Devuelve objetos reales de Python desde tus herramientas y ocurre lo correcto; la página **[Salida estructurada](structured-output.md)** trata justamente de eso.

### Pruébalo {#try-it}

Ejecuta el servidor con el MCP Inspector:

```console
uv run mcp dev server.py
```

Abre la URL que imprime, ve a la pestaña **Tools** y llama a `search_books`.

El Inspector muestra un formulario con un campo de texto obligatorio `query` y un campo numérico obligatorio `limit`. Construyó ese formulario a partir de tus anotaciones de tipo. Lo mismo hará cualquier otro cliente MCP.

## Argumentos opcionales {#optional-arguments}

Dale un valor por defecto a un parámetro y deja de ser obligatorio. Eso es todo. Es simplemente Python.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

El esquema lo refleja:

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

`limit` salió de `required` y ganó `"default": 10`. Un cliente que lo omite recibe `10`, exactamente como haría Python.

## Esquemas más ricos con `Field` {#richer-schemas-with-field}

Las anotaciones de tipo te llevan lejos, pero a veces quieres *describir* un argumento, o restringirlo.

Envuelve el tipo en `Annotated` y añade un `Field` de Pydantic:

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

Tres cosas nuevas, todas en los parámetros:

* `Field(description=...)`: una descripción por argumento que el modelo lee junto con el docstring.
* `Field(ge=1, le=50)`: límites numéricos. Llegan al esquema como `"minimum": 1, "maximum": 50`.
* `Literal["fiction", "non-fiction", "poetry"]`: una enumeración. El modelo solo puede elegir uno de esos valores.

!!! check
    Las restricciones no son decoración. Llama a la herramienta con `limit=999` y el SDK responde con un
    error de herramienta **antes de que tu función se ejecute**:

    ```text
    Input should be less than or equal to 50
    ```

    Ese error vuelve al modelo como resultado de la herramienta, y el modelo lo lee y reintenta con
    un valor válido. Escribiste `le=50` una vez y obtuviste agentes que se corrigen solos, gratis.

!!! info
    Si has usado FastAPI o Pydantic, ya sabes todo esto. Es el mismo `Field`,
    el mismo `Annotated`, la misma validación. No hay nada específico de MCP que aprender aquí.

## Un modelo como parámetro {#a-model-as-a-parameter}

Cuando una herramienta recibe más de un par de argumentos, agrúpalos en un modelo de Pydantic:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

El esquema de `Book` queda anidado dentro del esquema de entrada de la herramienta (como referencia en `$defs`), el modelo lo rellena como un objeto JSON y tu función recibe una **instancia real de `Book`**, ya validada, con los atributos `.title`, `.author` y `.year`.

Puedes combinar a tu gusto: parámetros simples junto a parámetros de modelo, modelos anidados, listas de modelos. Es Pydantic hasta el fondo.

## `async def` {#async-def}

Si una herramienta hace E/S (llama a una API, lee un archivo, consulta una base de datos), declárala como `async def` y usa `await` dentro. El SDK se encarga de esperarla.

Una herramienta con `def` normal también funciona: el SDK la ejecuta en un hilo para que nunca bloquee el servidor.

No hay nada más que configurar.

## Nombres, títulos y anotaciones {#names-titles-and-annotations}

Todo lo que el SDK infiere, puedes sobrescribirlo en el decorador:

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` es un nombre legible para las interfaces de usuario. Los clientes muestran *"Search the catalog"* en lugar de `search_books`.
* `annotations` son **pistas** de comportamiento para el cliente:
  * `read_only_hint=True`: esta herramienta no cambia nada.
  * `open_world_hint=False`: trabaja sobre un conjunto cerrado de cosas (este catálogo), no sobre la web abierta.
  * Las otras dos, `destructive_hint` e `idempotent_hint`, describen una herramienta que *escribe*: ¿puede
    borrar algo?, ¿y llamarla dos veces equivale a llamarla una? La especificación define ambas
    solo para herramientas que no son de solo lectura, así que en `search_books` no dirían nada.

Un cliente bien hecho las usa para decidir cosas como *"¿tengo que preguntarle al usuario antes de ejecutar esto?"*. Son pistas, no seguridad. Nunca des por hecho que un cliente las respetará.

!!! tip
    `@mcp.tool()` también acepta `name=` y `description=` si no quieres derivarlos
    del nombre de la función y del docstring. La mayoría de las veces sí quieres.

## Resumen {#recap}

* `@mcp.tool()` sobre una función la convierte en herramienta. El nombre sale de la función, la descripción del docstring.
* Las anotaciones de tipo **son** el esquema de entrada. Los valores por defecto hacen opcionales los argumentos.
* `Annotated[..., Field(...)]` añade descripciones y restricciones; `Literal` añade enumeraciones.
* Un parámetro que es un modelo de Pydantic es la forma de recibir un "cuerpo" estructurado.
* Los argumentos incorrectos se rechazan por ti, con un error que el modelo puede leer y del que puede recuperarse.
* `async def` para E/S, `def` normal para todo lo demás.

**[Salida estructurada](structured-output.md)** es lo que le ocurre al valor que devuelves con `return`.
