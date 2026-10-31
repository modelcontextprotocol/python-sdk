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

    `SkillCatalog` is a provider built on top of `Skills` that implements these handlers for a
    source of skill files, such as a local directory. See
    [Serving skills from a directory](#serving-skills-from-a-directory).

## Serving a skill

Here's a server that serves one skill:

```python title="server.py" hl_lines="31-41 44-51 55"
--8<-- "docs_src/skills/tutorial001.py"
```

There are three moves here:

* `Skill(uri=..., frontmatter=..., resources=[...])` is one entry. It has the same shape whether it
  comes back from `skills/list` or `skills/get`. `resources` is the skill's complete file
  manifest — every file, `SKILL.md` included, each with a `sha256:...` digest and byte size — or
  the string `"dynamic"` for content generated on demand. An optional `_meta` dict rides along
  unchanged on both methods.
* `list_skills` and `get_skill` are plain async callables, invoked once per request. `get_skill`
  **must** answer for a skill even if your `list_skills` left it out — SEP-2640 requires a server
  to answer by URI for every skill it serves, listed or not.
* `mcp.add_resource(TextResource(uri=SKILL_URI, ...))` registers the skill's actual file content,
  served through the SDK's ordinary resource machinery. `Skills` never reads or writes resource
  content itself.

And that's it. `Skills(list_skills=..., get_skill=...)` is all a server needs;
`resources/directory/read` is optional (more on that below).

## Inspecting a skill

On the client side, `Skills` is a [`ClientExtension`](extensions.md). You register it the same way
you register any other one — by passing it to `Client(extensions=[...])` — and then call `extension` to
get the verbs tied to that connection:

```python title="client.py" hl_lines="9-11"
--8<-- "docs_src/skills/tutorial001_client.py"
```

`client.extension(Skills)` hands you a `SkillsClient` with the SEP-2640 methods:

* `list_skills` and `read_directory` follow `nextCursor` to completion, so a single call gives you
  every page's skills or resources.
* `get_skill` costs exactly one request.

These three validate the server's response against the SEP-2640 conformance rules before returning
it. A name that doesn't match its URI, a digest in the wrong shape, or an incomplete manifest raises
`ValueError` rather than reaching your code.

Read a skill file with `Client.read_resource(uri)`, the same method you use for any MCP resource.
It returns raw content without checking it against the skill's manifest.

!!! warning "Verify files before loading"
    A host that loads a skill must hold its `Skill` entry. Before using a fetched file, check that
    its URI appears in that entry's `resources` and that its bytes match the advertised size and
    SHA-256 digest. A `"dynamic"` skill has no digest to check. Refreshing the entry to accept
    changed bytes also changes the content to which any prior approval applied.

    Skill content is untrusted model input, exactly like any other server-provided text. SEP-2640
    requires a host to tag it with its originating server before it reaches the model, and to
    never grant the frontmatter's `allowed-tools` field (or any other permission-widening field)
    without explicit per-skill user approval.

    A matching digest confirms the *bytes*, not the *frontmatter*: it doesn't prove the
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

## Serving skills from a directory

`SkillCatalog` is a `Skills` extension that discovers skills in a `SkillProvider` and answers
`skills/list`, `skills/get`, and optionally `resources/directory/read` from what it finds. It
removes the need to write handlers or to register each file as a resource.

```python title="server.py" hl_lines="11-15"
--8<-- "docs_src/skills/tutorial002.py"
```

`SkillCatalog.load()` is a coroutine, so the server is constructed inside a running event loop.
`FilesystemSkillProvider` reads skills from a local directory. `parse_frontmatter` supplies the
YAML parser. The SDK does not install one, so this example uses [PyYAML](https://pypi.org/project/PyYAML/),
which you add to your own project (`uv add pyyaml`).

### How skills are discovered

A skill is a directory that contains a `SKILL.md` file. The skill's files are all files beneath
that directory, including the files of any skill nested inside it. A nested skill is also listed
as a skill in its own right.

Each file is served as a `skill://` resource. Its URI is `skill://` followed by its path, with
each path segment percent-encoded. A file has the same URI regardless of which skill lists it.

Files and directories whose names begin with `.` are excluded. They are never read, listed, or
served. Files outside any skill directory are not served.

The catalog reads and hashes every file once, when `load()` runs, and serves that snapshot. The
`resources` manifest of each skill therefore describes the files exactly as they were read.
The catalog is fixed for the lifetime of the server; to publish changes, create a new catalog.

### Options

`SkillCatalog.load(provider, *, parse_frontmatter, ...)` accepts the following arguments.

| Argument | Default | Description |
|---|---|---|
| `provider` | required | The `SkillProvider` that lists and reads the files. |
| `parse_frontmatter` | required | Receives the text between the `---` lines of a `SKILL.md` and returns a mapping with `str` keys, for example `yaml.safe_load`. |
| `strict` | `False` | Controls the handling of invalid skills. See [Invalid skills](#invalid-skills). |
| `directory_read` | `False` | Serves `resources/directory/read` and advertises the `directoryRead` setting. |
| `ttl_ms` | `0` | The `ttlMs` value set on `skills/list`, `skills/get` and directory read results. |
| `cache_scope` | `"private"` | The `cacheScope` value set on the same results. |
| `page_size` | `None` | The maximum number of entries in one `skills/list` or directory read response. See [Pagination](#pagination). |

`ttl_ms` and `cache_scope` follow the rules described in
[Protocol version and caching](#protocol-version-and-caching). A negative `ttl_ms` raises
`ValueError`.

The frontmatter mapping is returned in `skills/list` and `skills/get` without modification,
including keys the SDK does not interpret. Values are converted to JSON; for example, YAML dates
are returned as ISO 8601 strings. A value with no JSON representation, such as NaN, makes the
skill invalid.

With `directory_read=True`, every directory that contains a served file can be read, including
directories above the skill root such as `skill://acme`. A directory lists its direct children;
subdirectories are returned with the MIME type `inode/directory`. Empty directories are not served.

### Pagination

By default, `skills/list` and `resources/directory/read` return every entry in a single response.
When `page_size` is set, each response contains at most that many entries, and a response that is
followed by another page carries a `nextCursor`. The client passes it back as `cursor`, as for any
other paginated list in the protocol. `SkillsClient.list_skills()` and `read_directory()` do this
automatically.

A skill entry is never split across pages. The cursor is opaque to clients. A cursor that the
catalog did not issue is rejected with Invalid params (`-32602`), and so is any cursor when
`page_size` is not set. A `page_size` below 1 raises `ValueError`.

### Invalid skills

A skill is invalid when its `SKILL.md` has no frontmatter block, has an unterminated block, cannot
be parsed, or fails the SEP-2640 requirements for `name` and `description`. A `SKILL.md` placed
directly in the provider root is also invalid, because the skill has no directory name.

* With `strict=False`, an invalid skill is omitted and a warning is logged.
* With `strict=True`, `load()` raises a single `ValueError` that lists every invalid skill.

A skill whose manifest exceeds the 512 files or 16 MiB recommended by SEP-2640 is still served,
and a warning is logged.

### File content

`SKILL.md` and other Markdown files are served as `text/markdown`, and YAML files as
`application/yaml`. The MIME type of any other file is determined with `mimetypes`, with
`application/octet-stream` as the fallback.

File content is returned unchanged. A file whose bytes are valid UTF-8 is returned as text,
including any byte order mark and line endings; any other file is returned as a base64 blob. In
both cases the content matches the `digest` and `size` in the skill's manifest. Each read is
verified against the values recorded at load time, and a file that has changed is reported as an
internal error (`-32603`) until you restart the server or create a new catalog.

`load()` reads and hashes every file of every valid skill once, so a large asset directory makes
startup slower and temporarily uses memory for the largest file.

### Providers

A `SkillProvider` supplies the files to the catalog. It is a `typing.Protocol`, so an
implementation does not need to subclass it.

```python
class SkillProvider(Protocol):
    async def list_files(self) -> Sequence[str]: ...
    async def read_file(self, path: str) -> bytes: ...
```

`list_files()` returns the path of every file, recursively and without directories. `read_file()`
returns the raw bytes of one file. Paths use `/` as the separator and are relative to the root of
the provider. A provider can therefore be backed by any storage, such as an archive, a database,
or object storage.

`load()` raises `ValueError` if the provider lists a path that is empty, absolute, contains a `.`
or `..` segment, is listed more than once, or lies beneath another listed file. This applies
regardless of `strict`, because it indicates an error in the provider rather than in a skill.

`FilesystemSkillProvider(root)` is the provider for a local directory. It serves regular files
only. Symbolic links and Windows junctions are never followed: they are omitted, with a warning,
when listing, and refused when read. A skill directory therefore cannot expose files outside
itself. Blocking file system calls run in a worker thread.

## Protocol version and caching

In protocol version `2026-07-28` and later, `skills/list`, `skills/get`, and
`resources/directory/read` results carry the base
protocol's caching fields, [`ttlMs` and `cacheScope`](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) —
the same freshness hint `tools/list`, `resources/list`, and `resources/read` carry. `Skills` fills
`cacheScope` with `"private"` when your handler leaves it unset, and omits both fields entirely on an
older connection. Set `cache_scope="public"` only when the result is the same for every user.
You don't have to branch on protocol version yourself.

## What this SDK doesn't do

`Skills` is a protocol adapter, not a skills provider. It has no opinion on where a skill's bytes
live, how they're indexed, or when a catalog is refreshed — that's for a higher-level library, or
your own handler, to decide.

If you're looking for "scan this directory and serve whatever's in it," you're looking for a
provider built on top of `Skills`, not `Skills` itself.

[`SkillCatalog`](#serving-skills-from-a-directory) is such a provider. It has the following
limitations:

* It does not include a YAML parser. The `parse_frontmatter` argument supplies one.
* The catalog is not reloaded. To publish changes, create a new catalog.
* Empty directories are not served by directory reads.
* Pagination is opt-in through `page_size`. Without it, `skills/list` and directory reads return
  all entries in a single response.
