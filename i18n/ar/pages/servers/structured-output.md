---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, 91be9b73602abcf1, 6cdbad079f7b47f0, d4b607372fb28b51, 7608fc5ebc31d6ea, c7eff2a5698225fa, c851964bb3301907, 8f296f1f09e4c400, d715db6f8dccc9cc, a0c344a48450dbe4]
  tool: 1
---
# المخرجات المنظّمة {#structured-output}

تنتج الأداة التي تعيد `str` عادية النتيجة مرتين: كنص في `content`، وكـ`{"result": "..."}` في `structured_content`.

تتناول هذه الصفحة القناة الثانية: مصدرها، وجميع الأشكال التي يمكن أن تتخذها، وكيف تضمن SDK صحتها.

الفكرة المختصرة: **تعليق نوع الإرجاع هو مخطط المخرجات**. وقد كتبته بالفعل.

## مخطط المخرجات {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

السطر المهم هو التوقيع: `-> int`.

بسببه، تحمل الأداة التي ترسلها SDK أثناء `tools/list` حقل `output_schema` بجانب مخطط المدخلات الذي تبنيه من مَعلماتك (تغطي **[الأدوات](tools.md)** ذلك المخطط):

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

لا يشكّل `int` منفرد كائن JSON، لذا **تغلّفه** SDK في `{"result": ...}`. استدعِ الأداة فتُملأ القناتان:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

تحصل كل قيمة مفردة على الغلاف نفسه: `str` و`int` و`float` و`bool` و`bytes` و`None`.

## قناتان {#two-channels}

لماذا تُرسل القيمة نفسها مرتين؟

* `content` مخصص لـ**النموذج**. يقرأ النموذج اللغوي النص؛ وهذا الجزء الوحيد من النتيجة الذي يراه.
* `structured_content` مخصص لـ**التطبيق** الذي يعمل النموذج داخله: شيفرة تريد `17`، لا جملة تحتوي على "17".
* `output_schema` هو العقد بينهما، ويُنشَر قبل أي استدعاء للأداة.

تعيد قيمة Python واحدة. وتملأ SDK الثلاثة جميعًا.

## أعِد نموذجًا {#return-a-model}

أعلن الشكل باستخدام `BaseModel` من Pydantic وأعِد نسخة منه:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

أصبحت `WeatherData` **هي** المخطط. لا غلاف ولا مفتاح `result`:

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

`structured_content` هو الكائن بكل حقوله:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

ولا يُترك النموذج اللغوي دون محتوى. تسلسِل SDK الكائن نفسه إلى نص JSON في `content`:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

لاحظ أن `Field(description=...)` على `temperature` و`humidity` ظهرت في المخطط. تصف `Field` نفسها التي وصفت **مدخلاتك** مخرجاتك أيضًا.

!!! info
    إذا استخدمت `response_model` في FastAPI، فأنت تعرف ذلك: نموذج Pydantic للاستجابة
    المعلنة، يجري تسلسله وتوثيقه نيابة عنك. الفرق الوحيد هنا أن تعليق نوع الإرجاع
    هو الإعلان بأكمله.

## استخدام `TypedDict` {#a-typeddict}

لا يحتاج كل شكل إلى فئة. ينتج `TypedDict` المخطط نفسه:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

يكون `TypedDict` قاموس `dict` عاديًا أثناء التشغيل، لذلك فهذا ما تبنيه وتعيده. يتبع المخطط والتحقق و`structured_content` القواعد نفسها في إصدار `BaseModel`: أضف سلسلة توثيق للفئة أو `Annotated[..., Field(description=...)]` فتصبح الأوصاف، وإذا تركت مفتاح `NotRequired` خارج القاموس، يبقى خارج `structured_content`.

## فئة بيانات {#a-dataclass}

تعمل فئات البيانات أيضًا، وكذلك أي فئة عادية تملك خصائصها تلميحات أنواع. تبني SDK داخليًا نموذج Pydantic من التعليقات.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

ثلاث صيغ ومخطط واحد. استخدم ما هو موجود أصلًا في قاعدة شيفرتك.

## القوائم {#lists}

لا تكون `list[...]` كائن JSON أيضًا، لذا تحصل على غلاف `{"result": ...}`، مع نوع عناصرها كمرجع `$defs` داخله:

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

اطلب توقعات يومين، فيكون `structured_content` هو `{"result": [{...}, {...}]}`. ويتحول `content` إلى كتلتَي `TextContent`، **اثنتين**، واحدة لكل عنصر: تُفك القائمة إلى عناصر للنموذج بدلًا من تحويلها إلى سلسلة واحدة.

تُغلَّف `tuple[...]` واتحادات الأنواع و`Optional[...]` بالطريقة نفسها.

## القواميس {#dictionaries}

`dict[str, ...]` هو النوع العام الوحيد الذي *يشكّل* كائن JSON أصلًا، لذلك لا يُغلَّف:

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

يجب أن تكون المفاتيح `str`. لا يمكن أن يكون `dict[int, float]` كائن JSON، لذلك يعود إلى غلاف `{"result": ...}`.

تستخدم نتائج القواميس `TypeAdapter` من Pydantic للتحقق والتسلسل. إذا فحصت `FuncMetadata.output_model` لأداة، فستجده يحمل تعليق نوع القاموس مع عنوان مخططه.

## التحقق {#validation}

ليس `output_schema` مجرد توثيق. **يُتحقَّق من توافق** كل ما تعيده دالتك معه قبل خروجه من الخادم.

لن تلاحظ ذلك عندما تبني القيمة يدويًا: فقد تأكدت Pydantic بالفعل أن `WeatherData` لديك هي `WeatherData`. ستلاحظه حين تأتي البيانات من مصدر لا تتحكم فيه:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

يَعِد التعليق بإعادة `WeatherData`. لكن الاستجابة من الخدمة الأخرى توقفت عن إرسال `humidity`.

!!! check
    استدعِ `get_weather`، ولن يمرّر كائنًا نصف فارغ إلى العميل بصمت. يفشل الاستدعاء:
    يتلقى العميل `is_error=True` مع `Error executing tool get_weather`، فيعرف النموذج أن
    الاستدعاء فشل بدلًا من قراءة معلومات طقس غير موجودة بثقة. أما اسم الحقل فهو لك،
    في سجل الخادم بمستوى `ERROR`:

    ```text
    Tool 'get_weather' raised an unexpected exception
    ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

وبالمناسبة، لا بأس بإعادة `dict` عادية من أداة تعلن `-> WeatherData`. وهذا بالضبط ما أنتجته `json.loads`. يجري التحقق من القيمة، لا من نوع Python.

## تعطيل المخرجات المنظّمة {#opting-out}

يكون تعليق الإرجاع أحيانًا مخصصًا لفاحص الأنواع لا للبروتوكول. مرّر `structured_output=False` فتصبح الأداة نصية فقط:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

لا `output_schema` ولا تغليف ولا تحقق. تكون `structured_content` هي `None`، و`content` السلسلة التي أعدتها.

أما العكس، `structured_output=True`، فيحوّل الاكتشاف التلقائي إلى شرط: تثير الأداة التي لا يستطيع نوع إرجاعها إنتاج مخطط استثناءً أثناء الاستيراد بدلًا من الاكتفاء بالنص.

## كتل المحتوى والوسائط {#content-blocks-and-media}

تُستثنى كتل المحتوى والوسائط (`TextContent` و`EmbeddedResource` و`Image` و`Audio` وما شابه، منفردة أو كعناصر `list` أو `tuple` أو `Sequence`، أو كبدائل ضمن اتحاد أنواع) تلقائيًا: فهي مخصصة لقراءة النموذج، لذا لا يشتق الاكتشاف التلقائي مخططًا منها (تغطي **[الصور والصوت والأيقونات](media.md)** كلًّا من `Image` و`Audio`). ما زال `structured_output=True` يفرض مخططًا لفئات كتل المحتوى.

## فئة دون تلميحات أنواع {#a-class-without-type-hints}

هناك طريقة واحدة للحصول على مخرجات غير منظّمة دون طلب ذلك: إعادة فئة **لا توجد تعليقات أنواع في جسمها**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

تعيّن `Station` كلًّا من `name` و`online` داخل `__init__`، لكن *الفئة* لا تعلن شيئًا. تقرأ SDK تعليقات الفئة فلا تجد أيًّا منها، وتتوقف عن المحاولة.

!!! warning
    يحدث ذلك **بصمت**. تكون `output_schema` هي `None`، و`structured_content` هي `None`، والنص
    الذي يقرؤه النموذج هو `repr` للكائن:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    لا خطأ ولا تحذير، وأداة غير مفيدة. انقل التعليقات إلى جسم الفئة، أو مرّر
    `structured_output=True` لتحويل هذا إلى خطأ صريح لحظة استيراد الوحدة:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    هل تحتاج إلى تحكم كامل (بناء `CallToolResult` بنفسك، أو إرفاق `_meta` يستطيع
    التطبيق رؤيتها ولا يستطيع النموذج)؟ راجع **[الخادم منخفض المستوى](../advanced/low-level-server.md)**.

## مراجعة {#recap}

* **تعليق نوع الإرجاع** هو مخطط المخرجات. يُنشر في `tools/list` باسم `output_schema`.
* تُغلَّف القيم المفردة والقوائم والصفوف واتحادات الأنواع في `{"result": ...}`. أما النماذج و`TypedDict` وفئات البيانات والفئات ذات تعليقات الأنواع و`dict[str, ...]` فهي كائنات أصلًا وتبقى كما هي.
* تحمل كل نتيجة `content` (نصًا للنموذج) **و**`structured_content` (بيانات للتطبيق).
* يُتحقَّق من القيمة المعادة مقابل المخطط. عدم التطابق خطأ أداة، لا نتيجة تالفة.
* يستثني `structured_output=False` الأداة. تُستثنى كتل المحتوى و`Image` و`Audio` افتراضيًا؛ وتُستثنى الفئة دون تلميحات أنواع بصمت، لذا انتبه إليها.

أصبحت تتحكم الآن في كل ما يمكن أن تعيده الأداة. التالي هو العنصر الأساسي الثاني: **[الموارد](resources.md)**.
