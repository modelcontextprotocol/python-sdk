---
translation:
  sections: [7be05607887e6853, e7375894888d9750, c36f73fc7e3af13b, 2fec2d7e129e62fe, 809b0e0a7c27295a, b4395a04d2a5d906, 1a436007f5f54779, c6b2078ed1e63ba5]
  tool: 1
---
# Manejo de errores {#handling-errors}

Una herramienta puede fallar de tres maneras, y el SDK trata cada una de forma distinta.

Lanza `ToolError` y el **modelo** ve tu mensaje. Lanza `MCPError` y lo ve el **protocolo**. Lanza cualquier otra cosa y es un fallo inesperado: el modelo solo se entera de que la llamada falló, y el traceback va a tu log.

Esta página trata de cómo elegir.

## Un error que el modelo puede corregir {#an-error-the-model-can-fix}

Toma una herramienta que busca algo, y deja que la búsqueda falle:

```python title="server.py" hl_lines="2 12-13"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`ToolError`, de `mcp.server.mcpserver.exceptions`, es la forma en que una herramienta le dice al modelo que algo salió mal.

Llámala con un título que no esté en el catálogo y observa el resultado:

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* La solicitud **tuvo éxito**. Hay un resultado; no se lanzó nada del lado de quien llama.
* `is_error` es `True`, y tu mensaje (con el nombre de la herramienta como prefijo) está en `content`, justo donde lee el modelo.
* `structured_content` es `None`. Una llamada fallida no tiene valor devuelto que estructurar.

Esto es un **error de herramienta**, y casi siempre es lo que quieres.

El modelo es quien llama a tu herramienta. Él eligió los argumentos. Así que un error de herramienta es un turno de la conversación: el modelo lee *"No book titled 'Nothing' in the catalog."*, se da cuenta de que adivinó mal el título y vuelve a llamar con uno mejor. Escribiste un `raise` y obtuviste un agente que se corrige solo.

En el servidor, un `ToolError` es una sola línea `INFO` en el log, sin traceback. Lo veías venir, así que no hay nada que investigar.

!!! tip
    Nunca devuelvas con `return` un mensaje de error desde una herramienta. Una cadena devuelta
    tiene `is_error=False`, así que para el modelo (y para toda interfaz de cliente) parece que la
    herramienta funcionó y que esa cadena era la respuesta. Usa `raise`. El indicador es la señal.

## Un error que el modelo no puede corregir {#an-error-the-model-cannot-fix}

Ahora cambia `ToolError` por `MCPError`.

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` es el **error de protocolo** del SDK. Es la única excepción que el envoltorio de la herramienta *no* captura: se propaga, y toda la solicitud `tools/call` falla con un error JSON-RPC en lugar de un resultado.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **No hay resultado**. No hay `content` ni `is_error`: nada que el modelo pueda leer.
* En su lugar, el error lo recibe la aplicación **host**, igual que si la herramienta no existiera.
* `code`, `message` y `data` llegan intactos. `INVALID_PARAMS` es `-32602`; `mcp.types` lo exporta, junto con los demás códigos de error JSON-RPC (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...), como constantes para que nunca escribas un número mágico.

!!! check
    La misma búsqueda, el mismo fallo, pero ahora la llamada *lanza* una excepción del lado del cliente en lugar de devolver un resultado:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    La primera versión le entregaba al modelo una frase a la que podía reaccionar. Esta no le
    entrega nada. Para `get_author` eso es estrictamente peor, y de eso trata la siguiente sección.

## Cuál lanzar {#which-one-to-raise}

Los dos caminos responden a dos preguntas distintas.

* **Lanza `ToolError`** ante un fallo de *ejecución*: lo que tu herramienta intentó hacer no funcionó. El modelo eligió la llamada, así que el modelo debería ver la consecuencia y tener la oportunidad de recuperarse. Un título mal escrito, una API externa que agotó el tiempo de espera, una fila que no existe: todos son errores de herramienta.
* **Lanza `MCPError`** cuando debe rechazarse la *solicitud misma*: al cliente le falta una capacidad de la que depende tu herramienta, el servidor no está en condiciones de atender a nadie, quien llama se saltó un paso obligatorio. Ningún reintento del modelo arregla nada de eso, así que no se gana nada entregándole el mensaje.

Una sola pregunta lo decide: **¿podría haberlo evitado un modelo más inteligente?** Sí -> `ToolError`. No -> `MCPError`.

Según ese criterio, la segunda versión de `get_author` eligió mal: un título mejor lo arregla, así que el modelo merecía ver el mensaje. Está ahí para mostrarte el mecanismo, no para recomendarlo.

!!! info
    `MCPError` se importa con `from mcp import MCPError` y recibe `code`, `message` y un payload
    opcional `data`. Lo que pongas en ellos es lo que recibe el cliente: el SDK reenvía un
    `MCPError` lanzado tal cual, en lugar de sanearlo.

## Cualquier otra excepción {#any-other-exception}

Ahora quita la comprobación y deja que la búsqueda en el diccionario falle por sí sola:

```python title="server.py" hl_lines="11"
--8<-- "docs_src/handling_errors/tutorial004.py"
```

`CATALOG[title]` lanza `KeyError`. No lo tenías previsto, así que el SDK lo trata como un fallo inesperado:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool get_author")]
```

La llamada sigue devolviendo `is_error=True`, así que el modelo sabe que falló y puede seguir adelante. Lo que no recibe es el texto de la excepción: un `KeyError` de tu código, o un montón de SQL de un driver tres bibliotecas más abajo, puede describir el funcionamiento interno de tu servidor, así que nunca sale del servidor.

Lo recibes tú. El servidor registra el fallo inesperado en nivel `ERROR` con el traceback completo, como `Tool 'get_author' raised an unexpected exception`. Así, un log de producción en `WARNING` se mantiene en silencio ante cada `ToolError` y habla en cuanto algo está realmente roto.

## Un recurso que no existe {#a-resource-that-doesnt-exist}

Los recursos trazan la misma línea, e incluyen una excepción con nombre propio para el caso común.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` es una **plantilla**. Coincide con *cualquier* título, así que "la URI está bien formada" y "el libro existe" son dos preguntas distintas, y solo tu función puede responder la segunda.

Cuando no pueda, lanza `ResourceNotFoundError`. El SDK lo convierte en el error de protocolo que la especificación asigna a un recurso que falta: `-32602` con la URI solicitada en `data`, para que el cliente sepa *cuál* lectura falló.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

Fíjate en que aquí no hay un resultado a medias con `is_error=True`. La lectura de un recurso devuelve contenido o falla: los recursos solo tienen el camino del protocolo. `ResourceError` es lo mismo para un fallo que no es "no encontrado" (`-32603`, tu mensaje), y ambos son una sola línea `INFO` en tu log. Cualquier otra excepción salvo `MCPError` es un fallo inesperado: el cliente recibe un `-32603` que solo nombra la URI, y el traceback va a tu log en nivel `ERROR`. Las plantillas y todo lo demás sobre recursos están en **[Recursos](resources.md)**.

## Errores que nunca lanzas {#errors-you-never-raise}

Un argumento incorrecto nunca llega a tu función.

Envíale a `get_author` un `title` que no sea una cadena y el SDK lo rechaza contra el esquema de entrada **antes** de llamarte, como el mismo tipo de error de herramienta con `is_error=True` que el modelo puede leer y corregir. **[Herramientas](tools.md)** muestra el mismo rechazo con una restricción `Field(le=50)`.

Eso significa toda una clase de sentencias `raise` que no escribes: no vuelvas a validar tus propias anotaciones de tipo.

!!! info
    Todo lo que ve un **cliente** en esta página lo ve también el `Client` en memoria con el que
    escribirás pruebas. Ni siquiera `raise_exceptions=True` le devuelve a quien llama la excepción
    de una herramienta que falla: para cuando ese indicador podría actuar, tu excepción ya es el
    resultado con `is_error=True`. Haz las aserciones sobre el resultado. Si necesitas el traceback
    de un fallo inesperado, está en el log del servidor, y el `caplog` de pytest lo captura.
    **[Pruebas](../get-started/testing.md)** cubre el patrón.

## Resumen {#recap}

* Lanza **`ToolError`** en una herramienta -> la llamada devuelve `is_error=True` con tu mensaje en `content`. El modelo lo lee y puede reintentar.
* Lanza **`MCPError`** -> la llamada misma falla con un error JSON-RPC. El modelo no ve nada; el host se encarga. `code`, `message` y `data` sobreviven intactos.
* La pregunta decisiva: *¿podría haberlo evitado un modelo más inteligente?* Sí -> `ToolError`. No -> `MCPError`.
* Cualquier **otra excepción** es un fallo inesperado -> `is_error=True` con solo `Error executing tool <name>` para el modelo, y un registro `ERROR` con el traceback para ti.
* `ResourceNotFoundError` desde un handler de recurso -> el `-32602` del protocolo, con la URI en `data`.
* Los argumentos incorrectos se rechazan contra el esquema antes de que se ejecute tu función; para esos no usas `raise`.
* Importaciones: `from mcp import MCPError`, `from mcp.server.mcpserver.exceptions import ToolError, ResourceError, ResourceNotFoundError`, y las constantes de códigos de error de `mcp.types`.

Errores resueltos. Eso es todo lo que un servidor *expone*. Lo que cada handler puede leer, y hacer de vuelta hacia el cliente mientras se ejecuta, es la siguiente sección: **[Dentro de tu handler](../handlers/index.md)**.

El texto exacto de los errores del SDK que es más probable que encuentres, qué significa cada uno y la solución de un solo paso para cada uno están en **[Solución de problemas](../troubleshooting.md)**.
