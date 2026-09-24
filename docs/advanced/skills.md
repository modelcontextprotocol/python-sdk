# Skills

[SEP-2640](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640) defines a
convention for serving [Agent Skills](https://agentskills.io/) over MCP. A skill is just a
directory of files — at minimum a `SKILL.md` with YAML frontmatter — that you expose as ordinary
MCP resources, conventionally under a `skill://` URI.

A server enumerates its skills with `skills/list`, answers for any single one by URI with
`skills/get`, and — optionally — lists a directory's direct children with
`resources/directory/read`.

The SDK ships this as the built-in `Skills` extension (`io.modelcontextprotocol/skills`). There's
one on the server side and one on the client side. If [Extensions](extensions.md) are new to you,
skim that page first.

!!! info
    `Skills` gives you the **protocol** primitives: request/response handling, capability
    advertisement, and SEP-2640 conformance validation.

    It does **not** discover, read, or hash skills from a filesystem. You supply handlers that
    answer from wherever your catalog actually lives — a database, a generated index, an in-memory
    list, or a directory you walk yourself — and you serve each skill's files as ordinary resources
    through `MCPServer.add_resource` or an `@mcp.resource(...)` template handler.

## Serving a skill

Here's a server that serves one skill:

```python title="server.py" hl_lines="31-41 44-51 55"
--8<-- "docs_src/skills/tutorial001.py"
```

There are three moves here:

* `Skill(uri=..., frontmatter=..., resources=[...])` is one entry. It has the same shape whether it
  comes back from `skills/list` or `skills/get`. `resources` is the skill's complete file
  manifest — every file, `SKILL.md` included, each with a `sha256:...` digest and byte size — or
  the string `"dynamic"` for content generated on demand.
* `list_skills` and `get_skill` are plain async callables, invoked once per request. `get_skill`
  **must** answer for a skill even if your `list_skills` left it out — SEP-2640 requires a server
  to answer by URI for every skill it serves, listed or not.
* `mcp.add_resource(TextResource(uri=SKILL_URI, ...))` registers the skill's actual file content,
  served through the SDK's ordinary resource machinery. `Skills` never reads or writes resource
  content itself.

And that's it. `Skills(list_skills=..., get_skill=...)` is all a server needs;
`resources/directory/read` is optional (more on that below).

## Fetching a skill

On the client side, `Skills` is a [`ClientExtension`](extensions.md). You register it the same way
you register any other one — by passing it to `Client(extensions=[...])` — and then call `bind` to
get the verbs tied to that connection:

```python title="client.py" hl_lines="9-11"
--8<-- "docs_src/skills/tutorial001_client.py"
```

`skills.bind(client)` hands you a `BoundSkills`, and its methods are the SEP-2640 verbs:

* `list_skills` and `read_directory` follow `nextCursor` to completion, so a single call gives you
  every page's skills or resources.
* `get_skill` costs exactly one request.

These three validate the server's response against the SEP-2640 conformance rules before returning
it. A name that doesn't match its URI, a digest in the wrong shape, or an incomplete manifest raises
`ValueError` rather than reaching your code.

`read_skill_uri` is the exception. It's a thin, discoverable alias for `resources/read` that returns
a `ReadResourceResult` (text or blob contents) and validates nothing itself — that's the next step.

!!! tip
    `verify_skill_resource(skill, uri, content)` checks a file's bytes — size, then SHA-256
    digest — against the entry you hold for it. Call it after `read_skill_uri` and *before* you
    treat the content as trustworthy.

    `resources/read` returns whatever bytes the server sends *right now*; verification is what ties
    those bytes back to the manifest you already validated. It applies to a static manifest only —
    a `"dynamic"` skill carries no digests, so calling it on one raises `ValueError`.

!!! warning
    Skill content is untrusted model input, exactly like any other server-provided text. SEP-2640
    requires a host to tag it with its originating server before it reaches the model, and to
    never grant the frontmatter's `allowed-tools` field (or any other permission-widening field)
    without explicit per-skill user approval.

    A digest match confirms the *bytes*, not the *frontmatter*: it doesn't prove the
    `frontmatter` the server advertised in `skills/get` matches the frontmatter inside the fetched
    `SKILL.md`. If you act on `skill.frontmatter` — especially `allowed-tools` — parse the fetched
    file and compare its frontmatter yourself.

    These are host responsibilities the SDK cannot discharge for you — read the SEP's
    [Security Implications](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640)
    section before building a host on top of this extension.

## Directory reads

A skill's instructions often point at a directory rather than a file ("pick the matching
template from `templates/`"). `resources/list` can't answer that — it enumerates a server's
entire resource space, not one subtree — so SEP-2640 adds `resources/directory/read`, gated
behind the `directoryRead` capability setting:

```python
mcp = MCPServer(
    "catalog",
    extensions=[
        Skills(
            list_skills=list_skills,
            get_skill=get_skill,
            read_directory=read_directory,  # lists uri's direct children
        )
    ],
)
```

Supplying `read_directory` advertises `{"directoryRead": true}` under the extension's
capabilities. Omitting it advertises neither the setting nor the method — a client calling
`resources/directory/read` against such a server gets `METHOD_NOT_FOUND`. On the client side,
`read_directory` raises before it sends anything if the connected server hasn't advertised the
setting.

## Protocol version and caching

In protocol version `2026-07-28` and later, `skills/list` and `skills/get` results carry the base
protocol's caching fields, [`ttlMs` and `cacheScope`](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) —
the same freshness hint `tools/list`, `resources/list`, and `resources/read` carry. `Skills` fills
`cacheScope` with `"public"` when your handler leaves it unset, and omits both fields entirely on an
older connection. So you don't have to branch on protocol version yourself.

## What this SDK doesn't do

`Skills` is a protocol adapter, not a skills provider. It has no opinion on where a skill's bytes
live, how they're indexed, or when a catalog is refreshed — that's for a higher-level library, or
your own handler, to decide.

If you're looking for "scan this directory and serve whatever's in it," you're looking for a
provider built on top of `Skills`, not `Skills` itself.
