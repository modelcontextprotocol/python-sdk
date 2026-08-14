---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# Primeros pasos {#first-steps}

La **[página de inicio](../index.md)** va rápido: escribes un servidor, lo ejecutas, llamas a una herramienta.

Esta página va despacio, con las tres cosas que un servidor puede exponer y un nombre para cada pieza por el camino.

## Host, cliente y servidor {#host-client-and-server}

Tres palabras que verás en cada página a partir de aquí:

* Un **host** es la aplicación LLM: Claude, un IDE, un entorno de ejecución de agentes. Es aquello con lo que habla el usuario.
* Un **cliente** vive dentro del host y habla MCP. El host ejecuta un cliente por cada servidor al que está conectado.
* Un **servidor** es lo que construyes con este SDK. Expone cosas a los clientes. Nunca habla directamente con el modelo.

Tú escribes el servidor. Los hosts son el producto de otra persona. El SDK también te da un `Client`. Lo usarás para probar tus servidores, y aparece más adelante en esta página.

## Las tres primitivas {#the-three-primitives}

Un servidor expone exactamente tres tipos de cosas. Lo que las distingue es **quién decide usarlas**:

| Primitiva        | Quién la controla | Qué es                                                                 | Ejemplo                                         |
|------------------|-------------------|------------------------------------------------------------------------|-------------------------------------------------|
| **Herramientas** | El modelo         | Una función que el modelo llama para realizar una acción               | Una llamada a una API, una escritura en base de datos |
| **Recursos**     | La aplicación     | Datos que el host carga en el contexto del modelo                      | El contenido de un archivo, una respuesta de una API |
| **Prompts**      | El usuario        | Una plantilla de mensajes reutilizable que el usuario invoca por nombre | Un comando de barra, una entrada de menú        |

"Quién la controla" es precisamente la razón de la división. Una herramienta se ejecuta porque el **modelo** decidió llamarla. Un recurso se adjunta porque la **aplicación** decidió que el modelo lo necesitaba. Un prompt se ejecuta porque el **usuario** lo eligió.

!!! info
    Si has construido una API web ya tienes casi toda la intuición: un **recurso** es un `GET`
    (carga datos y no cambia nada) y una **herramienta** es un `POST` (hace trabajo y puede tener
    efectos secundarios). Un **prompt** no tiene equivalente HTTP; se parece más a una consulta
    guardada que el usuario ejecuta por nombre.

## Un servidor, las tres {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Tres funciones normales, tres decoradores. Cada decorador es el registro completo:

* `@mcp.tool()` convierte `add` en una **herramienta**.
* `@mcp.resource("greeting://{name}")` convierte `greeting` en una **plantilla de recurso**: el `{name}` de la URI es el parámetro de la función.
* `@mcp.prompt()` convierte `summarize` en un **prompt**. La cadena que devuelve se convierte en un mensaje de usuario.

Todo lo demás (el nombre, la descripción, el esquema de argumentos) el SDK lo lee de la propia función: su nombre, su docstring, sus anotaciones de tipo. Nunca declaraste nada de eso por separado.

!!! tip
    Las dos mitades del SDK tienen dos rutas de importación: `from mcp import Client` y
    `from mcp.server import MCPServer`. No existe `from mcp import MCPServer`.

### Pruébalo {#try-it}

Ejecútalo con el MCP Inspector:

```console
uv run mcp dev server.py
```

Abre la URL que imprime. El Inspector tiene una pestaña por primitiva; recórrelas en orden.

**Tools.** Una entrada: `add`, descrita como *Add two numbers.* El formulario tiene un campo entero obligatorio para `a` y otro para `b`. Rellénalos, llámala, y el resultado es `3`. El Inspector construyó ese formulario a partir de `a: int, b: int`. Lo mismo hace cualquier otro cliente.

**Resources.** La lista *Resources* está vacía. `greeting` está en **Resource Templates**, porque `greeting://{name}` tiene un parámetro: no hay un recurso concreto que listar hasta que alguien indique un `name`. Dale `World` y léelo:

```text
Hello, World!
```

**Prompts.** Una entrada: `summarize`, con un único argumento obligatorio `text`. Obtenlo con algo de texto y recibes un mensaje con `role: user` y tu cadena ya generada como contenido. Eso es todo lo que es un prompt: una función que construye mensajes.

El Inspector ejecutó tu servidor sobre **stdio**, uno de los transportes que puede hablar un servidor MCP. Todavía no eliges uno; **[Ejecutar tu servidor](../run/index.md)** es la página para eso.

## Capacidades {#capabilities}

Viste tres pestañas en el Inspector. ¿Cómo supo que había tres?

Cuando un cliente se conecta, el servidor declara sus **capacidades**: qué familias de solicitudes va a responder. El cliente usa esa declaración para decidir qué vale la pena pedir siquiera. Nunca la escribiste; `MCPServer` la declara por ti.

Míralo tú mismo. El `Client` del SDK acepta el objeto servidor directamente y se conecta a él **en memoria** (sin subproceso, sin puerto):

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

Ese diccionario son las **capacidades** declaradas de tu servidor. Es lo primero que aprende cada cliente que se conecta:

| Capacidad   | El cliente ya puede llamar a                                   |
|-------------|----------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                      |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                                   |

`MCPServer` sirve las tres primitivas, así que las tres se declaran siempre.

Fíjate en lo que no está. `completions` (autocompletado de argumentos para plantillas de recurso y prompts) necesita un handler que escribes tú, este servidor no tiene uno, así que la capacidad está ausente y un cliente bien hecho no la pedirá. Esa es la regla para todo lo opcional: registra la cosa y la capacidad aparece; **[Autocompletado](../servers/completions.md)** lo demuestra.

!!! info
    `Client(mcp)` es el mismo cliente en memoria con el que se prueba cada ejemplo de esta
    documentación, y es como probarás los tuyos. Tiene una página entera: **[Pruebas](testing.md)**.

## Lo que no escribiste {#what-you-did-not-write}

Repasa esta página. Escribiste tres pequeñas funciones de Python. **No** escribiste:

* Un JSON Schema. `a: int, b: int` *es* el esquema de `add`.
* Un handler de solicitudes. `tools/list`, `resources/read`, `prompts/get`: todos servidos por ti.
* Una declaración de capacidades. `MCPServer` la hizo por ti.
* Una línea de protocolo. La negociación de versión, el encuadre JSON-RPC, el intercambio de capacidades: todo ocurrió dentro de `mcp dev` y `Client(mcp)`, y nunca lo viste.

Esa proporción es la razón de ser del SDK.

## Resumen {#recap}

* Un **host** es la app LLM, un **cliente** es su mitad que habla MCP, un **servidor** es lo que construyes.
* Las herramientas las controla el **modelo**, los recursos los controla la **aplicación**, los prompts los controla el **usuario**.
* Un decorador por primitiva: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Nombre, descripción y esquema salen de la función.
* Una URI con un `{param}` crea una **plantilla** de recurso, que se lista aparte de los recursos concretos.
* Las **capacidades** del servidor se declaran por ti, y un cliente solo pide lo que un servidor declara.
* `Client(mcp)` se conecta al objeto servidor en memoria: tu entorno de pruebas desde el primer día.

Lo siguiente es **[Conectar a un host real](real-host.md)**: este servidor dentro de Claude Desktop o un IDE, de verdad. Después, **[Pruebas](testing.md)**: una página, un cliente en memoria, y nunca más adivinas si funciona. Tras eso, cada primitiva tiene su propia página, empezando por la que maneja el modelo: **[Herramientas](../servers/tools.md)**.
