---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Структурированный вывод {#structured-output}

Инструмент, возвращающий обычную строку `str`, выдаёт результат дважды: как текст в `content` и как `{"result": "..."}` в `structured_content`.

Эта страница посвящена второму каналу: откуда он берётся, какие формы может принимать и как SDK следит за его корректностью.

Если коротко: **аннотация возвращаемого типа и есть выходная схема**. Вы её уже написали.

## Выходная схема {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

Важна строка с сигнатурой: `-> int`.

Благодаря ей инструмент, который SDK отправляет в ответ на `tools/list`, несёт `output_schema` рядом с входной схемой, построенной по параметрам (о ней — на странице **[Инструменты](tools.md)**):

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

Голое значение `int` — не JSON-объект, поэтому SDK **оборачивает** его в `{"result": ...}`. Вызовите инструмент — и оба канала заполнены:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Ту же обёртку получает любой скаляр: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Два канала {#two-channels}

Зачем отправлять одно и то же значение дважды?

* `content` — для **модели**. Языковая модель читает текст; это единственная часть результата, которую она видит.
* `structured_content` — для **приложения**, внутри которого работает модель: для кода, которому нужно `17`, а не предложение, содержащее «17».
* `output_schema` — контракт между ними, опубликованный ещё до первого вызова инструмента.

Вы возвращаете одно значение Python. SDK заполняет все три.

## Возврат модели {#return-a-model}

Объявите форму как Pydantic `BaseModel` и верните экземпляр:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

Теперь схема — **это** `WeatherData`. Ни обёртки, ни ключа `result`:

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

`structured_content` — это сам объект, поле за полем:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

И модель не остаётся в стороне. SDK сериализует тот же объект в JSON-текст для `content`:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Обратите внимание: `Field(description=...)` у `temperature` и `humidity` попали в схему. Тот же `Field`, который описывал **входы**, описывает и выходы.

!!! info
    Если вы пользовались `response_model` в FastAPI, вам это уже знакомо: модель Pydantic как объявленный
    ответ, который за вас сериализуется и документируется. Единственное отличие — здесь всё объявление
    сводится к аннотации возвращаемого типа.

## `TypedDict` {#a-typeddict}

Не каждая форма заслуживает класса. `TypedDict` даёт ту же схему:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

Во время выполнения `TypedDict` — обычный `dict`, его вы и собираете и возвращаете. Схема, валидация и `structured_content` идентичны варианту с `BaseModel` (за вычетом описаний, которые в `TypedDict` разместить негде).

## Dataclass {#a-dataclass}

Dataclass тоже подходят, как и любой обычный класс, атрибуты которого снабжены аннотациями типов. SDK незаметно строит модель Pydantic по этим аннотациям.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Три способа записи — одна схема. Используйте тот, что уже принят в вашей кодовой базе.

## Списки {#lists}

`list[...]` тоже не JSON-объект, поэтому получает обёртку `{"result": ...}`, а тип элемента попадает внутрь как ссылка `$defs`:

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

Запросите прогноз на два дня — и `structured_content` будет `{"result": [{...}, {...}]}`. `content` превращается в **два** блока `TextContent`, по одному на элемент: для модели список раскладывается поэлементно, а не сваливается в одну строку.

`tuple[...]`, объединения и `Optional[...]` оборачиваются так же.

## Словари {#dictionaries}

`dict[str, ...]` — единственный дженерик, который уже *является* JSON-объектом, поэтому он не оборачивается:

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

Ключи должны быть `str`. `dict[int, float]` не может быть JSON-объектом, поэтому для него применяется запасной вариант — обёртка `{"result": ...}`.

## Валидация {#validation}

`output_schema` — не документация. Всё, что возвращает функция, **проверяется на соответствие схеме** до того, как покинет сервер.

Пока значение собирается вручную, этого не замечаешь: Pydantic уже позаботился о том, чтобы `WeatherData` был `WeatherData`. Заметно становится в тот день, когда данные приходят из источника, который вы не контролируете:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

Аннотация обещает `WeatherData`. Ответ вышестоящего сервиса перестал присылать `humidity`.

!!! check
    Вызовите `get_weather` — и он не передаст клиенту молча полупустой объект. Вызов завершается ошибкой,
    и первые же строки ошибки называют поле:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    Этот текст возвращается как результат инструмента с `is_error=True`, так что модель знает, что вызов
    не удался, а не уверенно читает погоду, которой нет.

Кстати, вернуть обычный `dict` из инструмента с `-> WeatherData` вполне допустимо. Именно это и выдал `json.loads`. Проверяется значение, а не тип Python.

## Отказ от структурированного вывода {#opting-out}

Иногда аннотация возвращаемого типа нужна для проверки типов, а не для протокола. Передайте `structured_output=False` — и инструмент станет чисто текстовым:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

Ни `output_schema`, ни обёртки, ни валидации. `structured_content` равен `None`, а `content` — строка, которую вы вернули.

Обратный вариант, `structured_output=True`, превращает автоматическое определение в требование: инструмент, по возвращаемому типу которого нельзя построить схему, выбрасывает исключение при импорте, а не переключается на текст.

## Класс без аннотаций типов {#a-class-without-type-hints}

Есть один способ оказаться без структурированного вывода, не прося об этом: вернуть класс, в **теле которого нет аннотаций**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` задаёт `name` и `online` внутри `__init__`, но сам *класс* ничего не объявляет. SDK читает аннотации класса, не находит ни одной и сдаётся.

!!! warning
    Сдаётся он **молча**. `output_schema` равен `None`, `structured_content` равен `None`, а текст,
    который читает модель, — это `repr` объекта:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Ни ошибки, ни предупреждения — бесполезный инструмент. Перенесите аннотации в тело класса или передайте
    `structured_output=True`, что превратит это в жёсткую ошибку в момент импорта модуля:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Нужен полный контроль (собирать `CallToolResult` самостоятельно или прикреплять `_meta`, которые
    видит приложение, но не модель)? Это **[Низкоуровневый Server](../advanced/low-level-server.md)**.

## Итоги {#recap}

* **Аннотация возвращаемого типа** — это выходная схема. Она публикуется в `tools/list` как `output_schema`.
* Скаляры, списки, кортежи и объединения оборачиваются в `{"result": ...}`. Модели, `TypedDict`, dataclass, классы с аннотациями и `dict[str, ...]` уже являются объектами и остаются как есть.
* Каждый результат несёт `content` (текст, для модели) **и** `structured_content` (данные, для приложения).
* Возвращаемое значение проверяется на соответствие схеме. Несоответствие — это ошибка инструмента, а не испорченный результат.
* `structured_output=False` отключает структурированный вывод для инструмента. Класс без аннотаций типов отключает его молча — следите за этим.

Теперь вы владеете всем, что инструмент может сказать в ответ. Дальше — второй примитив: **[Ресурсы](resources.md)**.
