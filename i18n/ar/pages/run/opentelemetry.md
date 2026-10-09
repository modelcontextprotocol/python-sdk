---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

خادمك مجهّز بالتتبّع بالفعل. لا تحتاج إلى إضافة شيء.

يصدر كل خادم تنشئه مقطع تتبّع [OpenTelemetry](https://opentelemetry.io/) لكل
رسالة يعالجها. لم تكتب ذلك ولا تستورده. يوجد بمجرد
استدعاء `MCPServer(...)`.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

هذا خادم كامل مزود بالتتبّع. استدعِ `search_books` فيُنشأ له مقطع. وينطبق
الأمر على `Server` منخفض المستوى: يوجد التتبّع في كليهما.

## ما تحصل عليه {#what-you-get}

تصبح كل رسالة واردة مقطع `SERVER` يُسمّى بالطريقة والهدف. لذا يكون
مقطع `tools/call` لـ`search_books` هو `tools/call search_books`، ويكون `tools/list` المجرد
هو `tools/list` فقط.

يحمل كل مقطع بعض الخصائص:

* `mcp.method.name` و`mcp.protocol.version` على كل مقطع.
* `jsonrpc.request.id` على الطلب (لا يملك الإشعار معرّفًا).
* تضبط دالة معالجة تثير استثناءً حالة المقطع إلى خطأ. وكذلك نتيجة أداة فيها `is_error=True`.

ولأن تتبّع استدعاء أداة حاجة شائعة، تستخدم مقاطع `tools/call`
[الاتفاقيات الدلالية لـGenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) في OpenTelemetry:

* `gen_ai.operation.name` بقيمة `"execute_tool"`.
* `gen_ai.tool.name` بقيمة الأداة المستدعاة.

يحصل مقطع `prompts/get` على `gen_ai.prompt.name` بالطريقة نفسها. لا تحمل طرق عرض القوائم
مفاتيح `gen_ai.*`، إذ لا يوجد عنصر لتسميته.

!!! tip
    خصائص GenAI هذه هي ما يجعل واجهة التتبّع تجمع استدعاءات أدواتك كما تجمع
    أدوات أي وكيل آخر. تحصل على ذلك دون شيفرة إضافية.

## بلا تكلفة حتى تحتاج إليه {#it-costs-nothing-until-you-want-it}

هذا ما يجعل "مفعّل افتراضيًا" إعدادًا مريحًا.

تعتمد SDK على `opentelemetry-api` فقط، النصف الخفيف من OpenTelemetry. دون تثبيت SDK
ومكوّن تصدير، لا يفعل إنشاء مقطع شيئًا. لذا لا تكلفك المقاطع التي يصدرها خادمك
حاليًا إلا القليل جدًا، ولا يجمعها أحد.

عندما تريد *رؤيتها*، ثبّت النصف الآخر ووجّهه إلى وجهة:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

اضبط مكوّن تصدير بالطريقة المعتادة في OpenTelemetry، فتظهر كل المقاطع التي كانت SDK
تنشئها بصمت. لا تتغير شيفرة خادمك، ولا سطر واحد.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) أحد هذه الأنظمة، ويتولى
    الإعداد عنك: `pip install logfire` ثم `logfire.configure()`، فتظهر مقاطع MCP
    في العرض المباشر. وهو مبني على OpenTelemetry، لذا ينطبق عليه ما يلي أيضًا.

## تتبّعات تعبر النقل {#traces-that-cross-the-wire}

يكون التتبّع أكثر فائدة حين يتابع الطلب من العميل إلى الخادم في صورة
مترابطة واحدة.

عندما يستخدم العميل والخادم SDK، يكون الربط تلقائيًا. يحقن العميل
[سياق التتبّع وفق W3C](https://www.w3.org/TR/trace-context/) في الطلب، ويقرأه الخادم،
فيتداخل مقطع الخادم تحت مقطع العميل ضمن التتبّع نفسه. هذا هو
[SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414)، وتحصل عليه دون
طلب.

إذا لم تحمل الرسالة الواردة سياق تتبّع، مثل طلب من عميل لا يستخدم
SDK، يرتبط مقطع الخادم بالمقطع الحالي على الخادم إن وُجد، بدلًا من
بدء تتبّع منفصل جديد.

## تعطيله {#turning-it-off}

التتبّع مكوّن وسيط، وهو الأول في قائمة خادمك. إذا أردت فعلًا خادمًا
لا يصدر مقاطع، فأزله:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    يبدأ ذلك الاستيراد بشرطة سفلية عمدًا. الفئة مؤقتة مثل
    [`Server.middleware`](../advanced/middleware.md)، لذا ينبغي أن تتوقع
    تغيّر مسار الاستيراد. لن تحتاج إلى ذلك غالبًا: دون مكوّن تصدير لا تكلف المقاطع
    شيئًا، لذا المعتاد تركها مفعّلة وعدم تثبيت مكوّن تصدير.

## مراجعة {#recap}

* يصدر كل `MCPServer` وكل `Server` منخفض المستوى مقطع `SERVER` لكل رسالة واردة
  افتراضيًا. لا تكتب شيئًا.
* تحمل المقاطع `mcp.method.name` و`mcp.protocol.version`؛ وتحمل `tools/call` و`prompts/get` أيضًا
  خصائص GenAI لتجميع استدعاءات أدواتك مثل أدوات أي وكيل آخر.
* لا يكلف ذلك شيئًا حتى تثبّت OpenTelemetry SDK ومكوّن تصدير، ثم تظهر المقاطع
  دون تغيير خادمك.
* ينتشر سياق التتبّع من العميل إلى الخادم تلقائيًا عندما يستخدم الطرفان SDK.

ما يقرر أصلًا إن كان الطلب سيُنفَّذ هو **[التفويض](authorization.md)**.
