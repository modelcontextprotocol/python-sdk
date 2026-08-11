---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Структурований вивід {#structured-output}

Інструмент, що повертає звичайний `str`, видає результат двічі: як текст у `content` і як `{"result": "..."}` у `structured_content`.

Ця сторінка — про той другий канал: звідки він береться, яких форм може набувати і як SDK стежить, щоб він не брехав.

Коротко: **анотація типу, що повертається, і є схемою виводу**. Ви її вже написали.

## Схема виводу {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

Важливий рядок — сигнатура: `-> int`.

Завдяки їй інструмент, який SDK надсилає під час `tools/list`, несе `output_schema` поруч зі схемою вводу, побудованою з параметрів (її описано на сторінці **[Інструменти](tools.md)**):

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

Голий `int` — це не JSON-об'єкт, тому SDK **загортає** його в `{"result": ...}`. Викличте інструмент — і обидва канали заповнені:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Таку саму обгортку отримує кожен скаляр: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Два канали {#two-channels}

Навіщо надсилати те саме значення двічі?

* `content` — для **моделі**. Мовна модель читає текст; це єдина частина результату, яку вона бачить.
* `structured_content` — для **застосунку**, усередині якого працює модель: коду, якому потрібне `17`, а не речення зі словом «17».
* `output_schema` — це контракт між ними, опублікований ще до першого виклику інструмента.

Ви повертаєте одне значення Python. SDK заповнює всі три.

## Повернення моделі {#return-a-model}

Оголосіть форму як `BaseModel` з Pydantic і поверніть екземпляр:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

Тепер схемою **є** сам `WeatherData`. Без обгортки, без ключа `result`:

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

`structured_content` — це сам об'єкт, поле в поле:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

І модель не лишається осторонь. SDK серіалізує той самий об'єкт у JSON-текст для `content`:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Зверніть увагу: `Field(description=...)` на `temperature` і `humidity` потрапили до схеми. Той самий `Field`, що описував **вхідні дані**, описує й вихідні.

!!! info
    Якщо ви користувалися `response_model` у FastAPI, це вам знайомо: модель Pydantic як оголошена
    відповідь, серіалізована й задокументована за вас. Єдина відмінність — тут усе оголошення
    вичерпується анотацією типу, що повертається.

## `TypedDict` {#a-typeddict}

Не кожна форма заслуговує на клас. `TypedDict` дає таку саму схему:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

Під час виконання `TypedDict` — це звичайний `dict`, тож саме його ви будуєте й повертаєте. Схема, валідація і `structured_content` ідентичні версії з `BaseModel` (за винятком описів, для яких у `TypedDict` немає місця).

## Dataclass {#a-dataclass}

Dataclass теж підходять, як і будь-який звичайний клас, атрибути якого мають анотації типів. SDK усередині будує з анотацій модель Pydantic.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Три записи — одна схема. Беріть той, що вже є у вашій кодовій базі.

## Списки {#lists}

`list[...]` — теж не JSON-об'єкт, тому він отримує обгортку `{"result": ...}`, а тип елемента всередині неї — посилання на `$defs`:

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

Запитайте прогноз на два дні — і `structured_content` буде `{"result": [{...}, {...}]}`. `content` перетворюється на **два** блоки `TextContent`, по одному на елемент: список для моделі розгортається, а не зливається в один рядок.

`tuple[...]`, об'єднання типів і `Optional[...]` загортаються так само.

## Словники {#dictionaries}

`dict[str, ...]` — єдиний узагальнений тип, що вже *є* JSON-об'єктом, тому він не загортається:

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

Ключі мають бути `str`. `dict[int, float]` не може бути JSON-об'єктом, тож він повертається до обгортки `{"result": ...}`.

## Валідація {#validation}

`output_schema` — це не документація. Усе, що повертає функція, **перевіряється на відповідність їй** перед тим, як залишити сервер.

Поки значення будується вручну, цього не помічаєш: Pydantic уже подбав, щоб `WeatherData` був `WeatherData`. Помічаєш того дня, коли дані приходять звідкись, що ви не контролюєте:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

Анотація обіцяє `WeatherData`. Відповідь зовнішнього сервісу перестала надсилати `humidity`.

!!! check
    Викличте `get_weather` — і він не передасть клієнту тихцем напівпорожній об'єкт. Виклик завершується помилкою,
    і перші рядки помилки називають поле:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    Цей текст повертається як результат інструмента з `is_error=True`, тож модель знає, що виклик не вдався,
    замість того щоб упевнено читати погоду, якої немає.

До речі, повертати звичайний `dict` з інструмента з `-> WeatherData` цілком можна. Саме це й видав `json.loads`. Перевіряється значення, а не тип Python.

## Відмова від структурованого виводу {#opting-out}

Іноді анотація типу, що повертається, призначена для перевірки типів, а не для протоколу. Передайте `structured_output=False` — і інструмент стане лише текстовим:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

Ні `output_schema`, ні обгортки, ні валідації. `structured_content` дорівнює `None`, а `content` — рядок, який ви повернули.

Протилежне, `structured_output=True`, перетворює автоматичне визначення на вимогу: інструмент, чий тип повернення не може дати схему, викидає виняток під час імпорту замість відкоту до тексту.

## Клас без анотацій типів {#a-class-without-type-hints}

Є один спосіб опинитися без структурованого виводу, не просивши про це: повернути клас, у **тілі якого немає анотацій**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` задає `name` і `online` всередині `__init__`, але сам *клас* нічого не оголошує. SDK читає анотації класу, не знаходить жодної й здається.

!!! warning
    Здається він **мовчки**. `output_schema` — `None`, `structured_content` — `None`, а текст,
    який читає модель, — це `repr` об'єкта:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Ні помилки, ні попередження — непридатний інструмент. Перенесіть анотації в тіло класу або передайте
    `structured_output=True`, що перетворює це на жорстку помилку в момент імпорту модуля:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Потрібен повний контроль (самостійно збудувати `CallToolResult` або додати `_meta`, які
    застосунок бачить, а модель — ні)? Це — **[Низькорівневий Server](../advanced/low-level-server.md)**.

## Підсумки {#recap}

* **Анотація типу, що повертається**, — це схема виводу. Вона публікується в `tools/list` як `output_schema`.
* Скаляри, списки, кортежі й об'єднання типів загортаються в `{"result": ...}`. Моделі, `TypedDict`, dataclass, анотовані класи й `dict[str, ...]` — уже об'єкти й лишаються як є.
* Кожен результат несе `content` (текст, для моделі) **і** `structured_content` (дані, для застосунку).
* Те, що ви повертаєте, перевіряється на відповідність схемі. Невідповідність — це помилка інструмента, а не зіпсований результат.
* `structured_output=False` вимикає це для інструмента. Клас без анотацій типів вимикає це мовчки; пильнуйте.

Тепер ви володієте всім, що інструмент може сказати у відповідь. Далі — другий примітив: **[Ресурси](resources.md)**.
