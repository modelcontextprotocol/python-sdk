---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# Sugerencias de caché {#caching-hints}

En el protocolo 2026-07-28, cada resultado que un servidor devuelve para `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` y `server/discover` lleva dos campos: `ttlMs`, cuántos milisegundos puede un cliente tratar el resultado como vigente, y `cacheScope`, si un resultado en caché puede compartirse entre usuarios (`"public"`) o pertenece a un único contexto de autorización (`"private"`).

El servidor no guarda nada en caché. Los campos son una *declaración*: "esta lista de herramientas es la misma para todos y no cambiará durante un minuto". Un cliente (o un gateway delante de ti) puede entonces saltarse la ida y vuelta. Respetar las sugerencias es decisión del cliente; emitirlas es trabajo del servidor, y el SDK lo hace por ti.

Por defecto, cada resultado dice `ttlMs: 0, cacheScope: "private"`: caducado de inmediato, nunca compartido. Eso siempre es seguro y siempre conforme. Si tus listas realmente son estables e idénticas para todos los que llaman, dilo en la construcción:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* El mapa usa como clave el **nombre del método**, y los seis métodos que admiten caché son las únicas claves válidas. El parámetro tiene el tipo `Mapping[CacheableMethod, CacheHint]`, así que tu editor autocompleta las claves y marca un error tipográfico antes de ejecutar; lo que se le escape al verificador de tipos lanza una excepción en la construcción.
* Un método que no mencionas conserva los valores por defecto. El mapa es un conjunto de sobrescrituras, no un manifiesto.
* `CacheHint(ttl_ms=5_000)` dejó `scope` sin definir, así que sigue siendo `"private"`: cinco segundos de vigencia, por cada llamador. El alcance y el TTL son decisiones independientes.
* `"server/discover"` también es una clave válida, ya que el resultado de descubrimiento admite caché como cualquier lista.

!!! warning
    `cacheScope: "public"` significa que *cualquiera* puede recibir tu respuesta en caché. Un
    gateway compartido entregará sin problema el resultado de un usuario a otro, incluso cuando
    la solicitud estaba autenticada. Marca un resultado como `"public"` solo cuando sea idéntico
    para todos los llamadores, y nunca uses `cacheScope` como control de acceso: es una etiqueta,
    no un candado.

## Sobrescritura por handler {#per-handler-override}

En el `Server` de bajo nivel, los handlers construyen sus resultados a mano, y `ttl_ms` / `cache_scope` son simplemente campos de los modelos de resultado. Un handler que los define explícitamente siempre gana al mapa del constructor, campo por campo:

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

El handler dijo `ttl_ms=1_000` y nada sobre el alcance. En lo que se transmite: `ttlMs: 1000` (el del handler, no el `60_000` del mapa) y `cacheScope: "public"` (el del mapa, porque el handler lo dejó sin definir). Lo explícito gana a lo configurado, y lo configurado gana a lo por defecto. Esto vale por campo, así que un handler puede fijar un campo y dejar el otro a la política de todo el servidor.

Esta es también la vía de escape para dinámicas que el constructor no puede conocer: un handler que filtra `resources/read` por usuario puede devolver `cache_scope="private"` para una URI desde un servidor por lo demás público.

Una salvedad sobre las listas paginadas: el protocolo exige el **mismo `cacheScope` en cada página** de una misma lista. El mapa del constructor lo cumple por construcción, ya que usa como clave el método, no la página. Pero un handler que sobrescribe el alcance se hace responsable de esa coherencia: sobrescríbelo en *todas* las páginas, nunca solo cuando hay un cursor, o la página uno y la página dos no coincidirán.

## Lo que ve el cliente {#what-the-client-sees}

En una sesión 2026-07-28, `Client` respeta las sugerencias por ti: tiene una caché de respuestas integrada, activada por defecto. Un resultado que llega con un `ttlMs` se almacena, y una llamada idéntica dentro de ese TTL se sirve desde la caché sin ida y vuelta. Un resultado que llega *sin* sugerencia no se guarda en caché: los resultados sin sugerencia reciben `CacheConfig.default_ttl_ms`, que es `0` por defecto (caducado de inmediato), así que un servidor que no declara nada ve exactamente el mismo tráfico llamada por llamada de siempre.

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

Cuatro llamadas, tres consultas al servidor. La segunda llamada encontró una entrada vigente y nunca llegó al servidor; adelantar el reloj (inyectado) más allá del TTL hizo que la tercera volviera a consultar; la cuarta dijo `cache_mode="refresh"`. Ese argumento nombrado existe en los cinco verbos con caché (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`):

* `"use"` (el valor por defecto) sirve una entrada vigente si la hay, y almacena lo consultado si no.
* `"refresh"` nunca sirve desde la caché: consulta al servidor y almacena el resultado, reemplazando lo que hubiera en caché.
* `"bypass"` hace la ida y vuelta sin tocar la caché en absoluto: ni lectura ni escritura.

Hay una regla por encima de `"use"`: **las llamadas que llevan `meta` siempre llegan al servidor.** Una solicitud con `meta` definido (un token de progreso, campos de trazado) espera una solicitud real por el canal, así que con `cache_mode="use"` se trata como `"refresh"`: se omite la lectura de la caché, y el resultado obtenido sigue reemplazando la entrada en caché. `"bypass"` y un `"refresh"` explícito se comportan como siempre.

Para desactivar la caché por completo, construye con `Client(server, cache=None)`: cada llamada vuelve a ser una ida y vuelta, y `cache_mode`, aunque se sigue aceptando, no hace nada.

El alcance también se respeta automáticamente: las entradas `"private"` se asocian a la *partición* de la caché (más abajo), mientras que las `"public"` pueden optar por compartirse más ampliamente. Y **las notificaciones ganan al TTL** para las entradas exactas que nombran: una notificación `list_changed` desaloja el listado en caché correspondiente, y `resources/updated` desaloja la lectura en caché almacenada exactamente bajo su URI, por muy vigentes que estuvieran. En una conexión 2026-07-28 esas notificaciones llegan por un stream `subscriptions/listen` que abres con `client.listen(...)`, y el desalojo se completa antes de que tu observador vea el evento; **[Suscripciones](subscriptions.md)** es esa página.

Una salvedad sobre `resources/updated`: el desalojo es solo por URI exacta. El contrato del almacén no tiene operación de enumerar ni de recorrer (igual que la implementación de referencia en TypeScript), así que una notificación que lleva la URI de un *sub*recurso no desaloja una lectura en caché de su padre. Si tu servidor señala los subrecursos de esta forma, vuelve a consultar el padre con `cache_mode="refresh"`.

### Configurarla: `CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`: dónde viven las entradas. Por defecto es un almacén en memoria nuevo por cliente; pasa tu propia implementación de `ResponseCacheStore` (respaldada por Redis, por ejemplo) para compartir una caché entre clientes o procesos. Los tipos del contrato (`ResponseCacheStore`, `CacheKey`, `CacheEntry` y el `InMemoryResponseCacheStore` por defecto) se pueden importar desde `mcp.client`. Una búsqueda puede emitir hasta dos `get` secuenciales al almacén (la rama privada, luego la pública), así que ajusta en consecuencia las expectativas de latencia de un almacén remoto. Un almacén personalizado **exige** una `partition` explícita.
* `partition`: la etiqueta de contexto de autorización que evita que las entradas `"private"` de un principal se sirvan a otro dentro de un almacén compartido.
* `target_id`: identidad explícita del servidor, para transportes personalizados y servidores en proceso (más abajo).
* `default_ttl_ms`: TTL aplicado a los resultados que no llevan sugerencia `ttlMs`. El `0` por defecto deja sin caché los resultados sin sugerencia.
* `share_public`: sirve entre particiones las entradas que el servidor afirma como `"public"` (más abajo). Desactivado por defecto.
* `clock`: la fuente de hora de reloj, en segundos desde la época Unix. Inyecta una, como hace el ejemplo de arriba, y las pruebas de caducidad no necesitan dormir.

!!! warning "Partición = principal verificado"
    Deriva `partition` de una **credencial verificada**, como el subject de un token validado. Nunca la derives de datos proporcionados por la solicitud, y nunca de la URL del servidor (la identidad del servidor es un eje de clave aparte). El SDK es una biblioteca sin autenticación propia: el ancla de confianza es quien construye el `CacheConfig`, que es el despliegue, no el inquilino. Un gateway multiinquilino crea un `CacheConfig` por cada principal autenticado.

    La partición también queda fija durante toda la vida del `Client`. Si el contexto de autorización de la conexión cambia a mitad de sesión (una reautenticación como un principal distinto, por ejemplo), la caché no lo sigue; construye un nuevo `Client` para el nuevo principal.

Las claves de caché también llevan la **identidad del servidor**: la cadena de URL a la que te conectaste, sin el userinfo `user:pass@` y, por lo demás, exacta byte por byte. Sin normalizar mayúsculas, sin reordenar la query, sin limpiar la barra final. Normalizar de menos solo cuesta compartición, mientras que normalizar de más podría fusionar dos inquilinos (`?tenant=a` frente a `?tenant=b`), así que las URL superficialmente distintas simplemente no comparten entradas. Cuando no hay URL (un servidor en proceso, o una instancia de `Transport`), el cliente recibe en su lugar una identidad aleatoria por instancia; define `CacheConfig.target_id` para nombrar el servidor (con un almacén personalizado es obligatorio, y la construcción lo dice). La identidad se pasa por un hash sha256 antes de entrar en el material de la clave, así que una URL con secretos en su cadena de consulta nunca aparece en las claves del almacén. Tampoco registres tú la forma previa al hash.

!!! warning "`share_public` confía en el servidor, para toda la flota"
    Por defecto, incluso las entradas `"public"` permanecen dentro de su partición. `share_public=True` sirve las entradas que el servidor marcó `cacheScope: "public"` a **todas** las particiones que usan el almacén, confiando en la clasificación del servidor en nombre de todas ellas. Un servidor que pone `"public"` a datos por inquilino (por error o por malicia) filtra entonces la respuesta de un inquilino a los demás. La opción es deliberadamente solo de nivel constructor: el `cache_mode` por llamada puede restringir la caché, pero nada por llamada puede ampliar la compartición.

### Lo que la caché nunca hace {#what-the-cache-never-does}

* **Las llamadas del nivel de sesión la omiten.** `client.session.list_tools()` y compañía siempre hacen la ida y vuelta; la caché vive en los verbos de `Client`.
* **`server/discover` queda fuera.** El resultado de discover se entrega una vez, al conectar, y nunca entra en la caché de respuestas, incluso cuando lleva un `ttlMs`. Si persistes uno tú mismo para saltarte el sondeo de reconexión ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), su vigencia es tu responsabilidad: `DiscoverResult` lleva `ttl_ms` y `cache_scope`, ya analizados, exactamente para eso.
* **Las páginas de continuación nunca se guardan en caché.** Solo participan las llamadas sin cursor. Una página de continuación rechazada por un cursor caducado sí *desaloja* el listado en caché, porque el listado cambió por debajo.
* **Las lecturas de varias idas y vueltas (multi-round-trip) nunca se guardan en caché.** Un `read_resource` iniciado con `input_responses`/`request_state`, o uno que se resuelve a través de rondas de entrada, nunca entra en la caché (un MUST de la especificación).
* **El desalojo por notificación necesita notificaciones.** El desalojo es tan bueno como la entrega del transporte, y la ruta moderna en proceso (`Client(server)` con el `mode="auto"` por defecto) hoy no entrega notificaciones independientes.
* **El desalojo es diferido, no instantáneo.** Las notificaciones de la ruta de red se despachan desde tareas lanzadas aparte, así que una llamada que compite con la llegada de una notificación puede recibir una vez más la entrada previa al desalojo; la ventana está acotada por la latencia de despacho, y el desalojo igualmente se produce.
* **Sin stale-if-error.** Una entrada caducada nunca se sirve porque la nueva consulta falló; el error se propaga.
* **Sin reconsulta anticipada.** Una entrada almacenada se sirve hasta que caduca su TTL y la siguiente llamada después de eso paga la ida y vuelta; nada se refresca en segundo plano.
* **Sin coalescencia.** Dos llamadas idénticas concurrentes son dos consultas.
* **Ningún TTL de más de 24 horas.** Un `ttlMs` mayor, ya sea enviado por el servidor o configurado, se recorta al almacenar (`mcp.client.caching.MAX_TTL_MS`), lo que acota cuánto tiempo puede servirse cualquier entrada, por generosa que sea su sugerencia.
* En un **almacén compartido**, los clientes compiten entre sí. Cada cliente descarta su propia escritura cuando un desalojo adelantó a la consulta en curso, pero un cliente *coinquilino* aún puede volver a escribir una entrada que un desalojo que nunca vio había eliminado; y esa contabilidad de carreras está acotada a su vez: pasadas 4096 claves rastreadas, primero se descarta la guarda de la clave más antigua. Ambas ventanas se aceptan, y las cierra el límite de TTL de arriba.
* **Nada se sirve entre generaciones del protocolo.** Las entradas están acotadas a la versión de protocolo negociada: en un almacén persistente compartido, una sesión nunca sirve una entrada escrita bajo otra versión negociada (el mismo listado difiere de verdad según la generación, ya que el SDK quita los campos 2026 para las sesiones más antiguas). El desalojo, igualmente, solo toca las entradas de la generación actual; las entradas de otra generación simplemente caducan por TTL.

### Leer las sugerencias por tu cuenta {#reading-the-hints-yourself}

Las sugerencias también son campos normales en cada resultado que admite caché (`result.ttl_ms` y `result.cache_scope`, ya analizados), por si quieres añadir tu propia contabilidad encima de la caché integrada (o en lugar de ella).

Contra un **servidor más antiguo** (protocolo anterior a 2026), los campos simplemente no aparecen en lo que se transmite, y los modelos muestran sus valores por defecto conservadores: `ttl_ms == 0` y `cache_scope == "private"`, caducado y sin compartir, la suposición correcta para un servidor que no declaró nada. La caché trata una sesión heredada de la misma forma: allí las sugerencias nunca se consultan (sean cuales sean las claves que aparezcan en lo que se transmite), solo se aplica `default_ttl_ms`, y su valor por defecto de `0` no guarda nada en caché, así que una conexión anterior a 2026 se comporta exactamente como antes de que existiera la caché. Si necesitas distinguir "el servidor dijo 0" de "el servidor no dijo nada", comprueba `"ttl_ms" in result.model_fields_set`: solo está definido cuando el campo llegó de verdad.

## Clientes más antiguos {#older-clients}

Los clientes con versiones del protocolo anteriores a 2026 nunca ven ninguno de los dos campos; el SDK los quita en la serialización para esas conexiones. Configura tus sugerencias una vez; no hay nada específico de versión que escribir.

## Resumen {#recap}

* Seis métodos llevan `ttlMs`/`cacheScope`; el SDK los deja por defecto en `0`/`"private"`, caducado y sin compartir, siempre seguro.
* `cache_hints={method: CacheHint(...)}` en la construcción (tanto en `MCPServer` como en `Server`) fija valores para todo el servidor por método.
* Un handler que define los campos en su resultado sobrescribe el mapa, campo por campo.
* `"public"` es una promesa de que el resultado es idéntico para todos los llamadores. No es control de acceso.
* `Client` respeta las sugerencias automáticamente: su caché de respuestas está activada por defecto, sirve entradas vigentes en lugar de volver a consultar, y no guarda nada en caché para servidores (o sesiones) que no proporcionan sugerencias.
* Por llamada, `cache_mode="refresh"` vuelve a consultar y `"bypass"` se salta la caché; `cache=None` en la construcción la desactiva por completo.
