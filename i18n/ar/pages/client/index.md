---
translation:
  sections: [ebef1e7a0df854f4, 7e16449f66e7dfd6, eeb0682f7d2a1079, 5713f0196a34e6e7, 0e844597859e4248, 3a97d9195ddcc92e, 1da08c483e59c141, 84702cc6e0a1fd42, 8dee7a31c86ffc5c, 83a5bce168ef23d7]
  tool: 1
---
# العميل {#the-client}

**`Client`** وسيلة برنامج Python للتواصل مع خادم MCP.

كائن واحد بدورة حياة واحدة: أنشئه، وادخل `async with`، واستدعِ الطرق. كل عملية في البروتوكول (عرض الأدوات أو استدعاء واحدة أو قراءة مورد أو توليد رسائل قالب توجيه) طريقة `async` عليه تعيد نتيجة محددة النوع.

## عميلك الأول {#your-first-client}

يحتاج العميل إلى خادم يتواصل معه. خادم Bookshop هذا هو ما تتصل به كل أمثلة الصفحة. احفظه باسم `server.py` واتركه يعمل عبر HTTP:

```python title="server.py"
--8<-- "docs_src/client/tutorial001.py"
```

```console
uv run mcp run server.py --transport streamable-http
```

يُتاح على `http://localhost:8000/mcp`. العميل برنامج مستقل. احفظه باسم `client.py` وشغّل `python client.py` في نافذة طرفية ثانية:

```python title="client.py" hl_lines="7-11"
--8<-- "docs_src/client/tutorial001_client.py"
```

* تتلقى `Client("http://localhost:8000/mcp")` **URL**، فتتصل عبر Streamable HTTP بالخادم الذي بدأته للتو.
* `async with` هي **دورة الحياة**. الدخول يتصل ويتفاوض؛ والخروج يقطع الاتصال. لا زوج `connect()` / `close()`، ولا يمكن إعادة استخدام `Client` بعد انتهاء الكتلة.
* داخل الكتلة، تكون معلومات الاتصال موجودة بالفعل كخصائص عادية.

### ما تستطيع تمريره إلى `Client` {#what-you-can-pass-to-client}

تأخذ `Client` وسيطة موضعية واحدة وتحدد وسيلة النقل من نوعها:

* سلسلة URL (`Client("http://localhost:8000/mcp")`): Streamable HTTP، وسيلة النقل التي تنشر عبرها.
* `StdioServerParameters`: الأمر الذي يُشغَّل كـ**عملية فرعية** محلية، ويجري التواصل معه عبر stdin وstdout.
* **وسيلة نقل**: أي شيء تستطيع استخدامه بصيغة `async with ... as (read, write)`، مثل `streamable_http_client(url, http_client=...)` حول عميل HTTP الخاص بك.
* نسخة `MCPServer` (أو `Server` منخفض المستوى): اتصال **داخل العملية**، دون عملية فرعية أو منفذ. هذا للاختبارات، وتبني عليه **[الاختبار](../get-started/testing.md)**.

بقية هذه الصفحة متطابقة في الأشكال الأربعة. للترويسات والعمليات الفرعية والمهل وبروتوكول `Transport` صفحة خاصة: **[وسائل نقل العميل](transports.md)**.

### ما يوجد على عميل متصل {#whats-on-a-connected-client}

أربع خصائص للقراءة فقط، تُملأ بمجرد دخول الكتلة:

* `client.server_info`: هوية الخادم، أو `None` لخادم جيل 2026 لا يقدّمها (تقدّمها خوادم python-sdk افتراضيًا). هنا `server_info.name` هي `"Bookshop"`، و`server_info.version` ما يعلنه الخادم.
* `client.server_capabilities`: ما يستطيع الخادم فعله (`tools` و`resources` و`prompts` و`completions`، ...). القدرة التي لا يملكها الخادم هي `None`.
* `client.protocol_version`: إصدار البروتوكول الذي اتفق عليه الطرفان. وهو هنا `"2026-07-28"`.
* `client.instructions`: سلسلة `instructions=` للخادم، أو `None` إذا لم يعيّنها.

لم تختر إصدار بروتوكول. تفحص `Client` الخادم افتراضيًا وتعود إلى المصافحة التقليدية مع الخوادم الأقدم، فيعمل عميل واحد مع أي جيل خادم. إذا احتجت إلى التحكم بذلك، فتتضمن **[إصدارات البروتوكول](../protocol-versions.md)** التفاصيل كاملة.

!!! tip
    `client.session` هي `ClientSession` الأساسية، منفذ التحكم المباشر منخفض المستوى.
    لن تحتاج إليها لأي شيء في هذه الصفحة.

## عرض الأدوات {#listing-tools}

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client/tutorial002.py"
```

تعيد `list_tools()` كائن `ListToolsResult`؛ وتوجد الأدوات في `.tools`. كل منها تعريف كامل يقدّمه المضيف للنموذج. إليك الأولى:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

و`tool.input_schema` هو JSON Schema الذي اشتقه الخادم من تلميحات أنواع الدالة:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

ذلك المخطط كل ما تحتاج إليه الواجهة لعرض نموذج وسائط، وكل ما يحتاج إليه النموذج لإنتاج وسائط صالحة.

سُجّلت الأداة الثانية `lookup_book` دون `title=`، لذا تكون `tool.title` هي `None`.

!!! tip
    `title` اختياري، لذا يجب على واجهة تعرض الأدوات لشخص الاختيار: `title` إن وُجد،
    وإلا `name`. تفعل `from mcp.shared.metadata_utils import get_display_name` ذلك بالضبط
    للأدوات والموارد وقوالب الموارد وقوالب التوجيه.

## استدعاء أداة {#calling-a-tool}

تشغّل `call_tool(name, arguments)` الأداة وتعيد `CallToolResult`.

```python title="client.py" hl_lines="9-16"
--8<-- "docs_src/client/tutorial003.py"
```

تعيد `lookup_book` على الخادم نموذج Pydantic باسم `Book`. إليك ما يراه العميل:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

قيمة إرجاع واحدة وثلاثة أشياء للقراءة. لكل منها مستهلك مختلف.

### `content`: ما يقرؤه النموذج {#content-what-the-model-reads}

`content` هي `list` من **كتل المحتوى**، وكتلة المحتوى اتحاد أنواع: `TextContent` أو `ImageContent` أو `AudioContent` أو `ResourceLink` أو `EmbeddedResource`. تستطيع الأداة إعادة عدة كتل من أنواع مختلفة.

لذلك تضيّق `main` النوع باستخدام `isinstance(block, TextContent)` قبل الوصول إلى `block.text`. لاحظ غياب `.text` خارج `isinstance`: يمنعه فاحص الأنواع لأن `ImageContent` تملك `.data` لا `.text`. يعكس اتحاد الأنواع بدقة ما يجوز للأداة إرساله؛ وينبغي لشيفرتك مراعاة ذلك أيضًا.

### `structured_content`: ما يقرؤه تطبيقك {#structured_content-what-your-application-reads}

`structured_content` هي قيمة إرجاع الأداة بصيغة JSON، مطابقة لـ`output_schema` المعلنة للأداة. لا تحليل نصوص ولا تخمين.

عند وجودهما معًا، يعبّران عن الشيء نفسه مرتين عمدًا: `content` للنموذج و`structured_content` للشيفرة. مصدر الجزء المنظّم وكيفية التحكم به في صفحة **[المخرجات المنظّمة](../servers/structured-output.md)**.

### `is_error`: هل فشلت الأداة؟ {#is_error-whether-the-tool-failed}

الأداة التي تثير استثناءً **لا** تثيره في عميلك. تعود كنتيجة عادية مع `is_error=True`.

!!! check
    اطلب من `lookup_book` العنوان `"Solaris"` (غير الموجود في الفهرس)، فتثير الدالة
    `ToolError`. ما زال الاستدعاء يعود بصورة عادية:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    تظهر رسالة `ToolError` في `content` حيث يستطيع **النموذج** قراءتها والمحاولة مجددًا. هذا
    مقصود: خطأ الأداة جزء من المحادثة، لا انهيار. (لو انهارت الأداة
    باستثناء آخر، لما قالت `content` إلا `Error executing tool lookup_book`.) افحص دائمًا
    `is_error` قبل الوثوق بـ`structured_content`.

!!! warning
    يشمل `is_error=True` أكثر من `raise` التي تكتبها. اطلب أداة لا يملكها الخادم أصلًا
    (`call_tool("does_not_exist", {})`)، ولا يُثار استثناء. تحصل على الشكل نفسه:
    `is_error=True` مع `Unknown tool: does_not_exist` في `content`. لا تثير طريقة `Client`
    الاستثناء `MCPError` إلا عندما يجيب الخادم بـ**خطأ** JSON-RPC بدلًا من نتيجة،
    وتغطي **[معالجة الأخطاء](../servers/handling-errors.md)** متى ينتج الخادم كل نوع.

## الموارد {#resources}

عمليات الموارد مترابطة: طريقتان لعرض القوائم وطريقة للقراءة.

```python title="client.py" hl_lines="9-18"
--8<-- "docs_src/client/tutorial004.py"
```

* تعيد `list_resources()` الموارد **المحددة**، ذات URI ثابت. هنا: `['catalog://genres']`.
* تعيد `list_resource_templates()` الموارد **ذات المَعلمات**. هنا: `['catalog://genres/{genre}']`. هما قائمتان مختلفتان لأن القالب لا يُقرأ حتى تملأه.
* تأخذ `read_resource(uri)` عنوان URI كـ`str` عادية وتعمل مع النوعين: مرّر `"catalog://genres/poetry"` فيطابقه الخادم بالقالب.

تعيد `read_resource` الحقل `contents`، وهو قائمة `TextResourceContents` أو `BlobResourceContents`. الفكرة نفسها لمحتوى الأداة: ضيّق باستخدام `isinstance`، ثم اقرأ `.text` (أو `.blob`).

يمكن أيضًا إبلاغ العميل عندما يتغير مورد. على اتصالات جيل 2025، يُستخدم `subscribe_resource(uri)` / `unsubscribe_resource(uri)`، وهو زوج طرق لا تنفّذه `MCPServer`، لذلك يجيب الطلب على بروتوكول 2026-07-28 (حيث لم تعد العمليتان موجودتين) بـ`-32601`، *الطريقة غير موجودة*. بديل 2026 تدفّق `subscriptions/listen` الذي *تخدمه* `MCPServer`؛ وتكون `server_capabilities.resources.subscribe` هي `True` فيه. تشرح صفحة **[الاشتراكات](subscriptions.md)** استهلاكه باستخدام `client.listen(...)`.

## قوالب التوجيه {#prompts}

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client/tutorial005.py"
```

تخبرك `list_prompts()` بما يتيحه الخادم وما يحتاج إليه كل قالب توجيه (prompt):

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

تولّد `get_prompt(name, arguments)` رسائله. قاموس الوسائط هو `str -> str`: وسائط قوالب التوجيه نصوص دائمًا. النتيجة `messages`، قائمة `PromptMessage` لكل منها `role` وكتلة `content`:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

يسلّم المضيف تلك الرسائل مباشرة إلى النموذج. هذه الميزة كاملة.

## الإكمالات {#completions}

يستطيع خادم يملك دالة معالجة للإكمال اقتراح قيم وسائط قوالب التوجيه والموارد تلقائيًا أثناء كتابة المستخدم.

```python title="client.py" hl_lines="9-13"
--8<-- "docs_src/client/tutorial006.py"
```

* يحدد `ref` *أي* قالب توجيه أو مورد تملؤه: `PromptReference` أو `ResourceTemplateReference`.
* `argument` هي `{"name": ..., "value": ...}`: الوسيطة وما كتبه المستخدم حتى الآن.

الإجابة في `result.completion.values`. اكتب `"p"` فيعيد الخادم `['poetry']`. جانب الخادم وكيف تستخدم دالة المعالجة الوسائط *الأخرى* المملوءة مسبقًا لتضييق الاقتراحات في صفحة **[الإكمالات](../servers/completions.md)**.

## تقسيم النتائج إلى صفحات {#pagination}

تأخذ كل طريقة `list_*` الخيار `cursor=`، وتحمل كل نتيجة `next_cursor`. عندما تكون `next_cursor` هي `None`، تكون لديك جميع النتائج.

```python title="client.py" hl_lines="7-15"
--8<-- "docs_src/client/tutorial007.py"
```

تعمل `list_all_tools` بصورة صحيحة مع كل خادم. تعيد `MCPServer` كل شيء في صفحة واحدة، لذا تكون `next_cursor` هي `None` وتعمل الحلقة مرة واحدة، ولذلك لا تكتبها معظم الشيفرات. الخوادم التي تقسّم النتائج فعلًا وقواعد المؤشرات في **[تقسيم النتائج إلى صفحات](../advanced/pagination.md)**.

## في الاختبارات {#in-tests}

تصل كل `client.py` في هذه الصفحة إلى `server.py` عبر HTTP. في اختبار، تتجاوز الشبكة وتمرّر إلى `Client` كائن الخادم نفسه: `from server import mcp` ثم `Client(mcp)`. لا عملية ولا منفذ، وتعمل كل الطرق أعلاه بالطريقة نفسها.

يوجد خيار مُنشئ لهذا الغرض: `Client(mcp, raise_exceptions=True)`. لا يؤثر إلا في الاتصالات داخل العملية، وتشرحه **[الاختبار](../get-started/testing.md)** وتبني النمط كاملًا حوله.

## مراجعة {#recap}

* تتصل `Client(x)` عبر Streamable HTTP بسلسلة URL، وتشغّل عملية فرعية لـ`StdioServerParameters`، وتدخل وسيلة نقل مباشرة، وتأخذ كائن الخادم نفسه في الاختبارات.
* `async with` هي دورة الحياة كاملة. داخلها تكون `server_capabilities` و`protocol_version` مملوءتين بالفعل؛ وكذلك `server_info` و`instructions` عندما يقدّمهما الخادم.
* تمنحك `list_tools()` حقول `name` و`title` و`description` و`input_schema` لكل أداة.
* تعيد `call_tool()` كلًّا من `content` للنموذج و`structured_content` لشيفرتك و`is_error`. الأداة التي تثير استثناءً تعيد نتيجة، لا استثناءً في العميل.
* `content` اتحاد أنواع كتل؛ ضيّق باستخدام `isinstance` قبل القراءة.
* تكمل `list_resources` / `list_resource_templates` / `read_resource` و`list_prompts` / `get_prompt` و`complete` العمليات.
* تأخذ كل `list_*` الخيار `cursor=`؛ كرر حتى تصبح `next_cursor` هي `None`.

ما يستطيع الخادم طلبه من *العميل*، وكيف تجيب، في **[دوال رد النداء لدى العميل](callbacks.md)**.
