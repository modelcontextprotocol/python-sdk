---
translation:
  sections: [2c79b6338e09b7ac, 9d5d10a5f0405d0a, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, d50fe7faead8cf68, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, 8db7116fc8ddd0ee, 2090d99b355bc2c7, 0fde3bcea081ba3a]
  tool: 1
---
# الخادم منخفض المستوى {#the-low-level-server}

تمثل `@mcp.tool()` طبقة. وتحتها صنف خادم آخر، هو `Server`، يتعامل مباشرة مع MCP: تعطيه كائنات البروتوكول، فيرسلها دون تغيير.

يُبنى `MCPServer` فوقه. تلجأ إلى المستوى الأدنى عندما تعيقك طبقة التسهيل:

* تحتاج إلى إصدار مخطط **مطابق تمامًا** (محمّل من ملف أو مولّد من قاعدة بيانات)، لا مخطط مشتق من توقيع Python.
* تحتاج إلى تحكم كامل في النتيجة: `_meta` و`is_error` وكل مفتاح في `structured_content`.
* تحتاج إلى معالجة طريقة لا يحددها MCP.

في كل الحالات الأخرى، ابقَ على `MCPServer`.

## الأداة نفسها، يدويًا {#the-same-tool-by-hand}

هذه أداة `search_books` التي تكتبها صفحة **[الأدوات](../servers/tools.md)** في تسعة أسطر باستخدام `@mcp.tool()`، بعد إزالة التسهيلات:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

تغيرت ثلاثة أمور، وهي واجهة API منخفضة المستوى بأكملها:

* **دوال المعالجة مَعلمات للمُنشئ.** تدخل `on_list_tools=` و`on_call_tool=` في `Server(...)`. لا توجد مزخرفات هنا، وكل دالة معالجة لها الشكل نفسه: `async (ctx, params) -> result`.
* **تكتب مخطط الإدخال.** `Tool.input_schema` قاموس `dict` عادي لـJSON Schema. لا يشتقه شيء من تلميحات الأنواع، فلا توجد تلميحات أنواع يُشتق منها.
* **تبني النتيجة.** تكتب `CallToolResult(content=[TextContent(...)])` يدويًا. لا تغليف ولا تحويل ولا استنتاج من تعليق نوع الإرجاع.

تمثل `params` الطلب المحلّل: تعطيك `CallToolRequestParams` حقلي `.name` و`.arguments`. أما `ctx` فهي `ServerRequestContext`: تتضمن `ctx.session` للتواصل مع العميل، و`ctx.lifespan_context` و`ctx.request_id` و`ctx.meta`، أي `_meta` الواردة في الطلب.

!!! info
    إذا استخدمت FastAPI، فأنت تعرف هذه العلاقة بالفعل. `MCPServer` طبقة المزخرفات وتلميحات الأنواع؛ و`Server` هو Starlette تحتها. لا يتنافسان: ينشئ `MCPServer` نسخة `Server` ويسجّل عليها دوال معالجة مثل هذه تمامًا.

### جرّبه {#try-it}

لا تقبل `mcp dev` و`mcp run` سوى `MCPServer`، ولذلك تشغّل هذا الخادم بنفسك. يبني السطر الأخير من `server.py` تطبيق ASGI عاديًا منه، ويشغّله uvicorn:

```console
uvicorn server:app --port 8000
```

وجّه Inspector أو أي عميل إلى `http://localhost:8000/mcp`:

```python title="client.py"
import asyncio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

النص نفسه الذي أنتجته نسخة `@mcp.tool()`. مع اختلافين واضحين:

* تكون `result.structured_content` مساوية لـ`None`. يغلّف الخادم عالي المستوى قيمة `-> str` في `{"result": ...}` نيابة عنك؛ أما هنا فلا يبني شيء ما لم تبنه أنت.
* تعيد `list_tools` المخطط الذي كتبته **أنت**، حرفًا بحرف. تضمنت النسخة عالية المستوى `"title": "Query"` في كل خاصية، و`"title": "search_booksArguments"` في الجذر: إضافات Pydantic. هنا، إذا ظهر شيء في البيانات المنقولة، فأنت وضعته هناك.

في الاختبار، تتجاوز uvicorn والمنفذ: تقبل `Client(server)` خادم `Server` منخفض المستوى داخل العملية كما تقبل `MCPServer` تمامًا، وتعرض صفحة **[الاختبار](../get-started/testing.md)** هذا النمط.

## لا فحوص نيابة عنك {#nothing-is-checked-for-you}

يرفض `MCPServer` الوسيطة غير الصالحة قبل تشغيل دالتك، ويتحقق من الاستدعاء مقابل المخطط الذي ولّده (**[الأدوات](../servers/tools.md)**).

لا يفعل `Server` ذلك. يُعلَن `input_schema` للعميل، لكنه لا يُطبّق مطلقًا على `params.arguments`.

!!! check
    استدعِ `search_books` دون `limit`، وسترفع `args["limit"]` الاستثناء `KeyError`. يرى العميل:

    ```text
    MCPError: Internal server error
    ```

    خطأ JSON-RPC برمز `-32603` ورسالة عامة عمدًا: لا تسرّب SDK تتبّع استثنائك إلى مستدعٍ بعيد. لا يعرف النموذج ما أخطأ فيه، فلا يستطيع إعادة المحاولة. (في الاختبار، يعرض `raise_exceptions=True` الاستثناء الفعلي بدلًا من ذلك؛ راجع **[الاختبار](../get-started/testing.md)**.)

تنطبق القاعدة عمومًا. الاستثناء الذي ترفعه دالة معالجة منخفضة المستوى هو **دائمًا** خطأ بروتوكول، وليس نتيجة أداة تحمل `is_error=True`. إذا أردت أن يقرأ النموذج الإخفاق ويتعافى منه، فتحقق من `params.arguments` بنفسك وأعِد `CallToolResult(content=[TextContent(...)], is_error=True)`. تشرح صفحة **[معالجة الأخطاء](../servers/handling-errors.md)** نوعي الإخفاق.

## أداتان ودالة معالجة واحدة {#two-tools-one-handler}

تمثل `on_call_tool` نقطة الدخول الوحيدة لكل أداة في الخادم. توجّه الاستدعاء وفق `params.name`:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* تعلن `list_tools` كلتيهما. وتوجّه `call_tool` وفق الاسم.
* فرع `else` مهم: يمرّر `Server` طلب `tools/call` لاسم لم تدرجه مطلقًا إلى دالتك مباشرة. رفع استثناء هناك يحوّل الاستدعاء إلى `-32603` نفسه أعلاه.

## المخرجات المنظّمة، يدويًا {#structured-output-by-hand}

أعلن `output_schema` في `Tool` وضع `structured_content` في النتيجة. كلاهما مسؤوليتك:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

استدعِ الأداة، فتحمل النتيجة التمثيلين:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

كتلة `_meta` وسم هوية الخادم: تضيفها SDK إلى كل نتيجة من جيل 2026، مع `version` من المُنشئ (يعرض الخادم الذي لا يعيّنها نصًا فارغًا). يستطيع الخادم الذي يجب ألا يعرّف نفسه حذف المفتاح باستخدام برمجية وسيطة تتحكم في النتائج التي تعيدها.

لا يقارن الخادم الحقلين مطلقًا. لكن `Client` في SDK يفعل: إذا أعدت `structured_content` لا تطابق `output_schema` الذي أعلنته، ترفع `call_tool` استثناء `RuntimeError` يبدأ بـ`Invalid structured content returned by tool search_books` ويتبعه تفاصيل إخفاق `jsonschema`. إعلان المخطط سهل؛ والوفاء به مسؤوليتك. تجد التسلسل الكامل لأنواع الإرجاع والمخططات في **[المخرجات المنظّمة](../servers/structured-output.md)**.

## الصيغة هي JSON Schema 2020-12 {#the-dialect-is-json-schema-2020-12}

يمثل `input_schema` و`output_schema` مخططات JSON Schema، وتحدد [مواصفة MCP](https://modelcontextprotocol.io/specification/latest/basic#json-schema-usage) الصيغة: المخطط الذي لا يتضمن مفتاح `$schema` هو **JSON Schema 2020-12**. تعتمد مخططات `MCPServer` المولّدة على هذا الافتراضي (تكتب Pydantic صيغة 2020-12 وتحذف المفتاح)، ويخضع القاموس المكتوب يدويًا له أيضًا، فتتوفر مفردات 2020-12 كاملةً:

```python title="server.py" hl_lines="8 14-15"
--8<-- "docs_src/lowlevel/tutorial007.py"
```

* يجب أن يكون جذر `input_schema` هو `"type": "object"`. وإلى جانبه تصل `oneOf` و`additionalProperties` و`anyOf` و`if`/`then`/`else` و`prefixItems` و`$defs` مع مراجع `$ref` المحلية وبقية الكلمات المفتاحية في 2020-12 إلى العميل كما كُتبت تمامًا.
* لا حاجة لمفتاح `$schema`. أضفه فقط لاختيار مسودة أقدم: يختار `Client` في SDK، الذي يتحقق من `structured_content` مقابل `output_schema` للأداة، المتحقق وفق `$schema`، ويستخدم 2020-12 عند غيابه.

## `_meta`: للتطبيق، لا للنموذج {#\_meta-for-the-application-not-the-model}

يمثل `content` جزء الإجابة الذي يقرؤه النموذج. ويمثل `structured_content` الإجابة نفسها كبيانات ذات أنواع. أما `_meta` فهي القناة الثالثة: بيانات ترافق النتيجة من أجل **تطبيق العميل**، دون أن تكون جزءًا من الإجابة أصلًا.

استخدمها لمعرّفات السجلات والتتبّع وأي شيء تحتاجه واجهة المستخدم ولا يحتاجه قالب التوجيه:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* تنشئها باسم `_meta=`، وهو الاسم على الشبكة. يقرؤها العميل عبر `result.meta`.
* ضع مفاتيحك في نطاق أسماء (`bookshop/record_ids`). مفاتيح `io.modelcontextprotocol/*` محجوزة للبروتوكول.

!!! warning
    `_meta` اتفاق بينك وبين تطبيق العميل، وليست ضمانًا لما يصل
    إلى النموذج. يحدد التطبيق المضيف ما يعرضه. لا تضع سرًا في أي جزء من نتيجة أداة.

## القدرات تتبع دوال المعالجة {#capabilities-follow-your-handlers}

يعلن `Server` عائلات الطرائق التي زوّدته بدوال معالجة لها فقط. يمرّر `Bookshop` أعلاه `on_list_tools` و`on_call_tool` دون غيرهما، ولذلك يرى العميل المتصل به:

```json
{"tools": {"listChanged": false}}
```

لا `resources` ولا `prompts`: لا توجد دوال تدعمهما. مرّر `on_list_prompts` فتظهر `prompts`؛ ومرّر `on_completion` فتظهر `completions`.

يعلن `MCPServer` دائمًا الأدوات والموارد وقوالب التوجيه، سواء سجّلت أيًا منها أم لا، لأن مديريها موجودون دائمًا. في هذا المستوى، يكون الإعلان *هو* استدعاء المُنشئ.

## النوع العام لدورة الحياة {#the-lifespan-generic}

يستخدم `Server` نوعًا عامًا وفق النوع الذي تنتجه دورة حياته. علّق نوعه مرة واحدة، وسيُعرف نوع الكائن أينما ظهر:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* دورة الحياة من النوع `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`؛ ويعطيك تطبيق `@asynccontextmanager` على مولّد `async` هذا النوع تمامًا.
* تصبح القيمة التي ينتجها عبر `yield` هي `ctx.lifespan_context`، وبما أن دوال المعالجة معلّقة بنوع `ServerRequestContext[Catalog]`، يتوفر الإكمال التلقائي وفحص الأنواع لـ`.search(...)`.
* يُدخل سياقها مرة عند بدء الخادم ويُخرج منه مرة عند توقفه. تعرض صفحة **[دورة الحياة](../handlers/lifespan.md)** بدء التشغيل والتنظيف ونسخة `MCPServer` من الفكرة نفسها.

دون `lifespan=`، تكون `ctx.lifespan_context` قاموس `dict` فارغًا.

## طريقة خاصة بك {#a-method-of-your-own}

يغطي المُنشئ الطرائق التي يحددها MCP. وتغطي `add_request_handler` كل ما عداها:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* الوسيطة الأولى هي نص الطريقة. وللإشعارات نظير هو `add_notification_handler`. تعمل دواله على stdio واتصالات HTTP من جيل المصافحة؛ أما على مسار streamable-HTTP لـ`2026-07-28`، فيُقر POST إشعار العميل برمز `202` ولا يُوزّع، لأن ذلك الإصدار لا يحدد إشعارات من العميل إلى الخادم عبر HTTP.
* `params_type` هو النموذج الذي تُفحص `params` الواردة مقابله **قبل** تشغيل دالتك، ولذلك تحصل الطرائق المخصصة على التحقق الذي لا تحصل عليه الأدوات. اشتق من `RequestParams` حتى يُحلّل حقل `_meta` كما في بقية الطرائق.
* تعيد الدالة `BaseModel` أو `dict` أو `None`. تسلسلها SDK في نتيجة JSON-RPC.

تنبيه واضح: لا يتضمن `Client` عالي المستوى إلا طرائق MCP المحددة، ولذلك لا توجد `client.reindex()`. الطريقة الخاصة بمورّد موجّهة إلى طرف يعرف وجودها بالفعل: عميل تقدّمه أنت أيضًا، أو خدمة أخرى لك تتحدث JSON-RPC.

طريقة واحدة لا تستطيع تولّيها:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

المصافحة من اختصاص مشغّل الاتصال. أما `server/discover` و`ping` وكل طريقة مدمجة أخرى، فيمكنك استبدالها.

!!! tip
    تغلّف `Server.middleware`، المذكورة في ذلك الخطأ، **كل** رسالة واردة، بما فيها `initialize`. إذا أردت مراقبة الحركة أو إعادة كتابتها بدلًا من الإجابة عن طريقة جديدة، فابدأ بـ**[البرمجيات الوسيطة](middleware.md)**.

## دوال المعالجة الأخرى {#the-other-handlers}

تمثل كل واحدة من هذه فكرة أصبحت تعرف مفرداتها؛ ولكل منها صفحتها.

* يمكن أن تعيد `on_call_tool` و`on_get_prompt` و`on_read_resource` قيمة `InputRequiredResult` بدلًا من نتيجتها المعتادة لإيقاف الاستدعاء مؤقتًا وطلب إدخال من العميل؛ راجع **[الطلبات متعددة جولات الطلب والرد](../handlers/multi-round-trip.md)**. وكما يليق بهذا المستوى، لا يُثبّت شيء نيابة عنك: بينما تحمي `MCPServer` قيمة `requestState` افتراضيًا، تعبر `request_state` التي تعيّنها هنا الشبكة كما كُتبت حتى تفعّل `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))`: سطر واحد (يمكن استيراد الاسمين من `mcp.server.request_state`) للحماية والتحقق نفسيهما اللذين تنفّذهما `MCPServer` (**[حماية `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* تستخدم `on_list_resources` و`on_read_resource` و`on_list_prompts` و`on_get_prompt` و`on_completion` الشكل نفسه `(ctx, params) -> result` لبقية العناصر الأساسية.
* تخدم `on_subscriptions_listen` تدفّق `subscriptions/listen` في 2026-07-28. مرّر `ListenHandler` مبنية على `SubscriptionBus` وانشر الأحداث إلى الناقل من دوالك الأخرى؛ راجع **[الاشتراكات](../handlers/subscriptions.md)** للتركيب الكامل.
* تُبقي `get_tool_input_schema` دالة `on_list_tools` خارج مسار الاستدعاء؛ راجع **[مَعلمات الترويسات](header-parameters.md#schemas-by-name)**.
* تعيد `server.streamable_http_app()` تطبيق Starlette نفسه الذي تعيده `MCPServer`؛ انشره كما تنشر صفحة **[تشغيل خادمك](../run/index.md)** أي تطبيق ASGI آخر. لا توجد `server.run(transport=...)` هنا: تدير `server.run(read_stream, write_stream, server.create_initialization_options())` اتصالًا واحدًا عبر زوج من التدفقات، وهذا السطر الواحد هو الآلية كاملةً.

## مراجعة {#recap}

* يأخذ `Server` منخفض المستوى دوال معالجته كـ**مَعلمات للمُنشئ** باسم `on_*`؛ وكل دالة معالجة هي `async (ctx, params) -> result`.
* تكتب قاموس `input_schema` وتبني `CallToolResult`. لا اشتقاق ولا تغليف ولا تحقق نيابة عنك.
* الاستثناء في دالة المعالجة خطأ بروتوكول `-32603`. أما خطأ الأداة الذي يقرؤه النموذج فهو `CallToolResult` مع `is_error=True` تعيدها **أنت**.
* تُوجّه `_meta` في النتيجة إلى تطبيق العميل، وليس إلى النموذج.
* يعتمد النوع العام `Server[T]` على ما تنتجه دورة حياته؛ وتكون `ctx.lifespan_context` من النوع `T`.
* تخدم `add_request_handler(method, params_type, handler)` أي طريقة. أما `initialize` فمحجوزة.
* تُشتق القدرات التي يعلنها `Server` من دوال المعالجة التي سجّلتها.

عامل العميل الخادمين بالطريقة نفسها لأنهما يستخدمان البروتوكول نفسه فعلًا، وهذا هو المقصود. أما المستوى الأدنى التالي فليس صنفًا أصلًا: إنه **[البرمجيات الوسيطة](middleware.md)**.
