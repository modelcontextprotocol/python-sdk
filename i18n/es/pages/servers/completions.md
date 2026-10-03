---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# Autocompletado {#completions}

Un cliente que construye una interfaz sobre tu servidor quiere autocompletar los valores de los argumentos mientras el usuario escribe: nombres de lenguajes, nombres de repositorios, rutas de archivos.

El **autocompletado** (completions) es la forma en que tu servidor proporciona esas sugerencias.

## Algo que valga la pena completar {#something-worth-completing}

El autocompletado se aplica exactamente a dos cosas: los argumentos de un **prompt** y los parámetros de una **plantilla de recurso**. Así que empieza con un servidor que tenga uno de cada:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

Aquí todavía no hay nada de autocompletado.

* `review_code` recibe un `language`. Un usuario no debería tener que adivinar qué formas de escribirlo aceptas.
* `github_repo` recibe un `owner` y un `repo`. Dos campos de texto libre hacen un mal formulario.

## El handler de autocompletado {#the-completion-handler}

Añade **una** función decorada con `@mcp.completion()`:

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* Hay un handler por servidor. Todas las solicitudes de autocompletado llegan aquí, y tú decides qué hacer según lo que se esté completando.
* Debe ser `async def`: el SDK lo espera con await.
* Recibe tres argumentos:
  * `ref`: *qué* prompt o plantilla de recurso, como `PromptReference` o `ResourceTemplateReference`. Con `isinstance` los distingues.
  * `argument`: `argument.name` es el argumento que se está completando, `argument.value` es lo que el usuario ha escrito hasta ahora.
  * `context`: los argumentos ya resueltos. Ignóralo por ahora.
* Devuelves un `Completion(values=[...])`, o `None` cuando no tienes nada que ofrecer.

!!! tip
    `argument.value` es el prefijo que el usuario ha escrito. El SDK **no** filtra por ti: lo que
    pongas en `values` es lo que muestra la interfaz. El `startswith` lo escribes tú.

### Pruébalo {#try-it}

Manéjalo con el `Client` en memoria de **[Pruebas](../get-started/testing.md)**. Llama a
`client.complete()` con `ref=PromptReference(name="review_code")` y
`argument={"name": "language", "value": "py"}`:

```python
result.completion.values  # ['python']
```

* `ref` es el mismo tipo de referencia que recibe tu handler.
* `argument` es un dict normal con exactamente dos claves, `name` y `value`.

Envía un `value` vacío y te devuelve la lista completa. `lang.startswith("")` es verdadero para todos los lenguajes:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

Pregunta por `code` (un argumento que tu handler no reconoce) y devuelve `None`, que el SDK convierte en una lista vacía:

```python
result.completion.values  # []
```

`None` significa *"sin sugerencias"*, nunca un error. La interfaz recurre a un campo de texto normal.

## Una capacidad que nunca declaraste {#a-capability-you-never-declared}

Registrar el handler es la declaración. Conecta un cliente y mira:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

No escribiste `completions` en ninguna parte. El SDK vio el handler y declaró la capacidad por ti. Todas las capacidades *opcionales* funcionan así: el handler es la declaración. (Las tres primitivas no son opcionales: `MCPServer` siempre las declara, haya handlers o no.)

!!! check
    Vuelve al primer `server.py` (el que no tiene handler) y pregúntale de todos modos. La llamada
    falla con un error JSON-RPC:

    ```text
    Method not found
    ```

    Y `client.server_capabilities.completions` es `None`. Ese es el sentido de la capacidad: un
    cliente bien hecho la comprueba y nunca envía la solicitud que no puedes responder.

## Argumentos dependientes {#dependent-arguments}

`github://repos/{owner}/{repo}` tiene dos parámetros, y los valores útiles para `repo` dependen de qué `owner` se eligió primero.

Para eso sirve `context`. Lleva los argumentos que el usuario **ya ha resuelto**:

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* La nueva rama se activa para el parámetro `repo` de la plantilla.
* `context.arguments` es un `dict[str, str] | None` con los valores elegidos hasta ahora (aquí, `owner`).
* Si todavía no hay `owner`, no hay sugerencias sensatas, así que el handler devuelve `None`.

El cliente envía esos valores resueltos con `context_arguments=`. Esta vez `ref` es un
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`. Pide `repo` con un
`value` vacío y pasa `context_arguments={"owner": "modelcontextprotocol"}`:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

Quita `context_arguments=` y la misma llamada devuelve `[]`. El handler no puede saber qué repositorios ofrecer hasta que conoce el propietario.

!!! info
    `Completion` también acepta `total=` y `has_more=`. Úsalos cuando `values` sea un fragmento de
    una lista más larga, para que la interfaz pueda mostrar *"y 200 más"*. La mayoría de los
    handlers nunca los necesitan.

## Resumen {#recap}

* El autocompletado son sugerencias para **argumentos de prompts** y **parámetros de plantillas de recurso**. Nada más.
* `@mcp.completion()` registra el único handler. Es `async def (ref, argument, context) -> Completion | None`.
* Decide según `isinstance(ref, ...)` y `argument.name`. Filtra por `argument.value` tú mismo.
* `None` se convierte en una lista vacía. Nunca es un error.
* `context.arguments` contiene los valores ya resueltos; el cliente los proporciona como `context_arguments=`.
* La capacidad `completions` aparece en cuanto registras el handler. Sin él, la solicitud da `Method not found`.

Las sugerencias ayudan mientras el usuario todavía está *rellenando* un prompt o una plantilla; para hacerle una pregunta en *mitad* de una llamada a una herramienta, lo que quieres es **[Elicitación](../handlers/elicitation.md)**. Todo lo que una herramienta puede devolver además de texto está en **[Imágenes, audio e iconos](media.md)**.
