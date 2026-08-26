---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

Una **MCP App** es una herramienta con cara visible: además de sus datos, la herramienta apunta a un
documento HTML que el host muestra como una superficie interactiva.

Dos partes, siempre dos partes:

1. **Una herramienta** que hace el trabajo y devuelve datos, como cualquier otra herramienta.
2. **Un recurso `ui://`** que contiene el HTML que el host muestra para ella.

La herramienta lleva una referencia `_meta.ui.resourceUri` al recurso. El host lo obtiene
con `resources/read`, lo muestra en un **iframe aislado (sandboxed)** y envía el resultado de la
herramienta a ese iframe mediante `postMessage`. El servidor nunca envía ni recibe
mensajes `ui/*`: ese tráfico ocurre entre el host y el iframe. Tú sirves una herramienta
y un documento HTML; el host monta el espectáculo.

El SDK incluye esto como la extensión integrada `Apps` (`io.modelcontextprotocol/ui`).
Si las [extensiones](extensions.md) son nuevas para ti, échale un vistazo primero a esa página. Un minuto,
y luego vuelve.

## Un reloj con cara visible {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

Cuatro pasos:

* `Apps()`: una sola instancia contiene tus herramientas vinculadas a una UI y sus recursos.
* `@apps.tool(resource_uri="ui://clock/app.html")`: una herramienta normal, más la
  marca `_meta.ui.resourceUri`. Todo lo que acepta `@mcp.tool()` (name, title,
  description, ...) se pasa tal cual.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: el recurso
  correspondiente, servido como `text/html;profile=mcp-app`. Ese tipo MIME exacto es lo que
  le dice a un host "esto es una app, muéstrala".
* `MCPServer("clock", extensions=[apps])`: la activación. El servidor ahora anuncia
  `io.modelcontextprotocol/ui` bajo `capabilities.extensions`.

El HTML en sí escucha el `postMessage` del host y muestra el resultado. Para apps
reales, usa el SDK oficial de navegador [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps)
dentro de tu HTML. Te da `ontoolresult`, `callServerTool`,
`getHostContext` y `onhostcontextchanged` en lugar de eventos de mensaje sin procesar.

## Degradación elegante {#graceful-degradation}

No todos los clientes muestran apps. La especificación es tajante sobre lo que eso significa para ti:

> Tools **MUST** return a meaningful `content` array even when UI is available.

El modelo lee `content`; el iframe es para humanos. Un host capaz de mostrar UI sigue entregando
el resultado en texto al modelo, y un cliente solo de texto recibe *solo* eso. Así que el
patrón canónico es una herramienta, dos respuestas. Mira `get_time` de nuevo:

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` es `True` solo cuando el cliente declaró la
extensión `io.modelcontextprotocol/ui` **y** incluyó `text/html;profile=mcp-app`
en su configuración `mimeTypes`. El campo es obligatorio, así que un cliente que lo omite
no cuenta. Eso es exactamente lo que declara `main()` en el mismo archivo: la
mitad cliente de la negociación, y vuelve la respuesta enriquecida.

!!! warning
    Nunca devuelvas un marcador de posición como `"[Rendered UI]"` como único contenido. Si el
    texto alternativo es inútil, la herramienta es inútil para todos los clientes solo de texto y para
    el propio modelo. Escribe la frase.

## Blindar el iframe {#locking-the-iframe-down}

El lado del recurso lleva los metadatos de seguridad: qué puede cargar el iframe, qué
permisos del navegador quiere, cómo le gustaría que lo enmarcaran:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` y `permissions` son **solicitudes al host**, no comportamiento del servidor. El host
construye las políticas Content-Security-Policy y Permissions-Policy del iframe a partir de ellas, y
puede negarse. Detecta las funcionalidades en tu JS en lugar de suponer que se concedieron.

`ResourceCsp`, campo por campo (nombre en Python, clave en el canal, qué hace el host con ella):

| Python | Canal (`_meta.ui.csp`) | Controla |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: adónde pueden ir `fetch`/XHR |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: recursos estáticos |
| `frame_domains` | `frameDomains` | `frame-src`: iframes anidados |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: a qué puede apuntar `<base>` |

`ResourcePermissions`: cada campo solicita un permiso del navegador para el iframe.

| Python | Canal (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    La CSP y los permisos viven en el **recurso**, nunca en la herramienta. Los metadatos de herramienta
    de la especificación no tienen hueco para ellos, y los hosts los ignoran ahí. El SDK hace que el
    error sea imposible de representar: `@apps.tool()` simplemente no tiene parámetro `csp`.

### Visibilidad {#visibility}

`visibility=["app"]` en una herramienta dice "esto existe para el iframe, no para el modelo":

* `"model"`: el modelo puede llamarla.
* `"app"`: el iframe puede llamarla (mediante `callServerTool`).
* Omitido: ambos, que es el valor por defecto.

Filtrar es tarea del **host**. El servidor lista las herramientas exclusivas de app en `tools/list`
como cualquier otra; el host las oculta al modelo. No filtres en el servidor.

## Las reglas que el SDK hace cumplir {#the-rules-the-sdk-enforces}

Todas estas fallan al arrancar, no en producción:

* Un `resource_uri` o una URI de recurso que no sea `ui://...` es un `ValueError` en el
  momento de decorar o registrar.
* Una herramienta vinculada a una URI **sin un recurso registrado que corresponda** es un `ValueError`
  cuando `MCPServer(extensions=[apps])` consume la extensión. Una herramienta que anuncia
  un HTML que responde 404 en `resources/read` es un error de configuración, así que se niega a
  construirse.
* `meta={"ui": ...}` en `@apps.tool()` es un `ValueError`. El decorador es dueño de
  `_meta["ui"]`; exprésalo con `resource_uri=` y `visibility=`. Otras claves de `meta=`
  se combinan sin problema al lado.

Ni el SDK ext-apps de TypeScript ni FastMCP detectan hoy ninguno de estos casos; preferimos
que te enteres antes de que lo haga un host.

## Más allá del HTML en línea {#beyond-inline-html}

`add_html_resource` cubre el caso común: una cadena de HTML. Para cualquier otra cosa,
HTML en disco o contenido generado, construye el recurso tú mismo y entrégalo:

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource` rellena el tipo MIME `text/html;profile=mcp-app` cuando el recurso
no fija uno explícitamente, y rechaza una discrepancia explícita: un recurso `ui://`
con cualquier otro tipo MIME es uno que ningún host va a mostrar.

!!! tip
    ¿Apuntas a un host previo a la disponibilidad general que todavía lee la clave plana
    obsoleta `_meta["ui/resourceUri"]`? Combínala tú mismo:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    El objeto `ui` anidado es la forma de la especificación; la clave plana está de salida.

## Verlo en marcha {#see-it-run}

La historia `apps` en `examples/stories/` es esta página en forma de pareja ejecutable: un servidor
con una herramienta de reloj vinculada a una UI y un cliente que negocia Apps, lee el
`_meta.ui.resourceUri` de la herramienta, obtiene el HTML y llama a la herramienta.

```bash
uv run python -m stories.apps.client
```
