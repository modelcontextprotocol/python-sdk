---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# Dependencias {#dependencies}

Los argumentos de una herramienta vienen del modelo. Algunos valores nunca deberían: un precio consultado en tus registros, una confirmación que solo una persona puede dar, cualquier cosa que el modelo podría estropear inventándosela.

Las **dependencias** son parámetros que rellenan tus propias funciones. Anotas el parámetro, nombras la función, y el SDK la llama antes de que se ejecute tu herramienta.

## Declara una {#declare-one}

Envuelve el tipo del parámetro en `Annotated[...]` y añade `Resolve(fn)`:

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` es un **resolutor**: una función normal que el SDK ejecuta antes de `reserve_book`, y cuyo valor devuelto se convierte en el argumento `stock`.
* Su parámetro `title` es el propio argumento `title` de la herramienta, emparejado **por nombre**. El resolutor ve exactamente el valor validado que verá el cuerpo de la herramienta.
* El cuerpo de la herramienta parte de un `Stock` que ya existe. Nada de código de consulta en la herramienta, nada de preámbulo del tipo "y si falta".

!!! info
    Si has usado FastAPI, esto es `Depends`. El mismo mecanismo, por la misma razón: la función declara lo
    que necesita, el framework lo proporciona, y el cableado vive en la anotación de tipo.

### Invisible para el modelo {#invisible-to-the-model}

Este es el esquema de entrada que `tools/list` reporta para `reserve_book`:

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

Una sola propiedad. Igual que el `Context` en **[El Context](context.md)**, un parámetro resuelto es un contrato entre tú y el SDK: `stock` no está en el esquema, al modelo nunca se le habla de él, y a un cliente que envíe un valor `stock` de todos modos se le ignora. El valor del resolutor es el único que puede recibir tu herramienta.

Esa última parte es la clave. Un parámetro que el modelo no puede proporcionar es un parámetro que el modelo no puede estropear.

### Pruébalo {#try-it}

Ejecuta el servidor con el MCP Inspector:

```console
uv run mcp dev server.py
```

El formulario de `reserve_book` tiene un único campo `title`. `stock` no aparece por ningún lado. Llámala con `Dune`:

```text
Reserved 'Dune' (6 copies left).
```

El cuerpo de la herramienta nunca consultó nada: `check_stock` se ejecutó primero, y el `Stock` que devolvió llegó como argumento. Prueba con `Neuromancer` y el mismo resolutor le entrega un cero a la herramienta.

!!! tip
    Podrías simplemente llamar a `check_stock(title)` en el cuerpo de la herramienta. Decláralo como
    dependencia cuando el valor merezca más que una llamada a una función auxiliar: todas las herramientas
    que necesitan el stock declaran el mismo parámetro, y el SDK ejecuta el resolutor como mucho una vez por
    llamada, sin importar cuántas lo declaren. Las siguientes secciones añaden el resto: resolutores que
    dependen unos de otros, y resolutores que preguntan al usuario.

## Dependencias de dependencias {#dependencies-of-dependencies}

Un resolutor puede declarar sus propias dependencias, con la misma anotación:

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` depende de `check_stock`. El SDK ejecuta el grafo en orden: primero el stock, luego la estimación, luego la herramienta.
* Tanto `stock` como `delivery` necesitan `check_stock` en última instancia, pero se ejecuta **una vez por llamada**. Una consulta de inventario, dos consumidores.
* No hay nada que registrar. El grafo *son* las anotaciones.

!!! check
    No te creas lo de una vez por llamada sin comprobarlo. Pon un `print` en `check_stock` y llama a
    `order_book` desde el Inspector: una línea por llamada. Dos consumidores, una consulta.

El SDK analiza el grafo cuando se registra la herramienta, no cuando se llama. Un parámetro que no puede clasificar (ni un `Context`, ni un `Resolve(...)`, ni el nombre de un argumento de la herramienta) y un ciclo de resolutores lanzan ambos `InvalidSignature` al arrancar. El servidor falla antes de que ningún cliente se conecte, con el parámetro o resolutor problemático nombrado en el error.

Los parámetros de un resolutor se resuelven exactamente igual que los de una herramienta: otro `Resolve(...)`, los argumentos de la propia herramienta por nombre, o el `Context`: `ctx.headers`, el objeto del lifespan, todo.

!!! warning
    En los transportes HTTP el `Context` incluye `ctx.headers`. Las cabeceras son **entrada proporcionada
    por el cliente**, como cualquier argumento de herramienta: bien para una configuración regional o un
    feature flag, nunca para una identidad. Quién es el que llama viene de tu capa de autorización
    (**[Autorización](../run/authorization.md)**), no de una cabecera que cualquiera puede establecer.

!!! tip
    *Una vez por llamada* significa exactamente eso: el siguiente `tools/call` ejecuta `check_stock` otra
    vez. Un recurso que debe sobrevivir a una solicitud (un pool de base de datos, un cliente HTTP)
    pertenece al **[Lifespan](lifespan.md)**, y un resolutor puede llegar a él a través de
    `ctx.request_context.lifespan_context`.

## Pregunta cuando debas {#ask-when-you-must}

Un resolutor no tiene por qué saber la respuesta. Puede devolver `Elicit(message, Model)` y el SDK pregunta al usuario: la maquinaria de **[Elicitación](elicitation.md)** (elicitation), ejecutada por ti:

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* Con stock: `confirm_backorder` devuelve un `Backorder` directamente. **Sin pregunta, sin ida y vuelta.** Solo se interrumpe al usuario cuando su respuesta importa.
* Sin stock: el SDK envía la elicitación, valida la respuesta contra `Backorder` y la inyecta. Tu resolutor nunca toca el protocolo.
* La herramienta lee `backorder.confirm` como cualquier otro argumento. Responder **no** sigue siendo una respuesta: la elicitación se acepta con `confirm=False`, la herramienta se ejecuta y no se hace ningún pedido. Preguntar se convirtió en una precondición, no en fontanería dentro del cuerpo de la herramienta.

¿Y si el usuario no responde en absoluto, si rechaza la pregunta o la cancela?

!!! check
    Ejecuta `order_book` para `Neuromancer` y rechaza la pregunta. Con la anotación escrita como
    `Annotated[Backorder, Resolve(...)]` el cuerpo de la herramienta nunca se ejecuta; la llamada falla con
    un resultado de error que el modelo puede leer:

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

Ese es el valor por defecto correcto para una precondición: sin respuesta, no hay pedido. Cuando rechazar es un resultado que tu herramienta quiere manejar (omitir el pedido pendiente pero aun así sugerir otro título), anota `ElicitationResult[Backorder]` en su lugar y la herramienta recibe el resultado completo de aceptar/rechazar/cancelar para bifurcar según él. **[Elicitación](elicitation.md)** muestra esa forma, y todo lo demás sobre preguntar: las reglas del esquema, las tres respuestas, el lado del cliente en la conversación.

!!! info
    El framework elige el transporte de la pregunta a partir de la versión del protocolo negociada; el
    código de arriba es idéntico en ambas. En **2026-07-28** y posteriores la pregunta viaja dentro de un
    `tools/call` de varias idas y vueltas (multi-round-trip): el servidor la devuelve, el
    `elicitation_callback` del cliente la responde, y el `Client` reintenta la llamada por ti
    (**[Solicitudes de varias idas y vueltas](multi-round-trip.md)**). En **2025-11-25** y anteriores es
    una solicitud de elicitación síncrona a mitad de llamada. Cada pregunta se hace exactamente una vez por
    llamada: una garantía sobre la pregunta, no sobre el resolutor. En la forma de varias idas y vueltas
    cualquier resolutor puede volver a ejecutarse cada vez que la llamada se reanuda tras una pregunta, así
    que el código anterior a un `return Elicit(...)` se ejecuta en cada una de esas rondas; la respuesta
    registrada satisface entonces la pregunta repetida sin volver a preguntar al usuario. Una respuesta
    registrada solo se consulta cuando el resolutor pregunta; un resolutor que responde *sin* preguntar,
    como `check_stock`, siempre proporciona su propio valor calculado. Como cada respuesta se empareja con
    su pregunta, un resolutor que elicita debe derivar su pregunta de forma determinista a partir de los
    argumentos de la herramienta y las respuestas anteriores. Un valor generado por llamada (un id de
    `default_factory`, una marca de tiempo) se vuelve a derivar en cada ronda y no debe aparecer en una
    pregunta a la que la respuesta deba quedar vinculada. Una pregunta construida con datos tan volátiles
    hace que toda respuesta registrada parezca obsoleta, así que el servidor la vuelve a hacer en cada
    ronda hasta que el límite de rondas del cliente termina la llamada.

## Pregunta al cliente, no al usuario {#ask-the-client-not-the-user}

La elicitación es una de las tres preguntas que puede hacer un resolutor, y el flujo de varias idas y vueltas no permite otras. Las otras dos van al **cliente** en lugar de al usuario: devuelve `Sample(...)` para ejecutar una llamada a un LLM a través del cliente (una solicitud `sampling/createMessage`), o `ListRoots()` para obtener los roots actuales del cliente. Ninguna tiene un resultado de aceptar/rechazar; el consumidor anota el tipo de resultado directamente, `CreateMessageResult` (`CreateMessageResultWithTools` cuando la solicitud lleva `tools` o `tool_choice`) o `ListRootsResult`:

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* El framework las enruta exactamente igual que `Elicit`: dentro del `tools/call` de varias idas y vueltas en **2026-07-28**, sobre la solicitud independiente servidor->cliente en **2025-11-25**. Una capacidad no declarada rechaza la llamada con un error de protocolo `-32021` (`sampling`, `roots`, `elicitation` en modo formulario; `sampling.tools` cuando la solicitud lleva `tools` o `tool_choice`).
* Todo lo que dice el recuadro informativo de arriba sobre las preguntas se aplica sin cambios: una solicitud `Sample` se empareja con su resultado registrado por su representación exacta, así que constrúyela de forma determinista a partir de los argumentos de la herramienta y las respuestas anteriores; el cliente paga entonces la llamada al LLM una vez por llamada a la herramienta, no una vez por ronda. El resultado registrado viaja en `request_state` durante el resto de la llamada, así que una respuesta del modelo muy grande hace más pesada cada ida y vuelta restante.
* Las *funcionalidades* independientes de muestreo (sampling) y roots quedan obsoletas en 2026-07-28 (SEP-2577). Los servidores nuevos que necesitan el modelo del cliente preguntan a través de este mecanismo; los que no, deberían integrarse directamente con un proveedor de LLM. Los valores de `include_context` distintos de `"none"` están ellos mismos obsoletos; evítalos.

## Resumen {#recap}

* `Annotated[T, Resolve(fn)]` en un parámetro de herramienta: el SDK ejecuta `fn` e inyecta su valor devuelto.
* Un parámetro resuelto es invisible para el modelo y un cliente no puede proporcionarlo. Los valores que el modelo no debe inventar (precios, identidades, permisos) van aquí.
* Los parámetros de un resolutor se resuelven del mismo modo: el `Context`, otro `Resolve(...)`, o un argumento de la herramienta por nombre. El grafo ejecuta cada resolutor como mucho una vez por ronda, tenga los consumidores que tenga; cada pregunta se hace exactamente una vez, y cualquier resolutor puede volver a ejecutarse cuando una llamada se reanuda tras una pregunta.
* Los grafos incorrectos fallan en el registro con `InvalidSignature`, no a mitad de llamada.
* Devuelve `Elicit(message, Model)` para preguntar al usuario, solo cuando tengas que hacerlo. Las anotaciones sin envolver abortan al rechazar; `ElicitationResult[T]` permite a la herramienta bifurcar.
* Devuelve `Sample(...)` o `ListRoots()` para pedir al cliente una respuesta del modelo o la lista de roots; se inyecta el resultado sin más.

El estado que tu servidor construye una vez al arrancar, y cómo llega a él un handler, es la página de **[Lifespan](lifespan.md)**.
