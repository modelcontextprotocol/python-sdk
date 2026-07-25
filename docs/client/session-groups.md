# Session groups

A `Client` connects to one server. Real applications often want several (a search server, a database server, an internal API) and end up juggling a connection and a tool list for each.

**`ClientSessionGroup`** is one object that holds many connections and merges everything they expose into a single view.

## Two servers

Start with two ordinary servers. They have nothing to do with each other, so both naturally called their tool `search`:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## One group

Create a `ClientSessionGroup` and call **`connect_to_server`** once per server:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` takes transport parameters, not a server object: `StdioServerParameters` (from `mcp`) to launch a subprocess, or `StreamableHttpParameters` / `SseServerParameters` (from `mcp.client.session_group`) for a server already listening on a URL.
* `group.tools` is a `dict[str, Tool]` of every connected server's tools. `group.resources` and `group.prompts` are the same shape.
* `group.call_tool(name, arguments)` looks the name up, finds the session that owns it, and forwards the call. You never say which server.

!!! check
    Put `client.py` next to the two servers and run it. The second `connect_to_server` refuses:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    That is an `MCPError`, raised before anything from the second server is registered. A name must
    be unique across the **whole** group, and two servers you don't control will collide eventually.

## `component_name_hook`

You fix this at the group, not at the servers. Pass a function of `(name, server_info)` and the group runs it on every name it registers:

```python title="client.py" hl_lines="8-9 16"
--8<-- "docs_src/session_groups/tutorial004.py"
```

Run it again. `print(sorted(group.tools))` now shows both:

```text
['Library.search', 'Web.search']
```

* The **key** is yours. `by_server` built it from `server_info.name`, the name each `MCPServer(...)` was constructed with.
* The `Tool` inside is untouched: `group.tools["Web.search"].name` is still `"search"`, and that is the name `call_tool` puts on the wire. The prefix never leaves your process.
* It is not only tools. The library's `hours` resource is registered as `Library.hours`.

!!! tip
    The hook runs on **every** name from **every** server, not only on conflicts: there is no
    prefix-on-collision mode. Pick one scheme and let it apply everywhere.

## Adding and removing servers

`connect_to_server` returns the `ClientSession` it opened. Keep it if you ever want that server gone: `await group.disconnect_from_server(session)` removes its tools, resources, and prompts from the group.

If you already hold a connected `ClientSession` (`Client.session` is one), hand it to `await group.connect_with_session(server_info, session)` instead of opening a new transport. It aggregates the same way. The group never closes a session it didn't open. `server_info` names the server for component prefixes; on a 2026-era connection `client.server_info` can be `None` (identity is optional), so pass your own `Implementation(name=..., version=...)` in that case.

## The classic handshake

`ClientSessionGroup` is built on `ClientSession`, not on `Client`. Each `connect_to_server` runs the classic `initialize` handshake. It never sends the `server/discover` probe described in **[Protocol versions](../protocol-versions.md)**. Every MCP server understands that handshake, so this costs you compatibility with nothing; it only means a group takes the older, slower path to a server that could do better.

## Recap

* `ClientSessionGroup` holds many server connections and merges their tools, resources, and prompts into one `dict` each.
* `connect_to_server(params)` per server. It takes transport parameters, never the server object or URL a `Client` takes.
* `group.call_tool(name, arguments)` routes to the owning server for you.
* Names must be unique across the whole group; two servers with a `search` tool cannot coexist on their own.
* `component_name_hook=` rewrites every registered name. The dict key changes, the wire name does not.
* `connect_with_session` adds a session you already hold; `disconnect_from_server` removes one.

The handshake a group speaks (and the faster one a `Client` prefers) is the subject of **[Protocol versions](../protocol-versions.md)**.
