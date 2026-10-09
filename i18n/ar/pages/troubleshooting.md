---
translation:
  sections: [3d58228e81b99543, 170514ce901c4139, 17d61fad0a50d62b, 8a6e351ec756904d, 137454d469c867f5, fcf984fa0615ed11, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 525cdf1755e29d4c, 30fd31be74169d9a, d2e88333d4f7841f, c2dc3b1007d2e987, d6eabf60cc366341, f798e815252852c2, 0cba47bae78d04eb, cdc6d86a4dae8a34]
  tool: 1
---
# استكشاف الأخطاء وإصلاحها {#troubleshooting}

كل عنوان في هذه الصفحة هو النص المطابق تمامًا لخطأ تنتجه SDK، يتبعه معناه والحل المباشر. ابحث هنا عن السطر الأخير من تتبّع الاستثناء (أو سجل الخادم) باستخدام البحث داخل الصفحة في المتصفح، واقرأ ذلك المدخل فقط.

تستخدم عدة مداخل هذا الخادم الواحد. أداة واحدة ومورد قالب واحد، يثير كل منهما استثناءً لمدينة لا يعرفها:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

تتصل به هذه المداخل على `http://localhost:8000/mcp`، فأبقِه يعمل عبر HTTP:

```console
uv run mcp run server.py --transport streamable-http
```

الأخطاء المقتبسة في هذه الصفحة حقيقية: تعيد مجموعة اختبارات SDK نفسها إنتاج كل واحد منها.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

ليس هذا خطأ MCP. إنه تغليف من anyio، والخطأ الفعلي هو **السطر الأخير** في النص المنسوخ.

تبدأ `Client.__aenter__` مجموعة مهام. تغلّف anyio كل ما يخرج من مجموعة مهام في `ExceptionGroup`، ولذلك يصل *كل* استثناء يفلت من كتلة `async with Client(...)`، أيًا كان، داخل مجموعة:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

يمكنك فعل أمرين:

1. **اقرأ النهاية.** `MCPError: No forecast for 'Atlantis'.` هو الإخفاق؛ ابحث عن *نصه* في هذه الصفحة.
2. **التقط داخل الكتلة.** لا تظهر `ExceptionGroup` إلا عندما *يغادر* الاستثناء `async with`. إذا التقطته داخلها، يكون الإخفاق نفسه `MCPError` عاديًا دون مجموعة:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    يفلت الإخفاق أثناء *الاتصال* (عنوان URL خاطئ، أو خادم لا يعمل، أو `421` المذكور
    أدناه) من `async with` نفسها، فلا توجد كتلة داخلية لالتقاطه فيها.
    في هذه الحالات، اقرأ نهاية المجموعة.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

تبني `Client(...)` الكائن فقط. لا يحدث اتصال حتى `async with`، ولذلك ترفض كل طريقة العمل:

```python
async def main() -> None:
    client = Client("http://localhost:8000/mcp")
    tools = await client.list_tools()  # RuntimeError
```

ادخل السياق. تمثل `__aenter__` الاتصال:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        tools = await client.list_tools()
```

وتمثل `__aexit__` قطع الاتصال، ولذلك لا توجد `client.close()` قد تنساها. تُبنى **[الاختبار](get-started/testing.md)** على هذا النمط نفسه.

## `Error executing tool <name>: <message>` و`Error executing tool <name>` و`Unknown tool: <name>` {#error-executing-tool-name-message-error-executing-tool-name-and-unknown-tool-name}

تقرأ **نتيجة**، وليست استثناءً. لم ترفع `call_tool` استثناءً، ولن تفعل ذلك لمجرد إخفاق أداة.

استدعِ `forecast` لمدينة لا يعرفها الخادم، وستعود `ToolError` التي ترفعها مع تعليم الطلب بأنه *نجح*:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

تمثل `Unknown tool: get_forecast` الشكل نفسه لاسم لم يسجّله الخادم، وتُرفض الوسيطة غير الصالحة بالطريقة نفسها مقابل مخطط إدخال الأداة، قبل أن تعمل دالتك.

الحل في عميلك: **افحص `result.is_error`**. لا تلتقط `try/except` حول `call_tool` أيًا من هذه الحالات، فلا يوجد استثناء لالتقاطه. هذا مقصود، وهو أهم فكرة في هذه الصفحة: *النموذج* اختار الاستدعاء، ولذلك يحصل على الرسالة وفرصة إعادة المحاولة. تشرح **[معالجة الأخطاء](servers/handling-errors.md)** التفاصيل كاملةً، بما فيها مسار `MCPError` الذي يرفع استثناءً بالفعل.

تعني الصيغة المجردة، `Error executing tool <name>` دون رسالة، أن الأداة **تعطلت**: أفلت منها استثناء لم تتوقعه (أو لم تطابق قيمة إرجاعها مخطط المخرجات)، ويُحجب نص الاستثناء عن الشبكة. يوجد التتبّع في **سجل الخادم** بمستوى `ERROR`، تحت `Tool '<name>' raised an unexpected exception`.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

كتبت `@mcp.tool` بدلًا من `@mcp.tool()`. تمثل `tool()` *مصنعًا* للمزخرفات: دون الأقواس، تمرّر Python دالتك إلى مَعلمة `name=` الخاصة بها.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

أضف الأقواس. تقول `@mcp.resource(...)` و`@mcp.prompt()` الشيء نفسه عند الخطأ نفسه.

!!! note
    يُرفع هذا عند **استيراد** الوحدة، قبل اتصال أي عميل. إذا عرض التطبيق المضيف
    خادمك بأنه *فشل في البدء* (أو *غير متصل*)، بدلًا من متصل بلا
    أدوات، فقد تكون هذه الحالة: شغّل `python server.py` بنفسك واقرأ التتبّع. يكتشف فاحص الأنواع
    ذلك أيضًا: الدالة ليست قيمة `name=` صالحة.

## `InvalidSignature: Tool '<name>' has an invalid x-mcp-header annotation: <reason>` {#invalidsignature-tool-name-has-an-invalid-x-mcp-header-annotation-reason}

عُلّمت وسيطة أداة بـ`x-mcp-header` بطريقة لا تسمح بها المواصفة، وتحدد `<reason>` القاعدة المخالفة. تستبعد العملاء على `2026-07-28` أداة كهذه من قائمتها، ولذلك ترفض SDK تسجيلها.

لا يمكن تعليم سوى وسيطات `str` و`int` و`bool`، وليست `str | None` أيًا منها. تعرض **[مَعلمات الترويسات](advanced/header-parameters.md)** الصيغة المناسبة لوسيطة اختيارية.

مثل المدخل أعلاه، يُرفع هذا عند **استيراد** الوحدة، قبل اتصال أي عميل.

## `Tool already exists: <name>` {#tool-already-exists-name}

استخدم تسجيلان اسم الأداة نفسه. يتقدم **الأول**، ويُسقط الثاني بصمت، ولا تظهر سوى هذه الرسالة في *سجل الخادم*:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

تعرض `tools/list` أداة `forecast` واحدة، وهي `forecast_today`. أعِد تسمية إحداهما. تسكت `MCPServer(..., warn_on_duplicate_tools=False)` التحذير دون تغيير النتيجة، فأبقِه مفعّلًا. تتبع الموارد وقوالب التوجيه القاعدة نفسها ورسالة السجل نفسها (`Resource already exists:` و`Prompt already exists:`).

## يعرض التطبيق المضيف صفر أدوات {#my-host-lists-zero-tools}

لا يوجد نص خطأ لهذا، وهو ما يصعّب البحث عنه. لا تسقط SDK أداة مسجّلة من `tools/list` مطلقًا، فافحص من الداخل إلى الخارج:

* **هل بدأ الخادم أصلًا؟** تثير `@mcp.tool` دون أقواس استثناءً عند الاستيراد، ويبدو الخادم المتعطل مثل خادم فارغ في بعض التطبيقات المضيفة. شغّل `python server.py` بنفسك.
* **هل الأداة موجودة في `mcp` الذي يشغّله التطبيق المضيف؟** تمثل `MCPServer(...)` ثانية في وحدة أخرى خادمًا مختلفًا وفارغًا. تحقّق من الكائن الذي يستورده أمر التطبيق المضيف فعلًا.
* **هل اشتركت أداتان في اسم؟** عندئذ اختفت إحداهما. ابحث عن `Tool already exists:` في سجل الخادم.
* **هل قائمة التطبيق المضيف قديمة؟** لا تصل إضافة أداة بعد بدء التشغيل إلا إلى العملاء التي تعالج `notifications/tools/list_changed`. إعادة تشغيل التطبيق المضيف حل مباشر.
* **هل كتب شيء إلى `stdout` خارج فترة التحويل؟** أثناء التشغيل، تحوّل SDK المخرجات العارضة *المفرغة* من stdout إلى stderr بقدر الإمكان (تُترك البيئة التي تستبدل التدفقات القياسية كما هي)، لكن المخرجات المفرغة إلى stdout قبل ذلك (مثل سكربت تغليف يطبع، أو `print()` عند الاستيراد في عملية بلا تخزين مؤقت)، أو `print()` مخزّنة تُفرغ عند خروج المفسّر، تصل إلى تدفّق البروتوكول. وقد يدفع سطر غير صالح واحد التطبيق المضيف إلى قطع الاتصال، وهو ما تعرضه بعض التطبيقات كخادم فارغ. استخدم وحدة `logging` للتسجيل بدلًا من ذلك. توجد بقية قائمة فحوص جانب التطبيق المضيف في **[الاتصال بتطبيق مضيف فعلي](get-started/real-host.md)**.

اسم الأداة «غير الصالح» *ليس* ضمن القائمة: يسجّل الاسم غير المطابق تحذيرًا، لكن تُسجّل الأداة وتُدرج رغم ذلك.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

رفض الخادم طلب HTTP بالكامل، مع جسم ليس JSON-RPC، فلا يملك `Client` في Python رسالة أفضل من هذه البديلة.

السبب الأكثر شيوعًا هو خادم Streamable HTTP منشور حديثًا. تستخدم `streamable_http_app()` (و`mcp.run("streamable-http")`) دون `transport_security=` **الحماية من إعادة ربط DNS** افتراضيًا: لا تقبل إلا الطلبات التي تكون ترويسة `Host` فيها localhost. هذا افتراضي صحيح على حاسوبك، لكنه غير مناسب خلف اسم مضيف فعلي:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

انشر ذلك، ووجّه عميلًا إليه، وسيفشل الاتصال أثناء المصافحة:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

لا تصلك القيم التي أرسلها الخادم فعلًا، `421` و`Invalid Host header`: لا يتضمن جسم 421 ترويسة `Content-Type: application/json`، فلا يستطيع العميل تحليله. توجد في **سجل الخادم**، وهو المكان التالي الذي تبحث فيه:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

الحل هو `transport_security=`. أضف اسم المضيف الذي تخدمه فعلًا إلى قائمة السماح:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    هذا هو التغيير كاملًا. يتصل العميل نفسه الآن، ويتفاوض على `2026-07-28`،
    ويستدعي `forecast`.

تشرح **[النشر والتوسّع](run/deploy.md)** معنى كل حقل، وحالة الوكيل العكسي، وكل ما يتغير عند النشر. وتمثل `421 Misdirected Request` / `Invalid Host header` أدناه الإخفاق نفسه من الجانب الآخر.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

هذا هو `Server returned an error response` كما يراه أي شيء *غير* `Client` في Python: curl أو تبويب الشبكة في المتصفح أو سجل وصول وكيل عكسي أو SDK أخرى.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

تمثل `421 Misdirected Request` عبارة السبب لحالة HTTP؛ وتمثل `Invalid Host header` جسم رد SDK؛ ويعرض `Client` في Python الحدث نفسه كـ`Server returned an error response`. الثلاثة رفض واحد. يجري الفحص على **ترويسة `Host` التي يحملها الطلب**، وليس العنوان الذي ارتبط به الخادم، ولذلك يفعّله الوكيل العكسي الذي يمرّر اسم المضيف العام مثل العميل المباشر تمامًا.

الحل هو `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` نفسه المعروض تحت `Server returned an error response`. يستحق جانبان منه التوضيح:

* إدخال `allowed_hosts` نص مطابق تمامًا. تطابق `"mcp.example.com"` ترويسة `Host` بلا منفذ، وتطابق `"mcp.example.com:*"` أي منفذ صريح. أدرج الاثنين.
* رد `403` بجسم `Invalid Origin header` هو الفحص النظير لترويسة `Origin`. يعمل للمتصفحات فقط (لا يرسل غيرها `Origin`)، وتكون `allowed_origins=` قائمة السماح له.

تتضمن **[النشر والتوسّع](run/deploy.md)** الشرح الكامل، بما فيه الحالات التي يكون فيها تعطيل الفحص الإعداد المناسب.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

رُكّب تطبيق MCP داخل تطبيق ASGI آخر، ولم يبدأ شيء **مدير جلساته**.

تعيد `mcp.streamable_http_app()` تطبيق Starlette تبدأ دورة حياته مدير الجلسات، وتشغّل `uvicorn server:app` تلك الدورة نيابة عنك. لكن Starlette **لا تشغّل دورة حياة تطبيق فرعي مركّب مطلقًا**، ولذلك عندما يدخل التطبيق في `Mount`، لا يبدأ المدير ويفشل الطلب الأول:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

يبدأ الخادم ويُحل المسار، ثم تطبع `uvicorn` هذا لكل طلب:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

يرى العميل 500. الحل هو دورة حياة في التطبيق **المضيف** تدخل `mcp.session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

تشرح **[الإضافة إلى تطبيق موجود](run/asgi.md)** ذلك، بما فيه خوادم متعددة في تطبيق واحد وFastAPI. رسالتان قريبتان من الصنف نفسه:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` المدير أحادي الاستخدام؛ ويؤدي الدخول في دورة حياة التطبيق نفسه مرتين إلى هذه الرسالة.
* لا توجد `mcp.session_manager` إلا **بعد** استدعاء `streamable_http_app()`، فابنِ المسارات أولًا، ولا تستخدم المدير إلا داخل دورة الحياة.

## `MCPError: Session not found` {#mcperror-session-not-found}

لا يتعرف الخادم على `Mcp-Session-Id` الذي أرسله عميلك. إما أن الخادم **أُعيد تشغيله** (أو وُجهت إلى نسخة أخرى)، أو **انتهت صلاحية** الجلسة لعدم وجود عمل جارٍ طوال `session_idle_timeout`، وافتراضيها 30 دقيقة. راجع [عمر الجلسة وحدودها](run/legacy-clients.md#session-lifetime-and-limits). تعيش الجلسات في ذاكرة تلك العملية وحدها.

ليس هناك خطأ برمجي في الخادم تبحث عنه. رد HTTP هو `404` وجسمه JSON-RPC فعلًا، ولذلك يعرضه `Client` في Python حرفيًا، بخلاف `421` أعلاه:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

الحل هو إعادة الاتصال: اخرج من كتلة `async with Client(...)` وادخل أخرى جديدة، فتتفاوض على جلسة جديدة. للعميل طويل العمر، يعني ذلك التقاط `MCPError` حول الاستدعاءات وإعادة الاتصال عند هذه الرسالة، بدلًا من إعادة المحاولة داخل جلسة ميتة.

إذا حدث ذلك *دون* إعادة تشغيل ودون أن يصمت العميل لهذه المدة، فأنت تشغّل أكثر من عامل دون جلسات ثابتة التوجيه: يحتفظ كل عامل بجدول جلساته الخاص، فيؤدي توجيه الطلب إلى العامل الخطأ إلى هذه الحالة. تشرح **[النشر والتوسّع](run/deploy.md)** و**[خدمة العملاء القدامى](run/legacy-clients.md)** ذلك وحلّيه (تثبيت التوجيه أو `stateless_http=True`).

بالنسبة إلى مشغّل الخادم، رسالة السجل المطابقة هي `Rejected request with unknown or expired session ID: <id>`. تُسجّل بمستوى `INFO`، فلا تظهر عند حد `WARNING` المعتاد. ظهورها في دفعات بعد النشر مباشرة طبيعي؛ فكل العملاء المتصلة تعيد الاتصال. أما عند انتهاء صلاحية الجلسة، فيسبقها `Session <id> idle timeout`، بمستوى `INFO` أيضًا.

## `MCPError: Method not found` {#mcperror-method-not-found}

أرسل طرف طلب JSON-RPC لا يملك الطرف الآخر دالة لمعالجته، وتسمّي `e.error.data` الطريقة. السبب المعتاد **اختلاف الجيلين**: طريقة موجودة في إصدار بروتوكول لا في الآخر، أُرسلت إلى طرف على الإصدار غير المناسب، مثل وصول `resources/subscribe` من جيل `2025` إلى اتصال `2026-07-28`، أو إرسال `subscriptions/listen` الخاصة بـ`2026` من عميل مثبت على `mode="legacy"`. توضح **[إصدارات البروتوكول](protocol-versions.md)** دعم الطرفين، وتشرح **[الإكمالات](servers/completions.md)** السبب الآخر (قدرة اختيارية لم تسجّل لها دالة معالجة).

حالة واحدة **لا** تنتج هذا الخطأ، رغم أنها طلب أزاله البروتوكول الحديث: أداة تستدعي `ctx.elicit()` في اتصال `2026-07-28`. يرفض الخادم *إرسال* الطلب أصلًا، فتحصل بدلًا منه على `Cannot send 'elicitation/create': ...`، الموضّح لاحقًا في هذه الصفحة.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

يريد خادمك سؤال المستخدم، ولم يعلن هذا العميل أنه يستطيع تلقي السؤال.

يسأل Bistro هذا قبل الحجز باستخدام دالة حل:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

شغّله بدلًا من خادم Weather واستدعِ `book_table` من عميل لم يمرّر `elicitation_callback`. ترفض دالة الحل مسبقًا، لأن العميل المتصل لم يعلن استقاء المعلومات بنموذج، وتسمّي `e.error.data` ما ينقص بالضبط:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

مرّر `elicitation_callback=` إلى `Client(...)`. تسجيل دالة رد النداء *هو* إعلان القدرة؛ لا يوجد خيار ثانٍ:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

تسرد **[دوال رد نداء العميل](client/callbacks.md)** غيرها (`sampling_callback` و`list_roots_callback`)، وكل واحدة إعلان بالطريقة نفسها.

!!! info
    يمثل `-32021` الثابت `MISSING_REQUIRED_CLIENT_CAPABILITY`، أحد ثلاثة رموز أخطاء تضيفها مواصفة
    2026-07-28. لا يمثل أي منها صنف استثناء: تصل كلها كـ`MCPError`،
    وتفحص `e.error.code` لمعرفتها. تصدّر `mcp.types` الثوابت. الرمزان الآخران هما
    `-32020` و`HEADER_MISMATCH` (تختلف ترويسة HTTP عن جسم الطلب الذي ترافقه)،
    و`-32022` و`UNSUPPORTED_PROTOCOL_VERSION` (سمّى الطلب إصدارًا لا يدعمه
    الخادم). لا يستطيع عميل SDK متوافق إنتاج أي منهما، فإذا رأيتهما، فافحص ما
    يعيد كتابة الطلبات بين العميل والخادم.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

النقص نفسه الذي تشير إليه `Client did not declare the form elicitation capability ...`، بصياغة المسارات التي لا تفحص مسبقًا: احتاج الخادم إلى إجابة عن استقاء معلومات، ولم يسجّل العميل المتصل `elicitation_callback`.

تراه من `ctx.elicit()` في اتصال قديم، وفي أي اتصال عند وصول سؤال مُعاد متعدد الجولات (**[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md)**) إلى عميل بلا دالة رد نداء للإجابة عنه. الحل نفسه: مرّر `elicitation_callback=` إلى `Client(...)`. لا توجد حالة «لم يُسأل المستخدم» تتلقاها أداتك كـ`decline`؛ فالعميل الذي لا يمكن سؤاله يؤدي إلى إخفاق الاستدعاء، فصمّم أدواتك مع مراعاة ذلك.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

حاولت دالة المعالجة الوصول إلى العميل أثناء الطلب، في اتصال لا يملك الاستدعاء فيه قناة تحمل طلبًا من الخادم. توجد ثلاثة إعدادات للخادم تؤدي إلى ذلك.

**اتصال `2026-07-28`: أي وسيلة نقل، دائمًا.** لا يتضمن البروتوكول الحديث طلبات يبدأها الخادم أصلًا، فيرفض الخادم قبل إرسال أي شيء. استخدام `ctx.elicit()` داخل أداة هو المثال المعتاد، غالبًا في أول **[اختبار](get-started/testing.md)** داخل الذاكرة لتلك الأداة، لأن `Client(mcp)` تتفاوض على `2026-07-28` تلقائيًا. لا يغيّر تمرير `elicitation_callback=` شيئًا، فلا يصل إلى العميل أي طلب ليجيب عنه:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def test_book_table() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**اتصال قديم بخادم `stateless_http=True`.** يعني انعدام الحالة أن كل طلب مستقل: لا جلسة ولا تدفّق من الخادم إلى العميل، فلا يوجد موضع لإرسال `elicitation/create` (أو `sampling/createMessage` أو `roots/list`) حتى للجيل الذي يدعمها:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**اتصال قديم بخادم `json_response=True`.** يُجاب عن `POST` بجسم JSON واحد، والجسم الواحد يحمل الرد فقط، فلا يوجد هنا أيضًا التدفّق الخاص بالطلب الذي تحتاجه `ctx.elicit()` أثناء الطلب. تبقى الجلسة و`Mcp-Session-Id` وتدفّقها المستقل موجودة؛ اختفت القناة الخاصة بالطلب فقط.

تسمّي الرسالة الطريقة التي تعذر إرسالها. يرفع الخادم الصنف `NoBackChannelError`، لكن الشبكة تحمل `MCPError` الأساسية فقط، ولذلك تظهر الجملة أعلاه في آخر سطر من التتبّع، لا اسم الصنف.

بالنسبة إلى عميل `2026-07-28`، الحل نفسه في الحالات الثلاث: لا تتواصل عكسيًا أثناء الاستدعاء. انقل السؤال إلى **دالة حل** (أو أعِد `InputRequiredResult` بنفسك)، فيصبح جزءًا من *الرد* الذي يستطيع كل اتصال حمله:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

السؤال نفسه، و`elicitation_callback` نفسها في العميل. الاختلاف في التنفيذ: تتيح دالة الحل للخادم *إعادة* السؤال من الاستدعاء بدلًا من دفعه، فلا يُرسل طلب من الخادم إلى العميل. يحل ذلك المشكلة لكل عميل `2026-07-28`، أيًا كان إعداد الخادم من الثلاثة. أما العميل *القديم* فلا تكفيه إعادة الكتابة وحدها: لا توجد في `2025-11-25` طريقة لإعادة سؤال في النتيجة، ولذلك تظل دالة الحل في اتصال قديم ترسل `elicitation/create` عبر القناة الخاصة بالطلب، وتحتاج إلى خادم يبقيها — دون `stateless_http=True` أو `json_response=True`. تغطي **[استقاء المعلومات](handlers/elicitation.md)** دوال الحل؛ وتشرح **[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md)** ما يحدث على الشبكة.

!!! check
    الأداة التي تستخدم `ctx.elicit()` ليست خاطئة؛ إنها من جيل *ما قبل 2026*. اتصل بـ`mode="legacy"`
    (مصافحة `initialize` التقليدية، ومواصفة `2025-11-25` أو أقدم) بخادم لا يستخدم
    `stateless_http=True` ولا `json_response=True`، وستعمل، لأن قناة الخادم إلى العميل
    موجودة هناك.
    تشرح **[إصدارات البروتوكول](protocol-versions.md)** ما يتوفر في كل إصدار.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

تعذر على الخادم التحقق من رمز `requestState` الذي أعاده عميلك، فرفض الجولة.

يمثل `requestState` رمز الاستئناف المعتم الذي يحمله استدعاء **[متعدد الجولات](handlers/multi-round-trip.md)** بين مراحله. تحميه `MCPServer` عند الإرسال وتتحقق من كل إعادة له، وتفحص *كل* `request_state` واردة في `tools/call` و`prompts/get` و`resources/read`، حتى لدالة لا تصدر رمزًا أصلًا. ولذلك يُرفض الرمز الذي لم تحمه هذه العملية أينما وصل:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

نص الرسالة ثابت عن قصد: لا تكشف الشبكة أي فحص أخفق. يصل السبب إلى **سجل الخادم**، وقراءته هي التشخيص كاملًا:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

الأسباب التي ستراها فعلًا:

* **`unknown key`** هو الأهم. يُولّد مفتاح الحماية الافتراضي عند بدء العملية، ولذلك تكون إعادة المحاولة التي تصل إلى **عامل مختلف** أو نسخة أخرى خلف موازن أحمال أو الخادم نفسه **بعد إعادة التشغيل** محمية بمفتاح لم تملكه هذه العملية. لا يعني ذلك مهاجمًا؛ بل إعدادًا افتراضيًا يُستخدم مع أكثر من عملية.
* **`audience`**: حمت الرمز نسخة لها *اسم خادم مختلف*. الاسم هو ادعاء الجمهور الافتراضي للحماية، ولذلك يجب أن تشارك النسخ الاسم (أو تعيّن `RequestStateSecurity(audience=...)` صراحةً)، إلى جانب المفاتيح.
* **`expired`**: استغرقت الجولة أكثر من `ttl` للحماية، وهي 600 ثانية لكل جولة، لا لكل استدعاء.
* **`malformed`** / **`codec error`**: تغير الرمز أثناء النقل، أو لم يكن رمزًا محميًا أصلًا.
* **`request binding`**: عاد الرمز بأداة مختلفة أو وسيطات مختلفة أو طريقة مختلفة.

حل تعدد العمليات هو وسيطة واحدة (`keys` *نفسها* في كل نسخة)، مع شيء ليس وسيطة أصلًا: *اسم* الخادم نفسه (أو `audience=` مشتركة وصريحة).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

تحمي `keys[0]` الرموز، ويتحقق كل مفتاح في القائمة منها، مما يتيح تدوير المفاتيح دون توقف. تشرح **[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md#protecting-requeststate)** ما تحميه الآلية وتسلسل التدوير، وتعرض **[النشر والتوسّع](run/deploy.md)** إخفاق العاملين كاملًا وحلّه ذا الجزأين.

!!! tip
    ترفض `keys=[...]` المفتاح الضعيف فورًا برسالة مفيدة على غير المعتاد:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    نفّذ ما تقوله.

## هل ما زلت عالقًا؟ {#still-stuck}

* إذا لم تجد رسالة أنتجتها SDK في هذه الصفحة، فهذه مشكلة توثيق تستحق الإبلاغ عنها بذاتها.
* ابحث في [متعقّب البلاغات](https://github.com/modelcontextprotocol/python-sdk/issues)؛ فقد شرح شخص بالفعل معظم رسائل الأخطاء الموجودة فيه.
* لم تجد شيئًا؟ [افتح بلاغًا](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) مع التتبّع الكامل، أو اسأل في [#python-sdk-dev على Discord الخاص بمساهمي MCP](https://discord.gg/6CSzBmMkjX).

## مراجعة {#recap}

* لا تمثل `ExceptionGroup: unhandled errors in a TaskGroup` الخطأ الفعلي مطلقًا. اقرأ **السطر الأخير**؛ والتقاط `MCPError` *داخل* كتلة `async with Client(...)` يتجنب التغليف بالكامل.
* لا ترفع `call_tool` استثناءً لأداة تفشل. تمثل `Error executing tool ...` و`Unknown tool: ...` نتائج: افحص `result.is_error`. غياب رسالة بعد اسم الأداة يعني أنها تعطلت، ويوجد التتبّع في سجل الخادم.
* `Client must be used within an async context manager` -> استخدم `async with`. و`Use @tool() instead of @tool` -> أضف الأقواس.
* `has an invalid x-mcp-header annotation` -> لا يمكن تعليم سوى وسيطات `str` و`int` و`bool`.
* `Tool already exists:` في سجل الخادم هي الإشارة الوحيدة إلى دمج أداتين تحملان الاسم نفسه في واحدة.
* رد 421 واحد بثلاث صيغ: `Server returned an error response` (في `Client` الخاص بـPython)، و`421 Misdirected Request` / `Invalid Host header` (في غيره)، و`Invalid Host header: <host>` (في سجل الخادم). الحل: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> تطبيق مركّب لم تدخل دورة حياة تطبيقه المضيف `mcp.session_manager.run()`.
* `Session not found` -> أُعيد تشغيل الخادم أو انتهت صلاحية الجلسة (`session_idle_timeout`)؛ أعِد الاتصال.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> تحتاج `ctx.elicit()` إلى قناة من الخادم إلى العميل: لا يملكها اتصال `2026-07-28` مطلقًا، وتزيل `stateless_http=True` قناة الجيل القديم، وتزيل `json_response=True` القناة الخاصة بالطلب. استخدم دالة حل (ويحتاج العميل القديم أيضًا إلى خادم يبقي القناة). أما `Method not found` المجاورة فهي طلب لطريقة لا توجد في إصدار بروتوكول الطرف الآخر.
* `Client did not declare the form elicitation capability ...` و`Elicitation not supported` -> يفتقد العميل `elicitation_callback=`.
* لا توضّح `Invalid or expired requestState` السبب على الشبكة مطلقًا. يوضّحه سجل الخادم؛ وتعني `unknown key` ضرورة مشاركة `RequestStateSecurity(keys=[...])` بين العمال.
