---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# Grupos de sesiones {#session-groups}

Un `Client` se conecta a un servidor. Las aplicaciones reales suelen querer varios (un servidor de búsqueda, un servidor de base de datos, una API interna) y terminan haciendo malabares con una conexión y una lista de herramientas para cada uno.

**`ClientSessionGroup`** es un único objeto que mantiene muchas conexiones y reúne todo lo que exponen en una sola vista.

## Dos servidores {#two-servers}

Empieza con dos servidores normales. No tienen nada que ver entre sí, así que, como es natural, ambos llamaron `search` a su herramienta:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## Un grupo {#one-group}

Crea un `ClientSessionGroup` y llama a **`connect_to_server`** una vez por servidor:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` recibe parámetros de transporte, no un objeto servidor: `StdioServerParameters` (de `mcp`) para lanzar un subproceso, o `StreamableHttpParameters` / `SseServerParameters` (de `mcp.client.session_group`) para un servidor que ya está escuchando en una URL.
* `group.tools` es un `dict[str, Tool]` con las herramientas de todos los servidores conectados. `group.resources` y `group.prompts` tienen la misma forma.
* `group.call_tool(name, arguments)` busca el nombre, encuentra la sesión a la que pertenece y le reenvía la llamada. Nunca indicas qué servidor.

!!! check
    Pon `client.py` junto a los dos servidores y ejecútalo. El segundo `connect_to_server` se niega:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    Es un `MCPError`, lanzado antes de que se registre nada del segundo servidor. Un nombre debe
    ser único en **todo** el grupo, y dos servidores que no controlas acabarán chocando tarde o temprano.

## `component_name_hook` {#component_name_hook}

Esto se arregla en el grupo, no en los servidores. Pasa una función de `(name, server_info)` y el grupo la ejecuta sobre cada nombre que registra:

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

Ejecútalo de nuevo. `print(sorted(group.tools))` ahora muestra ambos:

```text
['Library.search', 'Web.search']
```

* La **clave** es tuya. `by_server` la construyó a partir de `server_info.name`, el nombre con el que se creó cada `MCPServer(...)`.
* El `Tool` que contiene queda intacto: `group.tools["Web.search"].name` sigue siendo `"search"`, y ese es el nombre que `call_tool` transmite por el canal. El prefijo nunca sale de tu proceso.
* No son solo las herramientas. El recurso `hours` de la biblioteca se registra como `Library.hours`.

!!! tip
    El hook se ejecuta sobre **cada** nombre de **cada** servidor, no solo en los conflictos: no hay un
    modo de prefijo solo en caso de colisión. Elige un esquema y deja que se aplique en todas partes.

## Añadir y quitar servidores {#adding-and-removing-servers}

`connect_to_server` devuelve la `ClientSession` que abrió. Guárdala si alguna vez quieres deshacerte de ese servidor: `await group.disconnect_from_server(session)` quita del grupo sus herramientas, recursos y prompts.

Si ya tienes una `ClientSession` conectada (`Client.session` lo es), pásala a `await group.connect_with_session(server_info, session)` en lugar de abrir un transporte nuevo. La agrega de la misma manera. El grupo nunca cierra una sesión que no abrió. `server_info` da nombre al servidor para los prefijos de los componentes; en una conexión de la generación 2026, `client.server_info` puede ser `None` (la identidad es opcional), así que en ese caso pasa tu propio `Implementation(name=..., version=...)`.

## El handshake clásico {#the-classic-handshake}

`ClientSessionGroup` está construido sobre `ClientSession`, no sobre `Client`. Cada `connect_to_server` ejecuta el handshake clásico de `initialize`. Nunca envía el sondeo `server/discover` descrito en **[Versiones del protocolo](../protocol-versions.md)**. Todos los servidores MCP entienden ese handshake, así que esto no te cuesta compatibilidad con nada; solo significa que un grupo toma el camino más antiguo y lento hacia un servidor que podría hacerlo mejor.

## Resumen {#recap}

* `ClientSessionGroup` mantiene muchas conexiones a servidores y reúne sus herramientas, recursos y prompts en un `dict` para cada tipo.
* `connect_to_server(params)` por servidor. Recibe parámetros de transporte, nunca el objeto servidor ni la URL que recibe un `Client`.
* `group.call_tool(name, arguments)` enruta por ti al servidor al que pertenece.
* Los nombres deben ser únicos en todo el grupo; dos servidores con una herramienta `search` no pueden coexistir por sí solos.
* `component_name_hook=` reescribe cada nombre registrado. La clave del dict cambia; el nombre que se transmite por el canal, no.
* `connect_with_session` añade una sesión que ya tienes; `disconnect_from_server` quita una.

El handshake que habla un grupo (y el más rápido que prefiere un `Client`) es el tema de **[Versiones del protocolo](../protocol-versions.md)**.
