---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# 工具 {#tools}

**工具**是模型可以调用的函数。

在一个普通的 Python 函数上加上 `@mcp.tool()`，就声明了一个工具。整个 API 就这些。

## 第一个工具 {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

看看刚才写的代码。没有模式、没有 JSON、没有协议，只是一个函数。SDK 从中读出三样东西：

* 工具的**名称**就是函数名：`search_books`。
* 模型看到的**描述**就是文档字符串：`Search the catalog by title or author.`
* 模型可以传入的**参数**来自类型提示：`query: str` 和 `limit: int`。

### 输入模式 {#the-input-schema}

SDK 根据这些类型提示生成一份 JSON Schema，并在 `tools/list` 时发给客户端：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

两个参数都在 `required` 里，因为都没有默认值。这一点马上就会改。（`title` 键是 Pydantic 附带生成的；属性、属性的类型和 `required` 才是契约。）

!!! tip
    类型提示在这里不是文档，而是**契约**。如果客户端发来 `"limit": "ten"`，SDK 会在你的函数运行之前就把它拒掉。

### 模型会收到什么 {#what-the-model-gets-back}

用 `{"query": "dune", "limit": 5}` 调用这个工具，结果有两部分：

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` 是给**模型**读的文本。`structured_content` 是给**客户端应用**的带类型数据。之所以有它，是因为你把返回类型声明成了 `-> str`。

先不用操心 `structured_content`。从工具里返回真正的 Python 对象，结果自然是对的；**[结构化输出](structured-output.md)** 页面专门讲这件事。

### 试一试 {#try-it}

用 MCP Inspector 运行服务器：

```console
uv run mcp dev server.py
```

打开它打印出来的 URL，切到 **Tools** 标签页，调用 `search_books`。

Inspector 会渲染出一个表单，里面有一个必填的 `query` 文本字段和一个必填的 `limit` 数字字段。这个表单是它根据你的类型提示生成的。其他所有 MCP 客户端也会这样做。

## 可选参数 {#optional-arguments}

给参数设一个默认值，它就不再是必填参数。就这样，只是普通的 Python。

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

模式也随之改变：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

`limit` 从 `required` 里移了出来，并多了 `"default": 10`。省略它的客户端会拿到 `10`，和 Python 的行为一模一样。

## 用 `Field` 写出更丰富的模式 {#richer-schemas-with-field}

类型提示已经很够用了，但有时还想**描述**某个参数，或者给它加约束。

把类型包进 `Annotated`，再加一个 Pydantic 的 `Field`：

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

新东西有三样，全在参数上：

* `Field(description=...)`：单个参数的描述，模型会把它和文档字符串一起读。
* `Field(ge=1, le=50)`：数值上下界。它们在模式里变成 `"minimum": 1, "maximum": 50`。
* `Literal["fiction", "non-fiction", "poetry"]`：枚举。模型只能从中选一个。

!!! check
    约束不是摆设。用 `limit=999` 调用这个工具，SDK 会**在你的函数运行之前**就回复一个工具错误：

    ```text
    Input should be less than or equal to 50
    ```

    这个错误会作为工具结果回到模型那里，模型读到后会换一个合法的值重试。只写了一次 `le=50`，就免费得到了会自我纠错的智能体。

!!! info
    如果用过 FastAPI 或 Pydantic，这些你全都已经会了。同一个 `Field`、同一个 `Annotated`、同一套校验。这里没有任何 MCP 特有的东西要学。

## 用模型作参数 {#a-model-as-a-parameter}

当工具的参数不止两三个时，把它们归进一个 Pydantic 模型：

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

`Book` 的模式嵌套在工具的输入模式里（以 `$defs` 引用的形式），模型把它当作一个 JSON 对象填写，而你的函数收到的是一个**真正的 `Book` 实例**，已经校验过，带有 `.title`、`.author` 和 `.year` 属性。

可以随意搭配：普通参数和模型参数并列、嵌套模型、模型列表。从里到外都是 Pydantic。

## `async def` {#async-def}

如果工具要做 I/O（调用 API、读文件、查数据库），就把它声明为 `async def`，并在里面 `await`。SDK 会 await 它。

普通的 `def` 工具也可以：SDK 会在线程里运行它，所以它永远不会阻塞服务器。

没有别的需要配置。

## 名称、标题与注解 {#names-titles-and-annotations}

SDK 推断出来的一切，都可以在装饰器里覆盖：

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` 是给 UI 用的人类可读名称。客户端会显示“Search the catalog”，而不是 `search_books`。
* `annotations` 是给客户端的行为**提示**：
  * `read_only_hint=True`：这个工具不会改动任何东西。
  * `open_world_hint=False`：它针对的是一个封闭的集合（这份书目），而不是开放的互联网。
  * 另外两个，`destructive_hint` 和 `idempotent_hint`，描述的是会**写入**的工具：它会不会删除东西？调用两次和调用一次是不是一样？规范只为非只读工具定义了这两项，所以它们放在 `search_books` 上什么也说明不了。

守规矩的客户端会用它们来决定诸如“运行它之前要不要先问用户？”之类的事。它们是提示，不是安全机制。永远不要指望客户端一定会遵守。

!!! tip
    如果不想从函数名和文档字符串推导名称和描述，`@mcp.tool()` 也接受 `name=` 和 `description=`。大多数时候，直接推导就够了。

## 回顾 {#recap}

* 在函数上加 `@mcp.tool()`，它就成了工具。名称来自函数名，描述来自文档字符串。
* 类型提示**就是**输入模式。默认值让参数变为可选。
* `Annotated[..., Field(...)]` 添加描述和约束；`Literal` 添加枚举。
* 要接收结构化的“请求体”，就用 Pydantic 模型参数。
* 错误的参数会替你拒掉，并附带一条模型能读懂、也能据此纠正的错误信息。
* I/O 用 `async def`，其他一律用普通的 `def`。

**[结构化输出](structured-output.md)** 讲的是你 `return` 的值之后会怎样。
