---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# 分页 {#pagination}

大多数服务器永远用不到这个。

`MCPServer` 对每个 `list_*` 请求都一次返回它拥有的全部内容，只有一页，`next_cursor=None`。对于几十个工具、资源或提示词来说，这就是正确答案，没有什么需要配置的。

分页是给那种资源列表其实是一个数据库的服务器准备的：几千行数据，它不肯在一个响应里全部序列化。协议给出的答案是**游标（cursor）**：服务器返回一页数据外加一个不透明的令牌，客户端把这个令牌发回去，就能拿到下一页。

`@mcp.resource()` 没有为这些提供任何钩子。要分页，就得在 **[底层 Server](low-level-server.md)** 上自己写 list 处理函数。

## 会分页的服务器 {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* 在底层 `Server` 上，处理函数是构造函数参数，而不是装饰器。`on_list_resources` 响应每一个 `resources/list` 请求；整个接入就这些。
* 每个分页处理函数的类型标注都是 `params: PaginatedRequestParams | None`，示例对两种情况都做了处理。不过在连接上，SDK 永远不会交给你 `None`（没有 `params` 成员的请求到达处理函数时，是带默认值的模型实例），所以真正重要的信号是 `params.cursor is None`：**从头开始**。
* 游标**是**什么由你决定。这里是转成字符串的偏移量。时间戳、主键、base64 数据块：只要发出去时能生成、收回来时能认出，什么都行。
* `next_cursor=None` 表示“那是最后一页”。没有计数，没有总数，没有 `has_more`。`None` 就是全部信号。

!!! tip
    `PAGE_SIZE` 设为 10 是为了让示例好读。按端点选你自己的：一行一个的资源列表，一页放 500 个也负担得起；一堆臃肿的提示词模板列表就不行。客户端对此没有发言权，这是有意为之。

### 试一试 {#try-it}

`Client(server)` 在内存中连接底层 `Server` 的方式，和连接 `MCPServer` 完全一样。

不带参数调用 `list_resources()`。得到十个资源，从 `book-1` 到 `book-10`，`next_cursor` 是字符串 `"10"`。

用 `list_resources(cursor="10")` 把它交回去，第一个资源就是 `book-11`，新的 `next_cursor` 是 `"20"`。

第十页回来时 `next_cursor` 为 `None`。结束。

## 客户端循环 {#the-client-loop}

`Client` 上的每个 `list_*` 方法（`list_tools`、`list_resources`、`list_resource_templates`、`list_prompts`）都接受一个 `cursor=` 关键字参数。取完一个分页列表只需要一个 `while True`：

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` 起始为 `None`，所以第一个请求不带游标。
* 先 extend，**再**看 `next_cursor`：最后一页也有资源。
* `next_cursor is None` 是出口。其他任何值都原封不动地直接塞回 `cursor=`。

运行它的 `main()`，会打印 `100 resources`：十页、每页十个，由一个从头到尾都不知道有十页的循环拼在一起。

这和 **[客户端](../client/index.md)** 为每个 `list_*` 动词展示的是同一个循环，而且面对不分页的服务器也没有任何代价：第一个响应里 `next_cursor` 就是 `None`，循环只跑一次。

## 三条规则 {#the-three-rules}

**游标是不透明的。** 客户端绝不能解析、构造或猜测游标。游标唯一合法的来源是上一页的 `next_cursor`，一字不改。

**页大小由服务器决定。** 协议里没有 `limit=`。需要不同的页大小，就改服务器。

**忽略分页的客户端照样能用。** 它调用一次 `list_resources()`，拿到前十个，从没注意到自己扔掉的 `next_cursor`。什么都没坏；只是看到的少一些。

!!! check
    不透明就是不透明。自己编一个游标（`list_resources(cursor="page-2")`），协议帮不了你任何忙。这个服务器会尝试 `int("page-2")`，处理函数抛出异常，回到客户端的是：

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    不是从服务器拿到的游标是 bug，不是功能请求。

## 回顾 {#recap}

* `MCPServer` 把所有内容放在一页里返回。分页需要主动启用，启用的地方是底层 `Server`。
* `on_list_resources`（以及 `on_list_tools`、`on_list_prompts`、`on_list_resource_templates`）接收 `PaginatedRequestParams | None`；第一页时 `params.cursor` 为 `None`。
* 返回一页外加 `next_cursor`：任何以后能认出来的字符串，或者在没有剩余内容时返回 `None`。
* 客户端循环：传入 `cursor=`，累积，重复直到 `next_cursor is None`。
* 游标不透明，页大小归服务器管，不分页的客户端仍然能拿到第一页。

手写 `Server` API 的其余部分（`on_call_tool`、`input_schema` 字典、`_meta`）见 **[底层 Server](low-level-server.md)**。
