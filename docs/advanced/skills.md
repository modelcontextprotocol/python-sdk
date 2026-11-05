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

    On its own it doesn't discover, read, or hash anything. You supply handlers that answer from
    wherever your catalog lives — a database, a generated index, an in-memory list — and you serve
    each skill's files as ordinary resources through `MCPServer.add_resource` or an
    `@mcp.resource(...)` template handler.

    If your skills live in a directory, skip the handlers and use `SkillCatalog`. See
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

Most of the time your skills are just a folder on disk. For that, you don't need to write handlers
or register each file: `SkillCatalog` reads the folder and answers everything for you.

Say you have this layout:

```text
skills/                          <-- the path you give FilesystemSkillProvider
└── git-workflow/                <-- one skill: a folder named after the skill
    ├── SKILL.md                 <-- required: YAML frontmatter, then instructions
    └── references/
        └── conventions.md       <-- any other files the skill needs
```

The `SKILL.md` starts with the skill's `name` and `description`, and `name` must match the
folder name:

```markdown
---
name: git-workflow
description: Follow this team's Git conventions for branching and commits
---

Branch from `main` using `type/short-description`. ...
```

Load it and pass it to your server:

```python title="server.py" hl_lines="11-15"
--8<-- "docs_src/skills/tutorial002.py"
```

That's the whole server. `skills/list`, `skills/get`, and `resources/directory/read` are answered
from the folder, and every file in it is served as a `skill://` resource.

* `FilesystemSkillProvider(root)` tells the catalog where the files are.
* `parse_frontmatter` turns the YAML between the `---` lines of a `SKILL.md` into a dict. The SDK
  doesn't ship a YAML parser, so bring your own. This example uses
  [PyYAML](https://pypi.org/project/PyYAML/) (`uv add pyyaml`).
* `directory_read=True` also serves `resources/directory/read` (more on that
  [below](#directory-reads-from-a-catalog)).

`SkillCatalog.load()` is a coroutine, so build the server inside a running event loop, as
`main()` does above.

### How skills are found

The path you give `FilesystemSkillProvider` is the **root**: a folder that holds one folder per
skill. A fuller example:

```text
skills/                          <-- FilesystemSkillProvider(Path("skills"))
├── git-workflow/                <-- a skill, served as skill://git-workflow/SKILL.md
│   ├── SKILL.md
│   ├── references/
│   │   └── conventions.md
│   └── scripts/
│       └── check-branch.sh
├── pdf-processing/              <-- another skill
│   ├── SKILL.md
│   └── assets/
│       └── template.pdf
├── .git/                        <-- ignored: names starting with `.` are skipped
├── README.md                    <-- not served: it is outside any skill folder
└── draft/                       <-- not a skill: it has no SKILL.md
    └── notes.txt
```

A skill is a directory that contains a `SKILL.md`. Its files are everything beneath that
directory, including the files of any skill nested inside it, which is also listed as a skill in
its own right.

Each file's URI is `skill://` followed by its path, with every segment percent-encoded. Files and
directories whose names start with `.` are ignored entirely, and files outside any skill directory
are not served.

!!! warning
    Point the provider at the folder that **contains** your skill folders, not at a skill folder
    itself. A skill's URI is built from its path under the root, and its last segment must match
    the skill's `name`. With `FilesystemSkillProvider(Path("skills/git-workflow"))`, the
    `SKILL.md` sits directly in the root, so it has no directory name and the skill is skipped
    (an error with `strict=True`). Use `FilesystemSkillProvider(Path("skills"))` instead.

!!! note
    The catalog reads and hashes every file **once**, when `load()` runs, and serves that snapshot.
    That's how the `digest` and `size` in each skill's manifest are guaranteed to match what
    `resources/read` returns.

    It also means the catalog is fixed for the lifetime of the server. If a file changes
    afterwards, reading it fails with an internal error (`-32603`) until you restart the server or
    create a new catalog. And because `load()` reads every file, a large asset directory makes
    startup slower.

### Directory reads from a catalog

Pass `directory_read=True` and every directory that contains a served file can be read, including
directories above a skill such as `skill://acme`. A directory lists its direct children;
subdirectories come back with the MIME type `inode/directory`. Empty directories are not served.

### Caching hints

`ttl_ms` and `cache_scope` set the `ttlMs` and `cacheScope` values on every result:

```python
async def build_catalog(root: Path) -> SkillCatalog:
    return await SkillCatalog.load(
        FilesystemSkillProvider(root),
        parse_frontmatter=yaml.safe_load,
        ttl_ms=60_000,
        cache_scope="public",
    )
```

They follow the rules in [Protocol version and caching](#protocol-version-and-caching). A negative
`ttl_ms` raises `ValueError`.

### Pagination

By default every entry comes back in one response. If your catalog is big, set `page_size`:

```python
async def build_catalog(root: Path) -> SkillCatalog:
    return await SkillCatalog.load(
        FilesystemSkillProvider(root),
        parse_frontmatter=yaml.safe_load,
        directory_read=True,
        page_size=50,
    )
```

Each response then holds at most 50 entries and carries a `nextCursor` while more remain.
`SkillsClient.list_skills()` and `read_directory()` follow it for you. A skill entry is never split
across pages.

The cursor is opaque, and the catalog keeps no record of the cursors it has handed out. It accepts
a cursor that marks a page boundary of its listing. A cursor that is malformed, out of range, or
not on a page boundary is rejected with Invalid params (`-32602`), and so is any cursor when
`page_size` isn't set. A `page_size` below 1 raises `ValueError`.

### Invalid skills

A skill is invalid when its `SKILL.md` has no frontmatter block, has an unterminated block, can't
be parsed, or fails the SEP-2640 requirements for `name` and `description`. A `SKILL.md` placed
directly in the root is also invalid, because the skill has no directory name.

By default (`strict=False`) an invalid skill is left out and a warning is logged, so one bad skill
doesn't take the server down. Pass `strict=True` to make `load()` raise a single `ValueError` that
lists every invalid skill, which is handy in CI.

The frontmatter is returned in `skills/list` and `skills/get` as written, including keys the SDK
doesn't interpret. Values are converted to JSON, so YAML dates become ISO 8601 strings. A value with
no JSON form, such as NaN, makes the skill invalid.

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

`list_files()` returns the path of every file it serves, recursively and without directories. It
may leave files out; `FilesystemSkillProvider` omits any name that starts with `.`. `read_file()`
returns the raw bytes of one file. Paths use `/` as the separator and are relative to the root of
the provider. A provider can therefore be backed by any storage, such as an archive, a database,
or object storage.

`load()` raises `ValueError` if the provider lists a path that is empty, absolute, contains a `.`
or `..` segment, is listed more than once, or lies beneath another listed file. This applies
regardless of `strict`, because it indicates an error in the provider rather than in a skill.

`FilesystemSkillProvider(root)` is the provider for a local directory. It serves regular files
only. Symbolic links and Windows junctions found while listing are omitted, with a warning, and
ones found while reading are refused, so a skill directory doesn't expose files outside itself.

The root is trusted. This is a best-effort check, not a defence against someone who can modify the
directory while the server runs. As a backstop, the catalog refuses to serve any file whose bytes
no longer match the digest taken at `load()`. Blocking file system calls run in a worker thread.

## Protocol version and caching

In protocol version `2026-07-28` and later, `skills/list`, `skills/get`, and
`resources/directory/read` results carry the base
protocol's caching fields, [`ttlMs` and `cacheScope`](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) —
the same freshness hint `tools/list`, `resources/list`, and `resources/read` carry. `Skills` fills
`cacheScope` with `"private"` when your handler leaves it unset, and omits both fields entirely on an
older connection. Set `cache_scope="public"` only when the result is the same for every user.
You don't have to branch on protocol version yourself.

## What this SDK doesn't do

`Skills` is a protocol adapter, not a skills store. It has no opinion on where a skill's bytes
live or when a catalog is refreshed.

`SkillCatalog` covers the common case of a directory (or any other file source behind a
`SkillProvider`), with a few limits:

* It doesn't include a YAML parser. `parse_frontmatter` supplies one.
* The catalog isn't reloaded. To publish changes, create a new catalog.
* Empty directories aren't served by directory reads.

For anything else, such as a database or a catalog that changes while the server runs, write your
own handlers for `Skills`.
