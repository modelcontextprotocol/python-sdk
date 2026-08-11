---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# Elicitación {#elicitation}

Una herramienta que va por la mitad de su trabajo y a la que le falta una respuesta no tiene por qué fallar.

La **elicitación** (elicitation) le permite preguntar. En medio de una llamada a la herramienta, el usuario recibe una pregunta y su respuesta vuelve a la misma llamada de función.

Hay dos modos:

* **Modo formulario**: necesitas un valor (una confirmación, una fecha, una cantidad). Describes los campos y el cliente muestra el formulario.
* **Modo URL**: necesitas que el usuario vaya a otro sitio (una pantalla de consentimiento OAuth, una página de pago). Nada de lo que haga allí pasa por el protocolo.

Y hay dos formas de preguntar. La que conviene usar es un **resolutor**: cuelgas la pregunta de un parámetro y el SDK pregunta, en cualquier conexión, sea cual sea la generación del protocolo que hable el cliente. La forma directa, `await ctx.elicit(...)`, es una solicitud del *servidor* al *cliente*, un canal que solo existe para un cliente en una conexión heredada (versión de la especificación 2025-11-25 o anterior). Ambas están en esta página; empieza por el resolutor.

## Preguntar con un resolutor {#ask-with-a-resolver}

Una pregunta que condiciona toda la herramienta (*¿estás seguro?, ¿cuál de las tres cuentas que coinciden?*) puede sacarse del cuerpo de la herramienta a un **resolutor**, y el framework la hace por ti.

Un parámetro anotado como `Annotated[T, Resolve(fn)]` se rellena ejecutando `fn` antes del cuerpo de la herramienta. El resolutor devuelve el valor directamente cuando ya lo conoce, o devuelve `Elicit(...)` para que el framework pregunte:

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` lee por nombre el propio argumento `path` de la herramienta, lista la carpeta y **solo pregunta cuando debe**: una carpeta vacía se resuelve a `Confirm(ok=True)` sin ninguna ida y vuelta al cliente.
* `delete_folder` anota `ElicitationResult[Confirm]`, así que el framework inyecta el resultado completo y la herramienta usa `match` para cubrir cada caso: aceptar y confirmar, aceptar pero conservar (`ok=False`), rechazar, cancelar.
* El parámetro `confirm` nunca aparece en el esquema de entrada de la herramienta: el cliente aporta `path`, el resolutor aporta `confirm`.

Anota en su lugar el modelo sin envolver (`Annotated[Confirm, Resolve(confirm_delete)]`) cuando la herramienta no necesita bifurcar: recibe el modelo si el usuario acepta y la llamada se interrumpe con un error si rechaza o cancela.

Un resolutor funciona en **todas** las conexiones. A un cliente en una conexión heredada, el SDK le envía la pregunta directamente; en una conexión **2026-07-28**, el SDK *devuelve* la pregunta desde la llamada y el siguiente intento del cliente lleva la respuesta. Tu resolutor nunca nota la diferencia; lo que ocurre por debajo está en **[Solicitudes de varias idas y vueltas](multi-round-trip.md)** (multi-round-trip).

Preguntar es solo una de las cosas que puede hacer un resolutor. El mecanismo general (dependencias que calculan sin preguntar, dependencias de dependencias, qué puede aportar el modelo y qué no) está en la página **[Dependencias](dependencies.md)**.

## Preguntar desde dentro de la herramienta {#ask-from-inside-the-tool}

Una herramienta también puede detenerse en medio de su propio cuerpo y preguntar.

!!! warning
    `ctx.elicit()` y `ctx.elicit_url()` son solicitudes del *servidor* al *cliente*: un
    canal que solo existe para un cliente en una conexión heredada (versión de la especificación
    **2025-11-25** o anterior). En una conexión **2026-07-28** no hay solicitudes iniciadas por el
    servidor, así que estas llamadas fallan. Un resolutor funciona en ambas.
    **[Versiones del protocolo](../protocol-versions.md)** tiene todos los detalles.

`await ctx.elicit()` recibe un mensaje y un modelo de Pydantic:

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* El parámetro **`Context`** es lo que te da `ctx.elicit`; cualquier herramienta puede recibir uno. Ese objeto tiene su propia página: **[El Context](context.md)**.
* `AlternativeDate` es el **esquema** de la respuesta que quieres.
* La herramienta es `async def`. Tiene que serlo: se detiene a mitad y espera a una persona.
* En cualquier otra fecha la herramienta devuelve enseguida. Solo pregunta cuando tiene que hacerlo.
* La fecha que acepta el usuario vuelve a pasar por el propio `book_table`. Una respuesta es una entrada como cualquier otra: una alternativa que también está completa provoca una nueva pregunta, no se confirma a ciegas.

### Qué recibe el cliente {#what-the-client-receives}

El cliente recibe tu mensaje y, junto a él, un JSON Schema generado a partir del modelo:

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

Ese esquema es el formulario. `Field(description=...)` es la etiqueta; un valor por defecto rellena el campo de antemano y lo hace opcional. Es la misma maquinaria de Pydantic a JSON Schema que **[Herramientas](../servers/tools.md)** describe para los argumentos de una herramienta.

!!! warning
    Un esquema de elicitación no es tan expresivo como el esquema de entrada de una herramienta.
    Solo campos planos y primitivos: `str`, `int`, `float`, `bool` o un `Literal` de cadenas (se
    convierte en un `enum`). Pon un modelo dentro del modelo y `ctx.elicit` lanza una excepción
    antes de que se envíe nada al cliente:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    Estás interrumpiendo a una persona en plena tarea. Si la respuesta necesita anidamiento,
    debería haber sido un argumento de la herramienta.

### Las tres respuestas {#the-three-answers}

`result.action` te dice qué hizo el usuario, y hay exactamente tres posibilidades:

* `"accept"`: envió el formulario. `result.data` es una instancia de `AlternativeDate`, ya validada.
* `"decline"`: dijo que no.
* `"cancel"`: descartó la pregunta sin elegir.

`result.data` solo existe con `"accept"`, y por eso el ejemplo comprueba primero `result.action`. Tu verificador de tipos impone el orden: después de `result.action == "accept"`, `result.data` es un `AlternativeDate`; antes, no hay ningún `.data`.

Una negativa no es un error. La herramienta decide qué significa rechazar (aquí, no hay reserva) y responde al modelo con normalidad.

!!! tip
    La respuesta se valida contra tu modelo antes de que tu código la vea. Un cliente que envía
    `"maybe"` para un `bool` no corrompe tu reserva: la llamada falla con un error de
    discrepancia de esquema y tu `if` nunca se ejecuta.

## Enviar al usuario a una URL {#send-the-user-to-a-url}

Algunas cosas no deben pasar por el modelo ni por el cliente: credenciales, números de tarjeta, consentimiento OAuth. Para esas no pides datos; pides al usuario que vaya a algún sitio:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` recibe el mensaje, la **URL** que hay que visitar y un `elicitation_id` que eliges tú: cualquier cadena que identifique esta elicitación dentro de tu servidor.
* El resultado tiene una acción y nada más. `"accept"` significa que el usuario aceptó abrir la URL, **no** que haya terminado lo que hay al otro lado.
* El pago ocurre fuera de banda, entre el navegador del usuario y tu proveedor de pagos. Ningún contenido vuelve nunca a través de MCP.

Fíjate en la segunda herramienta. Cuando el servidor se entera de que el flujo fuera de banda terminó (un webhook, un sondeo; aquí se modela como una segunda herramienta), `ctx.session.send_elicit_complete(...)` envía `notifications/elicitation/complete` con el mismo `elicitation_id`. Así es como el cliente sabe que puede dejar de mostrar *"waiting for payment..."*. Sin eso, el cliente solo puede adivinar.

## El lado del cliente {#the-client-side}

Los servidores preguntan. Los clientes responden pasando un **`elicitation_callback`** a `Client(...)`:

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* Un solo callback maneja ambos modos. `params` es una unión de `ElicitRequestFormParams` y `ElicitRequestURLParams`; `isinstance` es la bifurcación.
* Para una URL, muestras `params.url` al usuario y devuelves la acción que eligió. Nunca ningún `content`.
* Para un formulario, una aplicación real muestra `params.requested_schema` y devuelve la entrada del usuario como `content`. Este siempre dice que sí con una respuesta predefinida, que es justo el callback que quieres en una prueba.
* Pasar el callback es también la **declaración de capacidad**: es como el servidor se entera de que a este cliente se le puede preguntar. Las demás cosas que un cliente puede responder a un servidor están en **[Callbacks del cliente](../client/callbacks.md)**.

!!! info
    La elicitación es una solicitud del *servidor* al *cliente*, y esas solo existen en una
    sesión con handshake clásico, por eso este cliente pasa `mode="legacy"`.
    En una conexión **2026-07-28**, una herramienta pregunta *devolviendo* la pregunta desde la
    llamada; ese flujo está en **[Solicitudes de varias idas y vueltas](multi-round-trip.md)**.

### Pruébalo {#try-it}

Arranca el `server.py` del modo formulario con `ctx.elicit` (el de `book_table`) sobre Streamable HTTP (**[Ejecutar tu servidor](../run/index.md)** tiene el comando de una línea), luego ejecuta el `main()` del cliente y pide a `book_table` el día de Navidad.

El callback imprime la pregunta que recibió:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

Responde con `{"accept_alternative": True, "date": "2025-12-27"}`, y la herramienta, que ha estado esperando dentro de `await ctx.elicit(...)` todo este tiempo, termina la reserva:

```text
Booked a table for 2 on 2025-12-27.
```

Ahora cambia al `server.py` del modo URL y apunta el mismo `main()` a `pay_deposit`: el mismo callback toma la otra rama, imprime el enlace de pago y la herramienta vuelve con *"Complete the payment in your browser."* Una ida y vuelta, en mitad de la llamada, en ambos sentidos.

!!! check
    Ahora quita `elicitation_callback=` del `Client` y vuelve a llamar a `book_table` para el día
    de Navidad. Toda la llamada falla con un error de protocolo:

    ```text
    Elicitation not supported
    ```

    Un cliente que no registró ningún callback nunca declaró la capacidad `elicitation`, así que
    no hay nadie a quien preguntar. Tu herramienta no recibió un `"decline"`; recibió una
    excepción. Diseña para ello: toda elicitación necesita una respuesta sensata a "¿y si no
    puedo preguntar?".

## Resumen {#recap}

* Un parámetro anotado como `Annotated[T, Resolve(fn)]` lo rellena un resolutor, que devuelve `Elicit(...)` cuando tiene que preguntar. Funciona en todas las conexiones.
* El esquema es un modelo plano de Pydantic: solo campos primitivos, validados al volver.
* `result.action` es `"accept"`, `"decline"` o `"cancel"`; `result.data` solo existe en accept.
* `await ctx.elicit(message, schema=Model)` pregunta desde dentro del cuerpo de la herramienta, y `await ctx.elicit_url(message, url, elicitation_id)` es para todo lo que no debe pasar por el modelo (`ctx.session.send_elicit_complete(elicitation_id)` indica que la parte fuera de banda terminó). Ambas son solicitudes del servidor al cliente: necesitan al cliente en una conexión heredada.
* El cliente responde con un solo `elicitation_callback`, bifurcando según el tipo de params; registrarlo es lo que declara la capacidad.
* En una conexión 2026-07-28 el servidor devuelve la pregunta en lugar de enviarla; el mismo callback se alimenta desde **[Solicitudes de varias idas y vueltas](multi-round-trip.md)**.

Todo lo que hay debajo de ese retorno (el bucle de reintentos, proteger `requestState`, manejarlo tú mismo) está en **[Solicitudes de varias idas y vueltas](multi-round-trip.md)**.
