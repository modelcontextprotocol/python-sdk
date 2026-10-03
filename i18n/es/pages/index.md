---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "Esta documentación describe v2, la línea de versiones estable actual"
    ¿Eres nuevo en v2 o vienes de v1? **[Novedades de v2](whats-new.md)** es el recorrido de cinco minutos por lo que cambió, y la **[Guía de migración](migration.md)** cubre cada cambio incompatible.
    ¿Sigues en v1.x? Su documentación está en la [documentación de v1.x](https://py.sdk.modelcontextprotocol.io/v1/).
    ¿Algo quedó tosco o confuso? [Cuéntanos](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

El **Model Context Protocol (MCP)** permite que las aplicaciones proporcionen contexto a los LLM de forma estandarizada, separando la tarea de *proporcionar* contexto de la interacción con el LLM en sí.

Este es su SDK oficial para Python. Con él puedes:

* **Crear servidores MCP** que exponen herramientas, recursos y prompts a cualquier host MCP.
* **Crear clientes MCP** que se conectan a cualquier servidor MCP.
* Hablar todos los transportes estándar: stdio, Streamable HTTP y SSE.

## Requisitos {#requirements}

Python 3.10+.

## Instalación {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

El extra `[cli]` te da el comando `mcp`; lo vas a necesitar para desarrollar.
Consulta [Instalación](get-started/installation.md) para saber para qué sirve cada dependencia.

## Ejemplo {#example}

### Créalo {#create-it}

Crea un archivo `server.py`:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

Eso es un servidor MCP completo.

Expone una **herramienta**, `add`, y un **recurso** con plantilla, `greeting://{name}`.

### Ejecútalo {#run-it}

```console
uv run mcp dev server.py
```

Esto inicia el servidor y abre el [MCP Inspector](https://github.com/modelcontextprotocol/inspector), una interfaz interactiva para explorarlo. Abre la URL que imprime.

!!! note
    El Inspector es una app de Node.js, así que `mcp dev` necesita `npx` en tu `PATH`.

### Pruébalo {#try-it}

En el Inspector, ve a **Tools** y llama a `add` con `a=1`, `b=2`.

Te devuelve `3`. ✨

El Inspector construyó ese formulario (un campo entero obligatorio para `a` y otro para `b`) a partir de tus anotaciones de tipo. Lo mismo hará Claude, y cualquier otro host MCP.

Ahora ve a **Resources** y lee `greeting://World`:

```text
Hello, World!
```

### Resumen {#recap}

Fíjate de nuevo en lo que **no** escribiste:

* Ningún JSON Schema. `a: int, b: int` *es* el esquema.
* Nada de analizar solicitudes, ni de serialización, ni código de validación.
* Ningún manejo del protocolo.

Escribiste dos funciones de Python con anotaciones de tipo y un docstring. El SDK hace el resto.

## Dónde seguir {#where-to-go-next}

* **[Empieza aquí](get-started/index.md)** te lleva de la instalación a un servidor funcional y probado.
* ¿Estás creando una aplicación que *usa* servidores MCP? Empieza por **[Clientes](client/index.md)**.
* ¿Ya tienes una app de FastAPI o Starlette? **[Añadir a una app existente](run/asgi.md)** monta un servidor MCP dentro de ella.
* ¿Buscas un mensaje de error exacto? **[Solución de problemas](troubleshooting.md)** está organizada por el texto literal.
* ¿Te preguntas qué cambió en v2? **[Novedades de v2](whats-new.md)** es el recorrido de cinco minutos.
* ¿Migras desde v1? Empieza por la **[Guía de migración](migration.md)**.
* ¿Buscas una firma exacta? La **[Referencia de la API](api/mcp/index.md)** se genera a partir del código fuente.
* ¿Lees con un LLM? Esta documentación también se publica en el formato [llms.txt](https://llmstxt.org/):
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) es un índice de las páginas, y
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) contiene todas las páginas en un solo archivo.
