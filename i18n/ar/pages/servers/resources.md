---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# الموارد {#resources}

**المورد** بيانات تتيحها ليقرأها التطبيق.

هذا هو الفرق. الأداة شيء يقرر **النموذج** استدعاءه. أما المورد فهو شيء يقرر **التطبيق** تحميله (ملف إعدادات أو سجل أو مستند) ووضعه أمام النموذج كسياق.

تعلن عنه بوضع `@mcp.resource(uri)` على دالة Python عادية.

## موردك الأول {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

له شكل الأداة نفسه، مع إضافة واحدة: **URI**. تُطلب الموارد بعناوينها لا بأسمائها. يطلب العميل `config://app`، وليس `get_config` أبدًا.

ما زالت SDK تقرأ الباقي من الدالة:

* **الاسم** هو اسم الدالة: `get_config`.
* **الوصف** الذي يراه العميل هو سلسلة التوثيق.
* **المحتوى** هو ما تعيده.

أثناء `resources/list` يتلقى العميل هذا:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

وعندما يقرأ `config://app`، تعمل دالتك وتعود القيمة المعادة كنص:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    عرض القائمة قليل التكلفة. **لا** تُستدعى دالتك أثناء `resources/list`، بل أثناء
    `resources/read` فقط، ولعنوان URI المطلوب فقط. أتح ألف مورد
    ولن تدفع تكلفة إلا للموارد التي يفتحها أحدهم.

### جرّبه {#try-it}

شغّل الخادم باستخدام MCP Inspector:

```console
uv run mcp dev server.py
```

افتح عنوان URL الذي يطبعه وانتقل إلى تبويب **Resources**. يظهر `config://app` في القائمة مع وصفه. انقر عليه فيقرؤه Inspector: ها هما سطرا إعداداتك.

## قوالب الموارد {#resource-templates}

استخدام URI لكل سجل لا يتوسع جيدًا. ضع **عنصرًا نائبًا** في URI ومَعلمة مطابقة في الدالة:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

`{user_id}` في URI، و`user_id: str` في الدالة. هذا هو العقد بالكامل.

أصبح هذا **قالب مورد**، ويتغير مكان عرضه: يغادر `resources/list` ويظهر بدلًا منه في `resources/templates/list`، كنمط بدلًا من عنوان:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

يملأ العميل العنصر النائب ويقرأ URI محددًا: `users://42/profile` أو `users://ada/profile`. تجيب دالة واحدة عن الجميع، مع تمرير القيمة المطابقة في `user_id`:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

لاحظ `uri` في النتيجة. إنه URI **المحدد** الذي طلبه العميل، وليس القالب.

!!! check
    يجب أن تتطابق العناصر النائبة والمَعلمات. غيّر اسم مَعلمة الدالة إلى
    `user` بينما لا يزال URI يحتوي على `{user_id}`، وسيرفض المزخرف ذلك **أثناء الاستيراد**،
    قبل أن يتصل أي عميل:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    عدم التطابق لا يمكن أن يكون إلا خطأ، لذلك تمنع SDK تشغيل الخادم في هذه الحالة.

صياغة العناصر النائبة هي [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570): تستخدم `{+path}` للقيم متعددة المقاطع، و`{?q,lang}` لمَعلمات الاستعلام الاختيارية، وغير ذلك. تطبّق SDK أيضًا فحوص أمان المسارات على القيم المستخرجة افتراضيًا. راجع **[قوالب URI وأمان المسارات](uri-templates.md)** للمرجع الكامل.

يمكن أن تأخذ `get_user_profile` أيضًا مَعلمة ذات تعليق نوع `Context`. تحقنها SDK دون اعتبارها مَعلمة URI، وتشرح صفحة **[السياق](../handlers/context.md)** ما توفره لك.

## ما تعيده {#what-you-return}

لست مقيدًا بـ`str`. امنح كل مورد `mime_type` وأعِد ما يناسبه:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* تعيد `readme` قيمة `str`، فتُرسل كما هي. هذه الحالة الشائعة.
* تعيد `catalog_stats` قاموس `dict`، فتسلسله SDK إلى **نص JSON** نيابة عنك:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* تعيد `placeholder_cover` قيمة `bytes`، فيتلقى العميل `BlobResourceContents` بدلًا من `TextResourceContents`، مع ترميز بايتاتك بصيغة base64 في حقل `blob`.

تنطبق القاعدة نفسها على أي شيء آخر قابل للتسلسل إلى JSON: قائمة أو نموذج Pydantic أو فئة بيانات. إذا لم يكن `str` أو `bytes`، يصبح JSON.

أنت من يعلن `mime_type`، وقيمته الافتراضية `text/plain`. لا تفحص SDK القيمة المعادة لتخمينه، لذلك يُعلن مورد `dict` الذي لم تحدد نوعه كنص عادي أيضًا.

!!! tip
    يقبل `@mcp.resource()` أيضًا `name=` و`title=` و`description=` عندما لا
    تريد اشتقاقها من الدالة. وعندما لا توجد دالة تحتاج إلى كتابتها أصلًا،
    توفر `mcp.server.mcpserver.resources` فئات `Resource` جاهزة (`TextResource` و
    `BinaryResource` و`FileResource` و`HttpResource` و`DirectoryResource`) تسجّلها
    باستخدام `mcp.add_resource(...)`.

يستطيع العميل أيضًا **الاشتراك** في مورد وتلقي إشعار عند تغيّره؛ وهذا جانب العميل، وتشرحه **[العميل](../client/index.md)**.

## مراجعة {#recap}

* وضع `@mcp.resource(uri)` على دالة يجعلها موردًا. URI هو العنوان، والقيمة المعادة هي المحتوى، وسلسلة التوثيق هي الوصف.
* وجود `{placeholder}` في URI يجعله **قالبًا**: يُعرض ضمن `resources/templates/list` وتخدم دالة واحدة كل URI مطابق.
* يجب أن تساوي أسماء العناصر النائبة أسماء مَعلمات الدالة. إذا أخطأت، ستعرف أثناء الاستيراد، لا في الإنتاج.
* تعمل دالتك عند **قراءة** المورد، لا عند عرضه في القائمة.
* تتحول `str` إلى نص، و`bytes` إلى كتلة ثنائية base64، وكل ما عداهما إلى نص JSON. وتحدد النوع باستخدام `mime_type=`.
* الأدوات ليتصرف النموذج. والموارد ليقرأها التطبيق.

العنصر الأساسي الثالث، الذي يختاره شخص من قائمة، هو **[قوالب التوجيه](prompts.md)**.
