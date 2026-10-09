---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# التثبيت {#installation}

تتوفر Python SDK على PyPI باسم [`mcp`](https://pypi.org/project/mcp/). وتتطلب **Python 3.10+**.

يصف هذا التوثيق **v2**، سلسلة الإصدارات المستقرة الحالية:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "هل تنتقل من v1؟"
    v2 إصدار رئيسي يتضمن تغييرات غير متوافقة مع الإصدارات السابقة؛ ويغطي **[دليل الترحيل](../migration.md)**
    كلًّا منها. إذا كانت *حزمتك* تعتمد على `mcp` ولم تكن جاهزة للترحيل، فاحتفظ
    بالحد الأعلى `<2` (مثل `mcp>=1.28,<2`) كي يبقى حل الاعتماديات غير المثبّت على إصدار محدد ضمن سلسلة 1.x.

## ما الذي يُثبَّت؟ {#what-gets-installed}

لا تحتاج إلى معرفة هذه التفاصيل لاستخدام SDK، لكن إن كنت تتساءل عن دور كل اعتمادية:

* `mcp-types`: جميع أنواع البروتوكول (الطلبات والنتائج وكتل المحتوى) في حزمة مستقلة تتزامن إصداراتها مع SDK. تستوردها الشيفرة التي تعتمد على `mcp` عبر الاسم البديل `mcp.types` (كل `from mcp.types import ...` في هذا التوثيق)؛ ولا تستورد `mcp_types` مباشرة إلا في مشروع يثبّت `mcp-types` دون SDK.
* [`anyio`](https://anyio.readthedocs.io/): بيئة التنفيذ غير المتزامن. كُتبت SDK بالكامل باستخدام anyio، لذا تعمل على `asyncio` أو `trio`.
* [`pydantic`](https://docs.pydantic.dev/): الأساس الذي تُبنى عليه جميع نماذج `mcp.types`، وكذلك توليد المخططات والتحقق منها.
* [`httpx2`](https://pypi.org/project/httpx2/): عميل HTTP الذي تعتمد عليه وسائل نقل *العميل* Streamable HTTP وSSE، مع دعم مدمج للأحداث المرسلة من الخادم.
* [`starlette`](https://www.starlette.io/) و[`uvicorn`](https://www.uvicorn.org/) و[`sse-starlette`](https://pypi.org/project/sse-starlette/) و[`python-multipart`](https://pypi.org/project/python-multipart/): وسائل نقل *الخادم* عبر HTTP.
* [`jsonschema`](https://pypi.org/project/jsonschema/): يتحقق من توافق مخرجات الأداة المنظّمة مع مخطط المخرجات الذي أعلنت عنه.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): معالجة رموز OAuth للتفويض.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): API خفيفة فقط، لذا لا تفرض البرمجيات الوسيطة للتتبّع في SDK أي تكلفة ما لم تثبّت بنفسك OpenTelemetry SDK ومكوّن تصدير.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) و[`typing-inspection`](https://pypi.org/project/typing-inspection/): ميزات الأنواع الحديثة في Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): خاصة بـWindows، وتُستخدم لإدارة العمليات الفرعية في `stdio`.

## الإضافات الاختيارية {#optional-extras}

* تضيف `mcp[cli]` كلًّا من [`typer`](https://typer.tiangolo.com/) و[`python-dotenv`](https://pypi.org/project/python-dotenv/) لأداة سطر الأوامر `mcp` (`mcp dev` و`mcp run` و`mcp install`). ستحتاج إليها أثناء التطوير؛ وقد لا تحتاج إليها في خادم منشور.
* تضيف `mcp[rich]` مكتبة [`rich`](https://rich.readthedocs.io/) لتحسين عرض سجلات الخادم.
