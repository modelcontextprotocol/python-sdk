# Pagination

Most servers never need this.

`MCPServer` answers every `list_*` request with everything it has, in one page, `next_cursor=None`. For a few dozen tools, resources or prompts that is the right answer and there is nothing to configure.

Pagination is for the server whose resource list is really a database: thousands of rows it refuses to serialize in one response. The protocol's answer is a **cursor**: the server returns a page plus an opaque token, and the client sends that token back to get the next page.

`@mcp.resource()` has no hook for any of that. To page, you write the list handler yourself, on the **[low-level Server](low-level-server.md)**.

## A server that pages

```python title="server.py" hl_lines="13 16-17"
--8<-- "docs_src/pagination/tutorial001.py"
```

* On a low-level `Server`, handlers are constructor arguments, not decorators. `on_list_resources` answers every `resources/list` request; that's the whole hookup.
* Every paged handler is typed `params: PaginatedRequestParams | None`, and the example accepts both. Over a connection, though, the SDK never hands you `None` (a request with no `params` member reaches the handler as the model with its defaults), so the signal that matters is `params.cursor is None`: **start from the top**.
* You decide what a cursor *is*. Here it's an offset rendered as a string. A timestamp, a primary key, a base64 blob: anything you can mint on the way out and recognise on the way back in.
* `next_cursor=None` is how you say "that was the last page". There is no count, no total, no `has_more`. `None` is the entire signal.

!!! tip
    A `PAGE_SIZE` of 10 makes the example readable. Pick yours per endpoint: a list of
    one-line resources can afford a page of 500; a list of fat prompt templates cannot.
    The client has no say in it, and that is by design.

### Try it

`Client(server)` connects to a low-level `Server` in memory exactly as it connects to an `MCPServer`.

Call `list_resources()` with no arguments. You get ten resources, `book-1` through `book-10`, and `next_cursor` is the string `"10"`.

Hand it back with `list_resources(cursor="10")` and the first resource is `book-11`, the new `next_cursor` is `"20"`.

The tenth page comes back with `next_cursor` set to `None`. Done.

## The client loop

Every `list_*` method on `Client` (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) takes a `cursor=` keyword. Draining a paged list is one `while True`:

```python title="client.py" hl_lines="27-33"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` starts as `None`, so the first request carries no cursor.
* Extend **before** you look at `next_cursor`: the last page has resources too.
* `next_cursor is None` is the exit. Anything else goes straight back into `cursor=`, untouched.

Run its `main()` and it prints `100 resources`: ten pages of ten, stitched together by a loop that never knew there were ten pages.

This is the same loop **[The Client](../client/index.md)** shows for every `list_*` verb, and it costs nothing against a server that doesn't page: `next_cursor` is `None` on the first response and the loop runs once.

## Draining in one call

That loop is the same one in every client that pages, so `Client` ships it. The server here is the bookshop from before; only the client changed:

```python title="client.py" hl_lines="27 31"
--8<-- "docs_src/pagination/tutorial003.py"
```

* `list_all_resources()` walks `next_cursor` for you and hands back every page stitched into one list. There is one per pageable list: `list_all_tools`, `list_all_prompts`, `list_all_resources`, `list_all_resource_templates`.
* `iter_all_resources()` yields one resource at a time and only fetches the next page when you ask for it, so you can stop early without dragging down the whole catalog. Same four: `iter_all_tools`, `iter_all_prompts`, and so on.
* The single-page `list_*` methods are unchanged. Use them when you want one page and the cursor; use the drains when you want everything and don't want to own the loop.

`ClientSessionGroup` aggregation drains the same way, so a group fronting several servers reports the full collection instead of each server's first page. That aggregator is **[Session groups](../client/session-groups.md)**.

!!! warning
    A drain trusts the server to advance the cursor. A server that echoes back the
    `next_cursor` it was handed, or cycles through a longer loop of them, would page forever,
    so the drains remember every cursor they have seen and raise `RuntimeError` the moment one
    repeats. A repeated cursor is a broken server, and a loud failure beats a silent hang or a
    half-read list.

## The three rules

**Cursors are opaque.** A client must never parse, build, or guess one. The only legal source of a cursor is the previous page's `next_cursor`, verbatim.

**The server picks the page size.** There is no `limit=` in the protocol. If you need a different page size, you change the server.

**A client that ignores paging still works.** It calls `list_resources()` once, gets the first ten, and never notices the `next_cursor` it threw away. Nothing breaks; it sees less.

!!! check
    Opaque means opaque. Invent a cursor (`list_resources(cursor="page-2")`) and there is
    nothing the protocol can do for you. This server tries `int("page-2")`, the handler raises,
    and what comes back to the client is:

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    A cursor you didn't get from the server is a bug, not a feature request.

## Recap

* `MCPServer` returns everything in one page. Pagination is opt-in, and you opt in on the low-level `Server`.
* `on_list_resources` (and `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) receives `PaginatedRequestParams | None`; `params.cursor` is `None` for the first page.
* You return a page plus `next_cursor`: any string you'll recognise later, or `None` when there is nothing left.
* The client loop: pass `cursor=`, accumulate, repeat until `next_cursor is None`.
* Cursors are opaque, the server owns the page size, and a non-paging client still gets page one.

The rest of the hand-written `Server` API (`on_call_tool`, `input_schema` dicts, `_meta`) is **[The low-level Server](low-level-server.md)**.
