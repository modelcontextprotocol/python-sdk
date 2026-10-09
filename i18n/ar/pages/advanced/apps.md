---
translation:
  sections: [0355618e5f4d5fe4, 0fefa31fb7c7b585, 5c53e7487c9c70cc, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

**تطبيق MCP** أداة لها واجهة: إلى جانب بياناتها، تشير الأداة إلى وثيقة HTML
يعرضها التطبيق المضيف كواجهة تفاعلية.

يتألف دائمًا من جزأين:

1. **أداة** تنفّذ العمل وتعيد بيانات، مثل أي أداة أخرى.
2. **مورد `ui://`** يحتوي على HTML الذي يعرضه التطبيق المضيف لها.

تحمل الأداة مرجع `_meta.ui.resourceUri` إلى المورد. يجلبه التطبيق المضيف
باستخدام `resources/read`، ويعرضه في **iframe داخل بيئة معزولة**، ويدفع نتيجة
الأداة إلى ذلك الإطار عبر `postMessage`. لا يرسل خادمك أي رسائل
`ui/*` ولا يتلقاها: فهذه الحركة بين التطبيق المضيف والإطار. أنت تخدم أداة
ووثيقة HTML؛ ويتولى التطبيق المضيف العرض.

تقدّم SDK ذلك كامتداد `Apps` مدمج (`io.modelcontextprotocol/ui`).
إذا لم تكن تعرف [الامتدادات](extensions.md)، فاقرأ تلك الصفحة سريعًا أولًا. دقيقة واحدة،
ثم عد إلى هنا.

## ساعة بواجهة {#a-clock-with-a-face}

```python title="server.py" hl_lines="17 20 28 30"
--8<-- "docs_src/apps/tutorial001.py"
```

أربع خطوات:

* `Apps()`: نسخة واحدة تحمل أدواتك المرتبطة بالواجهة ومواردها.
* `@apps.tool(resource_uri="ui://clock/app.html")`: أداة عادية، مع
  وسم `_meta.ui.resourceUri`. يُمرّر كل ما تقبله `@mcp.tool()` (الاسم والعنوان
  والوصف وغيرها).
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: المورد
  المطابق، ويُقدّم بالنوع `text/html;profile=mcp-app`. نوع MIME هذا تحديدًا
  هو ما يخبر التطبيق المضيف: «هذا تطبيق، اعرضه».
* `MCPServer("clock", extensions=[apps])`: تفعيل اختياري. يعلن الخادم الآن
  `io.modelcontextprotocol/ui` تحت `capabilities.extensions`.

تستمع HTML نفسها إلى `postMessage` من التطبيق المضيف وتعرض النتيجة. للتطبيقات الفعلية،
استخدم SDK المتصفح الرسمية [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps)
داخل HTML. توفر لك `ontoolresult` و`callServerTool`
و`getHostContext` و`onhostcontextchanged` بدلًا من أحداث الرسائل الخام.

## تراجع سلس إلى النص {#graceful-degradation}

لا تعرض كل العملاء التطبيقات. المواصفة واضحة بشأن ما يعنيه ذلك لك:

> **يجب** أن تعيد الأدوات مصفوفة `content` ذات معنى حتى عندما تتوفر واجهة مستخدم.

يقرأ النموذج `content`؛ أما iframe فللبشر. يظل التطبيق المضيف القادر على عرض الواجهات يمرّر
النتيجة النصية إلى النموذج، ويحصل العميل النصي على ذلك *فقط*. ولذلك
فالنمط المعتمد هو أداة واحدة وإجابتان. انظر إلى `get_time` مجددًا:

```python title="server.py" hl_lines="21-25"
--8<-- "docs_src/apps/tutorial001.py"
```

لا تكون `client_supports_apps(ctx)` مساوية لـ`True` إلا عندما يعلن العميل
امتداد `io.modelcontextprotocol/ui` **و** يُدرج `text/html;profile=mcp-app`
في إعدادات `mimeTypes`. الحقل مطلوب، ولذلك لا يُعد العميل الذي يحذفه
داعمًا. إليك جانب العميل من التفاوض:

```python title="client.py" hl_lines="8 12"
--8<-- "docs_src/apps/tutorial001_client.py"
```

شغّل `server.py` عبر HTTP، ثم شغّل العميل في طرفية ثانية:

```console
uv run mcp run server.py --transport streamable-http
```

```console
python client.py
```

```text
2026-06-26T12:00:00Z
```

عادت الإجابة الغنية. احذف `extensions=[APPS_SUPPORT]` من استدعاء `Client`،
وسيَطبع البرنامج نفسه `The time is 2026-06-26T12:00:00Z.` بدلًا منها، وهو
كل ما يراه العميل النصي.

!!! warning
    لا تعِد عنصرًا نائبًا مثل `"[Rendered UI]"` بوصفه المحتوى الوحيد مطلقًا. إذا كان
    النص البديل غير مفيد، فالأداة غير مفيدة لكل عميل نصي وللنموذج
    نفسه. اكتب الجملة الفعلية.

## تقييد iframe {#locking-the-iframe-down}

يحمل جانب المورد البيانات الوصفية الأمنية: ما يجوز للإطار تحميله، وأذونات
المتصفح التي يطلبها، وكيف يريد تضمينه:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

تمثل `csp` و`permissions` **طلبات إلى التطبيق المضيف**، وليستا سلوكًا للخادم. يبني التطبيق المضيف
سياسَتي Content-Security-Policy وPermissions-Policy للإطار منهما، وقد
يرفض. تحقّق من توفر الميزات في JavaScript بدلًا من افتراض منحها.

حقول `ResourceCsp` واحدًا واحدًا (اسم Python، والمفتاح على الشبكة، وما يفعله التطبيق المضيف به):

| Python | على الشبكة (`_meta.ui.csp`) | ما يتحكم فيه |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: وجهات `fetch`/XHR المسموح بها |
| `resource_domains` | `resourceDomains` | `img-src` و`style-src` وغيرها: الملفات الثابتة |
| `frame_domains` | `frameDomains` | `frame-src`: إطارات iframe المتداخلة |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: الوجهات التي يجوز أن يشير إليها `<base>` |

`ResourcePermissions`: يطلب كل حقل إذنًا من المتصفح للإطار.

| Python | على الشبكة (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    توجد CSP والأذونات في **المورد**، وليس في الأداة مطلقًا. لا تتضمن البيانات الوصفية للأداة
    في المواصفة موضعًا لها، وتتجاهلها التطبيقات المضيفة هناك. تمنع SDK تمثيل
    هذا الخطأ: لا تحتوي `@apps.tool()` على مَعلمة `csp` أصلًا.

### الظهور {#visibility}

تعني `visibility=["app"]` في الأداة: «هذه موجودة للإطار، وليس للنموذج»:

* `"model"`: يستطيع النموذج استدعاءها.
* `"app"`: يستطيع الإطار استدعاءها (عبر `callServerTool`).
* عند الحذف: كلاهما، وهو الافتراضي.

الترشيح مهمة **التطبيق المضيف**. يدرج خادمك الأدوات الخاصة بالتطبيق فقط في `tools/list`
مثل غيرها؛ ويخفيها التطبيق المضيف عن النموذج. لا ترشّحها على جانب الخادم.

## القواعد التي تفرضها SDK {#the-rules-the-sdk-enforces}

تفشل كل الحالات التالية عند بدء التشغيل، وليس في الإنتاج:

* تؤدي `resource_uri` أو URI مورد لا تتبع `ui://...` إلى `ValueError` عند
  تطبيق المزخرف أو التسجيل.
* تؤدي الأداة المرتبطة بعنوان URI **دون مورد مسجّل مطابق** إلى `ValueError`
  عندما تستهلك `MCPServer(extensions=[apps])` الامتداد. الأداة التي تعلن
  HTML تعيد 404 عند `resources/read` إعداد خاطئ، ولذلك يرفض
  المُنشئ إكمال الإنشاء.
* تؤدي `meta={"ui": ...}` في `@apps.tool()` إلى `ValueError`. يتولى المزخرف
  `_meta["ui"]`؛ عبّر عنها باستخدام `resource_uri=` و`visibility=`. تُدمج مفاتيح `meta=` الأخرى
  بصورة طبيعية إلى جانبها.

لا تكتشف SDK ext-apps في TypeScript ولا FastMCP أيًا من هذه الحالات حاليًا؛ ويفضّل أن
تعرفها قبل أن يصادفها التطبيق المضيف.

## ما بعد HTML المضمّنة {#beyond-inline-html}

تغطي `add_html_resource` الحالة الشائعة: نص HTML. أما في غير ذلك،
مثل HTML على القرص أو محتوى مولّد، فابنِ المورد بنفسك ومرّره:

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

تضع `add_resource` نوع MIME `text/html;profile=mcp-app` عندما لا يعيّن المورد
نوعًا صريحًا، وترفض النوع الصريح المخالف: لن يعرض أي تطبيق مضيف مورد `ui://`
تحت نوع MIME آخر.

!!! tip
    هل تستهدف تطبيقًا مضيفًا يسبق الإتاحة العامة وما زال يقرأ المفتاح المسطح المهمل
    `_meta["ui/resourceUri"]`؟ ادمجه بنفسك:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    كائن `ui` المتداخل هو شكل المواصفة؛ أما المفتاح المسطح فسيُستغنى عنه.

## شاهده يعمل {#see-it-run}

قصة `apps` في `examples/stories/` هي هذه الصفحة في زوج قابل للتشغيل: خادم
بأداة ساعة مرتبطة بواجهة، وعميل يتفاوض على Apps ويقرأ
`_meta.ui.resourceUri` الخاصة بالأداة ويجلب HTML ويستدعي الأداة.

```bash
uv run python -m stories.apps.client
```
