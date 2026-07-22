# Structured Output

A tool that returns a plain `str` produces the result twice: as text in `content`, and as `{"result": "..."}` in `structured_content`.

This page is about that second channel: where it comes from, every shape it can take, and how the SDK keeps it honest.

The short version: **the return type annotation is the output schema**. You already wrote it.

## The output schema

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

The line that matters is the signature: `-> int`.

Because of it, the tool the SDK sends during `tools/list` carries an `output_schema` next to the input schema it builds from your parameters (**[Tools](tools.md)** covers that one):

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

A bare `int` isn't a JSON object, so the SDK **wraps** it in `{"result": ...}`. Call the tool and both channels are filled:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Every scalar gets the same wrapper: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Two channels

Why send the same value twice?

* `content` is for the **model**. A language model reads text; this is the only part of the result it sees.
* `structured_content` is for the **application** the model runs inside: code that wants `17`, not a sentence containing "17".
* `output_schema` is the contract between them, published before the tool is ever called.

You return one Python value. The SDK fills in all three.

## Return a model

Declare the shape as a Pydantic `BaseModel` and return an instance:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

`WeatherData` **is** the schema now. No wrapper, no `result` key:

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

`structured_content` is the object, field for field:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

And the model is not left out. The SDK serializes the same object to JSON text for `content`:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Notice the `Field(description=...)` on `temperature` and `humidity` landed in the schema. The same `Field` that described your **inputs** describes your outputs.

!!! info
    If you've used FastAPI's `response_model`, you already know this: a Pydantic model as the declared
    response, serialized and documented for you. The only difference is that here the return annotation
    is the whole declaration.

## A `TypedDict`

Not every shape deserves a class. A `TypedDict` produces the same schema:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

A `TypedDict` is a plain `dict` at runtime, so that is what you build and return. The schema, the validation, and `structured_content` are identical to the `BaseModel` version (minus the descriptions, which `TypedDict` has no place for).

## A dataclass

Dataclasses work too, and so does any ordinary class whose attributes have type hints. The SDK builds a Pydantic model out of the annotations behind the scenes.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Three spellings, one schema. Use whichever your codebase already has.

## Lists

A `list[...]` isn't a JSON object either, so it gets the `{"result": ...}` wrapper, with your item type as a `$defs` reference inside it:

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

Ask for a two-day forecast and `structured_content` is `{"result": [{...}, {...}]}`. `content` becomes **two** `TextContent` blocks, one per item: a list is flattened for the model rather than dumped as one string.

`tuple[...]`, unions, and `Optional[...]` are wrapped the same way.

## Dictionaries

`dict[str, ...]` is the one generic that already *is* a JSON object, so it isn't wrapped:

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

The keys must be `str`. A `dict[int, float]` can't be a JSON object, so it falls back to the `{"result": ...}` wrapper.

## Validation

`output_schema` is not documentation. Whatever your function returns is **validated against it** before it leaves the server.

You don't notice while you build the value by hand: Pydantic already made sure your `WeatherData` was a `WeatherData`. You notice the day the data comes from somewhere you don't control:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

The annotation promises `WeatherData`. The upstream response stopped sending `humidity`.

!!! check
    Call `get_weather` and it does not quietly hand the client a half-empty object. The call fails,
    and the first lines of the error name the field:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    That text comes back as the tool result with `is_error=True`, so the model knows the call failed
    instead of confidently reading weather that isn't there.

Returning a plain `dict` from a `-> WeatherData` tool is fine, by the way. That's exactly what `json.loads` produced. Validation is on the value, not on the Python type.

## Opting out

Sometimes the return annotation is for your type checker, not for the protocol. Pass `structured_output=False` and the tool is text-only:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

No `output_schema`, no wrapping, no validation. `structured_content` is `None` and `content` is the string you returned.

The opposite, `structured_output=True`, turns the automatic detection into a requirement: a tool whose return type can't produce a schema raises at import time instead of falling back to text.

## A class without type hints

There is one way to end up unstructured without asking for it: return a class that has **no annotations on its body**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` sets `name` and `online` inside `__init__`, but the *class* declares nothing. The SDK reads class annotations, finds none, and gives up.

!!! warning
    It gives up **silently**. `output_schema` is `None`, `structured_content` is `None`, and the text
    the model reads is the object's `repr`:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    No error, no warning, a useless tool. Move the annotations onto the class body, or pass
    `structured_output=True`, which turns this into a hard error the moment the module imports:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Need full control (building the `CallToolResult` yourself, or attaching `_meta` that the
    application can see but the model can't)? That's **[The low-level Server](../advanced/low-level-server.md)**.

## Skip the text copy

By default a structured tool fills **both** channels: `structured_content` for the application, and a serialized copy in `content` for the model. That copy is the spec's recommendation (a SHOULD, not a MUST) so an old client that only reads `content` still sees the value. When the payload is large, or the host routes `structured_content` to the model itself, the copy is wasted — the same data crosses the wire twice.

Pass `mirror_structured_content=False` to return `structured_content` only, with empty `content`:

```python
@mcp.tool(mirror_structured_content=False)
def list_accounts(segment: str) -> list[Account]:
    return query_accounts(segment)  # only structured_content is sent
```

The default is `True`, so nothing changes unless you opt out. A tool with no `output_schema` is unaffected — its `content` is the only representation and is always sent. If you want a *smaller* model-facing rendering rather than none, build the `CallToolResult` yourself and set `content` to a summary.

## Recap

* The **return type annotation** is the output schema. It's published in `tools/list` as `output_schema`.
* Scalars, lists, tuples and unions are wrapped in `{"result": ...}`. Models, `TypedDict`s, dataclasses, annotated classes and `dict[str, ...]` are objects already and stay as they are.
* Every result carries `content` (text, for the model) **and** `structured_content` (data, for the application) — unless you pass `mirror_structured_content=False`, which sends `structured_content` only.
* What you return is validated against the schema. A mismatch is a tool error, not a corrupt result.
* `structured_output=False` opts a tool out. A class without type hints opts out silently; watch for it.

You now own everything a tool can say back. Next, the second primitive: **[Resources](resources.md)**.
