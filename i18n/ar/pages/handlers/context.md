---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# السياق {#the-context}

تأتي وسائط الأداة من النموذج. وكل ما عداها (الطلب الذي تخدمه، والخادم الذي تعمل فيه، ووسيلة التواصل مع العميل) يأتي من كائن واحد: **`Context`**.

لا تنشئه ولا تعدّه. تطلبه فقط.

## اطلبه {#ask-for-it}

أضف مَعلمة ذات تعليق نوع `Context` إلى أي أداة:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* تبني SDK كائن `Context` جديدًا لكل طلب وتمرّره.
* **لا يهم اسم** المَعلمة. سواء `ctx` أو `context` أو `c`، تعثر عليها SDK من تعليق نوعها.
* تستطيع الموارد وقوالب التوجيه إعلان واحد أيضًا بالطريقة نفسها.
* `ctx.request_id` هو معرّف الطلب الذي تخدمه دالتك الآن.

!!! info
    إذا استخدمت FastAPI، فقد رأيت هذا الأسلوب: أعلن مَعلمة بنوع خاص بإطار العمل
    (`Request` هناك و`Context` هنا) فيوفرها الإطار. لا تسجيل ولا
    إعداد: تعليق النوع هو الآلية كاملة.

### غير مرئي للنموذج {#invisible-to-the-model}

هذه الفكرة التي ينبغي استيعابها. إليك مخطط المدخلات الذي يعرضه `tools/list` لـ`search_books`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

خاصية واحدة. ليست `ctx` وسيطة: لا تظهر أبدًا في المخطط، ولا يعرف عنها النموذج، ولا يستطيع أي عميل ملأها. إنها عقد بينك وبين SDK، وغير مرئية في البيانات المنقولة.

### جرّبه {#try-it}

شغّل الخادم باستخدام MCP Inspector:

```console
uv run mcp dev server.py
```

يملك نموذج `search_books` حقل `query` واحدًا. استدعِه مع `dune`:

```text
[request 3] Found 3 books matching 'dune'.
```

الرقم هو معرّف الطلب الحالي. استدعِ الأداة مجددًا فيتغير: لكل طلب `Context` خاص به.

## ما الذي يوفّره لك؟ {#what-it-gives-you}

الكائن المحقون صغير. إلى جانب `request_id`:

* `await ctx.read_resource(uri)`: اقرأ أحد موارد الخادم **نفسه** من داخل أداة. يشرح ذلك القسم التالي.
* `await ctx.report_progress(progress, total, message)`: أرسل التقدم إلى المستدعي أثناء استدعاء طويل. التفاصيل كاملة في **[التقدم](progress.md)**.
* `await ctx.elicit(message, schema)` و`await ctx.elicit_url(...)`: أوقف الأداة مؤقتًا واسأل المستخدم. هذا موضوع **[استقاء المعلومات](elicitation.md)**.
* `ctx.session`: جانب الخادم من المحادثة مع هذا العميل. توجد هنا الإشعارات التي ترسلها إليه؛ ويستخدمها القسم الأخير.
* `ctx.headers`: ترويسات الطلب التي حملتها وسيلة النقل، أو `None` في stdio. اقرأ ترويسة مخصصة باستخدام `(ctx.headers or {}).get("x-...")`. الترويسات مدخلات يقدّمها العميل؛ تصلح للغة أو لخيار ميزة، ولا تصلح أبدًا لإثبات الهوية.
* `ctx.request_context`: السجل الخام الخاص بكل طلب. الحقل الذي ستحتاج إليه هو `lifespan_context`، أي الكائن الذي أنتجته شيفرة بدء التشغيل (راجع **[دورة الحياة](lifespan.md)**).

التسجيل غير موجود في هذه القائمة عمدًا. يسجّل الخادم باستخدام وحدة `logging` في Python مثل أي برنامج Python آخر. وتشرح **[التسجيل](logging.md)** السبب باختصار.

!!! tip
    يحدث الحقن للدالة التي سجّلتها فقط. لا تحصل دالة مساعدة تستدعيها أداتك
    على `Context` خاص بها؛ مرّر `ctx` إليها كوسيطة عادية. لا يوجد
    "سياق حالي" عام تسترجعه من مكان آخر.

## اقرأ مواردك الخاصة {#read-your-own-resources}

موارد الخادم ليست للعملاء فقط. تستطيع الأداة قراءتها أيضًا:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

تحلّ `ctx.read_resource` عنوان URI عبر السجل نفسه الذي يخدم `resources/read`، لذلك تحصل الأداة على ما يحصل عليه العميل: كائن قابل للتكرار من `ReadResourceContents`، واحد لكل كتلة محتوى. لهذا URI كتلة واحدة:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` هو بالضبط ما أعادته `genres()`. مصدر حقيقة واحد: يتصفح العميل المورد، وتستهلكه أدواتك، ولا ينسخ أحد السلسلة النصية.
* المَعلمة الوحيدة لـ`describe_catalog` هي `Context`، لذا **لا توجد أي خصائص** في مخطط المدخلات. يستدعيها النموذج باستخدام `{}`.

## أخبر العميل بتغيّر القائمة {#tell-the-client-the-list-changed}

ما يتيحه الخادم ليس ثابتًا عند الاستيراد. سجّل أداة أثناء التشغيل، ثم أخبر العميل:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* تسجّل `mcp.add_tool(recommend_book)` دالة عادية كأداة: يُشتق الاسم والوصف والمخطط تمامًا كما يفعل `@mcp.tool()`.
* ترسل `await ctx.session.send_tool_list_changed()` إشعار `notifications/tools/list_changed`. يعيد العميل الذي يتلقاه استدعاء `tools/list` ويرى `recommend_book`.

العمليات المقابلة هي `send_resource_list_changed()` و`send_prompt_list_changed()` و`send_resource_updated(uri)` لتغيّر مورد محدد.

في اتصال 2026-07-28، لا يتلقى العملاء إشعارات التغيير إلا على تدفّق `subscriptions/listen` فتحوه، لذلك لا تصل طرق `send_*` أعلاه إلى تلك التدفّقات. توصل طرق النشر في `Context` الإشعارات إلى كل التدفّقات المشتركة دفعة واحدة: `await ctx.notify_tools_changed()` و`await ctx.notify_prompts_changed()` و`await ctx.notify_resources_changed()` و`await ctx.notify_resource_updated(uri)`. التفاصيل كاملة، بما فيها التوسع عبر نسخ الخادم، في **[الاشتراكات](subscriptions.md)**.

!!! check
    قبل أن يشغّل أحد `enable_recommendations`، لا توجد الأداة التي تعد بها. استدعِها
    رغم ذلك فتكون النتيجة خطأ يستطيع النموذج قراءته:

    ```text
    Unknown tool: recommend_book
    ```

    شغّل `enable_recommendations` فينجح الاستدعاء نفسه. قائمة الأدوات
    ديناميكية فعلًا: يعكس `tools/list` كل ما هو مسجّل *الآن*.

## مراجعة {#recap}

* أضف تعليق نوع `Context` إلى مَعلمة (في أداة أو مورد أو قالب توجيه) فتحقنها SDK. أنت تختار الاسم.
* هي غير مرئية للنموذج: لا يحتوي مخطط المدخلات إلا على وسائطك الفعلية.
* تحدد `ctx.request_id` الطلب؛ و`ctx.request_context.lifespan_context` هو ما أنتجته شيفرة بدء التشغيل.
* تتيح `await ctx.read_resource(uri)` للأداة قراءة موارد الخادم نفسه.
* `ctx.session` قناة التواصل مع العميل: تخبره `send_tool_list_changed()` والطرق المقابلة بإعادة جلب قائمة غيّرتها.
* يبدأ الإبلاغ عن التقدم واستقاء المعلومات أيضًا من `Context`؛ ولكل منهما صفحة خاصة.

المَعلمات التي لا يراها النموذج وتملؤها دوالك هي **[الاعتماديات](dependencies.md)**.
