---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# Paginación {#pagination}

La mayoría de los servidores nunca necesitan esto.

`MCPServer` responde a cada solicitud `list_*` con todo lo que tiene, en una sola página, `next_cursor=None`. Para unas cuantas docenas de herramientas, recursos o prompts esa es la respuesta correcta y no hay nada que configurar.

La paginación es para el servidor cuya lista de recursos es en realidad una base de datos: miles de filas que se niega a serializar en una sola respuesta. La respuesta del protocolo es un **cursor**: el servidor devuelve una página más un token opaco, y el cliente envía ese token de vuelta para obtener la siguiente página.

`@mcp.resource()` no tiene ningún punto de extensión para nada de eso. Para paginar, escribes el handler de listado tú mismo, sobre el **[Server de bajo nivel](low-level-server.md)**.

## Un servidor que pagina {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* En un `Server` de bajo nivel, los handlers son argumentos del constructor, no decoradores. `on_list_resources` responde a cada solicitud `resources/list`; esa es toda la conexión necesaria.
* Todo handler paginado lleva el tipo `params: PaginatedRequestParams | None`, y el ejemplo acepta ambos. Sin embargo, a través de una conexión el SDK nunca te entrega `None` (una solicitud sin miembro `params` llega al handler como el modelo con sus valores por defecto), así que la señal que importa es `params.cursor is None`: **empieza desde el principio**.
* Tú decides qué *es* un cursor. Aquí es un desplazamiento representado como cadena. Una marca de tiempo, una clave primaria, un blob en base64: cualquier cosa que puedas generar de salida y reconocer cuando vuelva.
* `next_cursor=None` es la forma de decir "esa fue la última página". No hay recuento, ni total, ni `has_more`. `None` es toda la señal.

!!! tip
    Un `PAGE_SIZE` de 10 hace legible el ejemplo. Elige el tuyo por endpoint: una lista de
    recursos de una línea se puede permitir una página de 500; una lista de plantillas de prompt voluminosas, no.
    El cliente no tiene voz en ello, y así está diseñado.

### Pruébalo {#try-it}

`Client(server)` se conecta a un `Server` de bajo nivel en memoria exactamente igual que se conecta a un `MCPServer`.

Llama a `list_resources()` sin argumentos. Obtienes diez recursos, de `book-1` a `book-10`, y `next_cursor` es la cadena `"10"`.

Devuélvelo con `list_resources(cursor="10")` y el primer recurso es `book-11`; el nuevo `next_cursor` es `"20"`.

La décima página vuelve con `next_cursor` en `None`. Listo.

## El bucle del cliente {#the-client-loop}

Cada método `list_*` de `Client` (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) acepta el argumento nombrado `cursor=`. Vaciar una lista paginada es un solo `while True`:

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` empieza como `None`, así que la primera solicitud no lleva cursor.
* Extiende **antes** de mirar `next_cursor`: la última página también tiene recursos.
* `next_cursor is None` es la salida. Cualquier otra cosa vuelve directamente a `cursor=`, sin tocarla.

Ejecuta su `main()` e imprime `100 resources`: diez páginas de diez, unidas por un bucle que nunca supo que había diez páginas.

Es el mismo bucle que **[El cliente](../client/index.md)** muestra para cada verbo `list_*`, y no cuesta nada frente a un servidor que no pagina: `next_cursor` es `None` en la primera respuesta y el bucle se ejecuta una vez.

## Las tres reglas {#the-three-rules}

**Los cursores son opacos.** Un cliente nunca debe analizar, construir ni adivinar uno. La única fuente legítima de un cursor es el `next_cursor` de la página anterior, tal cual.

**El servidor elige el tamaño de página.** No hay `limit=` en el protocolo. Si necesitas un tamaño de página distinto, cambias el servidor.

**Un cliente que ignora la paginación sigue funcionando.** Llama a `list_resources()` una vez, obtiene los diez primeros y nunca se entera del `next_cursor` que descartó. Nada se rompe; simplemente ve menos.

!!! check
    Opaco significa opaco. Inventa un cursor (`list_resources(cursor="page-2")`) y no hay
    nada que el protocolo pueda hacer por ti. Este servidor intenta `int("page-2")`, el handler lanza una excepción,
    y lo que le vuelve al cliente es:

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    Un cursor que no obtuviste del servidor es un bug, no una petición de funcionalidad.

## Resumen {#recap}

* `MCPServer` devuelve todo en una página. La paginación es opcional, y la activas en el `Server` de bajo nivel.
* `on_list_resources` (y `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) recibe `PaginatedRequestParams | None`; `params.cursor` es `None` para la primera página.
* Devuelves una página más `next_cursor`: cualquier cadena que reconozcas después, o `None` cuando no queda nada.
* El bucle del cliente: pasa `cursor=`, acumula, repite hasta que `next_cursor is None`.
* Los cursores son opacos, el servidor es dueño del tamaño de página y un cliente que no pagina sigue recibiendo la primera página.

El resto de la API del `Server` escrito a mano (`on_call_tool`, diccionarios `input_schema`, `_meta`) está en **[El Server de bajo nivel](low-level-server.md)**.
