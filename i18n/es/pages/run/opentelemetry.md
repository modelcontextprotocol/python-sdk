---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

Tu servidor ya está trazado. No tienes que añadir nada.

Cada servidor que creas emite un span de [OpenTelemetry](https://opentelemetry.io/) por cada
mensaje que maneja. No lo escribiste ni lo importas. Está ahí desde el momento en que
llamas a `MCPServer(...)`.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

Ese es un servidor completo y trazado. Llama a `search_books` y se crea un span para esa llamada.
Lo mismo vale para el `Server` de bajo nivel: el trazado vive en ambos.

## Qué obtienes {#what-you-get}

Cada mensaje entrante se convierte en un span `SERVER` con el nombre del método y su destino. Así,
un `tools/call` para `search_books` es el span `tools/call search_books`, y un `tools/list` a secas
es simplemente `tools/list`.

Cada span lleva unos cuantos atributos:

* `mcp.method.name` y `mcp.protocol.version`, en todos los spans.
* `jsonrpc.request.id`, en una solicitud (una notificación no tiene).
* Un handler que lanza una excepción marca el estado del span como error. Lo mismo hace un resultado de herramienta con `is_error=True`.

Y como trazar una llamada a herramienta es algo que se quiere muy a menudo, los spans de `tools/call`
siguen las [convenciones semánticas GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) de OpenTelemetry:

* `gen_ai.operation.name`, con el valor `"execute_tool"`.
* `gen_ai.tool.name`, con el nombre de la herramienta que se llama.

Un span de `prompts/get` recibe `gen_ai.prompt.name` con la misma idea. Los métodos de listado no
llevan claves `gen_ai.*`, porque no hay nada que nombrar.

!!! tip
    Esos atributos GenAI son la razón por la que una interfaz de trazas agrupa tus llamadas a
    herramientas igual que agrupa las de cualquier otro agente. Obtienes esa agrupación gratis,
    sin código extra.

## No cuesta nada hasta que lo quieras {#it-costs-nothing-until-you-want-it}

Esta es la parte que hace que "activado por defecto" sea un valor por defecto cómodo.

El SDK depende solo de `opentelemetry-api`, la mitad ligera de OpenTelemetry. Sin un SDK ni un
exportador instalados, crear un span es una operación nula. Así que los spans que tu servidor está
emitiendo ahora mismo no te cuestan casi nada, y nadie los está recolectando.

El día que quieras *verlos*, instalas la otra mitad y la apuntas a algún sitio:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

Configura un exportador como se hace normalmente en OpenTelemetry, y cada span que el SDK ha estado
creando en silencio se enciende. El código de tu servidor no cambia. Ni una línea.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) es uno de esos backends, y hace la
    configuración por ti: `pip install logfire`, `logfire.configure()`, y tus spans de MCP aparecen
    en la vista en vivo. Está construido sobre OpenTelemetry, así que todo lo que sigue también se aplica a él.

## Trazas que cruzan el canal {#traces-that-cross-the-wire}

Una traza es más útil cuando sigue una solicitud desde el cliente hasta el servidor, en una sola
imagen conectada.

Cuando el cliente y el servidor ejecutan ambos el SDK, esa conexión es automática. El cliente inyecta
el [contexto de traza W3C](https://www.w3.org/TR/trace-context/) en la solicitud, y el servidor lo
lee de vuelta, de modo que el span del servidor queda anidado bajo el span del cliente en la misma
traza. Esto es [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414), y lo
obtienes sin pedirlo.

Si el mensaje entrante no lleva contexto de traza, por ejemplo una solicitud de un cliente que no es
el SDK, el span del servidor simplemente toma como padre el span que ya esté activo en el servidor,
en lugar de iniciar una traza huérfana nueva.

## Desactivarlo {#turning-it-off}

El trazado es un middleware, el primero de la lista de tu servidor. Si de verdad quieres un servidor
que no emita spans, quítalo:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    Ese import lleva un guion bajo inicial, y es a propósito. La clase es provisional, igual que
    [`Server.middleware`](../advanced/middleware.md) es provisional, así que debes contar con que la
    ruta de importación cambie. Casi nunca necesitas esto: sin un exportador instalado los spans son
    gratis, así que la respuesta habitual es dejarlos activados y no instalar un exportador.

## Resumen {#recap}

* Cada `MCPServer` y cada `Server` de bajo nivel emite un span `SERVER` por mensaje entrante, por
  defecto. No escribes nada.
* Los spans llevan `mcp.method.name` y `mcp.protocol.version`; `tools/call` y `prompts/get` también
  llevan atributos GenAI para que tus llamadas a herramientas se agrupen como las de cualquier otro agente.
* No cuesta nada hasta que instalas un SDK de OpenTelemetry y un exportador, y entonces se enciende
  sin ningún cambio en tu servidor.
* El contexto de traza de cliente a servidor se propaga automáticamente cuando ambos lados ejecutan el SDK.

Lo que decide si una solicitud se ejecuta o no es la **[Autorización](authorization.md)**.
