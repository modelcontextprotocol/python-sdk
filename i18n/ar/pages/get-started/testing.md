---
translation:
  sections: [5d13c2f0ba42c0d2, c52a1de2b6b32f40, 8e792bf8c7489ec6, 38552ea228b0a04f]
  tool: 1
---
# الاختبار {#testing}

تستطيع فئة `Client` في SDK، وهي نفسها التي تتصل بعنوان URL أو تشغّل عملية فرعية، الاتصال **داخل الذاكرة** أيضًا: مرّر إليها كائن الخادم فتتواصل معه مباشرة.

لا عملية فرعية. لا منفذ. لا شيء يمر عبر الشبكة. إنها الفكرة نفسها التي تعتمد عليها `TestClient` في FastAPI.

## الاستخدام الأساسي {#basic-usage}

لنفترض أن لديك خادمًا بسيطًا بأداة واحدة:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

لتشغيل الاختبار أدناه، ستحتاج إلى اعتماديتين إضافيتين للتطوير:

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    يفترض هذا التوثيق أنك تعرف [`pytest`](https://docs.pytest.org/en/stable/) بالفعل.

    يستخدم الاختبار أدناه [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/)
    للتحقق من كائن النتيجة كاملًا في سطر واحد. وهي تسجّل مخرجات الاختبار بصيغة القيمة الحرفية
    `snapshot(...)` التي تراها. إذا فضّلت عدم استخدامها، فاحذف الاستيراد وتحقق من
    الحقول التي تهمك (`result.content[0].text == "3"`) كما في أي اختبار آخر.

والآن الاختبار:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. إذا كنت تستخدم `trio`، فأعِد `"trio"` بدلًا من ذلك. راجع [توثيق anyio](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) للتفاصيل.
2. يوفّر مُجهّز الاختبار عميلًا متصلًا. يحصل كل اختبار يأخذ `client` على اتصال جديد داخل الذاكرة بالخادم نفسه.

هذا كل شيء! يمكنك الآن توسيع اختباراتك لتشمل سيناريوهات أكثر.

## لماذا `raise_exceptions=True`؟ {#why-raise_exceptionstrue}

قد يحدث نوعان مختلفان من الأخطاء، ولا يؤثر هذا الخيار إلا في أحدهما.

الاستثناء داخل إحدى **أدواتك** ليس إخفاقًا في البروتوكول. بل يصبح نتيجة عادية فيها
`is_error=True` (وإذا كان `ToolError`، يقرأ النموذج رسالتك). لا يغيّر `raise_exceptions`
ذلك: سواء فعّلته أم لا، يعيد `call_tool` النتيجة نفسها مع `is_error=True`. توجد صفحة كاملة لذلك:
**[معالجة الأخطاء](../servers/handling-errors.md)**.

أما الإخفاق **خارج** جسم الأداة فمختلف. في الاتصال الذي يوفّره `Client(mcp)`، يحوّل
الخادم الخطأ إلى رسالة عامة `"Internal server error"` قبل أن يراه العميل. ينبغي
ألّا تسرّب تفاصيل انهيار غير متوقع إلى مستدعٍ بعيد. وفي الاختبار، هذا تحديدًا ما
*لا* تريده، وهو ما يغيّره `raise_exceptions=True`: يرى اختبارك الرسالة الفعلية
بدلًا من الرسالة التي أُخفيت تفاصيلها.

اتركه مفعّلًا في الاختبارات. لا معنى له في شيفرة الإنتاج.

## مستقل عن جيل البروتوكول افتراضيًا {#era-neutral-by-default}

!!! note
    يتصل `Client(mcp)` داخل العملية ويكون **مستقلًا عن جيل البروتوكول** افتراضيًا: يفحص الخادم
    ويختار مسار البروتوكول المناسب. ثبّت `mode="legacy"` إذا كان اختبارك يختبر سلوكًا خاصًا بالبروتوكول القديم
    (دفع طلبات أخذ العينات أو استقاء المعلومات، أو `message_handler`)، واحذف `raise_exceptions=True`
    حينها: فالاتصال القديم لا يُخفي التفاصيل أصلًا، ويعيد هذا الخيار إطلاق
    الإخفاق داخل مهمة الخادم بدلًا من اختبارك.

هذا السطر الواحد هو أيضًا ما يتيح لهذا التوثيق ضمان عمل أمثلته: تختبر
مجموعة اختبارات SDK كل ملف مثال، ومعظمها باستخدام هذا
العميل نفسه. أنت تستخدم الأداة نفسها التي تستخدمها SDK لاختبار ذاتها.

لديك خادم يعمل وتُختبر صحته. توضح **[الاتصال بتطبيق مضيف فعلي](real-host.md)** وضعه داخل تطبيق حقيقي (Claude Desktop أو
IDE)؛ وتوضح كل الطرق الأخرى لإتاحته صفحة
**[تشغيل خادمك](../run/index.md)**.
