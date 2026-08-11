---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# 结构化输出 {#structured-output}

返回普通 `str` 的工具会把结果产出两次：一次是 `content` 里的文本，一次是 `structured_content` 里的 `{"result": "..."}`。

本页讲的就是这第二个通道：它从哪里来、可能有哪些形态，以及 SDK 如何保证它货真价实。

一句话概括：**返回类型注解就是输出模式（output schema）**。你其实已经写好了。

## 输出模式 {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

重要的是签名那一行：`-> int`。

有了它，SDK 在 `tools/list` 时发出的工具除了根据参数构建的输入模式（详见 **[工具](tools.md)**），还会带上一个 `output_schema`：

```json
{
  "properties": {
    "result": {"title": "Result", "type": "integer"}
  },
  "required": ["result"],
  "title": "get_temperatureOutput",
  "type": "object"
}
```

单独一个 `int` 不是 JSON 对象，所以 SDK 把它**包装**进 `{"result": ...}`。调用这个工具，两个通道都有内容：

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

所有标量都是同样的包装：`str`、`int`、`float`、`bool`、`bytes`、`None`。

## 两个通道 {#two-channels}

为什么同一个值要发两次？

* `content` 是给**模型**看的。语言模型读的是文本；整个结果里它只看得到这一部分。
* `structured_content` 是给模型所在的**应用程序**用的：代码想要的是 `17`，而不是一句含有“17”的话。
* `output_schema` 是二者之间的契约，早在工具被调用之前就已发布。

你只返回一个 Python 值，SDK 把这三样全部填好。

## 返回模型 {#return-a-model}

用 Pydantic `BaseModel` 声明形状，并返回一个实例：

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

现在 `WeatherData` **就是**模式。没有包装，也没有 `result` 键：

```json
{
  "properties": {
    "temperature": {"description": "Degrees Celsius.", "title": "Temperature", "type": "number"},
    "humidity": {"description": "Relative humidity, 0 to 1.", "title": "Humidity", "type": "number"},
    "conditions": {"title": "Conditions", "type": "string"}
  },
  "required": ["temperature", "humidity", "conditions"],
  "title": "WeatherData",
  "type": "object"
}
```

`structured_content` 就是这个对象，字段逐一对应：

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

语言模型也没有被落下。SDK 把同一个对象序列化为 JSON 文本，放进 `content`：

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

注意，`temperature` 和 `humidity` 上的 `Field(description=...)` 进入了模式。描述**输入**的那个 `Field`，同样描述了输出。

!!! info
    如果用过 FastAPI 的 `response_model`，这一套你已经熟悉：把 Pydantic 模型声明为响应，序列化和文档都替你做好。唯一的不同是，在这里返回注解就是全部的声明。

## `TypedDict` {#a-typeddict}

不是每种形状都值得专门写一个类。`TypedDict` 产出的模式完全一样：

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

`TypedDict` 在运行时就是普通的 `dict`，所以构建并返回的也就是它。模式、校验和 `structured_content` 都与 `BaseModel` 版本完全相同（只是少了描述，`TypedDict` 里没有地方写）。

## dataclass {#a-dataclass}

dataclass 也行，任何属性带类型提示的普通类同样可以。SDK 会在幕后根据注解构建出一个 Pydantic 模型。

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

三种写法，一个模式。代码库里本来用哪种，就用哪种。

## 列表 {#lists}

`list[...]` 也不是 JSON 对象，所以同样套上 `{"result": ...}` 包装，元素类型以 `$defs` 引用的形式放在里面：

```python title="server.py" hl_lines="15"
--8<-- "docs_src/structured_output/tutorial005.py"
```

```json
{
  "$defs": {
    "WeatherData": {
      "properties": {
        "temperature": {"title": "Temperature", "type": "number"},
        "humidity": {"title": "Humidity", "type": "number"},
        "conditions": {"title": "Conditions", "type": "string"}
      },
      "required": ["temperature", "humidity", "conditions"],
      "title": "WeatherData",
      "type": "object"
    }
  },
  "properties": {
    "result": {"items": {"$ref": "#/$defs/WeatherData"}, "title": "Result", "type": "array"}
  },
  "required": ["result"],
  "title": "get_forecastOutput",
  "type": "object"
}
```

请求两天的预报，`structured_content` 就是 `{"result": [{...}, {...}]}`。`content` 则变成**两个** `TextContent` 块，每个元素一个：列表会为模型逐项展开，而不是整个转储成一个字符串。

`tuple[...]`、联合类型和 `Optional[...]` 的包装方式相同。

## 字典 {#dictionaries}

`dict[str, ...]` 是唯一一个本身**就是** JSON 对象的泛型，所以不会被包装：

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial006.py"
```

```json
{
  "additionalProperties": {"type": "number"},
  "title": "get_temperaturesDictOutput",
  "type": "object"
}
```

```python
result.structured_content  # {"London": 16.2, "Reykjavik": 4.4}
```

键必须是 `str`。`dict[int, float]` 成不了 JSON 对象，所以会退回到 `{"result": ...}` 包装。

## 校验 {#validation}

`output_schema` 并非只是文档。函数返回的任何内容，在离开服务器之前都会**对照它校验**。

手工构建值的时候你察觉不到：Pydantic 早已保证你的 `WeatherData` 确实是 `WeatherData`。等到哪天数据来自你控制不了的地方，你就会察觉了：

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

注解承诺的是 `WeatherData`，上游响应却不再发送 `humidity` 了。

!!! check
    调用 `get_weather`，它不会悄悄把一个缺了一半的对象递给客户端。调用会失败，错误的头几行直接点名那个字段：

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    这段文本作为工具结果返回，并带着 `is_error=True`，于是模型知道调用失败了，而不会信心十足地去读根本不存在的天气数据。

顺带一提，从 `-> WeatherData` 的工具里返回普通 `dict` 完全没问题。`json.loads` 产出的正是它。校验针对的是值，而不是 Python 类型。

## 选择退出 {#opting-out}

有时返回注解是写给类型检查器看的，而不是给协议的。传入 `structured_output=False`，工具就变成纯文本：

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

没有 `output_schema`，没有包装，没有校验。`structured_content` 为 `None`，`content` 就是你返回的字符串。

反过来，`structured_output=True` 会把自动检测变成硬性要求：返回类型产不出模式的工具会在导入时直接抛错，而不是退回到纯文本。

## 没有类型提示的类 {#a-class-without-type-hints}

有一种情况，你没有要求也会落得非结构化：返回一个**类体上没有任何注解**的类。

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` 在 `__init__` 里设置了 `name` 和 `online`，但**类**本身什么都没声明。SDK 去读类注解，一个也没找到，于是放弃。

!!! warning
    而且是**悄无声息地**放弃。`output_schema` 是 `None`，`structured_content` 是 `None`，模型读到的文本是这个对象的 `repr`：

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    没有报错，没有警告，只剩一个没用的工具。把注解挪到类体上，或者传入 `structured_output=True`——后者会在模块导入的那一刻就让它直接报错：`Function get_station: return type <class 'server.Station'> is not serializable for structured output`。

!!! tip
    需要完全掌控（自己构建 `CallToolResult`，或者附加应用程序看得见、模型看不见的 `_meta`）？详见 **[底层 Server](../advanced/low-level-server.md)**。

## 回顾 {#recap}

* **返回类型注解**就是输出模式，在 `tools/list` 中以 `output_schema` 发布。
* 标量、列表、元组和联合类型会被包装进 `{"result": ...}`。模型、`TypedDict`、dataclass、带注解的类以及 `dict[str, ...]` 本身已是对象，保持原样。
* 每个结果都同时带有 `content`（文本，给模型）**和** `structured_content`（数据，给应用程序）。
* 返回的内容会对照模式校验。不匹配就是工具错误，而不是一个损坏的结果。
* `structured_output=False` 让工具退出结构化输出。没有类型提示的类会悄无声息地退出；要当心。

至此，工具能回传的一切都由你掌控。接下来是第二种原语：**[资源](resources.md)**。
