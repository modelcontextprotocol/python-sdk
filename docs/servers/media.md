# Media

Text is not the only thing a tool can return.

The SDK ships two helpers for binary results (**`Image`** and **`Audio`**) and an **`Icon`** type for giving your server, tools, resources, and prompts a face in the client's UI.

## Returning an image

Annotate the return type as `Image`, point it at a file, and return it:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` takes exactly one of `path` (a file to read) or `data` (raw bytes).
* The MIME type the client sees is guessed from the suffix: `logo.png` is announced as `image/png`.
* Nothing here is special about logos. Any PNG next to `server.py` works: a chart your code rendered, a diagram, a photo.

`Image` is an SDK convenience, not a protocol type. On the wire your return value becomes an **`ImageContent`** block (the file's bytes base64-encoded, plus the MIME type):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Two things to notice:

* `data` is base64. You never touched the bytes; the SDK read the file and did the encoding.
* `structured_content` is `None`. An `Image` is content for the model to look at, not data for the application to parse: there is no output schema. (Contrast **[Structured Output](structured-output.md)**, where the return annotation *is* the schema.)

!!! info
    `ImageContent` and `AudioContent` live in `mcp_types`, right next to the `TextContent`
    that a plain `str` result becomes (**[Tools](tools.md)**). A tool result is a list of content blocks; `Image` and `Audio` are
    the shortest way to produce the two binary kinds.

### Try it

Drop any PNG next to `server.py`, name it `logo.png`, and run:

```console
uv run mcp dev server.py
```

Open the **Tools** tab and call `logo`. The result is not a string: it is an `image` content block, and the Inspector renders your picture. Everything between the file on disk and the pixels on screen was the SDK.

## Returning audio

`Audio` is the same shape. Keep `logo.png` where it was, and put any WAV beside it as `chime.wav`:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

The result is an **`AudioContent`** block:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

Same deal: a file on disk in, base64 and a MIME type out, no output schema.

## Bytes or a file

Both helpers also accept `data=` (raw bytes) instead of `path=`. That is the mode for bytes that never came from a file of their own — a database column, an HTTP response, something Pillow just drew:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

With `path=` there is nothing to declare: the file is read when the result is built, and the MIME type is guessed from the suffix:

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

A suffix it doesn't recognise falls back to `application/octet-stream`.

!!! check
    With `data=` there is no filename, so there is nothing to guess from. Forget `format=` and
    the SDK falls back to a default: `image/png` for images, `audio/wav` for audio. Build an
    `Audio` from MP3 bytes that way and the client is told `mime_type="audio/wav"`, then
    faithfully fails to decode it. When you pass `data=`, pass `format=`.

## Icons

An `Icon` is metadata, not content. It doesn't carry the image; it points at one with a URI, and a client may fetch it and show it next to your server's name, a tool, a resource, or a prompt.

```python title="server.py" hl_lines="5-6 8 11 17"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` is a URI the client can resolve: `https:`, or a `data:` URI if you want the icon embedded with no extra fetch.
* `mime_type` and `sizes` (`"48x48"`, or `"any"` for a scalable format) let the client pick the right one when you offer several.
* `theme="light"` or `theme="dark"` marks an icon for one colour scheme.

The same `icons=[...]` keyword is accepted by `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()`.

### Where a client sees them

Icons travel with whatever they decorate. The server's arrive when the client connects, on `client.server_info` (optional on 2026-era connections, so narrow it first):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

A tool's icons are on the `Tool` object from `tools/list`, a resource's on the `Resource` from `resources/list`, a prompt's on the `Prompt` from `prompts/list`. The field is always called `icons`.

## Recap

* Return an `Image` or `Audio` from a tool and the client receives an `ImageContent` / `AudioContent` block: your bytes base64-encoded, with a MIME type.
* Build one from a `path=` and let the suffix decide the MIME type, or from in-memory `data=` plus an explicit `format=`.
* Media results carry no `structured_content` and no output schema.
* An `Icon` is a pointer: a `src` URI plus optional `mime_type`, `sizes`, and `theme`.
* `icons=[...]` works on the server, on tools, on resources, and on prompts, and clients find them on the matching objects.

That is everything a tool can put *into* a result. What happens when a tool *fails* (and who should find out) is **[Handling errors](handling-errors.md)**.
