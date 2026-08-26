---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# Progreso {#progress}

Una herramienta que tarda treinta segundos y no dice nada durante treinta segundos parece rota.

Las **notificaciones de progreso** lo solucionan. La herramienta informa de cuánto lleva avanzado; el cliente decide qué dibujar con eso: una barra, un indicador giratorio, una línea de log.

## Repórtalo desde la herramienta {#report-it-from-the-tool}

Acepta un parámetro **`Context`** y llama a `report_progress`:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

Tres argumentos, y tú decides qué significan:

* `progress`: cuánto llevas avanzado. La especificación exige que **aumente** con cada reporte; nunca repitas un valor ni retrocedas.
* `total`: cuánto hay en total, si lo sabes. Opcional.
* `message`: una línea legible para humanos sobre *este* paso. Opcional.

`ctx` se inyecta por su anotación de tipo y el modelo nunca lo ve: el esquema de entrada de `import_catalog` tiene una sola propiedad, `urls`. La página **[El Context](context.md)** trata por completo de ese objeto; el progreso es una de las cosas que te da.

## Escúchalo desde el cliente {#listen-for-it-from-the-client}

El cliente lo activa **por llamada**, pasando `progress_callback=` a `call_tool`:

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

El callback es una función `async` que recibe exactamente lo que reportó el servidor: `progress`, `total`, `message`.

!!! info
    `Client(mcp)` se conecta directamente al objeto servidor, en memoria; es el mismo cliente sobre el que se construye la página **[Pruebas](../get-started/testing.md)**.
    `progress_callback` es el mismo parámetro sea cual sea el transporte que use el `Client`;
    los *tiempos* que vas a ver son los de la conexión en memoria. Ejecuta tu callback
    de forma directa, así que cada reporte llega antes de que `call_tool` devuelva. Con un transporte real,
    las notificaciones compiten con el resultado, y un callback lento puede seguir ejecutándose después de que `call_tool`
    haya devuelto.

### Pruébalo {#try-it}

Pon `client.py` junto a `server.py` y ejecútalo:

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

Cada `await ctx.report_progress(...)` en el servidor se convirtió en una llamada a `show` en el cliente, en orden, y ambas líneas se imprimieron **antes** de que `call_tool` devolviera. El progreso no va empaquetado en el resultado; se transmite mientras la herramienta sigue trabajando.

!!! warning
    `progress_callback` pertenece a la **llamada**, no al `Client`. No hay un argumento del constructor
    para él, porque llamadas distintas quieren callbacks distintos: una maneja una barra de descarga, la siguiente
    una línea de log.

!!! check
    Ahora borra `progress_callback=show` y ejecútalo de nuevo:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    Ningún error, ningún aviso, el mismo resultado. `report_progress` **no hace nada cuando quien llama no pidió
    progreso**, así que reportas sin condiciones y nunca tienes que preguntarte si alguien está
    escuchando.

## Cuando no conoces el total {#when-you-dont-know-the-total}

`total` es para cuando conoces el denominador. A menudo no es así: estás vaciando un feed, recorriendo un cursor, descargando algo sin cabecera de longitud.

Omítelo:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

El callback recibe `total=None`. Un cliente todavía puede mostrar *actividad* ("3 imported so far...") pero no puede mostrar un porcentaje. No te inventes un total para conseguir una barra más bonita.

!!! tip
    `progress` no tiene por qué contar nada en particular. Bytes, filas, páginas: elige la unidad que el
    usuario reconocería, y promete solo un `total` que puedas cumplir.

## Resumen {#recap}

* `await ctx.report_progress(progress, total=None, message=None)` desde cualquier herramienta que reciba un `Context`.
* El cliente pasa `progress_callback=` a `call_tool`: por llamada, nunca en el `Client`.
* El callback es `async (progress, total, message) -> None` y se dispara mientras la herramienta sigue ejecutándose.
* Si la llamada no lleva callback, `report_progress` no hace nada. Reporta sin condiciones.
* Omite `total` cuando no lo conozcas; el callback recibe `None`.

El progreso es lo que una herramienta en ejecución le muestra al *usuario*. Las líneas que registra para *ti*, la persona que opera el servidor, van por otro canal: **[Logging](logging.md)**.
