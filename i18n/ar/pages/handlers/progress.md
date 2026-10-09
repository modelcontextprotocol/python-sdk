---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 52d6009a07e770ea, 8534d8dbb4053a70, 2e9aff14d3a882c0]
  tool: 1
---
# التقدم {#progress}

تبدو الأداة التي تستغرق ثلاثين ثانية دون أن تقول شيئًا طوالها معطلة.

تصلح **إشعارات التقدم** ذلك. تبلّغ الأداة عن مدى تقدمها؛ ويقرر العميل ما يعرضه: شريطًا أو مؤشر دوران أو سطر سجل.

## أبلِغ عنه من الأداة {#report-it-from-the-tool}

خذ مَعلمة **`Context`** واستدعِ `report_progress`:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

ثلاث وسائط، وأنت تقرر معناها:

* `progress`: مقدار ما أنجزته. تشترط المواصفة أن **يزداد** مع كل تقرير؛ لا تكرر قيمة أو تتراجع أبدًا.
* `total`: المقدار الكلي، إذا عرفته. اختياري.
* `message`: سطر مقروء للبشر عن *هذه* الخطوة. اختياري.

تُحقن `ctx` بسبب تلميح نوعها ولا يراها النموذج: يملك مخطط مدخلات `import_catalog` خاصية واحدة هي `urls`. تتناول صفحة **[السياق](context.md)** هذا الكائن؛ والتقدم أحد ما يوفّره.

## استمع إليه من العميل {#listen-for-it-from-the-client}

يختار العميل تلقي التقدم **لكل استدعاء** بتمرير `progress_callback=` إلى `call_tool`:

```python title="client.py" hl_lines="5 14"
import anyio
from mcp import Client


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

دالة رد النداء `async` وتتلقى بالضبط ما أبلغ عنه الخادم: `progress` و`total` و`message`.

!!! info
    `progress_callback` هي المَعلمة نفسها مهما مرّرت إلى `Client`: عنوان URL كما هنا، أو
    `StdioServerParameters`، أو كائن الخادم في اختبار. لكن انتبه للتوقيت عبر وسيلة
    نقل فعلية. يُسلَّم كل إشعار مستقلًا بجانب الاستجابة، لذلك قد تستمر دالة
    رد نداء بطيئة بعد عودة `call_tool`. اتصال الاختبار داخل العملية فقط
    ينفّذ الدالة مباشرة ويضمن وصول كل تقرير أولًا.

### جرّبه {#try-it}

أتح `server.py` عبر HTTP، ثم شغّل العميل من نافذة طرفية ثانية:

```console
uv run mcp run server.py --transport streamable-http
```

```console
python client.py
```

```text
Imported https://example.com/a.json (1.0/2.0)
Imported https://example.com/b.json (2.0/2.0)
{'result': 'Imported 2 records.'}
```

أصبح كل `await ctx.report_progress(...)` على الخادم استدعاءً واحدًا لـ`show` على العميل بالترتيب. لا يُضم التقدم إلى النتيجة، بل يتدفق أثناء استمرار عمل الأداة.

!!! warning
    تخص `progress_callback` **الاستدعاء**، لا `Client`. لا توجد وسيطة لها في المُنشئ،
    لأن الاستدعاءات المختلفة تحتاج إلى دوال مختلفة: واحدة تدير شريط تنزيل، وأخرى
    سطر سجل.

!!! check
    احذف الآن `progress_callback=show` وشغّل مجددًا:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    لا خطأ ولا تحذير والنتيجة نفسها. **لا تفعل `report_progress` شيئًا إذا لم يطلب المستدعي
    التقدم**، لذلك تُبلّغ دون شرط ولا تحتاج إلى التساؤل عمّا إذا كان أحد
    يستمع.

## عندما لا تعرف الإجمالي {#when-you-dont-know-the-total}

`total` للحالات التي تعرف فيها الإجمالي. غالبًا لا تعرفه: تستهلك تدفق بيانات، أو تمر على مؤشر، أو تنزّل شيئًا دون ترويسة طول.

احذفه:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

تتلقى دالة رد النداء `total=None`. يستطيع العميل إظهار *نشاط* ("استُوردت 3 حتى الآن...")، لكنه لا يستطيع عرض نسبة مئوية. لا تختلق إجماليًا لتحسين شكل الشريط.

!!! tip
    لا يلزم أن يعدّ `progress` شيئًا معينًا. بايتات أو صفوف أو صفحات: اختر الوحدة التي
    يفهمها المستخدم، ولا تعد إلا بقيمة `total` تستطيع الوفاء بها.

## مراجعة {#recap}

* استخدم `await ctx.report_progress(progress, total=None, message=None)` من أي أداة تأخذ `Context`.
* يمرّر العميل `progress_callback=` إلى `call_tool`: لكل استدعاء، وليس إلى `Client` أبدًا.
* دالة رد النداء `async (progress, total, message) -> None` وتعمل أثناء استمرار تشغيل الأداة.
* غياب دالة رد نداء في الاستدعاء يعني أن `report_progress` لا تفعل شيئًا. أبلِغ دون شرط.
* احذف `total` إذا لم تعرفه؛ فتتلقى الدالة `None`.

التقدم لعميل ما زال ينتظر. ما تراه أداتك عندما يتوقف العميل عن الانتظار موضوع **[الإلغاء](cancellation.md)**.
