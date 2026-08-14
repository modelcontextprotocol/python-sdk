---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Pruebas {#testing}

El SDK de Python incluye una clase `Client` con un **transporte en memoria**: le pasas tu objeto servidor y se conecta a él directamente.

Sin subproceso. Sin puerto. Sin transporte alguno. Es la misma idea que el `TestClient` de FastAPI.

## Uso básico {#basic-usage}

Supongamos que tienes un servidor sencillo con una sola herramienta:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Para ejecutar la prueba de abajo necesitarás dos dependencias adicionales (de desarrollo):

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Esta documentación supone que ya conoces [`pytest`](https://docs.pytest.org/en/stable/).

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) es lo que usa la prueba
    de abajo para comprobar el objeto de resultado completo en una sola línea. Registra la salida de
    una prueba como el literal `snapshot(...)` que ves. Si prefieres no usarlo, quita la importación
    y comprueba los campos que te interesan (`result.content[0].text == "3"`) como en cualquier otra prueba.

Ahora la prueba:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. Si usas `trio`, devuelve `"trio"` en su lugar. Consulta la [documentación de anyio](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) para los detalles.
2. El fixture entrega un cliente conectado. Cada prueba que recibe `client` obtiene una conexión en memoria nueva al mismo servidor.

¡Listo! Ahora puedes ampliar tus pruebas para cubrir más escenarios.

## ¿Por qué `raise_exceptions=True`? {#why-raise_exceptionstrue}

Pueden fallar dos cosas distintas, y este indicador solo afecta a una de ellas.

Una excepción dentro de una de **tus herramientas** no es un fallo del protocolo. Se convierte en un
resultado normal con `is_error=True`, y el modelo lee el mensaje. `raise_exceptions` no cambia eso:
con o sin él, `call_tool` devuelve el mismo resultado con `is_error=True`. Hay una página entera
dedicada a esto: **[Manejo de errores](../servers/handling-errors.md)**.

Un fallo **fuera** del cuerpo de una herramienta es otra cosa. En la conexión que te da
`Client(mcp)`, el servidor lo depura y lo convierte en un genérico `"Internal server error"` antes de
que el cliente lo vea. Nunca deberías filtrar los detalles de un fallo inesperado a un llamador
remoto. En una prueba eso es exactamente lo que *no* quieres, y es lo que cambia
`raise_exceptions=True`: tu prueba ve el mensaje real en lugar del depurado.

Déjalo activado en las pruebas. No tiene ningún sentido en código de producción.

## En proceso por defecto {#in-process-by-default}

!!! note
    `Client(mcp)` se conecta en proceso y es **neutral respecto a la generación** por defecto: sondea
    el servidor y elige la ruta de protocolo adecuada. Fija `mode="legacy"` si tu prueba ejercita
    comportamientos específicos de las conexiones heredadas (envío de muestreo (sampling) o
    elicitación (elicitation), `message_handler`), y quita `raise_exceptions=True` en ese caso: una
    conexión heredada nunca depura los errores en primer lugar, y el indicador relanza el fallo
    dentro de la tarea del servidor en lugar de en tu prueba.

Esa única línea es también la razón por la que esta documentación puede prometerte que sus ejemplos
funcionan: cada archivo de ejemplo lo ejercita la propia suite de pruebas del SDK, casi todos a
través de exactamente este cliente. Estás usando la misma herramienta que el SDK usa consigo mismo.

Tienes un servidor que funciona y está probado. Ponerlo dentro de una aplicación real (Claude
Desktop, un IDE) es **[Conectar a un host real](real-host.md)**; todas las demás formas de servirlo
están en **[Ejecutar tu servidor](../run/index.md)**.
