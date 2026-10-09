---
translation:
  sections: [9cac816674181eb0, 5619e950d206e6c8, 40b4916d82eaf1d4, 10d151f2cc75317f, 3d0832f39b0d7059, 92742ba36533633d, 991c10e47fda2636]
  tool: 1
---
# وسائل نقل العميل {#client-transports}

تتواصل كل `Client` مع خادمها عبر **وسيلة نقل**: ما يحمل الرسائل فعليًا.

لا تضبط واحدة منفصلة. تأخذ `Client` وسيطة موضعية واحدة وتحدد وسيلة النقل من نوعها.

جانب *الخادم* لكل وسيلة (ما تفعله `mcp.run()` وما تنشره) في **[تشغيل خادمك](../run/index.md)**.

## Streamable HTTP {#streamable-http}

مرّر سلسلة URL فتحصل على **Streamable HTTP**، وسيلة نقل النشر والخيار الأول:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

هذا عميل الإنتاج كاملًا. تغلّف `Client` عنوان URL في `streamable_http_client(...)` نيابة عنك، فوق `httpx2.AsyncClient` معدّة كما يحتاج MCP: مهلة 30 ثانية للاتصال والكتابة وانتظار اتصال متاح، و300 ثانية للقراءة لأن الخادم قد يُبقي تدفّق استجابة مفتوحًا.

!!! check
    `Client` التي أنشأتها **ليست** متصلة. الإنشاء يختار وسيلة النقل فقط؛
    وتفتحها `async with`. إذا استخدمت الاتصال قبل الدخول، تخبرك SDK بذلك:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    لم يُحَل عنوان أو يُجلَب شيء أو تُنشأ عملية عندما كتبت `Client("http://...")`. هذا السطر بلا تكلفة اتصال.

### استخدم `httpx2.AsyncClient` الخاصة بك {#bring-your-own-httpx2asyncclient}

عندما تحتاج إلى ترويسة `Authorization` أو ملف تعريف ارتباط أو وكيل أو mTLS أو مهلة مختلفة، ابنِ `httpx2.AsyncClient` بنفسك ومرّرها إلى `streamable_http_client`:

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client_transports/tutorial003.py"
```

لاحظ أمرين:

* أنت تملك `httpx2.AsyncClient`، لذلك **أنت** من يدخل سياقها ويخرج منه. لا تغلق SDK عميلًا لم تنشئه.
* تعيد `streamable_http_client(url, http_client=...)` وسيلة نقل، وتقبلها `Client(transport)` مثل أي وسيلة أخرى.

احتفظ بـ`timeout=`. إنها التي يستخدمها عميل SDK نفسه (30 ثانية و300 للقراءة)؛ وتحصل `httpx2.AsyncClient` دونها على مهلة `httpx2` الافتراضية، 5 ثوانٍ، فيفشل استدعاء أداة يتجاوزها بانتهاء مهلة القراءة.

ملاحظة TLS: تتحقق `httpx2` من الشهادات مقابل مخزن الثقة لنظام التشغيل (عبر
[`truststore`](https://pypi.org/project/truststore/))، لا قائمة CA مضمّنة. في بيئة
دون مخزن CA نظام صالح (بعض الحاويات المصغّرة)، عيّن متغيرَي البيئة القياسيين `SSL_CERT_FILE`/`SSL_CERT_DIR`
أو مرّر `verify=ssl_context` صريحًا إلى `httpx2.AsyncClient`
(الخلفية في
[استبدال `httpx` و`httpx-sse` بـ`httpx2`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

### أحداث SSE الأكبر {#larger-sse-events}

مرّر `max_sse_event_size` عندما يرسل الخادم نتيجة أداة أو إشعارًا كبيرًا في حدث SSE واحد:

```python title="client.py" hl_lines="6-9"
--8<-- "docs_src/client_transports/tutorial005.py"
```

الافتراضي 1 MiB لكل حدث، ويُقاس بالبايتات قبل تحليل الحدث. ينطبق الحد على
استجابات POST وتدفّق GET والتدفّقات المستأنفة. يُفشل الحدث الأكبر من المسموح في استجابة POST أو تدفّق
مستأنف ذلك الطلب بخطأ SSE. على تدفّق GET الخلفي، يسجّل العميل
الخطأ ويعيد محاولة التدفّق. عيّن `max_sse_event_size=None` لتعطيل الحد عندما تثق
بالخادم وتحتاج إلى أحداث أكبر. لا تتأثر استجابات JSON. إذا استخدمت `ClientSessionGroup`، فعيّن
الخيار نفسه على `StreamableHttpParameters`.

!!! warning
    كانت `streamable_http_client` تقبل `headers=` و`timeout=` مباشرة. لم تعد تفعل:
    مَعلماتها `url` و`http_client` و`terminate_on_close` و`max_sse_event_size`. إذا استخدمت `headers=`
    بحكم العادة، فستحصل على:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    توجد الترويسات والمصادقة والوكلاء والمهل على `httpx2.AsyncClient` التي تمرّرها.
    أما `max_sse_event_size` فينطبق على قارئات SSE في وسيلة نقل MCP.

!!! info
    تحتفظ `httpx2` بواجهة `httpx` المألوفة، لذا إذا عرفت `httpx`، فأنت تعرف إعداد المصادقة
    والوكلاء وخطافات الأحداث وإعادة المحاولة وحدود الاتصالات هنا. لا تضيف SDK شيئًا فوق ذلك ولا
    تزيل شيئًا، عدا [معالجة التحويلات](#redirects). وهذا موضع دمج OAuth أيضًا:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. التدفق كاملًا في **[عملاء OAuth](oauth-clients.md)**.

### التحويلات {#redirects}

تتصل وسيلة النقل بعنوان URL الذي أعطيتها وبذلك الأصل فقط.

* يُتّبع تحويل `307`/`308` الذي يبقى على المخطط والمضيف والمنفذ نفسها، وكذلك `http://` → `https://` على المضيف نفسه. يشمل ذلك تحويل الشرطة النهائية المعتاد `/mcp` → `/mcp/`.
* **لا** يُتّبع تحويل إلى أي وجهة أخرى. يفشل الاستدعاء بالرسالة:

    ```text
    MCPError: Redirect to https://other.example.com/mcp not followed; use that URL as the endpoint if it is the intended server
    ```

    إذا كان ذلك URL هو الخادم المقصود، فضعه في إعداداتك. وإلا فإعداد الخادم أو وكيل أمامه غير صحيح.

ينطبق هذا على أي `httpx2.AsyncClient` تمرّرها: لا يُستشار إعداد `follow_redirects` لطلبات MCP في أي اتجاه. يطبّق مزوّدو OAuth في SDK القاعدة نفسها على طلباتهم.

!!! tip
    تعني `Redirect to http://… not followed: it would downgrade this HTTPS endpoint to plain HTTP` أن
    الخادم وراء وكيل ينهي TLS لا يعرف عنه، ويصدر تحويلات `http://`.
    يُصلَح ذلك على الخادم (**[النشر والتوسع](../run/deploy.md#behind-a-tls-terminating-proxy)**)،
    أو باستخدام URL الدقيق `https://…/` الذي تقترحه الرسالة.

## stdio {#stdio}

خادم **stdio** عملية فرعية. يشغّله العميل ويكتب JSON-RPC إلى stdin ويقرأ JSON-RPC من stdout. هكذا يشغّل مضيف مكتبي خادمًا على جهازك: المضيف *هو* هذه الشيفرة مع واجهة، وتعرض **[الاتصال بتطبيق مضيف فعلي](../get-started/real-host.md)** العلاقة نفسها من جانب المضيف كملف إعدادات.

صِف العملية باستخدام `StdioServerParameters` ومرّرها إلى `Client`:

```python title="client.py" hl_lines="3-7 11"
--8<-- "docs_src/client_transports/tutorial004.py"
```

ينشئ دخول الكتلة العملية. ويغلق الخروج منها العملية الفرعية: يغلق stdin وينتظر ويقتلها إن استمرت. لا تنظّفها بنفسك.

تذهب stderr للعملية الابنة إلى stderr لديك. لإرسالها إلى مكان آخر، ابنِ وسيلة النقل بنفسك باستخدام `stdio_client` (من `mcp`) ومرّرها بدلًا من ذلك: `Client(stdio_client(server, errlog=log_file))`.

!!! warning
    **لا** ترث العملية الابنة بيئتك. تحصل على قائمة سماح محدودة (`HOME` و`LOGNAME` و
    `PATH` و`SHELL` و`TERM` و`USER` على POSIX)، كي لا تتسرب بيانات حساسة إلى عملية قد
    لا تكون كتبتها.

    لن يجد خادم يحتاج إلى مفتاح API ذلك المفتاح فيها. مرّره صراحة باستخدام `env=`؛ تُدمَج هذه
    المتغيرات فوق قائمة السماح. هذا ما يفعله `BOOKSHOP_API_KEY` أعلاه.

## داخل الذاكرة {#in-memory}

في الاختبار، لا شيء لتنشره أو تشغّله. مرّر كائن الخادم نفسه:

```python hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

لا عملية فرعية ولا منفذ ولا بايتات عبر الشبكة. العميل والخادم كائنان في العملية نفسها، وما زال الاستدعاء يمر بطبقة البروتوكول الفعلية: تُعرض `search_books` ويُتحقَّق منها وتُستدعى كما يحدث عبر HTTP تمامًا. تبني **[الاختبار](../get-started/testing.md)** النمط كاملًا حوله.

يعمل الشكل نفسه أيضًا كواجهة تضمين: يستطيع تطبيق ينشئ الخادم بنفسه استدعاء أدواته دون انتقال عبر الشبكة.

## SSE {#sse}

`sse_client(url)` من `mcp.client.sse` هي وسيلة نقل HTTP التي حلّت محلها Streamable HTTP. غلّفها بالطريقة نفسها، `Client(sse_client("http://localhost:8000/sse"))`، للتواصل مع خادم ما زال يستخدمها، ولا تبنِ شيئًا جديدًا عليها.

## بروتوكول `Transport` {#the-transport-protocol}

كل ما سبق شيء واحد بالنسبة إلى `Client`.

**وسيلة النقل** أي مدير سياق غير متزامن ينتج زوج تدفّقات رسائل `(read, write)`؛ رسميًا، بروتوكول `Transport` في `mcp.client`. تحدد `Client` وسيطتها بحسب النوع: تصبح `str` هي `streamable_http_client(url)`، وتصبح `StdioServerParameters` هي `stdio_client(params)`، ويتصل كائن الخادم داخل العملية، ويُدخَل سياق أي شيء آخر كوسيلة نقل مباشرة. هذه القاعدة الأخيرة سبب ملاءمة `stdio_client(...)` و`streamable_http_client(...)` و`sse_client(...)` كلها للموضع نفسه، وسبب قدرتك على كتابة وسيلتك الخاصة.

## مراجعة {#recap}

* تتصل `Client("http://.../mcp")` (عنوان URL) عبر Streamable HTTP، وسيلة نقل الإنتاج.
* توجد الترويسات والمصادقة والوكلاء والمهل على `httpx2.AsyncClient` تمرّرها إلى `streamable_http_client(url, http_client=...)`. لا خيار `headers=`.
* استخدم `streamable_http_client(url, max_sse_event_size=...)` لتغيير حد البايتات لكل حدث SSE.
* لا تُتّبع التحويلات إلا داخل أصل URL نفسه (`307`/`308` لإضافة الشرطة النهائية)، إضافة إلى `http`→`https` على المضيف نفسه. يفشل غير ذلك بـ`Redirect to … not followed`؛ اضبط URL النهائي.
* stdio هي `Client(StdioServerParameters(...))`. غلّفها في `stdio_client(...)` بنفسك فقط لإعادة توجيه stderr للعملية الابنة.
* تتلقى العملية الفرعية بيئة بقائمة سماح، لا بيئتك؛ وتضيف `env=` إليها.
* تتصل `Client(mcp)` (كائن الخادم) داخل الذاكرة. استخدمها في الاختبارات أو لتضمين خادم في التطبيق الذي بناه.
* وسيلة النقل أي شيء تستخدمه بصيغة `async with x as (read, write)`. تسلّم `Client` كل ما ليس كائن خادم أو URL أو `StdioServerParameters` إلى ذلك البروتوكول مباشرة.
* إنشاء `Client` يختار وسيلة النقل. وتفتحها `async with`.

بعد فتح وسيلة النقل، يجب أن يتفق الطرفان على إصدار البروتوكول. غالبًا لا تفكر في ذلك؛ وعندما تحتاج إليه، راجع **[إصدارات البروتوكول](../protocol-versions.md)**.
