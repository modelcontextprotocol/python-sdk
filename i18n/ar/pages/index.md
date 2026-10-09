---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "توثيق v2، سلسلة الإصدارات المستقرة الحالية"
    هل تبدأ مع v2، أم تنتقل من v1؟ تقدم **[المستجدات في v2](whats-new.md)** جولة مدتها خمس دقائق للتغييرات، ويغطي **[دليل الترحيل](migration.md)** جميع التغييرات غير المتوافقة مع الإصدارات السابقة.
    هل ما زلت تستخدم v1.x؟ ستجد توثيقها في [توثيق v1.x](https://py.sdk.modelcontextprotocol.io/v1/).
    هل وجدت شيئًا غير واضح أو يحتاج إلى تحسين؟ [أخبرنا](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

يتيح **Model Context Protocol (MCP)** للتطبيقات توفير السياق لنماذج LLM بطريقة موحّدة، مع فصل مهمة *توفير* السياق عن التفاعل مع النموذج نفسه.

هذه هي SDK الرسمية له بلغة Python. يمكنك استخدامها من أجل:

* **بناء خوادم MCP** تتيح أدوات وموارد وقوالب توجيه لأي تطبيق مضيف يدعم MCP.
* **بناء عملاء MCP** يتصلون بأي خادم MCP.
* التواصل عبر جميع وسائل النقل القياسية: stdio وStreamable HTTP وSSE.

## المتطلبات {#requirements}

Python 3.10+.

## التثبيت {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

تتيح لك الإضافة `[cli]` الأمر `mcp`؛ وستحتاج إليها أثناء التطوير.
راجع [التثبيت](get-started/installation.md) لمعرفة دور كل اعتمادية.

## مثال {#example}

### أنشئه {#create-it}

أنشئ ملفًا باسم `server.py`:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

هذا خادم MCP كامل.

يتيح **أداة** واحدة، هي `add`، و**موردًا** واحدًا يعتمد على قالب، هو `greeting://{name}`.

### شغّله {#run-it}

```console
uv run mcp dev server.py
```

يشغّل هذا خادمك ويفتح [MCP Inspector](https://github.com/modelcontextprotocol/inspector)، وهي واجهة تفاعلية لاستكشافه. افتح عنوان URL الذي يطبعه.

!!! note
    Inspector تطبيق Node.js، لذلك يحتاج `mcp dev` إلى وجود `npx` ضمن `PATH`.

### جرّبه {#try-it}

انتقل في Inspector إلى **Tools** واستدعِ `add` بالقيمتين `a=1` و`b=2`.

ستحصل على `3`. ✨

أنشأ Inspector ذلك النموذج (حقل عدد صحيح مطلوب لـ`a` وآخر لـ`b`) من تلميحات الأنواع لديك. وكذلك سيفعل Claude وكل تطبيق مضيف آخر يدعم MCP.

انتقل الآن إلى **Resources** واقرأ `greeting://World`:

```text
Hello, World!
```

### مراجعة {#recap}

انظر مجددًا إلى ما **لم** تكتبه:

* لم تكتب JSON Schema. فتلميح النوع `a: int, b: int` *هو* المخطط.
* لم تكتب تحليلًا للطلبات أو تسلسلًا للبيانات أو شيفرة تحقق.
* لم تكتب أي معالجة للبروتوكول.

كتبت دالتين بلغة Python مع تلميحات للأنواع وسلسلة توثيق. تتولى SDK الباقي.

## إلى أين تتجه بعد ذلك؟ {#where-to-go-next}

* تنقلك **[ابدأ هنا](get-started/index.md)** من التثبيت إلى خادم يعمل وتُختبر صحته.
* هل تبني تطبيقًا *يستخدم* خوادم MCP؟ ابدأ بصفحة **[العملاء](client/index.md)**.
* هل لديك تطبيق FastAPI أو Starlette بالفعل؟ تشرح **[الإضافة إلى تطبيق موجود](run/asgi.md)** تركيب خادم MCP داخله.
* هل تبحث عن رسالة خطأ بعينها؟ تُنظَّم **[استكشاف الأخطاء وإصلاحها](troubleshooting.md)** حسب النص الحرفي للرسائل.
* هل تتساءل عمّا تغيّر في v2؟ تقدم **[المستجدات في v2](whats-new.md)** جولة مدتها خمس دقائق.
* هل ترحّل من v1؟ ابدأ بـ**[دليل الترحيل](migration.md)**.
* هل تبحث عن توقيع دالة دقيق؟ يُولَّد **[مرجع API](api/mcp/index.md)** من الشيفرة المصدرية.
* هل تقرأ باستخدام LLM؟ يُنشر هذا التوثيق أيضًا بتنسيق [llms.txt](https://llmstxt.org/):
  يشكّل [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) فهرسًا للصفحات، بينما
  يحتوي [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) على جميع الصفحات في ملف واحد.
