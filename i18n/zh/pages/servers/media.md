---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# 媒体 {#media}

工具能返回的不只是文本。

SDK 自带两个用于二进制结果的辅助类型（**`Image`** 和 **`Audio`**），以及一个 **`Icon`** 类型，用来让服务器、工具、资源和提示词在客户端 UI 中有自己的图标。

## 返回图片 {#returning-an-image}

把返回类型标注为 `Image`，让它指向一个文件，然后返回：

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` 接受 `path`（要读取的文件）或 `data`（原始字节），二者只能取其一。
* 客户端看到的 MIME 类型根据后缀推断：`logo.png` 会被声明为 `image/png`。
* logo 在这里并不特殊。`server.py` 旁边的任何 PNG 都可以：代码渲染出的图表、示意图、照片都行。

`Image` 是 SDK 提供的便利类型，不是协议类型。在线路上，返回值会变成一个 **`ImageContent`** 块（文件字节经 base64 编码，再加上 MIME 类型）：

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

有两点值得注意：

* `data` 是 base64。你完全没碰过字节；文件是 SDK 读的，编码也是 SDK 做的。
* `structured_content` 是 `None`。`Image` 是给模型看的内容，不是给应用解析的数据：没有输出模式。（对比 **[结构化输出](structured-output.md)**，那里的返回标注**就是**模式。）

!!! info
    `ImageContent` 和 `AudioContent` 位于 `mcp.types` 中，紧挨着普通 `str` 结果所变成的那个 `TextContent`（**[工具](tools.md)**）。工具结果是一个内容块列表；`Image` 和 `Audio` 是产出这两种二进制内容块的最简方式。

### 试一试 {#try-it}

把任意一张 PNG 放到 `server.py` 旁边，命名为 `logo.png`，然后运行：

```console
uv run mcp dev server.py
```

打开 **Tools** 标签页，调用 `logo`。结果不是字符串：它是一个 `image` 内容块，Inspector 会把图片渲染出来。从磁盘上的文件到屏幕上的像素，中间的一切都是 SDK 做的。

## 返回音频 {#returning-audio}

`Audio` 的用法完全一样。`logo.png` 留在原处，再在旁边放任意一个 WAV 文件，命名为 `chime.wav`：

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

结果是一个 **`AudioContent`** 块：

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

一样的道理：进去的是磁盘上的文件，出来的是 base64 和 MIME 类型，没有输出模式。

## 字节还是文件 {#bytes-or-a-file}

两个辅助类型也都接受 `data=`（原始字节）来代替 `path=`。这种方式适用于本来就不是来自某个文件的字节——数据库的一列、一个 HTTP 响应、Pillow 刚画出来的东西：

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

用 `path=` 时什么都不用声明：文件在构建结果时读取，MIME 类型根据后缀推断：

* `Image`：`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`。
* `Audio`：`.wav`、`.mp3`、`.ogg`、`.flac`、`.aac`、`.m4a`。

识别不了的后缀会回退到 `application/octet-stream`。

!!! check
    用 `data=` 时没有文件名，也就无从推断。漏掉 `format=`，SDK 就会回退到默认值：图片是 `image/png`，音频是 `audio/wav`。照这样用 MP3 字节构建一个 `Audio`，客户端会被告知 `mime_type="audio/wav"`，然后老老实实地解码失败。传 `data=` 时，就要一并传 `format=`。

## 图标 {#icons}

`Icon` 是元数据，不是内容。它不携带图片本身，而是用一个 URI 指向图片；客户端可以获取它，并显示在服务器名称、某个工具、资源或提示词旁边。

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` 是客户端能解析的 URI：`https:`，或者如果想把图标内嵌、免去一次额外获取，就用 `data:` URI。
* `mime_type` 和 `sizes`（`"48x48"`，可缩放格式用 `"any"`）让客户端在你提供多个图标时挑出合适的那个。
* `theme="light"` 或 `theme="dark"` 把图标标记为适用于某一种配色方案。

`MCPServer(...)`、`@mcp.tool()`、`@mcp.resource()` 和 `@mcp.prompt()` 都接受同一个 `icons=[...]` 关键字参数。

### 客户端在哪里看到它们 {#where-a-client-sees-them}

图标跟着它们所装饰的对象一起传递。服务器的图标在客户端连接时送达，挂在 `client.server_info` 上（该字段在 2026 版连接上是可选的，所以先收窄类型）：

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

工具的图标在 `tools/list` 返回的 `Tool` 对象上，资源的在 `resources/list` 返回的 `Resource` 上，提示词的在 `prompts/list` 返回的 `Prompt` 上。字段一律叫 `icons`。

## 回顾 {#recap}

* 从工具返回 `Image` 或 `Audio`，客户端就会收到一个 `ImageContent` / `AudioContent` 块：字节经 base64 编码，附带 MIME 类型。
* 可以用 `path=` 构建，让后缀决定 MIME 类型；也可以用内存中的 `data=` 加上显式的 `format=` 构建。
* 媒体结果不带 `structured_content`，也没有输出模式。
* `Icon` 是一个指针：一个 `src` URI，加上可选的 `mime_type`、`sizes` 和 `theme`。
* `icons=[...]` 可用于服务器、工具、资源和提示词，客户端在对应的对象上就能找到它们。

这就是工具能放**进**结果里的全部内容。工具**失败**时会发生什么（以及该让谁知道），见 **[处理错误](handling-errors.md)**。
