# Media

Text is not the only thing a tool can return.

The SDK ships two helpers for binary results (**`Image`** and **`Audio`**) and an **`Icon`** type for giving your server, tools, resources, and prompts a face in the client's UI.

## Returning an image

Annotate the return type as `Image` and return one:

```python title="server.py" hl_lines="14 16"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` takes exactly one of `data` (raw bytes) or `path` (a file to read).
* `format="png"` becomes the MIME type the client sees: `image/png`.
* The bytes here are a one-pixel placeholder so the file runs on its own. In a real server they come from Pillow, matplotlib, a headless browser, or anything else that hands you `bytes`.

`Image` is an SDK convenience, not a protocol type. On the wire your return value becomes an **`ImageContent`** block (your bytes base64-encoded, plus the MIME type):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Two things to notice:

* `data` is base64. You returned raw `bytes`; the SDK did the encoding.
* `structured_content` is `None`. An `Image` is content for the model to look at, not data for the application to parse: there is no output schema. (Contrast **Structured Output**, where the return annotation *is* the schema.)

!!! info
    `ImageContent` and `AudioContent` live in `mcp_types`, right next to the `TextContent`
    you met in **Tools**. A tool result is a list of content blocks; `Image` and `Audio` are
    the shortest way to produce the two binary kinds.

### Try it

```console
uv run mcp dev server.py
```

Open the **Tools** tab and call `logo`. The result is not a string: it is an `image` content block, and the Inspector renders it as a picture. You returned `bytes`; everything between that and the pixels on screen was the SDK.

## Returning audio

`Audio` is the same shape:

```python title="server.py" hl_lines="21-24"
--8<-- "docs_src/media/tutorial002.py"
```

The result is an **`AudioContent`** block:

```python
result.content             # [AudioContent(type="audio", data="UklGRjQAAABXQVZFZm1...", mime_type="audio/wav")]
result.structured_content  # None
```

Same deal: raw bytes in, base64 and a MIME type out, no output schema.

## Bytes or a file

Both helpers also accept `path=` instead of `data=`. The file is read when the result is built, and the MIME type is guessed from the suffix:

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
--8<-- "docs_src/media/tutorial003.py"
```

* `src` is a URI the client can resolve: `https:`, or a `data:` URI if you want the icon embedded with no extra fetch.
* `mime_type` and `sizes` (`"48x48"`, or `"any"` for a scalable format) let the client pick the right one when you offer several.
* `theme="light"` or `theme="dark"` marks an icon for one colour scheme.

The same `icons=[...]` keyword is accepted by `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()`.

### Where a client sees them

Icons travel with whatever they decorate. The server's arrive during the handshake, on `client.server_info`:

```python
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

A tool's icons are on the `Tool` object from `tools/list`, a resource's on the `Resource` from `resources/list`, a prompt's on the `Prompt` from `prompts/list`. The field is always called `icons`.

## Recap

* Return an `Image` or `Audio` from a tool and the client receives an `ImageContent` / `AudioContent` block: your bytes base64-encoded, with a MIME type.
* Build one from in-memory `data=` plus an explicit `format=`, or from a `path=` and let the suffix decide.
* Media results carry no `structured_content` and no output schema.
* An `Icon` is a pointer: a `src` URI plus optional `mime_type`, `sizes`, and `theme`.
* `icons=[...]` works on the server, on tools, on resources, and on prompts, and clients find them on the matching objects.

That is everything a tool can put *into* a result. Helping the user fill in a prompt's or a resource template's arguments *before* anything runs is **Completions**.
