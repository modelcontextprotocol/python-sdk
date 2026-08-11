---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Structured output {#structured-output}

जो tool सादा `str` लौटाता है, वह result दो बार देता है: `content` में text के रूप में, और `structured_content` में `{"result": "..."}` के रूप में।

यह page उसी दूसरे channel के बारे में है: यह कहाँ से आता है, यह किन-किन रूपों में हो सकता है, और SDK इसे भरोसेमंद कैसे रखता है।

संक्षेप में: **return type annotation ही output schema है**। वह आप पहले ही लिख चुके हैं।

## Output schema {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

जो line मायने रखती है वह signature है: `-> int`।

इसी की वजह से `tools/list` के दौरान SDK जो tool भेजता है, उसमें input schema के साथ-साथ `output_schema` भी होता है। input schema आपके parameters से बनता है (उसकी जानकारी **[Tools](tools.md)** में है):

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

अकेला `int` JSON object नहीं है, इसलिए SDK उसे `{"result": ...}` में **wrap** कर देता है। tool को call करें और दोनों channel भर जाते हैं:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

हर scalar को यही wrapper मिलता है: `str`, `int`, `float`, `bool`, `bytes`, `None`।

## दो channel {#two-channels}

एक ही value दो बार क्यों भेजें?

* `content` **model** के लिए है। language model text पढ़ता है; result का यही हिस्सा उसे दिखता है।
* `structured_content` उस **application** के लिए है जिसके अंदर model चलता है: वह code जिसे `17` चाहिए, न कि ऐसा वाक्य जिसमें "17" आता हो।
* `output_schema` इन दोनों के बीच का करार है, जो tool के पहली बार call होने से पहले ही publish हो जाता है।

आप एक Python value लौटाते हैं। SDK तीनों भर देता है।

## Model लौटाना {#return-a-model}

आकार को Pydantic `BaseModel` के रूप में declare करें और उसका instance लौटाएँ:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

अब `WeatherData` ही schema **है**। न कोई wrapper, न `result` key:

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

`structured_content` वही object है, field दर field:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

और model को भी नहीं भूला गया। SDK उसी object को `content` के लिए JSON text में serialize करता है:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

ध्यान दें, `temperature` और `humidity` पर लगा `Field(description=...)` schema में पहुँच गया। जो `Field` आपके **inputs** का वर्णन करता था, वही आपके outputs का भी वर्णन करता है।

!!! info
    अगर आपने FastAPI का `response_model` इस्तेमाल किया है तो यह आपको पहले से पता है: declared
    response के रूप में Pydantic model, जो आपके लिए serialize और document हो जाता है। फ़र्क सिर्फ़ इतना है कि यहाँ return annotation
    ही पूरा declaration है।

## `TypedDict` {#a-typeddict}

हर आकार के लिए class बनाना ज़रूरी नहीं। `TypedDict` से भी वही schema बनता है:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

runtime पर `TypedDict` सादा `dict` होता है, इसलिए आप वही बनाते और लौटाते हैं। schema, validation और `structured_content` ठीक `BaseModel` वाले version जैसे हैं (descriptions को छोड़कर, जिनके लिए `TypedDict` में कोई जगह नहीं)।

## Dataclass {#a-dataclass}

dataclasses भी काम करते हैं, और हर वह साधारण class भी जिसके attributes पर type hints हों। SDK अंदर ही अंदर annotations से Pydantic model बना लेता है।

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

तीन लिखावटें, एक schema। जो आपके codebase में पहले से है, वही इस्तेमाल करें।

## Lists {#lists}

`list[...]` भी JSON object नहीं है, इसलिए इसे भी `{"result": ...}` wrapper मिलता है, और आपका item type उसके अंदर `$defs` reference के रूप में आता है:

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

दो दिन का forecast माँगें और `structured_content` होगा `{"result": [{...}, {...}]}`। `content` **दो** `TextContent` blocks बन जाता है, हर item के लिए एक: model के लिए list को एक string में dump करने के बजाय सपाट कर दिया जाता है।

`tuple[...]`, unions और `Optional[...]` भी इसी तरह wrap होते हैं।

## Dictionaries {#dictionaries}

`dict[str, ...]` वह इकलौता generic है जो पहले से ही JSON object **है**, इसलिए यह wrap नहीं होता:

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

keys का `str` होना ज़रूरी है। `dict[int, float]` JSON object नहीं बन सकता, इसलिए यह वापस `{"result": ...}` wrapper पर आ जाता है।

## Validation {#validation}

`output_schema` documentation नहीं है। आपका function जो भी लौटाता है, server से बाहर जाने से पहले उसे **इसके मुक़ाबले validate** किया जाता है।

जब तक आप value हाथ से बनाते हैं, इसका पता नहीं चलता: Pydantic पहले ही पक्का कर चुका होता है कि आपका `WeatherData` सच में `WeatherData` है। पता उस दिन चलता है जब data ऐसी जगह से आता है जो आपके हाथ में नहीं:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

annotation `WeatherData` का वादा करता है। upstream response ने `humidity` भेजना बंद कर दिया।

!!! check
    `get_weather` को call करें और यह चुपचाप client को आधा-खाली object नहीं थमाता। call fail होता है,
    और error की पहली lines field का नाम बताती हैं:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    यह text `is_error=True` के साथ tool result बनकर लौटता है, ताकि model को पता रहे कि call fail हुआ है,
    बजाय इसके कि वह पूरे भरोसे से ऐसा मौसम पढ़े जो है ही नहीं।

वैसे, `-> WeatherData` वाले tool से सादा `dict` लौटाना ठीक है। `json.loads` ने ठीक वही तो बनाया था। validation value पर होता है, Python type पर नहीं।

## इससे बाहर रहना {#opting-out}

कभी-कभी return annotation आपके type checker के लिए होता है, protocol के लिए नहीं। `structured_output=False` pass करें और tool सिर्फ़ text वाला हो जाता है:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

न `output_schema`, न wrapping, न validation। `structured_content` `None` है और `content` वह string है जो आपने लौटाई।

इसका उल्टा, `structured_output=True`, automatic detection को शर्त बना देता है: जिस tool का return type schema नहीं बना सकता, वह text पर वापस आने के बजाय import के समय ही raise करता है।

## बिना type hints वाली class {#a-class-without-type-hints}

बिना माँगे unstructured रह जाने का एक तरीका है: ऐसी class लौटाना जिसकी **body पर कोई annotations न हों**।

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` `__init__` के अंदर `name` और `online` set करती है, लेकिन **class** ख़ुद कुछ declare नहीं करती। SDK class annotations पढ़ता है, कोई नहीं मिलता, और हार मान लेता है।

!!! warning
    वह **चुपचाप** हार मानता है। `output_schema` `None` है, `structured_content` `None` है, और जो text
    model पढ़ता है वह object का `repr` है:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    न error, न warning, बस एक बेकार tool। annotations को class body पर ले जाएँ, या
    `structured_output=True` pass करें, जो module के import होते ही इसे hard error बना देता है:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`।

!!! tip
    पूरा control चाहिए (`CallToolResult` ख़ुद बनाना, या ऐसा `_meta` जोड़ना जो
    application देख सके पर model नहीं)? उसके लिए **[Low-level Server](../advanced/low-level-server.md)** है।

## सारांश {#recap}

* **return type annotation** ही output schema है। यह `tools/list` में `output_schema` के रूप में publish होता है।
* scalars, lists, tuples और unions `{"result": ...}` में wrap होते हैं। models, `TypedDict`, dataclasses, annotated classes और `dict[str, ...]` पहले से object हैं और जैसे हैं वैसे ही रहते हैं।
* हर result में `content` (text, model के लिए) **और** `structured_content` (data, application के लिए) होता है।
* आप जो लौटाते हैं वह schema के मुक़ाबले validate होता है। मेल न खाना tool error है, ख़राब result नहीं।
* `structured_output=False` tool को इससे बाहर रखता है। बिना type hints वाली class चुपचाप बाहर हो जाती है; इस पर नज़र रखें।

अब tool जो कुछ भी जवाब में कह सकता है, वह सब आपके हाथ में है। आगे, दूसरा primitive: **[Resources](resources.md)**।
