---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# Parámetros de encabezado {#header-parameters}

La mayoría de los servidores nunca necesita esto.

Un gateway o un balanceador de carga delante del servidor solo puede enrutar según lo que puede leer sin analizar el cuerpo. Marca un argumento de una herramienta con `x-mcp-header` y los clientes de la **[versión del protocolo](../protocol-versions.md)** `2026-07-28` envían su valor también como encabezado HTTP.

## Marcar un argumento {#mark-an-argument}

La marca es una clave adicional en el JSON Schema del argumento. En `MCPServer`, `Field` la pone ahí:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* Con Streamable HTTP en `2026-07-28`, el cliente envía `Mcp-Param-Region` junto con el cuerpo, y el servidor rechaza una llamada en la que los dos no coinciden.
* Un cliente que no ha listado la herramienta nunca ha visto la marca: no envía ningún encabezado y la llamada se rechaza. El `Client` de este SDK lista entonces las herramientas y reenvía la llamada una vez, así que listar primero solo ahorra una ida y vuelta.
* Cualquier otra conexión ignora la anotación.

Tu función no cambia: `region` sigue llegando como argumento.

## Qué se puede marcar {#what-can-be-marked}

Los argumentos `str`, `int` y `bool`. Cualquier otra cosa se rechaza al registrar la herramienta, con `InvalidSignature`.

Eso incluye `str | None`, que no tiene un tipo único. Un argumento opcional necesita su esquema escrito de forma explícita, con `WithJsonSchema` de Pydantic:

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## En el `Server` de bajo nivel {#on-the-low-level-server}

Ahí escribes `input_schema` a mano, así que la clave va directamente dentro:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* Nada verifica la anotación por ti: una no válida se sirve tal cual, y los clientes `2026-07-28` dejan la herramienta fuera de su listado.

### Esquemas por nombre {#schemas-by-name}

Para verificar el encabezado, el SDK necesita el esquema de entrada de la herramienta antes de despachar la llamada. Sin `get_tool_input_schema`, lo obtiene ejecutando tu handler `on_list_tools` en cada llamada que lleva argumentos, haya o no alguna herramienta marcada.

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* Pasa la función para responder a partir de lo que ya tienes.
* Devuelve `None` para una herramienta que no tiene nada que verificar.

## Resumen {#recap}

* `x-mcp-header` en un argumento de una herramienta hace que los clientes `2026-07-28` lo repitan como encabezado HTTP `Mcp-Param-*`.
* El servidor rechaza una llamada cuyo encabezado y cuerpo no coinciden.
* Solo se pueden marcar argumentos `str`, `int` y `bool`. `MCPServer` lanza `InvalidSignature` para cualquier otra cosa.
* El `Server` de bajo nivel no verifica nada, y los clientes descartan una herramienta cuya anotación no es válida.
* `get_tool_input_schema` evita que el `Server` de bajo nivel ejecute `on_list_tools` en cada llamada.

El resto de la API escrita a mano de `Server` está en **[El Server de bajo nivel](low-level-server.md)**.
