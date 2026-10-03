---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# Muestreo y roots {#sampling-and-roots}

Un handler puede pedirle al cliente conectado dos cosas más: una respuesta del propio modelo del cliente, el **muestreo** (sampling), y las carpetas del espacio de trabajo del cliente, los **roots** (directorios raíz).

Ambos siguen funcionando, en todas las versiones del protocolo que habla el SDK. Pero lee la advertencia antes de diseñar en torno a ellos:

!!! warning "Obsoletos según la especificación 2026-07-28"
    El muestreo y los roots están obsoletos a partir de `2026-07-28` ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). Siguen siendo plenamente funcionales y permanecen en la especificación al menos doce meses antes de poder ser eliminados, pero las implementaciones nuevas no deberían basarse en ellos. Las migraciones sugeridas: integra directamente la API de tu proveedor de LLM en lugar del muestreo, y pasa los directorios mediante parámetros de herramientas, URI de recursos o la configuración del servidor en lugar de los roots. La lista completa del SDK está en **[Funcionalidades obsoletas](../deprecated.md)**.

## Muestreo: toma prestado el modelo del cliente {#sampling-borrow-the-clients-model}

Un resolutor devuelve `Sample(...)` y la herramienta recibe la respuesta del modelo, a través del mismo mecanismo de dependencias que ejecuta `Elicit` en **[Dependencias](dependencies.md)**:

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` refleja los parámetros de `sampling/createMessage`. El valor inyectado es el `CreateMessageResult` del cliente; pasa `tools` o `tool_choice` y en su lugar será un `CreateMessageResultWithTools`.
* El cliente debe haber declarado la capacidad `sampling` (`sampling.tools` si pasas `tools` o `tool_choice`). Si no lo hizo, la llamada falla con un error de protocolo `-32021` en lugar de enviar una solicitud que el cliente no puede manejar. Una sesión anterior a 2026 sin canal de retorno (back-channel) falla con su error habitual de falta de canal de retorno, ya que no hay nada por donde enviarla.
* En `2026-07-28` la solicitud se entrega dentro del flujo de varias idas y vueltas (**[Solicitudes de varias idas y vueltas](multi-round-trip.md)**, multi-round-trip); en `2025-11-25` es una solicitud independiente al cliente. El código es el mismo en ambos casos, pero ten en cuenta la regla de las varias idas y vueltas: la solicitud debe generarse idéntica en cada ronda de reintento, así que constrúyela solo a partir de los argumentos de la herramienta y otros datos estables.
* Deja `include_context` tal cual: los valores distintos de `"none"` están a su vez obsoletos (SEP-2596) y necesitan una capacidad que casi ningún cliente declara.

## Roots: ¿dónde va esto? {#roots-where-should-this-go}

Los roots son las carpetas sobre las que, según el cliente, el servidor puede operar. Son una orientación informativa, no un mecanismo de control de acceso. Un resolutor devuelve `ListRoots()`:

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* El `ListRootsResult` inyectado lleva una lista de objetos `Root`: un URI `file://` y un nombre para mostrar opcional.
* La condición es la misma que para el muestreo: sin una capacidad `roots` declarada, la llamada falla con `-32021` en lugar de enviar la solicitud.

Al otro lado del canal, el cliente responde ambas solicitudes con los callbacks que ya tiene: `sampling_callback` y `list_roots_callback`, que se tratan en **[Callbacks del cliente](../client/callbacks.md)**.

## En conexiones de la generación 2025 {#on-2025-era-connections}

`ctx.session.create_message(...)` y `ctx.session.list_roots()` siguen existiendo para el código que maneja la sesión directamente. Solo funcionan donde existe un canal de retorno (conexiones de la generación 2025 que no sean sin estado), y llamarlos lanza un aviso de obsolescencia. Los marcadores de resolutor de arriba son la forma admitida: eligen la entrega según la versión negociada y no emiten ningún aviso.

## Resumen {#recap}

* Devuelve `Sample(...)` o `ListRoots()` desde un resolutor; la herramienta recibe el `CreateMessageResult` o el `ListRootsResult` como cualquier otra dependencia.
* El cliente debe declarar la capacidad correspondiente o la llamada falla con `-32021` en lugar de enviarse una solicitud.
* Ambas funcionalidades están obsoletas en `2026-07-28`: plenamente funcionales por ahora, equivocadas para diseños nuevos. Prefiere las API del proveedor frente al muestreo y los parámetros explícitos frente a los roots.

Informar cuánto lleva avanzado una herramienta lenta: **[Progreso](progress.md)**.
