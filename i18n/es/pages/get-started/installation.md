---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Instalación {#installation}

El SDK de Python está en PyPI como [`mcp`](https://pypi.org/project/mcp/). Requiere **Python 3.10+**.

Esta documentación describe **v2**, la línea de versiones estable actual:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "¿Vienes de v1?"
    v2 es una versión mayor con cambios incompatibles; la **[Guía de migración](../migration.md)**
    los cubre todos. Si tu *paquete* depende de `mcp` y aún no está listo para migrar, mantén un
    límite superior `<2` (por ejemplo `mcp>=1.28,<2`) para que una resolución sin versión fijada se quede en la línea 1.x.

## Qué se instala {#what-gets-installed}

No necesitas saber nada de esto para usar el SDK, pero si te preguntas para qué sirve cada dependencia:

* `mcp-types`: todos los tipos del protocolo (solicitudes, resultados, bloques de contenido) como paquete propio, versionado a la par del SDK. El código que depende de `mcp` lo importa a través del alias `mcp.types` (cada `from mcp.types import ...` de esta documentación); importa `mcp_types` directamente solo en un proyecto que instale `mcp-types` sin el SDK.
* [`anyio`](https://anyio.readthedocs.io/): el entorno de ejecución asíncrono. Todo el SDK está escrito sobre anyio, así que funciona tanto con `asyncio` como con `trio`.
* [`pydantic`](https://docs.pydantic.dev/): la base de todos los modelos de `mcp.types`, además de toda la generación y validación de esquemas.
* [`httpx2`](https://pypi.org/project/httpx2/): el cliente HTTP detrás de los transportes de *cliente* Streamable HTTP y SSE, con compatibilidad integrada con server-sent events.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) y [`python-multipart`](https://pypi.org/project/python-multipart/): los transportes HTTP de *servidor*.
* [`jsonschema`](https://pypi.org/project/jsonschema/): valida la salida estructurada de una herramienta contra su esquema de salida declarado.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): manejo de tokens OAuth para la autorización.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): solo la API ligera, de modo que el middleware de trazas del SDK no cuesta nada a menos que instales por tu cuenta un SDK y un exportador de OpenTelemetry.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) y [`typing-inspection`](https://pypi.org/project/typing-inspection/): funcionalidades modernas de tipado en Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): solo en Windows, se usa para la gestión de subprocesos `stdio`.

## Extras opcionales {#optional-extras}

* `mcp[cli]` añade [`typer`](https://typer.tiangolo.com/) y [`python-dotenv`](https://pypi.org/project/python-dotenv/) para la herramienta de línea de comandos `mcp` (`mcp dev`, `mcp run`, `mcp install`). La querrás durante el desarrollo; puede que no la necesites en un servidor desplegado.
* `mcp[rich]` añade [`rich`](https://rich.readthedocs.io/) para unos logs del servidor más legibles.
