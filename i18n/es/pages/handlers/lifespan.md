---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Lifespan {#lifespan}

La mayoría de los servidores reales mantienen algo durante toda su vida: un pool de conexiones a la base de datos, un cliente HTTP, un modelo cargado.

No quieres construirlo en cada llamada, y sí quieres cerrarlo limpiamente. Para eso está el **lifespan** (ciclo de vida del servidor).

## Un lifespan tipado {#a-typed-lifespan}

Un lifespan es un `@asynccontextmanager` que recibe el servidor y hace `yield` de **un solo objeto**. Lo que sea que entregues queda disponible para todos los handlers mientras el servidor esté en ejecución.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

Léelo de abajo hacia arriba:

* `app_lifespan` conecta la `Database` **antes** del `yield` y la desconecta **después**, en un `finally`. Eso es el arranque y el apagado.
* Entrega un `AppContext`, una dataclass simple que contiene las cosas que configuraste. Un campo hoy, diez mañana.
* `MCPServer("Bookshop", lifespan=app_lifespan)` es todo el cableado necesario.
* Dentro de la herramienta, el objeto entregado es `ctx.request_context.lifespan_context`.

El lifespan se ejecuta **una sola vez**. Se entra en él cuando el servidor arranca (antes de la primera solicitud) y se sale cuando el servidor se detiene. Todas las solicitudes intermedias comparten el mismo `AppContext`.

!!! info
    Si has escrito un `lifespan` de FastAPI, ya conoces esto. Mismo decorador, mismo `yield`, mismo `finally`.

### Lo que ve el modelo {#what-the-model-sees}

Nada nuevo. `ctx` es un parámetro **Context**, así que el SDK lo inyecta y nunca llega al esquema de entrada:

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` es el único argumento que el modelo puede pasar. El lifespan es asunto de tu servidor.

Las funciones `@mcp.resource()` y `@mcp.prompt()` también pueden recibir un parámetro `ctx`, escrito como un `Context` a secas por una razón que se explica en la siguiente sección. Todo lo que lleva `ctx` está en **[El Context](context.md)**.

### De verdad está tipado {#it-really-is-typed}

Mira de nuevo la anotación: `ctx: Context[AppContext]`.

Ese único parámetro de tipo es la razón por la que `ctx.request_context.lifespan_context` **es** un `AppContext` para tu verificador de tipos. `.db` se autocompleta; `.dbb` es un error antes de que llegues a ejecutar el servidor.

Si escribes un `Context` a secas, `lifespan_context` queda tipado como `dict[str, Any]`: el verificador de tipos no tiene forma de saber qué entregó tu lifespan. El objeto sigue ahí en tiempo de ejecución; lo que pierdes es la ayuda.

!!! warning
    `Context[AppContext]` es una forma de escribirlo **exclusiva de las herramientas**. Ponla en una
    función `@mcp.resource()` o `@mcp.prompt()` y todas las llamadas a ese handler fallan. El cliente
    recibe un error, y el log del servidor muestra por qué:

    ```text
    Context is not available outside of a request
    ```

    En recursos y prompts, escribe `ctx: Context` a secas. El objeto que entregó tu lifespan
    sigue siendo `ctx.request_context.lifespan_context` en tiempo de ejecución; renuncias al
    parámetro de tipo, no al objeto.

!!! tip
    Siempre hay un lifespan. Si no pasas uno, el lifespan por defecto del SDK entrega un `dict` vacío,
    así que `ctx.request_context.lifespan_context` es `{}`, nunca `None`. Ese valor por defecto es también
    la razón por la que un `Context` a secas lo tipa como `dict[str, Any]`.

## Míralo en acción {#watch-it-happen}

"El arranque se ejecuta antes de la primera solicitud" es el tipo de frase que no deberías tener que creerte sin más.

Reduce el servidor al ciclo de vida: dale a `Database` un indicador `connected`, cámbialo en `connect()` y `disconnect()`, y añade una herramienta que informe de su valor.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` vive a nivel de módulo por una sola razón: para que puedas observarla desde *fuera* del servidor.

!!! check
    Tres momentos, tres valores:

    * Antes de que el servidor arranque, `database.connected` es `False`. Importar el módulo no conectó nada.
    * Mientras está en ejecución, llama a `database_status` y el resultado es `"connected"`.
    * Detén el servidor y se ejecuta el bloque `finally`: `database.connected` es `False` de nuevo.

    El trabajo ocurrió exactamente donde lo pusiste: alrededor del `yield`, no al importar ni en cada solicitud.

## Resumen {#recap}

* `lifespan=` recibe un `@asynccontextmanager` que recibe el servidor y hace `yield` de un solo objeto.
* El código anterior al `yield` es el arranque. El `finally` posterior es el apagado.
* Se ejecuta una sola vez, alrededor de toda la vida del servidor, no en cada solicitud.
* Lo que sea que entregues con `yield` es `ctx.request_context.lifespan_context` en cada herramienta, recurso y prompt.
* `ctx: Context[AppContext]` hace que ese acceso esté completamente tipado en las herramientas. Los recursos y prompts reciben el `Context` a secas.
* Sin `lifespan=`, obtienes un `dict` vacío, nunca `None`.

Un handler que se detiene a mitad de una llamada para preguntarle al usuario algo que solo él sabe es **[Elicitación](elicitation.md)**.
