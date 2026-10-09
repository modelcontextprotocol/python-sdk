---
translation:
  sections: [4c1dea378b2b1bf7, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, c3d1099701156881, e185a1b8e53669f6]
  tool: 1
---
# الميزات المهملة {#deprecated-features}

تستغني مواصفة 2026-07-28 عن خمس ميزات. ما زالت SDK تنفّذها كلها، وأصبحت كل واحدة تحمل **تحذير إهمال**. وهناك أيضًا حالات إهمال خاصة بـSDK، مُدرجة [في النهاية](#deprecated-sdk-helpers).

يسمّي الجدول أدناه كل ميزة مهملة، وسبب الاستغناء عنها، والبديل الذي تبني عليه.

## ما المهمل {#what-is-deprecated}

| الميزة المهملة | السبب | ما تفعله بدلًا منها |
|---|---|---|
| **المجلدات الجذرية**: `ctx.session.list_roots()` و`client.send_roots_list_changed()` و`list_roots_callback=` التي تمرّرها إلى `Client(...)` | يستغني [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) عن هذه القدرة. | خذ المسارات كوسيطات أدوات عادية أو عناوين URI للموارد، أو ضمّن `ListRootsRequest` في `InputRequiredResult` (راجع **[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md)**). |
| **أخذ العينات الذي يبدأه الخادم**: `ctx.session.create_message()` و`sampling_callback=` التي تمرّرها إلى `Client(...)` | يستغني SEP-2577 عن هذه القدرة. | أعِد `InputRequiredResult` ودع العميل يعيد الاستدعاء (راجع **[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md)**). |
| **التسجيل عبر البروتوكول**: `ctx.log()` و`ctx.debug()` و`ctx.info()` و`ctx.warning()` و`ctx.error()` و`ctx.session.send_log_message()` و`client.set_logging_level()` | يستغني SEP-2577 عن هذه القدرة. لا يوجد بديل لها داخل البروتوكول. | استخدم `import logging` العادي إلى stderr (راجع **[التسجيل](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | **أُزيلت** من البروتوكول، ولم تُهمل فقط. لا توجد طريقة `ping` في 2026-07-28. | لا شيء. تعمل فقط في اتصال `mode="legacy"`. |
| **التقدم من العميل إلى الخادم**: `client.send_progress_notification()` | يجعل 2026-07-28 التقدم من الخادم إلى العميل فقط. | لا شيء لإرساله. يبلغ *خادمك* عن التقدم باستخدام `ctx.report_progress()` (راجع **[التقدم](handlers/progress.md)**). |

تنتج ثلاث نقاط من هذا الجدول:

* المجلدات الجذرية وأخذ العينات والتسجيل مترابطة. يهمل اقتراح واحد، **SEP-2577**، القدرات الثلاث معًا.
* يشترك أخذ العينات والمجلدات الجذرية في مشكلة أعمق: كلاهما موضع يرسل فيه **الخادم** **طلبًا** إلى **العميل**. يستبدل 2026-07-28 هذا الاتجاه كله بـ**[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md)**. ما اختفى هو طرائق RPC المستقلة (`sampling/createMessage` و`roots/list` و`elicitation/create` بالدفع)؛ أما أنواع الحمولة `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` فتبقى، مضمنة في `InputRequiredResult.input_requests`، وتصل إلى دوال رد النداء نفسها على جانب العميل.
* تختلف `ping` عن البقية. لا تهملها المواصفة، بل تزيلها. ما زالت طريقة SDK تحذّر (تقول رسالتها *أُزيلت* لا *أُهملت*)، ويرد استدعاؤها في اتصال حديث بـ*«Method not found»*.

## الإهمال إرشادي {#deprecated-is-advisory}

لا يتعطل شيء حاليًا.

تظل كل طريقة أعلاه تعمل في أي جلسة تفاوضت على **2025-11-25 أو أقدم**. ثبّت `mode="legacy"` في العميل لتحصل على سلوك ما قبل 2026 نفسه تمامًا. لا تغييرات في البيانات المنقولة، ولا في التفاوض على القدرات.

ما يتغير هو ظهور تحذير واضح أول مرة تعمل فيها كل طريقة:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

يشتق `MCPDeprecationWarning` من `UserWarning`، **وليس** `DeprecationWarning`. هذا مقصود: لا يعرض مرشح Python الافتراضي `DeprecationWarning` إلا في الشيفرة المشغّلة مباشرة باسم `__main__`، ولذلك قد تهمل المكتبات شيئًا دون أن يلاحظ أحد لمدة سنتين. يظهر هذا التحذير في كل مكان، دون خيار `-W`.

!!! warning
    يتوقف معنى «إرشادي» عند النقل. أخذ العينات والمجلدات الجذرية *طلبات* من الخادم إلى العميل، ولا توجد
    في جلسة 2026-07-28 قناة لحملها. استدعِ `ctx.session.create_message()`
    داخل أداة في اتصال حديث، وسيظهر التحذير، ثم يفشل
    الإرسال بخطأ:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    إشارتان بهذا الترتيب. يظهر `MCPDeprecationWarning` بمجرد استدعاء
    الطريقة، في أي اتصال. ثم يعود الخطأ عندما تحاول SDK
    الإرسال. لا تعمل الميزتان من طرف إلى طرف إلا في اتصال `mode="legacy"` سجّل عميله
    دالة رد النداء المناسبة.

## `ping` في جلسة قديمة {#ping-on-a-legacy-session}

**ping** طلب فارغ يستطيع أي طرف إرساله للتحقق من أن الآخر ما زال يجيب. تزيله مواصفة 2026-07-28 ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): يثبت كل طلب يرسله عميل حديث بالفعل أن الخادم موجود، ولا يملك الخادم الحديث قناة لإرسال طلب كهذا. تظل طريقتا SDK تعملان في جلسة من جيل المصافحة. من العميل:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

ومن الخادم، داخل أي دالة معالجة:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* تحذّر `client.send_ping()` باستخدام `MCPDeprecationWarning` في كل استدعاء. وفي اتصال افتراضي (`2026-07-28`)، يجيب الخادم بـ`MCPError: Method not found` بدلًا من ذلك.
* لا تحمل `ctx.session.send_ping()` تحذيرًا. في اتصال حديث، ترفع خطأ غياب القناة العكسية نفسه مثل أي طلب آخر يبدأه الخادم.
* لا يسجّل أي طرف شيئًا للإجابة عن ping.

## إشعارات تغير المجلدات الجذرية {#roots-change-notifications}

يستطيع عميل من جيل 2025 أعلن قدرة المجلدات الجذرية إخبار الخادم بتغير مجلدات مساحة عمله عبر إرسال `notifications/roots/list_changed`؛ فيطلب الخادم `roots/list` مجددًا. تزيل مواصفة 2026-07-28 الإشعار مع بقية تدفّق المجلدات الجذرية بالدفع. في العميل، تعلن `list_roots_callback=` (**[دوال رد نداء العميل](client/callbacks.md)**) القيمة `"roots": {"listChanged": true}`، ويفي استدعاء واحد بهذا الوعد:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

في الخادم، يأخذ `Server` منخفض المستوى دالة معالجة الاستقبال:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` هي القائمة التي تعيدها `list_roots_callback`. تحذّر `client.send_roots_list_changed()`، وتحتاج إلى عميل `mode="legacy"`: في اتصال حديث، يُسقط الإشعار بصمت. أبقِ الجلسة مفتوحة بعد ذلك، لأن طلب الخادم اللاحق `roots/list` يصل عبرها.
* لا تتضمن `MCPServer` دالة لمعالجة الإشعار. في `Server` منخفض المستوى، تسجّل `on_roots_list_changed=` الدالة (وهي مهملة أيضًا وتحذّر عند الإنشاء). لا يحمل الإشعار حمولة، ولذلك تستدعي الدالة `ctx.session.list_roots()` للحصول على القائمة الجديدة.

## إسكات التحذير {#silencing-the-warning}

لا تفعل ذلك في الشيفرة الجديدة.

لكن الخادم الذي تصونه ويخدم فعلًا عملاء ما قبل 2026 يحق له سجل هادئ. رشّح الفئة قبل أول استدعاء مهمل:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

هذه واجهة API كاملةً. لا يوجد خيار لكل طريقة، ولا تحتاج إليه: فالغرض من الفئة الواحدة أن يسكتها سطر واحد ويعيدها سطر واحد.

!!! check
    استخدم المرشح في الاتجاه الآخر لتحصل على اختبار انحدار مجاني. أضف
    `"error::mcp.MCPDeprecationWarning"` إلى إعداد `filterwarnings` في
    إعدادات pytest، وسيؤدي الاستدعاء المهمل إلى **رفع استثناء** بدلًا من التحذير. تتوقف أداة اسمها
    `old_log` ما زالت تستدعي `ctx.info()` عن النجاح: يعود الاستدعاء بـ`is_error=True` مع
    `Error executing tool old_log`، ويسمّي سجل الخادم الملتقط السبب:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    سطر واحد من إعداد pytest، ولن يستطيع استدعاء مهمل العودة إلى
    شيفرتك دون إخفاق اختبار.

## الدوال المساعدة المهملة في SDK {#deprecated-sdk-helpers}

ليست هذه تغييرات في المواصفة، وإنما استخدامات SDK لها بدائل أفضل. تحذّر باستخدام `MCPDeprecationWarning` نفسه، ويزيل 3.0 الشكل القديم.

| الاستخدام المهمل | ما تفعله بدلًا منه |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | استخدم `FuncMetadata.validate_arguments()` ثم `FuncMetadata.call_fn()`. لم يستدعها إلا من يدير `FuncMetadata` مباشرة (مثل صنف `Tool` مخصص). |
| `AuthSettings(resource_server_url=...)` دون `validate_token_resource=` | عيّنها: تجعل `True` الخادم يرفض رموز الحامل التي لا يؤكد متحققك إصدارها لـ`resource_server_url`، وتعني `False` أن متحققك يفحص جمهور الرمز بنفسه (راجع **[التفويض](run/authorization.md#a-token-verifier)**). تتصرف القيمة غير المعيّنة مثل `False`؛ ويجعل 3.0 قيمة `True` افتراضية عندما تكون `resource_server_url` معيّنة. |
| `ClientCredentialsOAuthProvider(...)` أو `PrivateKeyJWTOAuthProvider(...)` دون `issuer=` | مرّر `issuer=` باسم خادم التفويض الذي أصدر بيانات الاعتماد (راجع **[كتابة عملاء OAuth](client/oauth-clients.md#machine-to-machine)**). دونها، يقرر خادم MCP خادم التفويض الذي يتلقاها؛ ويجعل 3.0 الوسيطة المسماة مطلوبة. |

## مراجعة {#recap}

* تهمل مواصفة 2026-07-28 **المجلدات الجذرية** و**أخذ العينات** الذي يبدأه الخادم و**التسجيل** عبر البروتوكول (كلها في [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577))، وتقصر **التقدم** على الخادم إلى العميل، وتزيل **`ping`**.
* يرشدك عمود البدائل إلى **[الطلبات متعددة جولات الطلب والرد](handlers/multi-round-trip.md)** لأخذ العينات والمجلدات الجذرية، و**[التسجيل](handlers/logging.md)** للتسجيل، و**[التقدم](handlers/progress.md)** للتقدم. لا تحتاج `ping` إلى أي بديل.
* الإهمال إرشادي: لا تغييرات في البيانات المنقولة، وتظل الميزات تعمل في جلسات ما قبل 2026، ويظهر `MCPDeprecationWarning` واضح (من نوع `UserWarning`، ولذلك يُعرض افتراضيًا).
* يحتاج أخذ العينات والمجلدات الجذرية أيضًا إلى قناة عكسية لا تملكها جلسة 2026-07-28. في اتصال حديث، يحذّران ثم يثيران استثناءً.
* تسكت `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` الفئة كاملةً؛ وتحولها `"error::mcp.MCPDeprecationWarning"` في pytest إلى إخفاق اختبار.
* تتبع [حالات الإهمال في SDK](#deprecated-sdk-helpers) القاعدة نفسها: تحذّر الآن، ويحذف 3.0 الشكل القديم.
* ينبغي ألا تُبنى الشيفرة الجديدة على أي من هذه الميزات.

تعلّمك كل صفحة أخرى في هذا التوثيق واجهة API الحالية.
