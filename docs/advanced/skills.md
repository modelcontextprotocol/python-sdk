# Skills

[SEP-2640](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640) defines a
convention for serving [Agent Skills](https://agentskills.io/) over MCP: a skill is a directory
of files — minimally a `SKILL.md` with YAML frontmatter — exposed as ordinary MCP resources,
conventionally under a `skill://` URI. A server enumerates its skills with `skills/list`,
answers for any one of them by URI with `skills/get`, and — optionally — lists a directory's
direct children with `resources/directory/read`.

The SDK ships this as the built-in `Skills` extension (`io.modelcontextprotocol/skills`). If
[Extensions](extensions.md) are new to you, skim that page first.

`Skills` provides the **protocol** primitives: request/response handling, capability
advertisement, and SEP-2640 conformance validation. It does not discover, read, or hash skills
from a filesystem — you supply handlers that answer from wherever your catalog actually lives
(a database, a generated index, an in-memory list, or a directory you walk yourself), and serve
each skill's files as ordinary resources through `MCPServer.add_resource` or
`add_resource_template`.

## Serving a skill

```python title="server.py" hl_lines="19-20 39-40 42"
--8<-- "docs_src/skills/tutorial001.py"
```

Three moves:

* `Skill(uri=..., frontmatter=..., resources=[...])`: one entry, identical in shape whether it
  comes back from `skills/list` or `skills/get`. `resources` is the skill's complete file
  manifest — every file, `SKILL.md` included, each with a `sha256:...` digest and byte size — or
  the string `"dynamic"` for content generated on demand.
* `list_skills`/`get_skill`: plain async callables, invoked per request. `get_skill` **must**
  answer for a skill even if a real `list_skills` implementation omitted it — SEP-2640 requires
  a server to answer by URI for every skill it serves, listed or not.
* `mcp.add_resource(TextResource(uri=SKILL_URI, ...))`: the skill's actual file content, served
  through the SDK's ordinary resource machinery. `Skills` never reads or writes resource content
  itself.

`Skills(list_skills=..., get_skill=...)` is all a server needs; `resources/directory/read` is
optional (below).

## Fetching a skill

```python title="client.py" hl_lines="4"
--8<-- "docs_src/skills/tutorial001_client.py"
```

`list_skills` and `read_directory` follow `nextCursor` to completion, so you get every page's
skills or resources in one call. `get_skill` and `read_skill_uri` (a thin, discoverable alias for
`resources/read`) each cost exactly one request. All four validate the server's response against
the SEP-2640 conformance rules before returning it — a name that doesn't match its URI, a digest
in the wrong shape, or an incomplete manifest raises `ValueError` rather than reaching your code.

`verify_skill_resource(skill, uri, content)` checks a file's bytes — size, then SHA-256 digest —
against the entry you hold for it. Call it after `read_skill_uri` and before treating the content
as trustworthy: `resources/read` returns whatever bytes the server sends *right now*, verification
is what ties those bytes back to the manifest you already validated.

!!! warning
    Skill content is untrusted model input, exactly like any other server-provided text. SEP-2640
    requires a host to tag it with its originating server before it reaches the model, and to
    never grant the frontmatter's `allowed-tools` field (or any other permission-widening field)
    without explicit per-skill user approval. Both are host responsibilities the SDK cannot
    discharge for you — see the SEP's [Security Implications](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640)
    section before building a host on top of this extension.

## Directory reads

A skill's instructions often point at a directory rather than a file ("pick the matching
template from `templates/`"). `resources/list` cannot answer that — it enumerates a server's
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
capabilities; omitting it advertises neither the setting nor the method — a client calling
`resources/directory/read` against such a server gets `METHOD_NOT_FOUND`.
`mcp.client.skills.read_directory` raises before sending if the connected server hasn't
advertised the setting.

## Protocol version and caching

In protocol version `2026-07-28` and later, `skills/list` results carry the base protocol's
list-caching fields, [`ttlMs` and `cacheScope`](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) — the
same freshness hint `tools/list` and `resources/list` carry. `Skills` fills `cacheScope` with
`"public"` when your handler leaves it unset, and omits both fields entirely on an
older connection, so you don't have to branch on protocol version yourself.

## What this SDK doesn't do

`Skills` is a protocol adapter, not a skills provider. It has no opinion on where a skill's
bytes live, how they're indexed, or when a catalog is refreshed — that's for a higher-level
library, or your own handler, to decide. If you're looking for "scan this directory and serve
whatever's in it," you're looking for a provider built on top of `Skills`, not `Skills` itself.
