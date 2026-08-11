---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# 結構化輸出 {#structured-output}

回傳普通 `str` 的工具會把結果產生兩份：一份是 `content` 裡的文字，一份是 `structured_content` 裡的 `{"result": "..."}`。

這一頁談的就是第二個通道：它從哪裡來、可以有哪些形狀，以及 SDK 如何確保它名副其實。

簡單說：**回傳型別註記就是輸出 schema**。你早就寫好了。

## 輸出 schema {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

重要的是簽章那一行：`-> int`。

因為有它，SDK 在 `tools/list` 送出的工具，除了從參數建出的輸入 schema（這部分在 **[工具](tools.md)** 說明），旁邊還帶了一個 `output_schema`：

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

單獨一個 `int` 不是 JSON 物件，所以 SDK 會把它**包**進 `{"result": ...}`。呼叫這個工具，兩個通道都會填上：

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

每種純量都會套上同樣的包裝：`str`、`int`、`float`、`bool`、`bytes`、`None`。

## 兩個通道 {#two-channels}

為什麼同一個值要送兩次？

* `content` 是給**模型**的。語言模型讀的是文字，結果裡它只看得到這個部分。
* `structured_content` 是給模型所在的**應用程式**的：那些程式碼要的是 `17`，不是一句包含「17」的話。
* `output_schema` 是兩者之間的合約，在工具被呼叫之前就已經公布。

你回傳一個 Python 值，SDK 把三者都填好。

## 回傳一個模型 {#return-a-model}

把形狀宣告成 Pydantic `BaseModel`，再回傳一個實例：

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

現在 `WeatherData` **就是** schema。沒有包裝，也沒有 `result` 鍵：

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

`structured_content` 就是這個物件，一個欄位都不差：

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

模型也沒被冷落。SDK 會把同一個物件序列化成 JSON 文字放進 `content`：

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

注意 `temperature` 和 `humidity` 上的 `Field(description=...)` 進到了 schema 裡。用來描述**輸入**的那個 `Field`，同樣可以描述輸出。

!!! info
    如果用過 FastAPI 的 `response_model`，這一套你早就認識了：把 Pydantic 模型宣告為回應，序列化和文件都幫你做好。唯一的差別是，這裡的回傳註記就是全部的宣告。

## `TypedDict` {#a-typeddict}

不是每個形狀都值得寫一個類別。`TypedDict` 會產生同樣的 schema：

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

`TypedDict` 在執行時就是普通的 `dict`，所以建立並回傳的就是它。schema、驗證和 `structured_content` 都跟 `BaseModel` 版本一模一樣（少了描述，因為 `TypedDict` 沒有地方放）。

## dataclass {#a-dataclass}

dataclass 也可以，任何屬性帶有型別提示的普通類別也都可以。SDK 會在背後用這些註記建出一個 Pydantic 模型。

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

三種寫法，同一個 schema。程式碼庫裡已經用哪一種，就用哪一種。

## 串列 {#lists}

`list[...]` 同樣不是 JSON 物件，所以也會套上 `{"result": ...}` 包裝，元素型別則以 `$defs` 參照的形式放在裡面：

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

要兩天的預報，`structured_content` 就是 `{"result": [{...}, {...}]}`。`content` 則變成**兩個** `TextContent` 區塊，每個元素一個：串列會為模型攤平，而不是整個倒成一個字串。

`tuple[...]`、union 和 `Optional[...]` 也用同樣的方式包裝。

## 字典 {#dictionaries}

`dict[str, ...]` 是唯一本身**就是** JSON 物件的泛型，所以不會被包裝：

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

鍵必須是 `str`。`dict[int, float]` 沒辦法成為 JSON 物件，所以會退回 `{"result": ...}` 包裝。

## 驗證 {#validation}

`output_schema` 不是寫來看的說明文件。函式回傳的任何東西，在離開伺服器之前都會**拿它來驗證**。

自己手動建值的時候感覺不到：Pydantic 早就確保 `WeatherData` 確實是 `WeatherData`。等到哪天資料來自你無法掌控的地方，就會感覺到了：

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

註記承諾的是 `WeatherData`，但上游回應不再送 `humidity` 了。

!!! check
    呼叫 `get_weather`，它不會默默把一個半空的物件交給用戶端。呼叫會失敗，錯誤的頭幾行就點名了那個欄位：

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    這段文字會以 `is_error=True` 的工具結果回傳，所以模型知道呼叫失敗了，而不是信心滿滿地讀一份根本不存在的天氣。

順帶一提，從 `-> WeatherData` 的工具回傳普通的 `dict` 沒問題，`json.loads` 產生的正是這個。驗證看的是值，不是 Python 型別。

## 選擇退出 {#opting-out}

有時候回傳註記是寫給型別檢查器看的，不是給協定用的。傳入 `structured_output=False`，工具就只有文字：

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

沒有 `output_schema`、沒有包裝、沒有驗證。`structured_content` 是 `None`，`content` 就是你回傳的字串。

反過來，`structured_output=True` 會把自動偵測變成硬性要求：回傳型別產生不出 schema 的工具，會在匯入時引發例外，而不是退回文字。

## 沒有型別提示的類別 {#a-class-without-type-hints}

有一種情況會在沒有要求的前提下變成非結構化：回傳一個**本體上沒有任何註記**的類別。

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` 在 `__init__` 裡設定了 `name` 和 `online`，但**類別**本身什麼都沒宣告。SDK 讀取類別註記，什麼都沒找到，於是放棄。

!!! warning
    而且是**默默**放棄。`output_schema` 是 `None`，`structured_content` 是 `None`，模型讀到的文字是物件的 `repr`：

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    沒有錯誤、沒有警告，只有一個沒用的工具。把註記移到類別本體上，或者傳入 `structured_output=True`，後者會在模組匯入的那一刻把這件事變成硬性錯誤：`Function get_station: return type <class 'server.Station'> is not serializable for structured output`。

!!! tip
    需要完全掌控（自己建構 `CallToolResult`，或附上應用程式看得到但模型看不到的 `_meta`）？請見 **[低階 Server](../advanced/low-level-server.md)**。

## 重點回顧 {#recap}

* **回傳型別註記**就是輸出 schema，會在 `tools/list` 裡以 `output_schema` 公布。
* 純量、串列、tuple 和 union 會包進 `{"result": ...}`。模型、`TypedDict`、dataclass、帶註記的類別和 `dict[str, ...]` 本來就是物件，維持原樣。
* 每個結果都帶有 `content`（文字，給模型）**和** `structured_content`（資料，給應用程式）。
* 回傳的東西會拿 schema 驗證。不符合就是工具錯誤，不會是一份壞掉的結果。
* `structured_output=False` 讓工具退出。沒有型別提示的類別會默默退出，要留意。

工具能回覆的一切，現在都掌握在你手上了。接下來是第二個基本元件：**[資源](resources.md)**。
