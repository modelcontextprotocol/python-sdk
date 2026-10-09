---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# الإكمالات {#completions}

يستطيع العميل إكمال قيم الوسائط تلقائيًا بينما يكتب المستخدم: أسماء لغات أو مستودعات أو مسارات ملفات.

**الإكمالات** هي طريقة خادمك لتوفير هذه الاقتراحات.

## ما يستفيد من الإكمال {#something-worth-completing}

تنطبق الإكمالات على شيئين فقط: وسائط **قالب توجيه** (prompt) ومَعلمات **قالب مورد**. لذا ابدأ بخادم فيه واحد من كل نوع:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

لا يتعلق شيء هنا بالإكمالات بعد.

* تأخذ `review_code` قيمة `language`. لا ينبغي أن يضطر المستخدم إلى تخمين الصيغ التي تقبلها.
* تأخذ `github_repo` قيمتي `owner` و`repo`. لا يشكّل حقلا نص حر لهما نموذجًا جيدًا.

## دالة معالجة الإكمال {#the-completion-handler}

أضف دالة **واحدة** بالمزخرف `@mcp.completion()`:

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* توجد دالة معالجة واحدة لكل خادم. يصل كل طلب إكمال إليها، وتتفرع حسب ما يجري إكماله.
* يجب أن تكون `async def`: تنتظرها SDK.
* تتلقى ثلاث وسائط:
  * `ref`: *أي* قالب توجيه أو قالب مورد، بصيغة `PromptReference` أو `ResourceTemplateReference`. تميّز بينهما باستخدام `isinstance`.
  * `argument`: تمثل `argument.name` الوسيطة التي يجري إكمالها، و`argument.value` ما كتبه المستخدم حتى الآن.
  * `context`: الوسائط التي حُددت قيمها بالفعل. تجاهلها الآن.
* تعيد `Completion(values=[...])`، أو `None` عندما لا تملك اقتراحًا.

!!! tip
    `argument.value` هي البادئة التي كتبها المستخدم. **لا** ترشّح SDK النتائج نيابة عنك: كل ما
    تضعه في `values` تعرضه الواجهة. أنت من يكتب `startswith`.

### جرّبها {#try-it}

استخدم `Client` داخل الذاكرة من **[الاختبار](../get-started/testing.md)**. استدعِ
`client.complete()` مع `ref=PromptReference(name="review_code")` و
`argument={"name": "language", "value": "py"}`:

```python
result.completion.values  # ['python']
```

* `ref` هو نوع المرجع نفسه الذي تتلقاه دالة المعالجة.
* `argument` قاموس عادي بمفتاحين فقط، `name` و`value`.

أرسل `value` فارغة وستتلقى القائمة كاملة. تكون `lang.startswith("")` صحيحة لكل لغة:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

اسأل عن `code` (وسيطة لا تعرفها دالة المعالجة) وستعيد `None`، التي تحوّلها SDK إلى قائمة فارغة:

```python
result.completion.values  # []
```

تعني `None` *"لا اقتراحات"*، ولا تعني خطأ أبدًا. تعود الواجهة إلى حقل نص عادي.

## قدرة لم تعلنها بنفسك {#a-capability-you-never-declared}

تسجيل دالة المعالجة هو الإعلان. صِل عميلًا وانظر:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

لم تدرج `completions` في أي مكان. رأت SDK دالة المعالجة وأعلنت القدرة نيابة عنك. تعمل كل قدرة *اختيارية* بهذه الطريقة: دالة المعالجة هي الإعلان. (العناصر الثلاثة ليست اختيارية: تعلنها `MCPServer` دائمًا، سواء وُجدت دوال معالجة أم لا.)

!!! check
    عُد إلى `server.py` الأول (دون دالة معالجة) واطلب الإكمال منه رغم ذلك. يفشل الاستدعاء
    بخطأ JSON-RPC:

    ```text
    Method not found
    ```

    وتكون `client.server_capabilities.completions` هي `None`. هذه غاية القدرة: يفحصها
    العميل الملتزم ولا يرسل طلبًا لا تستطيع الإجابة عنه.

## الوسائط المعتمدة على غيرها {#dependent-arguments}

يملك `github://repos/{owner}/{repo}` مَعلمتين، وتعتمد القيم المفيدة لـ`repo` على `owner` الذي اختير أولًا.

هذا دور `context`. يحمل الوسائط التي **حدد المستخدم قيمها بالفعل**:

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* يعمل الفرع الجديد لمَعلمة `repo` في القالب.
* `context.arguments` هي `dict[str, str] | None` للقيم المختارة حتى الآن (هنا `owner`).
* عدم وجود `owner` بعد يعني عدم وجود اقتراحات مناسبة، فتُعيد دالة المعالجة `None`.

يرسل العميل القيم المحددة باستخدام `context_arguments=`. هذه المرة يكون `ref` هو
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`. اطلب `repo` مع
`value` فارغة ومرّر `context_arguments={"owner": "modelcontextprotocol"}`:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

احذف `context_arguments=` فيعيد الاستدعاء نفسه `[]`. لا تستطيع دالة المعالجة معرفة المستودعات التي تقترحها حتى تعرف المالك.

!!! info
    تقبل `Completion` أيضًا `total=` و`has_more=`. عيّنهما عندما تكون `values` جزءًا من قائمة
    أطول، كي تعرض الواجهة *"و200 أخرى"*. لا تحتاج إليهما معظم دوال المعالجة.

## مراجعة {#recap}

* الإكمالات اقتراحات لـ**وسائط قوالب التوجيه** و**مَعلمات قوالب الموارد** فقط.
* تسجّل `@mcp.completion()` دالة المعالجة الوحيدة. وهي `async def (ref, argument, context) -> Completion | None`.
* تفرّع حسب `isinstance(ref, ...)` و`argument.name`. ورشّح النتائج حسب `argument.value` بنفسك.
* تصبح `None` قائمة فارغة. ولا تكون خطأ أبدًا.
* تحمل `context.arguments` القيم المحددة مسبقًا؛ ويقدّمها العميل باسم `context_arguments=`.
* تظهر قدرة `completions` بمجرد تسجيل دالة المعالجة. وبدونها يفشل الطلب بـ`Method not found`.

تساعد الاقتراحات بينما لا يزال المستخدم *يملأ* قالب توجيه أو مورد؛ أما لسؤاله *أثناء* استدعاء أداة، فتحتاج إلى **[استقاء المعلومات](../handlers/elicitation.md)**. وتغطي **[الصور والصوت والأيقونات](media.md)** كل ما تعيده الأداة غير النص.
