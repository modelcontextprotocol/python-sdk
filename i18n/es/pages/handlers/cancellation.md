---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# Cancelación {#cancellation}

Un cliente puede abandonar una llamada: el usuario pulsó detener o se agotó un timeout.

Cuando lo hace, el SDK **cancela tu handler**. El `await` en el que está esperando lanza una excepción, la ejecución sale de la función y no se envía nada de lo que devuelva. La mayoría de los handlers no necesita hacer nada al respecto.

Dos tipos sí: un handler que tiene algo que limpiar y un handler que es un `def` simple.

## Limpiar en una herramienta `async def` {#clean-up-in-an-async-def-tool}

Pon la limpieza en un `finally`:

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* El `finally` se ejecuta termine como termine la herramienta: devolvió un valor, lanzó una excepción o se canceló.
* La limpieza que tiene que hacer `await` necesita `shield=True`. En un handler cancelado, cada `await` posterior también lanza una excepción, así que sin el escudo `release_hold` se detendría en su primera línea.
* Nada puede cancelar un bloque protegido con escudo, así que ponle un límite de tiempo. Aquí son `5` segundos.

!!! tip
    Usa `finally`, no `except`. La cancelación tiene que seguir propagándose hacia arriba una vez
    terminada la limpieza, y un `finally` se lo permite.

## Detenerse antes en una herramienta `def` simple {#stop-early-in-a-plain-def-tool}

Una herramienta `def` simple se ejecuta en un hilo, y nada puede interrumpir un hilo desde fuera. La herramienta tiene que preguntar:

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` no hace nada mientras la llamada sigue activa, y lanza una excepción una vez que se ha cancelado. Llámala entre unidades de trabajo.
* Aquí la limpieza también va en un `finally`. En un hilo no hay esperas asíncronas, así que no necesita escudo.
* Una herramienta `def` que nunca pregunta se ejecuta hasta el final, y su resultado se descarta.

## Dónde se aplica {#where-it-applies}

Las funciones de prompts y de recursos se cancelan exactamente igual que las herramientas.

Funciona igual sobre stdio y Streamable HTTP. Con el `Client` de este SDK, abandonar significa cancelar la tarea que espera `call_tool` o dejar que se agote su `read_timeout_seconds`.

!!! warning
    Dos opciones de Streamable HTTP impiden que la noticia llegue a tu handler: `json_response=True`
    en una conexión `2026-07-28` y `stateless_http=True` en una heredada. Ahí el handler se ejecuta
    hasta el final, haya hecho lo que haya hecho el cliente.

## Resumen {#recap}

* Cuando el cliente abandona una llamada, el SDK cancela el handler: herramienta, prompt o recurso.
* `async def`: limpia en un `finally` y pon la limpieza con esperas asíncronas dentro de `anyio.move_on_after(seconds, shield=True)`.
* `def` simple: llama a `anyio.from_thread.check_cancelled()` entre unidades de trabajo, o la herramienta se ejecuta hasta el final. Un `finally` simple hace la limpieza.
* `json_response=True` (conexiones modernas) y `stateless_http=True` (las heredadas) desactivan la cancelación.

El progreso y la cancelación son cosa de una herramienta en ejecución y de *quien la llama*. Las líneas que registra para *ti*, la persona que opera el servidor, son un canal distinto: **[Registro de logs](logging.md)**.
