---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 864137b5e9c61e91, 043f526230dd243d, db1ef91db7d6b3f3]
  tool: 1
---
# الوسائط {#media}

النص ليس الشيء الوحيد الذي تستطيع الأداة إعادته.

توفّر SDK كائنين مساعدين للنتائج الثنائية (**`Image`** و**`Audio`**) ونوع **`Icon`** لمنح خادمك وأدواتك ومواردك وقوالب توجيهك مظهرًا في واجهة العميل.

## إعادة صورة {#returning-an-image}

أعلن نوع الإرجاع `Image`، وحدد ملفًا لها، ثم أعِدها:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* تقبل `Image` واحدًا فقط من `path` (ملف للقراءة) أو `data` (بايتات خام).
* يُستنتَج نوع MIME الذي يراه العميل من اللاحقة: يُعلَن `logo.png` كـ`image/png`.
* لا شيء هنا خاص بالشعارات. تعمل أي صورة PNG بجانب `server.py`: رسم بياني أنتجته شيفرتك أو مخطط أو صورة فوتوغرافية.

`Image` وسيلة مساعدة في SDK، وليست نوعًا في البروتوكول. أثناء النقل، تصبح القيمة المعادة كتلة **`ImageContent`** (بايتات الملف بترميز base64 مع نوع MIME):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

لاحظ أمرين:

* `data` بترميز base64. لم تتعامل مع البايتات؛ قرأت SDK الملف ورمّزته.
* تكون `structured_content` هي `None`. فـ`Image` محتوى ينظر إليه النموذج، لا بيانات يحلّلها التطبيق: لا يوجد مخطط مخرجات. (قارن بـ**[المخرجات المنظّمة](structured-output.md)**، حيث تعليق الإرجاع *هو* المخطط.)

!!! info
    توجد `ImageContent` و`AudioContent` في `mcp.types`، بجانب `TextContent`
    التي تنتج عن قيمة `str` عادية (**[الأدوات](tools.md)**). نتيجة الأداة قائمة كتل محتوى؛ و`Image` و`Audio`
    أقصر طريقة لإنتاج النوعين الثنائيين.

### جرّبها {#try-it}

ضع أي صورة PNG بجانب `server.py` باسم `logo.png`، وشغّل:

```console
uv run mcp dev server.py
```

افتح تبويب **Tools** واستدعِ `logo`. النتيجة ليست سلسلة نصية: إنها كتلة محتوى `image`، ويعرض Inspector صورتك. تتولى SDK كل ما بين الملف على القرص والبكسلات على الشاشة.

## إعادة صوت {#returning-audio}

لـ`Audio` الشكل نفسه. اترك `logo.png` في مكانه، وضع بجانبه أي ملف WAV باسم `chime.wav`:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

تكون النتيجة كتلة **`AudioContent`**:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

الفكرة نفسها: ملف على القرص يدخل، وbase64 ونوع MIME يخرجان، دون مخطط مخرجات.

## بايتات أو ملف {#bytes-or-a-file}

يقبل الكائنان المساعدان أيضًا `data=` (بايتات خام) بدلًا من `path=`. هذا مناسب لبايتات لم تأتِ من ملف مستقل: عمود قاعدة بيانات أو استجابة HTTP أو رسم أنتجته Pillow للتو:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

مع `path=`، لا تحتاج إلى إعلان شيء: يُقرأ الملف عند بناء النتيجة، ويُستنتَج نوع MIME من اللاحقة:

* `Image`: `.png`، `.jpg`، `.jpeg`، `.gif`، `.webp`.
* `Audio`: `.wav`، `.mp3`، `.ogg`، `.flac`، `.aac`، `.m4a`.

إذا لم تُعرف اللاحقة، يُستخدم `application/octet-stream`.

!!! check
    مع `data=` لا يوجد اسم ملف للاستنتاج منه. إذا نسيت `format=`،
    تعود SDK إلى قيمة افتراضية: `image/png` للصور و`audio/wav` للصوت. إذا بنيت
    `Audio` من بايتات MP3 بهذه الطريقة، يُبلَّغ العميل بأن `mime_type="audio/wav"`،
    فيفشل في فك الترميز رغم اتباعه التعليمات. عند تمرير `data=`، مرّر `format=`.

## تضمين مورد {#embedding-a-resource}

تستطيع الأداة أيضًا إعادة مستند: نص أو بايتات مع URI الذي يوجد عليه ونوع MIME. هذا **`EmbeddedResource`**، نوع آخر من كتل المحتوى. بخلاف `str` العادية، يخبر العميل بماهية المحتوى، فيستطيع عرضه كمرفق أو التعرف على مورد يعرفه مسبقًا.

```python title="server.py" hl_lines="7 14 16-18"
--8<-- "docs_src/media/tutorial005.py"
```

* `brand://guidelines` مورد عادي (تغطي **[الموارد](resources.md)** ذلك). تعطي الأداة المستند نفسه للنموذج عند الطلب، ويحافظ استدعاء `guidelines()` مباشرة على مصدر حقيقة واحد.
* تأتي `EmbeddedResource` و`TextResourceContents` من `mcp.types`. لا يوجد كائن مساعد مثل الصور: تدخل الكتلة التي تبنيها في النتيجة دون تغيير، ولا توجد `structured_content`.
* استخدم URI الذي سُجّل المورد عليه، كي يعرف العميل أن المرفق و`brand://guidelines` المستند نفسه. أي URI صالح، سواء كان مسجلًا أم لا.

```python
result.content  # [EmbeddedResource(type="resource", resource=TextResourceContents(uri="brand://guidelines", mime_type="text/markdown", text="# Brand guidelines\n\n..."))]
```

للمحتوى الثنائي، استخدم `BlobResourceContents(uri=..., mime_type=..., blob=...)` مع البايتات بترميز base64 في `blob`، بدلًا من `TextResourceContents`. لإرسال مرجع فقط يستطيع العميل قراءته لاحقًا باستخدام `resources/read`، أعِد `ResourceLink(name=..., uri=...)`؛ فهو كتلة محتوى أيضًا.

## الأيقونات {#icons}

`Icon` بيانات وصفية، لا محتوى. لا تحمل الصورة؛ بل تشير إليها باستخدام URI، ويمكن للعميل جلبها وعرضها بجانب اسم خادمك أو أداة أو مورد أو قالب توجيه.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` عنوان URI يستطيع العميل حله: `https:`، أو URI من نوع `data:` إذا أردت تضمين الأيقونة دون جلب إضافي.
* تتيح `mime_type` و`sizes` (`"48x48"`، أو `"any"` لتنسيق قابل للتحجيم) للعميل اختيار المناسب عند توفير عدة أيقونات.
* يحدد `theme="light"` أو `theme="dark"` أيقونة لنظام ألوان معين.

تقبل `MCPServer(...)` و`@mcp.tool()` و`@mcp.resource()` و`@mcp.prompt()` جميعًا الوسيطة `icons=[...]` نفسها.

### أين يراها العميل؟ {#where-a-client-sees-them}

تنتقل الأيقونات مع العناصر التي تزيّنها. تصل أيقونات الخادم عند اتصال العميل، في `client.server_info` (اختيارية في اتصالات جيل 2026، فتحقق من توفرها أولًا):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

توجد أيقونات الأداة على كائن `Tool` من `tools/list`، وأيقونات المورد على `Resource` من `resources/list`، وأيقونات قالب التوجيه على `Prompt` من `prompts/list`. يُسمّى الحقل دائمًا `icons`.

## مراجعة {#recap}

* أعِد `Image` أو `Audio` من أداة، فيتلقى العميل كتلة `ImageContent` / `AudioContent`: بايتاتك بترميز base64 مع نوع MIME.
* ابنِ الكائن من `path=` ودع اللاحقة تحدد نوع MIME، أو من `data=` داخل الذاكرة مع `format=` صريح.
* أعِد `EmbeddedResource` لوضع مستند (نص أو كتلة ثنائية base64، مع URI ونوع MIME) في النتيجة، أو `ResourceLink` لإرسال المرجع فقط.
* لا تحمل نتائج الوسائط `structured_content` أو مخطط مخرجات.
* `Icon` مرجع: URI في `src` مع `mime_type` و`sizes` و`theme` اختيارية.
* تعمل `icons=[...]` على الخادم والأدوات والموارد وقوالب التوجيه، ويجدها العملاء على الكائنات المقابلة.

هذا كل ما تستطيع الأداة وضعه *داخل* نتيجة. أما ما يحدث عندما *تفشل* الأداة (ومن ينبغي أن يعرف)، فتشرحه **[معالجة الأخطاء](handling-errors.md)**.
