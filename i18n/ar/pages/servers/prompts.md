---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# قوالب التوجيه {#prompts}

**قالب التوجيه** (prompt) قالب رسائل يختاره المستخدم.

الأدوات للنموذج. أما قالب التوجيه فعلى العكس: يختاره المستخدم من قائمة في عميله (أمر يبدأ بشرطة مائلة أو زر)، ويملأ وسائطه، ثم تدخل الرسائل الناتجة في المحادثة كما لو أنه كتبها.

تعلن عنه بوضع `@mcp.prompt()` على دالة تعيد النص.

## قالب توجيهك الأول {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

تقرأ SDK الأشياء الثلاثة نفسها التي تقرؤها من الأداة:

* **الاسم** هو اسم الدالة: `review_code`.
* **الوصف** الذي يعرضه العميل هو سلسلة التوثيق: `Review a piece of code.`
* تأتي **الوسائط** من المَعلمات. لا تملك `code` قيمة افتراضية، لذا فهي مطلوبة.

هذا ما يتلقاه العميل من `prompts/list`:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

لا يوجد JSON Schema هنا. وسائط قالب التوجيه قائمة مسطحة من **قيم نصية مسمّاة**: نموذج يملؤه شخص، لا حمولة يبنيها نموذج لغوي.

### توليد الرسائل منه {#rendering-it}

يولّد العميل رسائل القالب باستخدام `prompts/get`، مع تمرير الوسائط. تعمل دالتك وتصبح `str` التي تعيدها **رسالة مستخدم واحدة**:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

هذه دورة حياة قالب التوجيه كاملة: يُعرض بالاسم، وتُولَّد رسائله عند الطلب، وتُضاف إلى المحادثة.

!!! check
    يُفرَض `required` قبل تشغيل دالتك. اطلب رسائل `review_code` دون `code` فيفشل
    الطلب نفسه بخطأ JSON-RPC (رمزه `-32603`):

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    لا توجد نتيجة خطأ على نمط الأدوات لتُعاد إلى النموذج، لأن النموذج ليس طرفًا في العملية:
    يثير الاستدعاء استثناءً. ويظهر السبب (`Missing required arguments: {'code'}`) في سجل خادمك.

### جرّبه {#try-it}

شغّل الخادم باستخدام MCP Inspector:

```console
uv run mcp dev server.py
```

افتح تبويب **Prompts** واختر `review_code`. ينشئ Inspector نموذجًا بحقل `code` مطلوب واحد. املأه وولّد الرسائل، وستحصل بالضبط على رسالة المستخدم أعلاه.

## أكثر من رسالة واحدة {#more-than-one-message}

مراجعة الشيفرة رسالة واحدة. أما جلسة تصحيح الأخطاء فمحادثة، ويمكن لقالب توجيه تهيئتها كاملة.

أعِد قائمة رسائل بدلًا من `str`:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* تأتي `UserMessage` و`AssistantMessage` من `mcp.server.mcpserver.prompts.base`. مرّر إليهما `str` فتغلّفانها في `TextContent` نيابة عنك. يحدد اسم الفئة الدور.
* `Message` فئتهما الأساسية المشتركة. استخدمها كتعليق نوع الإرجاع.

ينتج توليد رسائل `debug_error` الآن ثلاث رسائل بالترتيب:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

لاحظ الأخيرة. تعبئة دور `assistant` مسبقًا وسيلة لتوجيه رد النموذج *التالي* دون أن يكتب المستخدم التوجيه بنفسه.

## العناوين وأوصاف الوسائط {#titles-and-argument-descriptions}

`review_code` اسم دالة، وليس عنوانًا للعرض. امنح العميل اسمًا أفضل لوضعه على الزر، وصف كل وسيطة كي يكون النموذج واضحًا:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` هو الاسم المقروء للبشر، تمامًا مثل `title` للأداة.
* `Annotated[str, Field(description=...)]` هو النمط نفسه الذي تستخدمه **[الأدوات](tools.md)** لوصف مَعلمات الأداة. هنا يظهر الوصف على الوسيطة بدلًا من مخطط.
* تملك `language` قيمة افتراضية، فتتوقف عن كونها مطلوبة.

يحمل إدخال `prompts/list` الآن كل ما يحتاج إليه العميل لإنشاء نموذج جيد:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    إذا قرأت **[الأدوات](tools.md)**، فأنت تعرف كل ما سبق بالفعل. المزخرف نفسه،
    وسلسلة التوثيق كوصف، و`Annotated`/`Field` نفسيهما. لا يتغير إلا من
    يبدأ الاستدعاء (المستخدم) وأين تذهب النتيجة (إلى المحادثة).

## أكثر من نص {#more-than-text}

تقبل `UserMessage` و`AssistantMessage` أيضًا كتلة محتوى، أو كائنًا مساعدًا `Image` / `Audio`، حيثما تقبلان `str`. تظهر حالتان في قوالب التوجيه: إرفاق مستند وإرفاق صورة.

### تضمين ملف {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* دليل الأسلوب مورد على `style://python` (تغطي **[الموارد](resources.md)** ذلك)، يُقرأ من `style-guide.md` بجانب `server.py`. ضع أي ملف Markdown هناك.
* تحمل `EmbeddedResource(resource=TextResourceContents(...))`، وكلاهما من `mcp.types`، الملف مع URI ونوع MIME كرسالة أولى؛ ويتبعها الطلب الذي يشير إليه كنص عادي.
* يسمح التضمين، بدلًا من لصق الدليل داخل سلسلة f-string، للعميل بعرضه كمرفق وإعادة فتح `style://python` لاحقًا، ويتلقى النموذج الملف حرفيًا. لملف ثنائي، استخدم `BlobResourceContents` مع `blob` بترميز base64.

بعد توليد الرسائل، يكون `content` للرسالة الأولى كتلة `resource`:

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### إرفاق صورة {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` هو الكائن المساعد في **[الصور والصوت والأيقونات](media.md)**. تحوّله `UserMessage` إلى كتلة `ImageContent` (الملف بترميز base64، ونوع MIME مستنتج من `.png`) عند توليد رسائل القالب؛ ويتحول `Audio` إلى `AudioContent` بالطريقة نفسها.
* ضع أي صورة PNG باسم `architecture.png` بجانب `server.py`. وسائط قوالب التوجيه نصوص، لذلك تأتي الصورة دائمًا من الخادم؛ ولا يوفّر `component` إلا الكلمات.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## تغيير القائمة أثناء التشغيل {#changing-the-list-at-runtime}

يمكن إضافة قوالب التوجيه أثناء اتصال العملاء، مثلًا للسماح للمستخدم بحفظ تعليمات كعنصر قائمة خاص به. سجّل القالب ثم أرسل الإشعار:

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* تسجّل `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` دالة تمامًا كما تفعل `@mcp.prompt()`، و`mcp.remove_prompt(name)` العملية العكسية. تحتفظ `add_prompt` بإدخال موجود بالاسم نفسه بدلًا من استبداله، لذلك تزيل الأداة الإدخال القديم أولًا كي يستبدله الحفظ. يعكس `prompts/list` التغيير فورًا.
* ترسل `await ctx.notify_prompts_changed()` إشعار `notifications/prompts/list_changed` إلى كل عميل `2026-07-28` يستمع على تدفّق `subscriptions/listen` (**[الاشتراكات](../handlers/subscriptions.md)**). وترسله `await ctx.session.send_prompt_list_changed()` إلى العميل المستدعي إذا كان يستخدم بروتوكولًا أقدم من 2026 (**[خدمة العملاء القدامى](../run/legacy-clients.md)**). استدعِ كليهما؛ لا تفعل أيٌّ منهما شيئًا إذا لم يوجد من تُبلغه.
* يعيد العميل الذي يتلقى الإشعار استدعاء `prompts/list`. في `Client` الخاص بـPython، تكون الصيغة `async with client.listen(prompts_list_changed=True) as sub:`، التي تنتج حدث `PromptsListChanged`.

## مراجعة {#recap}

* وضع `@mcp.prompt()` على دالة يجعلها قالب توجيه. يأتي الاسم من الدالة والوصف من سلسلة التوثيق.
* **يتحكم المستخدم** في قوالب التوجيه: يعرضها العميل، ويختار المستخدم واحدًا ويملأ الوسائط.
* الوسائط قائمة مسطحة من نصوص مسمّاة (دون مخطط). والمَعلمة ذات القيمة الافتراضية اختيارية.
* أعِد `str` فتصبح رسالة مستخدم واحدة. وأعِد قائمة `UserMessage` / `AssistantMessage` لتهيئة محادثة متعددة الأدوار.
* يضع العميل `title=` و`Field(description=...)` في واجهته.
* يؤدي غياب وسيطة مطلوبة إلى إخفاق الطلب كله. لا توجد نتيجة خطأ منفصلة لكل قالب.
* غلّف `EmbeddedResource` أو `Image` داخل `UserMessage` لإرفاق مستند أو صورة.
* أضف قوالب التوجيه أو احذفها أثناء التشغيل باستخدام `mcp.add_prompt(...)` / `mcp.remove_prompt(...)`، ثم `await ctx.notify_prompts_changed()` و`await ctx.session.send_prompt_list_changed()`.

الإكمال التلقائي من جانب الخادم لوسائط قالب توجيه (أو قالب مورد) موضوع **[الإكمالات](completions.md)**.
