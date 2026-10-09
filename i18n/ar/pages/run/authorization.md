---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, 128a492d18295f64, 14ad3bc7904036bb, 54a6697833fcc1d9, fe1626fdd5aad1da, 811d083c1da8bcf6]
  tool: 1
---
# التفويض {#authorization}

عبر Streamable HTTP، خادم MCP خدمة ويب عادية، وتحميه كما تحمي أي خدمة ويب: برموز حامل OAuth 2.1.

بمصطلحات OAuth، خادمك **خادم موارد**. لا يسجّل دخول أحد ولا يصدر رمزًا أبدًا. يفعل شيئًا واحدًا: يفحص ترويسة `Authorization` في كل طلب ويقرر صلاحية الرمز فيها.

هذه الصفحة لجانب الخادم. أما العميل الذي يكتشف خادم التفويض ويجلب الرمز، ففي **[عملاء OAuth](../client/oauth-clients.md)**.

## الأطراف الثلاثة {#the-three-parties}

* يسجّل **خادم التفويض** دخول المستخدمين ويصدر رموز الوصول. لا تكتبه أنت. إنه مزوّد الهوية لديك (Auth0 أو Keycloak أو Entra أو مزوّدك الخاص).
* **خادم الموارد** هو خادم MCP لديك. يتحقق من الرمز في كل طلب.
* يكتشف **العميل** خادم التفويض الذي تثق به، ويحصل منه على رمز، ويرسله إليك بصيغة `Authorization: Bearer <token>`.

هذا هو المثلث كاملًا. تتناول هذه الصفحة النقطة الوسطى فقط.

## متحقق الرموز {#a-token-verifier}

لا تفرض SDK شكلًا للرمز الصالح. تحدده أنت بتنفيذ **`TokenVerifier`**:

```python title="server.py" hl_lines="14-16 21-27"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` بروتوكول بطريقة غير متزامنة واحدة. تتلقى `verify_token` الرمز الخام من ترويسة `Authorization` وتعيد **`AccessToken`** إذا كان صالحًا، أو `None` إذا لم يكن. لا شيء آخر لتنفيذه.
* يبحث هذا المثال عن الرمز في جدول؛ ويسجّل كل إدخال المورد الذي صدر له. يتحقق التنفيذ الفعلي من توقيع JWT أو يستدعي نقطة نهاية استبطان الرموز لخادم التفويض، ويحدد لمن صدر الرمز (`aud` الخاص به) في `AccessToken.resource`. تلك الشيفرة مسؤوليتك؛ ولا تفعل SDK إلا استدعاءها.
* يأتي `token_verifier=` و`auth=` معًا دائمًا. مرّر أحدهما دون الآخر فتثير `MCPServer(...)` الاستثناء `ValueError` قبل خدمة أي طلب.

`AuthSettings` هي الواجهة العامة لخادم مواردك:

* `issuer_url`: خادم التفويض الذي يصدر رموزك.
* `resource_server_url`: عنوان URL العام لنقطة نهاية MCP هذه. يحدد *أي* مورد يخصه الرمز، وهو موضع مستند الاكتشاف.
* `required_scopes`: يجب أن يحمل كل رمز جميع هذه النطاقات.
* `validate_token_resource`: ارفض أي رمز لا تساوي فيه `AccessToken.resource` القيمة `resource_server_url`. تركه دون تعيين مع تعيين `resource_server_url` يصدر تحذيرًا (`MCPDeprecationWarning`) ويتصرف كـ`False`؛ ويجعل 3.0 القيمة `True` الافتراضية لخوادم الموارد.
  * فعّله عندما يربط خادم التفويض الرموز بـ`resource` الذي طلبه العميل، وهو ما ترسله عملاء MCP دائمًا. أبقِ `resource_server_url` مطابقًا تمامًا لعنوان اتصال العملاء.
  * اتركه معطّلًا عندما يستخدم خادم التفويض معرّفات جمهور خاصة به (معرّف API في Auth0 أو معرّف تطبيق Entra)، وافحص `aud` في متحققك بدلًا من ذلك، مع إعادة `None` للرمز الذي لا يخص هذا الخادم.
  * إذا كان `aud` قائمة، فضع الإدخال الذي يساوي `resource_server_url` في `resource`.

!!! tip
    يتضمن `examples/servers/simple-auth/` في مستودع SDK كائن `IntrospectionTokenVerifier` يستدعي
    نقطة نهاية [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) لخادم تفويض فعلي. هذا شكل معظم متحققات الإنتاج.

## ما تحصل عليه عبر HTTP {#what-you-get-over-http}

يوجد التفويض في ترويسات HTTP، لذلك لا يوجد إلا على وسائل نقل HTTP. شغّله على الوسيلة التي تنشرها: تضعه `mcp.run(transport="streamable-http")` على `http://127.0.0.1:8000/mcp`، وتشرح **[تشغيل خادمك](index.md)** الباقي. أصبح للتطبيق مساران:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

سجّلت أداة واحدة. أما المسار الثاني فمن SDK.

### الاكتشاف {#discovery}

أرسل `GET` إلى ذلك المسار المعروف فتحصل على **بيانات وصفية للمورد المحمي وفق [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)**، مبنية مباشرة من `AuthSettings`:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

هذا المستند وسيلة دخول عميل لم يسمع بخادمك: يقرأ `authorization_servers` ويتجه إليها للحصول على رمز. لم تكتب شيئًا من ذلك.

!!! check
    استدعِ `/mcp` دون رمز (أو برمز أعاد متحققك له `None`)، فيُوقَف
    الطلب عند المدخل:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    لم يُحلَّل شيء ولم تعمل أداة. ومرجع `resource_metadata` في `WWW-Authenticate` هو
    ما يجعل الاكتشاف تلقائيًا: 401 -> مستند البيانات الوصفية -> خادم التفويض -> رمز -> إعادة المحاولة.

!!! warning
    لا يحمي شيء من ذلك `stdio`. لا تملك القناة ترويسة `Authorization`، لذلك لا يُستشار
    `token_verifier` فيها أبدًا. الحد الأمني لخادم `stdio` هو العملية التي شغّلته. وينطبق
    الأمر على `Client(mcp)` داخل الذاكرة في الاختبارات: يتصل مباشرة بكائن الخادم
    ويتجاوز طبقة HTTP، بما فيها التفويض.

## هوية المستدعي {#the-callers-identity}

داخل أي دالة معالجة، تعيد **`get_access_token()`** كائن `AccessToken` الذي أعاده متحققك للطلب الحالي:

```python title="server.py" hl_lines="4 35-38"
--8<-- "docs_src/authorization/tutorial002.py"
```

* تعمل في الأدوات والموارد وقوالب التوجيه، ولا تحتاج إلى تمرير شيء: تخزّن البرمجيات الوسيطة للتفويض الكائن في متغير سياق لكل طلب.
* تحصل على **الكائن نفسه الذي بناه متحققك**: `client_id` و`scopes` و`subject` و`expires_at` وأي `claims` إضافية أرفقتها. هذه نقطة تطبيق قواعد لكل أداة: اقرأ النطاقات وارفض عند الحاجة.
* خارج طلب HTTP مصادَق عليه، تعيد `None`. داخل الذاكرة وعبر `stdio`، تكون دائمًا `None`.

استدعِ `whoami` مع `Authorization: Bearer alice-token` فيقرأ النموذج:

```text
alice (scopes: notes:read)
```

## النصف الذي لا تنفّذه SDK {#the-half-the-sdk-doesnt-do}

توفر SDK جانب خادم الموارد: التحقق والإعلان والرفض. لا توفر صفحة دخول أو شاشة موافقة أو رمزًا.

لمشاهدة عمل الأطراف الثلاثة، شغّل `examples/servers/simple-auth/` من مستودع SDK (خادم تفويض صغير وخادم موارد معدّان كما في هذه الصفحة)، ثم وجّه `examples/clients/simple-auth-client/` إليه لتجربة تدفق الاكتشاف والحصول على الرمز كاملًا.

!!! info
    توجد وسيطة مُنشئ ثانية، `auth_server_provider=`، تُضمّن خادم تفويض كاملًا
    داخل خادم MCP. تسبق فصل AS/RS الذي تقوم عليه
    مواصفة تفويض MCP. ينبغي ألّا تستخدمها الخوادم الجديدة.

يستطيع خادم التفويض أيضًا قبول إفادة موقعة من مزوّد هوية مؤسسة بدلًا من نقر المستخدم عبر شاشة الموافقة، وتدعم SDK جانبي التبادل. المنحة والعميل الذي يقدمها في **[إفادة الهوية](../client/identity-assertion.md)**.

## مراجعة {#recap}

* عبر Streamable HTTP، خادمك **خادم موارد** OAuth 2.1: يتحقق من الرموز ولا يصدرها أبدًا.
* `TokenVerifier` واجهة التكامل كاملة: طريقة غير متزامنة واحدة، يدخل الرمز وتخرج `AccessToken | None`.
* يأتي `token_verifier=` و`auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` معًا دائمًا.
* تنشر SDK بيانات المورد المحمي وفق [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) على `/.well-known/oauth-protected-resource/...`، وتجيب الطلبات دون مصادقة بـ401 تشير ترويسة `WWW-Authenticate` فيها إلى ذلك المستند. هذا الاكتشاف بالكامل.
* توضح `get_access_token()` في أي دالة معالجة من يستدعيها.
* التفويض شأن HTTP. لا يراه `stdio` ولا عميل الاختبار داخل الذاكرة أبدًا.

جانب العميل (اكتشاف خادم التفويض وجلب الرمز نيابة عنك) في **[عملاء OAuth](../client/oauth-clients.md)**. والعميل الذي *يفيد* بهوية بدلًا من سؤال المستخدم عنها في **[إفادة الهوية](../client/identity-assertion.md)**.
