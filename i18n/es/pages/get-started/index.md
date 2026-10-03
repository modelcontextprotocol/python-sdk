---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# Empieza aquí {#get-started}

¿Eres nuevo en MCP o nuevo en este SDK? Empieza aquí. Estas páginas te llevan desde cero hasta un servidor funcional y probado: [instala el SDK](installation.md), construye tu [primer servidor](first-steps.md), [conéctalo a un host real](real-host.md) y [pruébalo](testing.md) con un cliente en memoria.

## Ejecuta el código {#run-the-code}

Todos los bloques de código se pueden copiar y usar directamente: son archivos completos que funcionan.

Para seguir los pasos, pega un bloque en un `server.py` y ábrelo en el MCP Inspector:

```console
uv run mcp dev server.py
```

Se **RECOMIENDA ENCARECIDAMENTE** que escribas (o copies) el código, lo edites y lo ejecutes localmente. Usarlo en tu propio editor es lo que de verdad te muestra la idea: lo poco que escribes, el autocompletado, las comprobaciones de tipos que detectan errores antes de ejecutar nada.

## No vas a adivinar {#you-will-not-be-guessing}

Cada ejemplo de esta documentación es un archivo completo dentro de [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) en el propio repositorio del SDK, y cada uno de ellos lo ejercita la suite de pruebas del SDK mediante un **cliente en memoria**:

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

Sin subproceso, sin puerto, sin transporte. `Client(mcp)` se conecta directamente al objeto del servidor.

Si un cambio en el SDK rompe un ejemplo de una de estas páginas, la CI se pone en rojo antes que la página. El código que lees aquí es el código que se ejecuta.

Lo usarás tú mismo en [Pruebas](testing.md); así es también como pruebas tus propios servidores.

## Adónde ir después {#where-to-go-next}

Una vez que tengas un servidor en marcha, el resto de esta documentación es una referencia, no un curso. Cada página es independiente, así que ve directo a lo que necesitas:

* Lo que expone un servidor (herramientas, recursos, prompts) está en **[Servidores](../servers/index.md)**.
* Lo que tienes disponible dentro de las funciones que registras está en **[Dentro de tu handler](../handlers/index.md)**.
* Ponerlo delante de los clientes (stdio, HTTP, tu app FastAPI existente) está en **[Ejecutar el servidor](../run/index.md)**.
* Construir el otro lado, una aplicación que *usa* servidores MCP, está en **[Clientes](../client/index.md)**.
