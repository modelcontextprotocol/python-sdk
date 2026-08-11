---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# Plantillas de URI y seguridad de rutas {#uri-templates-and-path-safety}

Esta es la referencia de la sintaxis de plantillas de URI que acepta
[`@mcp.resource`](resources.md) y de la
política de seguridad de rutas que el SDK aplica a los valores extraídos. Para una
introducción a qué son los recursos y cuándo usarlos, empieza por
**[Recursos](resources.md)**; esta página supone que ya te sientes cómodo declarando un
recurso y quieres el conjunto completo de operadores, los ajustes de seguridad o la
conexión con la capa de bajo nivel.

La sintaxis de plantillas es [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570).
El SDK admite un subconjunto elegido para hacer coincidir las URI entrantes de
`resources/read`, más una capa de seguridad que rechaza los valores que se resolverían
fuera del directorio que pretendes servir. Para los detalles a nivel de protocolo
(formatos de mensaje, ciclo de vida, paginación) consulta la
[especificación de recursos de MCP](https://modelcontextprotocol.io/specification/latest/server/resources).

## El conjunto completo de operadores {#the-full-operator-set}

El marcador simple, `{user_id}`, es el que presenta **[Recursos](resources.md)**. Hay cuatro
formas de operador más; aquí están en un solo servidor para que puedas verlas una junto a
otra:

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

Cada decorador resaltado es una forma distinta de dividir la URI.
Las secciones siguientes los recorren de arriba abajo.

### Expansión simple: `{name}` {#simple-expansion-name}

`books://{isbn}` es la forma simple, la de todos los días. El marcador se asigna al
parámetro `isbn`, así que un cliente que lee `books://978-0441172719` llama a
`get_book("978-0441172719")`.

Un `{name}` simple se detiene en la primera `/`. `books://978/extra` no
coincide porque la barra después de `978` termina la captura y `/extra`
sobra.

### Conversión de tipos {#type-conversion}

Los valores extraídos llegan como cadenas, pero puedes declarar un tipo más específico
y el SDK los convierte. `orders://{order_id}` llega a una función
cuyo parámetro es `order_id: int`, así que leer `orders://12345` llama a
`get_order(12345)`, no a `get_order("12345")`. El handler hace
aritmética con él (`order_id + 1`) sin conversión explícita.

### Rutas de varios segmentos: `{+name}` {#multi-segment-paths-name}

Para capturar un valor que contiene barras, usa `{+name}`. Con
`manuals://{+path}`:

* `manuals://returns.md` da `path = "returns.md"`
* `manuals://printing/setup.md` da `path = "printing/setup.md"`

Recurre a `{+name}` siempre que el valor sea jerárquico: rutas del sistema de
archivos, claves de objetos anidados, rutas de URL que estés redirigiendo como proxy.

### Parámetros de consulta: `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` pone `limit` y `sort` después del `?`.
La ruta identifica *qué* libro; la consulta ajusta *cómo* lo lees.

Los parámetros de consulta se comparan con flexibilidad: el orden no importa, los
sobrantes se ignoran y los omitidos caen en los valores por defecto de tu función. Así que
`reviews://978-0441172719` usa `limit=10, sort="newest"`, y
`reviews://978-0441172719?sort=top` sobrescribe solo `sort`.

### Segmentos de ruta como lista: `{/name*}` {#path-segments-as-a-list-name}

Si quieres cada segmento de ruta como un elemento separado de una lista en lugar de una
sola cadena con barras, usa `{/name*}`. Con `shelves://browse{/path*}`, un
cliente que lee `shelves://browse/fiction/sci-fi` llama a
`browse_shelf(["fiction", "sci-fi"])`.

### Referencia de plantillas {#template-reference}

Los patrones más comunes:

| Patrón       | Entrada de ejemplo    | Obtienes                |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | *no coincide* (se detiene en `/`) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### Lo que rechaza el analizador {#what-the-parser-rejects}

Algunas formas de plantilla se detectan desde el principio en lugar de fallar en la
primera solicitud. `@mcp.resource` analiza la plantilla cuando se ejecuta el
decorador, así que ninguna de estas llega nunca a un servidor en ejecución.

`UriTemplate.parse()` lanza `InvalidUriTemplate` en estos casos:

* **Dos variables sin nada entre ellas.** `manuals://{+path}{ext}`
  se rechaza: la comparación no puede saber dónde termina `path` y dónde empieza `ext`.
  Pon un literal entre ellas (`manuals://{+path}/{ext}`) o usa un
  operador que aporte su propio delimitador. `manuals://{+path}{.ext}`
  se acepta porque `{.ext}` aporta el `.` por sí mismo.
* **Más de una variable de varios segmentos.** Como máximo una entre `{+var}`,
  `{#var}` o una variable expandida (`{/var*}`, `{.var*}`, `{;var*}`)
  por plantilla. Dos son intrínsecamente ambiguas: no hay una forma fundamentada
  de decidir cuál de ellas absorbe un segmento adicional.
* **Los errores de sintaxis habituales**: una llave sin cerrar, un nombre de variable usado
  dos veces o una característica de RFC 6570 que el SDK no admite, como el
  modificador de prefijo `{var:3}` o la expansión de consulta `{?vars*}`.

Además de eso, `@mcp.resource` lanza `ValueError` cuando un parámetro del
handler está vinculado a una variable de consulta en el tramo final
`{?...}`/`{&...}` de la plantilla pero no tiene valor por defecto en Python. Esas variables se
comparan con flexibilidad (un cliente puede omitir cualquiera de ellas), así que un parámetro
sin valor por defecto solo aparecería como un error interno opaco en la
primera solicitud que lo omita. `reviews://{isbn}{?limit,sort}` en el
servidor de arriba es la versión bien formada: tanto `limit` como `sort` tienen
valores por defecto.

## Seguridad {#security}

Los parámetros de plantilla vienen del cliente. Si llegan a operaciones del sistema de
archivos o de base de datos sin comprobar, valores como `../../etc/passwd` pueden
resolverse fuera del directorio que pretendías servir.

### Lo que el SDK comprueba por defecto {#what-the-sdk-checks-by-default}

Antes de que se ejecute tu handler, el SDK rechaza cualquier parámetro que:

* escaparía de su directorio de partida mediante componentes `..`
* parezca una ruta absoluta (`/etc/passwd`, `C:\Windows`) o una
  ruta relativa a unidad de Windows (`C:foo`). Un valor relativo a unidad y un
  identificador con espacio de nombres como `x:y` son indistinguibles como cadenas,
  así que cualquier valor de una sola letra seguida de dos puntos se rechaza por defecto;
  exime el parámetro si recibe legítimamente ese tipo de valores
* contenga un byte nulo (`\x00`)

La comprobación de `..` se basa en componentes, no en buscar subcadenas. Valores como
`v1.0..v2.0` o `HEAD~3..HEAD` pasan porque ahí `..` no es un segmento de ruta
independiente.

Estas comprobaciones se aplican al valor decodificado, así que detectan el recorrido de
directorios sin importar cómo se codificó en la URI (`../etc`, `..%2Fetc`,
`%2E%2E/etc`, `..%5Cetc`, `%00`: todos se detectan).

!!! check
    Lee `manuals://../etc/passwd` en el servidor de arriba y la solicitud
    se rechaza sin más: la comparación de plantillas se detiene en el primer fallo,
    así que no se prueba ninguna plantilla posterior (potencialmente más permisiva) como
    alternativa. El cliente ve el mismo error `-32602` "Unknown resource"
    que vería con una URI que no coincide con ninguna plantilla, y
    `read_manual` nunca se ejecuta.

### Handlers del sistema de archivos: usa safe_join {#filesystem-handlers-use-safe_join}

Las comprobaciones integradas detienen los casos comunes, pero no pueden conocer el límite
de tu entorno aislado. Para acceder al sistema de archivos, usa `safe_join` para resolver la
ruta y verificar que se mantiene dentro de tu directorio base:

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` detecta escapes mediante enlaces simbólicos, secuencias `..` y trucos con rutas
absolutas que una simple comprobación de cadenas pasaría por alto. Si la ruta resuelta
escapa de `DOCS_ROOT`, lanza `PathEscapeError`, que le llega al
cliente como un `ResourceError`.

### Cuando los valores por defecto estorban {#when-the-defaults-get-in-the-way}

A veces las comprobaciones bloquean valores legítimos. Una herramienta de importación de
catálogos podría recibir intencionadamente una ruta absoluta, o un parámetro podría ser una
referencia relativa como `../sibling` que tu handler interpreta con
seguridad sin tocar el sistema de archivos. Exime ese parámetro o relaja
la política para todo el servidor:

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* `security=ResourceSecurity(exempt_params={"source"})` en el decorador
  omite las comprobaciones para ese único parámetro en ese único recurso. El
  resto del servidor mantiene la política por defecto.
* `resource_security=` en el constructor de `MCPServer` fija el valor por defecto
  para todos los recursos. Aquí `relaxed` desactiva por completo la comprobación de `..`.

Las comprobaciones configurables:

| Ajuste                  | Por defecto | Qué hace                        |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | Rechaza secuencias `..` que escapan del directorio de partida |
| `reject_absolute_paths` | `True`  | Rechaza `/foo`, `C:\foo`, rutas UNC y la ruta relativa a unidad `C:foo` (también detecta `x:y`) |
| `reject_null_bytes`     | `True`  | Rechaza valores que contienen `\x00`    |
| `exempt_params`         | vacío   | Nombres de parámetros para los que se omiten las comprobaciones  |

Estas comprobaciones son un prefiltro heurístico; para el acceso al sistema de archivos,
`safe_join` sigue siendo el límite de contención.

!!! tip
    Si tu handler no puede satisfacer la solicitud (el archivo no existe,
    el id es desconocido), lanza una excepción. El SDK la convierte en una
    respuesta de error. Consulta **[Manejo de errores](handling-errors.md)** para ver la diferencia entre un
    error de protocolo y un error de herramienta.

## Recursos en el Server de bajo nivel {#resources-on-the-low-level-server}

Si construyes sobre el `Server` de bajo nivel (consulta **[El Server de bajo
nivel](../advanced/low-level-server.md)**), registras directamente los handlers para los métodos de protocolo
`resources/list` y `resources/read`. No hay decorador; devuelves
tú mismo los tipos del protocolo.

### Recursos estáticos {#static-resources}

Para URI fijas, mantén un registro y despacha por coincidencia exacta:

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

El handler de listado les dice a los clientes qué hay disponible; el handler de lectura
sirve el contenido. Comprueba primero tu registro, pasa a las
plantillas (más abajo) si tienes alguna y luego lanza una excepción para cualquier otra cosa.

### Plantillas {#templates}

El motor de plantillas que usa `MCPServer` vive en `mcp.shared.uri_template`
y funciona por sí solo. Obtienes el mismo análisis y la misma comparación; el
enrutamiento y la política de seguridad los conectas tú mismo.

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

En las líneas resaltadas ocurren tres cosas:

* **Analiza una vez, compara en cada solicitud.** `UriTemplate.parse()` construye la
  plantilla; `template.match(uri)` devuelve las variables extraídas como un
  `dict`, o `None` si la URI no encaja. La decodificación de URL ocurre dentro de
  `match()`; los valores decodificados se devuelven tal cual, sin validación de
  seguridad de rutas. Los valores salen como cadenas: conviértelos tú mismo
  (`int(matched["id"])`, `Path(matched["path"])`).
* **Aplica tú mismo las comprobaciones de seguridad.** Las comprobaciones de `..` y de rutas
  absolutas que `MCPServer` ejecuta por defecto viven en `mcp.shared.path_security`.
  `read_manual_safely` las llama antes de tocar `MANUALS`. Si un
  parámetro no es una ruta del sistema de archivos (un ISBN, una consulta de búsqueda), omite las
  comprobaciones para ese valor: controlas la política por handler en lugar de
  hacerlo mediante un objeto de configuración.
* **Lista las plantillas desde la misma fuente.** Los clientes descubren
  las plantillas mediante `resources/templates/list`. `str(template)` devuelve
  la cadena original de la plantilla, así que el listado y el comparador
  comparten una única fuente de verdad.

## Resumen {#recap}

* `{name}` coincide con un segmento; `{+name}` conserva las barras; `{?a,b}`
  toma de la cadena de consulta; `{/name*}` divide los segmentos en una lista.
* Dos variables sin nada entre ellas, o una segunda variable de varios
  segmentos, se rechazan al analizar. Un parámetro vinculado a una variable de consulta
  final `{?...}`/`{&...}` debe declarar un valor por defecto en Python.
* Anota el parámetro (`order_id: int`) y el SDK convierte.
* La política de seguridad por defecto rechaza `..`, rutas absolutas y bytes
  nulos antes de que se ejecute tu handler; sobrescríbela por recurso con
  `security=ResourceSecurity(...)` o para todo el servidor con
  `resource_security=`.
* Para el acceso al sistema de archivos, `safe_join` es el límite de contención.
* En el `Server` de bajo nivel, analiza con `UriTemplate.parse()`, compara
  con `.match()` y aplica `mcp.shared.path_security` tú mismo.
