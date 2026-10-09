---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, 32ef568335dd95a7, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 0abc5ea5cb7ff6b3]
  tool: 1
---
# دوال رد النداء لدى العميل {#client-callbacks}

تسير تقريبًا جميع طلبات MCP في اتجاه واحد: من العميل إلى الخادم.

يستطيع الخادم أيضًا طلب أشياء من **العميل**: طرح سؤال على المستخدم، أو طلب توليد من نموذجه، أو عرض مجلدات مساحة عمله. تجيب عن هذه الطلبات بتمرير **دوال رد نداء** (callbacks) إلى `Client(...)`.

## خادم يسأل {#a-server-that-asks}

إليك خادمًا لا تستطيع أداته إنهاء عملها بمفردها:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* ترسل `ctx.elicit(...)` طلب `elicitation/create` **إلى العميل** وتنتظر.
* لا تعود الأداة حتى يقدّم أحد (شخص في نموذج أو شيفرتك) قيمة `name`.

هذا جانب الخادم، وتشرحه صفحة **[استقاء المعلومات](../handlers/elicitation.md)** (elicitation). هذه الصفحة للطرف الآخر.

## دالة رد النداء لاستقاء المعلومات {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* دالة رد النداء لاستقاء المعلومات هي `async (context, params) -> ElicitResult`.
* `params.message` هو السؤال. و`params.requested_schema` هو JSON Schema للإجابة المطلوبة. يعرض العميل الفعلي نموذجًا منه؛ ويملؤه هذا المثال تلقائيًا.
* تعيد `ElicitResult(action="accept", content={...})` أو `action="decline"` أو `action="cancel"`. الخيار الآخر الوحيد `ErrorData(...)`، الذي يرفض الطلب ويُفشل الاستدعاء كله.
* `context` هو `ClientRequestContext`: الجلسة الحالية `session`، ومعرّف طلب الخادم `request_id`، وأي `meta` أرفقها.

!!! tip
    `params` اتحاد نمطَي استقاء المعلومات. هنا `params.mode` هي `"form"`؛ ويحمل طلب `"url"`
    الحقل `params.url` بدلًا من مخطط. تعالج دالة واحدة النمطين؛ تفرّع حسب `params.mode`.
    تعرض **[استقاء المعلومات](../handlers/elicitation.md)** النمط كاملًا.

### جرّبها {#try-it}

استدعِ `issue_card` وراقب الطرفين.

تتلقى دالتك سؤال الخادم بعد تحليله بالفعل:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

تجيب، فتستأنف `ctx.elicit(...)` داخل الأداة، وتكمل الأداة عملها:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

طلب `tools/call` واحد منك، وطلب `elicitation/create` عكسي واحد من الخادم تجيب عنه دالتك، وكل ذلك داخل استدعاء أداة واحد.

!!! info
    يؤدي `mode="legacy"` في استدعاء `Client(...)` عملًا فعليًا. تتفاوض `Client(...)` افتراضيًا على مسار
    البروتوكول الحديث، ولا يملك ذلك المسار قناة عكسية لطلبات الخادم إلى العميل: تفشل `ctx.elicit`
    قبل تشغيل دالتك أصلًا. لا تحدد وسيلة النقل ذلك؛ بل يحدده
    البروتوكول المتفاوض عليه. ثبّت `mode="legacy"` كلما اضطر عميلك
    إلى الإجابة عن طلب كهذا؛ وهذا ما يفعله كل اختبار لهذه الصفحة. تتضمن **[إصدارات البروتوكول](../protocol-versions.md)** التفاصيل كاملة.

    على جلسة 2026-07-28، لا تصبح الدالة معطّلة بل تُغذّى بصورة مختلفة: عندما تعيد الأداة
    `InputRequiredResult` تحمل `ElicitRequest`، توجّه `Client` ذلك الإدخال إلى
    `elicitation_callback` نفسها وتعيد الاستدعاء نيابة عنك. هذا تدفق **[الطلبات متعددة جولات التبادل](../handlers/multi-round-trip.md)**.

## دالة رد النداء إعلان قدرة {#a-callback-is-a-capability}

لم تخبر الخادم بأن عميلك يستطيع الإجابة عن استقاء المعلومات. فعلت SDK ذلك.

عند اتصال العميل، يعلن `capabilities` الخاصة به، وهي المقابل لقدرات الخادم. لا تكتب ذلك الكائن. **تسجيل دالة رد نداء هو الإعلان.**

| ما تمرّره | ما يعلنه العميل |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| لا شيء منها | `{}` |

القدرات الفرعية لأخذ العينات (sampling) هي الاستثناء التفصيلي: مرّر `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` بجانب `sampling_callback` عندما تدعم دالتك مَعلمات `tools` / `tool_choice`. يجب أن يرى الخادم إعلان `sampling.tools` قبل إرسالها.

لا توجد `logging_callback` و`message_handler` في الجدول. تتعاملان مع إشعارات، ولا تحتاج الإشعارات إلى قدرة.

يقرأ الخادم الإعلان باستخدام `ctx.session.check_client_capability(...)`. أضف أداة تفعل ذلك:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

اتصل باستخدام `elicitation_callback` فقط واستدعِها:

```python
result.structured_content  # {'result': ['elicitation']}
```

مرّر الدوال الثلاث فتحصل على `['elicitation', 'sampling', 'roots']`. لا تمرّر أيًّا منها فتحصل على `[]`.

!!! check
    جرّب الآن الاختيار الخاطئ: اتصل **دون** `elicitation_callback` واستدعِ `issue_card` رغم ذلك.

    ما زال طلب `elicitation/create` من الخادم يصل إلى عميلك، وتجيب عنه SDK نيابة
    عنك بخطأ لأنك لم تعلن قدرتك على معالجته. يُفشل ذلك الخطأ الاستدعاء كله.
    لا تعيد `call_tool` نتيجة `is_error`، بل تثير استثناءً:

    ```text
    MCPError: Elicitation not supported
    ```

    هذا خطأ بروتوكول (`-32600`، *طلب غير صالح*)، لا خطأ أداة: لا شيء
    يقرؤه النموذج ليعيد المحاولة. لذلك يفيد وجود `client_features`: يفحص الخادم الملتزم
    قبل السؤال.

## الزوج المهجور {#the-deprecated-pair}

تجيب `sampling_callback` عن `sampling/createMessage`: طلب الخادم من نموذجك *أنت* توليد استكمال. وتجيب `list_roots_callback` عن `roots/list`: سؤال الخادم عن المجلدات التي يجوز له العمل فيها.

كلاهما يعمل ويتبع القاعدة أعلاه. وكلاهما يخدم RPC **تزيلها مواصفة 2026-07-28**: لا يستدعي الخادم الحديث عميلك عكسيًا أثناء الطلب، بل يعيد الطلب كجزء من نتيجة الأداة (**[الطلبات متعددة جولات التبادل](../handlers/multi-round-trip.md)**). لا تُلغى الدوال نفسها. عندما تحمل `InputRequiredResult` طلب `CreateMessageRequest` أو `ListRootsRequest`، توجّهه الحلقة التلقائية في `Client` إلى `sampling_callback` أو `list_roots_callback` نفسها المسجلة هنا. القائمة الكاملة في **[الميزات المهجورة](../deprecated.md)**.

ما زلت تحتاج إلى الدوال للتواصل مع خوادم لم تنتقل بعد. التوقيعات:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* تتلقى دالة أخذ العينات `CreateMessageRequestParams` كاملة (`messages` و`model_preferences` و`max_tokens`) وتعيد `CreateMessageResult`. *أنت* تشغّل النموذج كما تشاء؛ ولا تحمل SDK إلا الطلب.
* لا تأخذ دالة المجلدات الجذرية (roots) أي مَعلمات، وتعيد `ListRootsResult`.
* تستطيع أيٌّ منهما إعادة `ErrorData(...)` بدلًا من ذلك للرفض.

مرّرهما إلى `Client(...)` تمامًا مثل `elicitation_callback`.

## دوال رد النداء للإشعارات {#the-notification-callbacks}

دالتان إضافيتان. لا تعلن أيٌّ منهما قدرة.

تتلقى `logging_callback` إشعار `notifications/message` الذي يرسله الخادم كـ`LoggingMessageNotificationParams` (`level` و`logger` و`data`). تسجيل البروتوكول نفسه مهجور بمواصفة 2026-07-28 (توضح **[التسجيل](../handlers/logging.md)** البديل)، لذلك توجد الدالة للخوادم التي ما زالت ترسله. على اتصال جيل 2026، لا تمنحك الدالة وحدها شيئًا، لأن خوادم 2026 لا ترسل رسائل سجل إلا للطلبات التي تختار ذلك: مرّر `log_level="info"` (أو مستوى آخر) إلى `Client(...)` لإضافة الاختيار لكل طلب وتلقي ذلك المستوى وما فوقه. تتجاهله الخوادم الأقدم من 2026 وتحتفظ بسلوك `logging/setLevel`.

`message_handler` هي الدالة العامة: يصلها كل إشعار خادم تتيحه الجلسة (إضافة إلى دالته المخصصة)، وكل `Exception` على مستوى النقل إذا كانت وسيلة النقل قائمة على تدفّق. لا يصل نوعان أبدًا: تطبّق SDK إشعار `notifications/cancelled` بدلًا من إتاحته، ويستهلك تدفّق `listen()` النشط إقرار اشتراكه. استخدم تعليق النوع `IncomingMessage` للمَعلمة (`ServerNotification | Exception`، وتصدّره `mcp.client`). النمط المهم `if isinstance(message, Exception): raise message`، كي يفشل الاتصال المعطل بوضوح بدلًا من اختفائه.

## مراجعة {#recap}

* يستطيع الخادم إرسال طلبات للعميل. تجيب عنها بدوال رد نداء تُمرَّر إلى `Client(...)`.
* دالة استقاء المعلومات هي الحالية: `async (context, params) -> ElicitResult`، دالة واحدة لنمطَي النموذج وURL.
* **تسجيل دالة رد نداء إعلان للقدرة.** وبدونها ترفض SDK طلب الخادم نيابة عنك ويفشل الاستدعاء كله بـ`MCPError`.
* يتحقق الخادم قبل السؤال باستخدام `ctx.session.check_client_capability(...)`.
* تعمل `sampling_callback` و`list_roots_callback` بالطريقة نفسها لكن لميزات مهجورة؛ وتستخدم الخوادم الحديثة طلبات متعددة الجولات بدلًا منها.
* تتلقى `logging_callback` و`message_handler` الإشعارات. ولا تعلنان شيئًا.

تختار الوسيطة الأولى لـ`Client(...)` وسيلة النقل. تغطي **[وسائل نقل العميل](transports.md)** كل نوع.
