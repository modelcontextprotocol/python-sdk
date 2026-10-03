---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# Recursos {#resources}

Un **recurso** es un dato que expones para que la aplicación lo lea.

Esa es la diferencia. Una herramienta es algo que el **modelo** decide llamar. Un recurso es algo que la **aplicación** decide cargar (un archivo de configuración, un registro, un documento) y poner delante del modelo como contexto.

Declaras uno poniendo `@mcp.resource(uri)` sobre una función normal de Python.

## Tu primer recurso {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

Tiene la misma forma que una herramienta, con un añadido: el **URI**. A los recursos se accede por dirección, no por nombre. Un cliente pide `config://app`, nunca `get_config`.

El SDK sigue leyendo el resto de la función:

* El **nombre** es el nombre de la función: `get_config`.
* La **descripción** que ve el cliente es el docstring.
* El **contenido** es lo que devuelvas.

Durante `resources/list` el cliente recibe esto:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

Y cuando lee `config://app`, tu función se ejecuta y el valor devuelto regresa como texto:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    Listar es barato. Tu función **no** se llama durante `resources/list`, solo durante
    `resources/read`, y solo para el URI que se pidió. Expón mil recursos
    y pagas por los que alguien abre.

### Pruébalo {#try-it}

Ejecuta el servidor con el MCP Inspector:

```console
uv run mcp dev server.py
```

Abre la URL que imprime y ve a la pestaña **Resources**. `config://app` está en la lista con su descripción. Haz clic en él y el Inspector lo lee: ahí están tus dos líneas de configuración.

## Plantillas de recurso {#resource-templates}

Un URI por registro no escala. Pon un **marcador de posición** en el URI y un parámetro correspondiente en la función:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

`{user_id}` en el URI, `user_id: str` en la función. Ese es todo el contrato.

Ahora es una **plantilla de recurso**, y se muda: sale de `resources/list` y aparece en `resources/templates/list`, como un patrón en lugar de una dirección:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

El cliente rellena el marcador de posición y lee un URI concreto: `users://42/profile`, `users://ada/profile`. Una sola función responde a todos, con el valor coincidente pasado como `user_id`:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

Fíjate en el `uri` del resultado. Es el URI **concreto** que pidió el cliente, no la plantilla.

!!! check
    Los marcadores de posición y los parámetros tienen que coincidir. Renombra el parámetro de la función a
    `user` mientras el URI sigue diciendo `{user_id}` y el decorador lo rechaza **en tiempo de importación**,
    antes de que ningún cliente se acerque:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    Una discrepancia así solo puede ser un bug, así que el SDK hace imposible arrancar el servidor con una.

La sintaxis de los marcadores de posición es [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570): `{+path}` para valores de varios segmentos, `{?q,lang}` para parámetros de consulta opcionales, y más. Por defecto, el SDK también aplica comprobaciones de seguridad de rutas a los valores extraídos. Consulta **[Plantillas de URI y seguridad de rutas](uri-templates.md)** para la referencia completa.

`get_user_profile` también puede recibir un parámetro anotado como `Context`. El SDK lo inyecta sin tratarlo nunca como un parámetro del URI, y la página **[El Context](../handlers/context.md)** explica lo que te ofrece.

## Lo que devuelves {#what-you-return}

No estás limitado a `str`. Dale a cada recurso un `mime_type` y devuelve lo que encaje:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` devuelve un `str`, así que se envía tal cual. Es el caso habitual.
* `catalog_stats` devuelve un `dict`, así que el SDK lo serializa a **texto JSON** por ti:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` devuelve `bytes`, así que el cliente recibe un `BlobResourceContents` en lugar de un `TextResourceContents`, con tus bytes codificados en base64 en su campo `blob`.

La misma regla vale para cualquier otra cosa serializable a JSON: una lista, un modelo de Pydantic, una dataclass. Si no es `str` ni `bytes`, se convierte en JSON.

El `mime_type` lo declaras tú, y es `text/plain` por defecto. El SDK nunca inspecciona lo que devuelves para adivinarlo, así que un recurso `dict` sin etiquetar se sigue anunciando como texto plano.

!!! tip
    `@mcp.resource()` también acepta `name=`, `title=` y `description=` cuando no quieres
    derivarlos de la función. Y cuando no hay ninguna función que escribir,
    `mcp.server.mcpserver.resources` tiene clases `Resource` listas para usar (`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`) que registras
    con `mcp.add_resource(...)`.

Un cliente también puede **suscribirse** a un recurso y recibir una notificación cuando cambie; esa es la mitad de la historia que le toca al cliente y vive en **[El cliente](../client/index.md)**.

## Resumen {#recap}

* `@mcp.resource(uri)` sobre una función la convierte en un recurso. El URI es la dirección, el valor devuelto es el contenido, el docstring es la descripción.
* Un `{placeholder}` en el URI la convierte en una **plantilla**: se lista en `resources/templates/list` y una sola función sirve todos los URI que coinciden.
* Los nombres de los marcadores de posición deben ser iguales a los nombres de los parámetros de la función. Equivócate y lo descubres en tiempo de importación, no en producción.
* Tu función se ejecuta cuando el recurso se **lee**, no cuando se lista.
* `str` se convierte en texto, `bytes` en un blob en base64, cualquier otra cosa en texto JSON. Con `mime_type=` lo etiquetas.
* Las herramientas son para que el modelo actúe. Los recursos son para que la aplicación lea.

La tercera primitiva, la que una persona elige de un menú, son los **[Prompts](prompts.md)**.
