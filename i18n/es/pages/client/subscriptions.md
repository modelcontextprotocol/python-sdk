---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# Suscripciones {#subscriptions}

El catálogo de un servidor no es fijo. Las herramientas aparecen en tiempo de ejecución y el contenido detrás de la URI de un recurso cambia. Un cliente se entera a través de `client.listen(...)`: una sola solicitud `subscriptions/listen` cuya respuesta *es* el flujo. Permanece abierta y transporta las notificaciones de cambio que el cliente pidió.

Esta página es el extremo del cliente: abrir el flujo, observarlo junto a tu flujo principal y manejar sus finales. Publicar cambios, filtrar y atender el método son la parte del servidor, que se cuenta en **[Suscripciones](../handlers/subscriptions.md)**, dentro de *Dentro de tu handler*. Los ejemplos de aquí hablan con el servidor del tablero de sprint que se construye allí.

## Observar el flujo {#watching-the-stream}

Una suscripción es un gestor de contexto. Al entrar se envía la solicitud, con tus argumentos nombrados como filtro de la suscripción, y se espera la confirmación del servidor, así que el flujo ya está activo cuando empieza el bloque.

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

La iteración produce cuatro eventos tipados: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged` y `ResourceUpdated(uri=...)`.

Un evento dice *qué* cambió, nunca *cómo*. Por eso `follow_board` llama a `read_resource` y a `list_tools`: el evento es una señal para volver a pedir los datos. Lee `event.uri` en lugar de suponer qué recurso se movió: un filtro puede nombrar varias URI, y un servidor puede informar de un cambio en un subrecurso de una de ellas.

Los eventos duplicados que esperan a ser consumidos se funden en uno, y al volver a pedir los datos obtienes igualmente el estado actual. Solo se funden los eventos idénticos: dos `ResourceUpdated` para URI distintas son dos eventos.

Dos propiedades más del objeto devuelto:

* `sub.honored` es el filtro que el servidor confirmó: un `SubscriptionFilter` con los campos que pasaste, que se leen como atributos (`sub.honored.prompts_list_changed`). `MCPServer` acepta todos los tipos que pides, así que te devuelve tu solicitud tal cual. Un servidor que admite menos tipos confirma menos, y un tipo aceptado puede no dispararse nunca. Un servidor también puede rechazar la solicitud entera en lugar de confirmarla (consulta [Decidir quién puede observar](../handlers/subscriptions.md#deciding-who-may-watch) en la página del servidor), lo que aparece como el error de la solicitud.
* `sub.subscription_id` es el id de la solicitud de escucha, el que va estampado en cada trama de este flujo. Puede haber varias suscripciones abiertas a la vez, cada una demultiplexada por su propio id.

## Observar sin bloquear {#watching-without-blocking}

`follow_board` se ejecuta hasta que el servidor cierra el flujo, lo que puede no ocurrir nunca, así que por sí solo se adueña de tu programa. Los clientes reales quieren el observador *junto* al flujo principal: un agente llama a herramientas mientras un observador mantiene al día una caché o una interfaz.

Abre primero la suscripción, luego inicia el observador y sigue con tu trabajo.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` importa `BOARD` y `read_board` del primer ejemplo, que este repositorio guarda como
    `tutorial003.py`. Si guardas los archivos renderizados uno junto al otro como `client.py` y `app.py`,
    escribe `from client import BOARD, read_board` en su lugar. El ejemplo `watch.py` de más abajo
    importa `read_board` de la misma manera.

El orden es la clave. No se reenvía nada, así que un evento publicado antes de que existiera tu flujo se pierde. Entrar en `client.listen(...)` espera la confirmación, así que cada cambio a partir de ese momento llega a tu observador, y la instantánea que tomas dentro del bloque no puede perderse ninguno.

Las solicitudes se ejecutan libremente junto a un flujo abierto, desde la tarea del observador o desde cualquier otra, en el mismo cliente. Como los eventos *duplicados* sin consumir se funden, un flujo principal ocupado puede producir una sola recarga en lugar de tres. Los eventos distintos no se funden: un filtro que nombra muchas URI encola un evento pendiente por URI.

Para dejar de observar, sal del bloque: no hay ninguna llamada `unsubscribe`. Cancelar la tarea propietaria del bloque lo hace por ti, y el SDK cancela la solicitud de escucha como espera el transporte: en Streamable HTTP, cerrando el flujo de esa solicitud. Un observador que se ejecuta durante toda la vida de tu app nunca vuelve por sí solo, así que cancélalo, o cancela el alcance de su grupo de tareas, al apagar.

## Los flujos terminan {#streams-end}

Un flujo termina de una de dos maneras, y ambas son flujo de control normal. Un cierre ordenado del servidor termina el `async for`; una caída abrupta lanza `SubscriptionLost`.

La diferencia es de diagnóstico, no de qué hacer después: el flujo ya no está, no se reenvió nada, y un observador al que todavía le importa vuelve a escuchar y vuelve a pedir los datos.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Los servidores cierran flujos de forma ordenada por sus propias razones, entre ellas deshacerse de un suscriptor cuyo atraso creció demasiado, así que un final limpio no es una señal para dejar de observar. Espera un poco antes de volver a escuchar.

`SubscriptionLost` también tiene una causa local. El cliente retiene como máximo 1024 eventos sin consumir, y un consumidor que se atrasa tanto pierde la suscripción en lugar de crecer sin límite. Mantén corto el cuerpo del `async for` y haz el trabajo lento en otro sitio.

`keep_following` captura solo `SubscriptionLost`. Entrar en `listen()` también puede lanzar `MCPError` (la conexión falló o el servidor no atiende el método), `TimeoutError` (no llegó ninguna confirmación) y `ListenNotSupportedError` (una conexión anterior a 2026). Decide cuáles de ellas debe reintentar tu observador: la última nunca se recupera.

## Resumen {#recap}

* Entra con `async with client.listen(...)`; al entrar se espera la confirmación, así que no se pierde nada publicado después.
* Itera con `async for event in sub`. Los eventos son señales para volver a pedir los datos, nunca cargas de datos.
* Abre la suscripción, luego ejecuta el observador como tarea, y las llamadas a herramientas siguen fluyendo junto a él.
* Un final limpio detiene el bucle; una caída lanza `SubscriptionLost`. En ambos casos: vuelve a escuchar, vuelve a pedir los datos y, antes, espera un poco.
* Salir del bloque es darse de baja.

Publicar estos eventos, acotar el filtro y escalar más allá de un proceso son la parte del servidor: **[Suscripciones](../handlers/subscriptions.md)**. Estos mismos eventos también mantienen fiable una caché del lado del cliente, y **[Caché](caching.md)** es la página siguiente.
