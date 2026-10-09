---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, ed4d17e894864056]
  tool: 1
---
# مجموعات الجلسات {#session-groups}

تتصل `Client` بخادم واحد. تحتاج التطبيقات الفعلية غالبًا إلى عدة خوادم (بحث وقاعدة بيانات وAPI داخلية)، فتدير اتصالًا وقائمة أدوات لكل منها.

**`ClientSessionGroup`** كائن واحد يحتفظ باتصالات عديدة ويجمع كل ما تتيحه في عرض واحد.

## خادمان {#two-servers}

ابدأ بخادمين عاديين. لا علاقة بينهما، لذا سمّى كل منهما أداته طبيعيًا `search`:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## مجموعة واحدة {#one-group}

أنشئ `ClientSessionGroup` واستدعِ **`connect_to_server`** مرة لكل خادم:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* تأخذ `connect_to_server` مَعلمات نقل، لا كائن خادم: `StdioServerParameters` (من `mcp`) لتشغيل عملية فرعية، أو `StreamableHttpParameters` / `SseServerParameters` (من `mcp.client.session_group`) لخادم يستمع بالفعل على URL.
* `group.tools` هي `dict[str, Tool]` لأدوات كل خادم متصل. ولـ`group.resources` و`group.prompts` الشكل نفسه.
* تبحث `group.call_tool(name, arguments)` عن الاسم وتجد الجلسة التي تملكه وتمرّر الاستدعاء. لا تحدد الخادم بنفسك.

!!! check
    ضع `client.py` بجانب الخادمين وشغّله. يرفض `connect_to_server` الثاني:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    هذا `MCPError` يُثار قبل تسجيل أي شيء من الخادم الثاني. يجب أن يكون الاسم
    فريدًا في المجموعة **كلها**، وسيتصادم خادمان لا تتحكم فيهما في النهاية.

## `component_name_hook` {#component_name_hook}

تصلح ذلك على مستوى المجموعة، لا الخوادم. مرّر دالة تأخذ `(name, server_info)` فتشغّلها المجموعة على كل اسم تسجّله:

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

شغّل مجددًا. تعرض `print(sorted(group.tools))` الآن الاثنين:

```text
['Library.search', 'Web.search']
```

* **المفتاح** من اختيارك. بنته `by_server` من `server_info.name`، وهو الاسم الذي أُنشئت به كل `MCPServer(...)`.
* يبقى كائن `Tool` الداخلي دون تغيير: ما زالت `group.tools["Web.search"].name` هي `"search"`، وهذا الاسم الذي تضعه `call_tool` في النقل. لا تغادر البادئة عمليتك.
* لا يقتصر ذلك على الأدوات. يُسجَّل مورد `hours` للمكتبة كـ`Library.hours`.

!!! tip
    يعمل الخطاف على **كل** اسم من **كل** خادم، لا على التعارضات فقط: لا يوجد
    وضع لإضافة بادئة عند التصادم وحده. اختر نظام تسمية واحدًا وطبّقه في كل مكان.

## إضافة الخوادم وإزالتها {#adding-and-removing-servers}

تعيد `connect_to_server` الجلسة `ClientSession` التي فتحتها. احتفظ بها إذا أردت إزالة الخادم لاحقًا: تزيل `await group.disconnect_from_server(session)` أدواته وموارده وقوالب توجيهه من المجموعة.

إذا كانت لديك `ClientSession` متصلة بالفعل (`Client.session` إحداها)، فمرّرها إلى `await group.connect_with_session(server_info, session)` بدلًا من فتح وسيلة نقل جديدة. يجري التجميع بالطريقة نفسها. لا تغلق المجموعة جلسة لم تفتحها. تسمّي `server_info` الخادم لبادئات المكونات؛ وقد تكون `client.server_info` هي `None` على اتصال جيل 2026 (الهوية اختيارية)، فمرّر `Implementation(name=..., version=...)` الخاصة بك حينها.

## المصافحة التقليدية {#the-classic-handshake}

تُبنى `ClientSessionGroup` على `ClientSession`، لا `Client`. ينفّذ كل `connect_to_server` مصافحة `initialize` التقليدية. لا يرسل فحص `server/discover` الموضح في **[إصدارات البروتوكول](../protocol-versions.md)**. يفهم كل خادم MCP المصافحة، فلا تفقد توافقًا؛ بل تسلك المجموعة الطريق الأقدم والأبطأ إلى خادم يستطيع أفضل من ذلك.

## مراجعة {#recap}

* تحتفظ `ClientSessionGroup` باتصالات عدة خوادم وتجمع أدواتها ومواردها وقوالب توجيهها في `dict` واحدة لكل نوع.
* استخدم `connect_to_server(params)` لكل خادم. تأخذ مَعلمات نقل، لا URL أو `Transport` التي تأخذها `Client` أبدًا.
* توجّه `group.call_tool(name, arguments)` الاستدعاء إلى الخادم المالك نيابة عنك.
* يجب أن تكون الأسماء فريدة في المجموعة كلها؛ لا يتعايش خادمان بأداة `search` دون معالجة ذلك.
* تعيد `component_name_hook=` كتابة كل اسم مسجّل. يتغير مفتاح القاموس، لا الاسم المنقول.
* تضيف `connect_with_session` جلسة لديك بالفعل؛ وتزيل `disconnect_from_server` واحدة.

المصافحة التي تستخدمها المجموعة (والأسرع التي تفضّلها `Client`) موضوع **[إصدارات البروتوكول](../protocol-versions.md)**.
