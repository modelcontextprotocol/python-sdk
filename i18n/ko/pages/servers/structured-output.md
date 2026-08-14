---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# 구조화된 출력 {#structured-output}

평범한 `str`을 반환하는 도구는 결과를 두 번 내놓습니다. `content`에는 텍스트로, `structured_content`에는 `{"result": "..."}` 형태로 담깁니다.

이 페이지는 그 두 번째 채널을 다룹니다. 이 채널이 어디에서 비롯되는지, 어떤 형태를 취할 수 있는지, 그리고 SDK가 이 채널이 선언과 어긋나지 않도록 어떻게 지키는지 설명합니다.

짧게 말하면 **반환 타입 어노테이션이 곧 출력 스키마**입니다. 이미 작성해 둔 셈입니다.

## 출력 스키마 {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

중요한 줄은 시그니처, 즉 `-> int` 부분입니다.

이 어노테이션이 있기 때문에, SDK가 `tools/list` 중에 보내는 도구에는 매개변수로부터 만든 입력 스키마(이쪽은 **[도구](tools.md)**에서 다룹니다) 옆에 `output_schema`가 함께 실립니다.

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

`int` 하나만으로는 JSON 객체가 아니므로 SDK가 이를 `{"result": ...}` 형태로 **감쌉니다**. 도구를 호출하면 두 채널이 모두 채워집니다.

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

모든 스칼라 값은 똑같이 감싸집니다. `str`, `int`, `float`, `bool`, `bytes`, `None`이 여기에 해당합니다.

## 두 채널 {#two-channels}

같은 값을 두 번 보내는 데는 이유가 있습니다.

* `content`는 **모델**을 위한 것입니다. 언어 모델은 텍스트를 읽으며, 결과 가운데 모델이 보는 부분은 이것뿐입니다.
* `structured_content`는 모델이 그 안에서 동작하는 **애플리케이션**, 즉 "17"이 들어간 문장이 아니라 숫자 `17` 자체를 원하는 코드를 위한 것입니다.
* `output_schema`는 이 둘 사이의 계약이며, 도구가 한 번이라도 호출되기 전에 공개됩니다.

반환하는 것은 Python 값 하나입니다. 세 가지 모두 SDK가 채웁니다.

## 모델 반환하기 {#return-a-model}

형태를 Pydantic `BaseModel`로 선언하고 인스턴스를 반환하세요.

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

이제 `WeatherData`가 **바로** 스키마입니다. 감싸는 것도, `result` 키도 없습니다.

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

`structured_content`는 필드 하나하나 그대로 이 객체입니다.

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

모델도 빠지지 않습니다. SDK가 같은 객체를 JSON 텍스트로 직렬화해 `content`에 담습니다.

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

`temperature`와 `humidity`에 붙인 `Field(description=...)` 설정이 스키마에 반영된 점을 눈여겨보세요. **입력**을 설명하던 바로 그 `Field`가 출력도 설명합니다.

!!! info
    FastAPI의 `response_model`을 써 본 적이 있다면 이미 아는 내용입니다. Pydantic 모델을 응답으로 선언하면 직렬화와 문서화가 알아서 이루어집니다. 유일한 차이는 여기서는 반환 어노테이션이 선언의 전부라는 점입니다.

## `TypedDict` {#a-typeddict}

모든 형태에 클래스가 필요한 것은 아닙니다. `TypedDict`로도 같은 스키마가 만들어집니다.

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

`TypedDict`는 런타임에 평범한 `dict`이므로, 바로 그 형태로 만들어서 반환하면 됩니다. 스키마와 검증, `structured_content`는 `BaseModel` 버전과 똑같습니다(설명은 빠지는데, `TypedDict`에는 설명을 둘 자리가 없기 때문입니다).

## 데이터클래스 {#a-dataclass}

데이터클래스도 되고, 속성에 타입 힌트가 달린 평범한 클래스라면 무엇이든 됩니다. SDK가 내부적으로 어노테이션을 바탕으로 Pydantic 모델을 만듭니다.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

표기법은 세 가지, 스키마는 하나입니다. 코드베이스에서 이미 쓰고 있는 방식을 사용하세요.

## 리스트 {#lists}

`list[...]` 역시 JSON 객체가 아니므로 `{"result": ...}` 형태로 감싸지며, 그 안에 항목 타입이 `$defs` 참조로 들어갑니다.

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

이틀치 예보를 요청하면 `structured_content`는 `{"result": [{...}, {...}]}` 형태가 됩니다. `content`는 항목마다 하나씩, **두 개**의 `TextContent` 블록이 됩니다. 리스트는 하나의 문자열로 통째로 쏟아 내는 대신 모델이 읽기 좋게 펼쳐집니다.

`tuple[...]`, 유니언, `Optional[...]`도 같은 방식으로 감싸집니다.

## 딕셔너리 {#dictionaries}

제네릭 가운데 `dict[str, ...]` 하나만은 **이미** 그 자체로 JSON 객체이므로 감싸지 않습니다.

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

키는 반드시 `str`이어야 합니다. `dict[int, float]` 타입은 JSON 객체가 될 수 없으므로 `{"result": ...}` 형태로 감싸는 방식으로 되돌아갑니다.

## 검증 {#validation}

`output_schema`는 문서가 아닙니다. 함수가 무엇을 반환하든 서버를 떠나기 전에 **이 스키마에 맞춰 검증됩니다**.

값을 직접 만드는 동안에는 이 사실이 눈에 띄지 않습니다. `WeatherData`가 정말 `WeatherData`인지는 Pydantic이 이미 확인해 두었기 때문입니다. 눈에 띄는 것은 데이터가 통제할 수 없는 곳에서 들어오는 날입니다.

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

어노테이션은 `WeatherData`를 약속합니다. 그런데 업스트림 응답이 더 이상 `humidity`를 보내지 않습니다.

!!! check
    `get_weather`를 호출해도 반쯤 빈 객체를 클라이언트에 슬그머니 넘기지 않습니다. 호출은 실패하고, 오류의 첫 몇 줄이 문제의 필드를 지목합니다.

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    이 텍스트는 `is_error=True` 상태의 도구 결과로 돌아오므로, 모델은 있지도 않은 날씨를 자신 있게 읽어 내는 대신 호출이 실패했다는 사실을 알게 됩니다.

참고로 `-> WeatherData` 도구에서 평범한 `dict`를 반환해도 괜찮습니다. 위 예제에서 `json.loads`가 만들어 낸 결과가 바로 평범한 딕셔너리였습니다. 검증 대상은 Python 타입이 아니라 값입니다.

## 구조화된 출력 끄기 {#opting-out}

반환 어노테이션이 프로토콜이 아니라 타입 체커를 위한 것일 때도 있습니다. `structured_output=False` 옵션을 전달하면 도구는 텍스트만 내놓습니다.

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

`output_schema`도, 감싸기도, 검증도 없습니다. `structured_content`는 `None`이고 `content`는 반환한 문자열 그대로입니다.

반대로 `structured_output=True` 옵션은 자동 감지를 필수 요건으로 바꿉니다. 반환 타입으로 스키마를 만들 수 없는 도구는 텍스트로 물러나는 대신 임포트 시점에 예외를 일으킵니다.

## 타입 힌트가 없는 클래스 {#a-class-without-type-hints}

요청하지 않았는데도 구조화되지 않은 결과로 끝나는 길이 하나 있습니다. **본문에 어노테이션이 전혀 없는** 클래스를 반환하는 경우입니다.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station`은 `__init__` 안에서 `name`과 `online`을 설정하지만, **클래스** 자체는 아무것도 선언하지 않습니다. SDK는 클래스 어노테이션을 읽고, 아무것도 찾지 못하면 포기합니다.

!!! warning
    게다가 **조용히** 포기합니다. `output_schema`는 `None`, `structured_content`도 `None`이 되고, 모델이 읽는 텍스트는 객체의 `repr`입니다.

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    오류도 경고도 없이 쓸모없는 도구만 남습니다. 어노테이션을 클래스 본문으로 옮기거나 `structured_output=True` 옵션을 전달하세요. 후자는 모듈을 임포트하는 순간 이 문제를 `Function get_station: return type <class 'server.Station'> is not serializable for structured output`이라는 확실한 오류로 바꿔 줍니다.

!!! tip
    완전한 제어(`CallToolResult`를 직접 만들거나, 애플리케이션은 볼 수 있지만 모델은 볼 수 없는 `_meta`를 붙이는 것)가 필요하다면 **[저수준 Server](../advanced/low-level-server.md)**를 살펴보세요.

## 요약 {#recap}

* **반환 타입 어노테이션**이 곧 출력 스키마입니다. `tools/list`에서 `output_schema`로 공개됩니다.
* 스칼라, 리스트, 튜플, 유니언은 `{"result": ...}` 형태로 감싸집니다. 모델, `TypedDict`, 데이터클래스, 어노테이션이 달린 클래스, 그리고 `dict[str, ...]` 타입은 이미 객체이므로 그대로 유지됩니다.
* 모든 결과에는 `content`(모델을 위한 텍스트)와 `structured_content`(애플리케이션을 위한 데이터)가 **함께** 담깁니다.
* 반환한 값은 스키마에 맞춰 검증됩니다. 어긋나면 손상된 결과가 아니라 도구 오류가 됩니다.
* `structured_output=False` 옵션으로 도구의 구조화된 출력을 끌 수 있습니다. 타입 힌트가 없는 클래스는 아무 경고 없이 꺼지므로 주의하세요.

이제 도구가 돌려줄 수 있는 모든 것을 손에 넣었습니다. 다음은 두 번째 프리미티브인 **[리소스](resources.md)**입니다.
