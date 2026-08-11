---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# Düşük seviyeli Server {#the-low-level-server}

`@mcp.tool()` bir katmandır. Altında ham MCP konuşan ikinci bir sunucu sınıfı, `Server`, vardır: protokol nesnelerini ona verirsiniz, o da hiç dokunmadan ağ üzerinden gönderir.

`MCPServer` onun üzerine kuruludur. Kolaylık katmanı size engel olduğunda alt katmana inersiniz:

* Python imzasından türetilmiş bir şema değil, **birebir** belirli bir şema (dosyadan yüklenen, veritabanından üretilen) yayımlamanız gerekir.
* Sonuç üzerinde tam denetim gerekir: `_meta`, `is_error`, `structured_content`'in her anahtarı.
* MCP'nin tanımlamadığı bir metodu ele almanız gerekir.

Geri kalan her şey için `MCPServer`'da kalın.

## Aynı araç, elle {#the-same-tool-by-hand}

Bu, **[Araçlar](../servers/tools.md)** sayfasında dokuz satır `@mcp.tool()` ile yazılan `search_books` aracının kolaylıklardan arındırılmış hali:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Üç şey değişti ve düşük seviyeli API'nin tamamı bu üçü:

* **İşleyiciler yapıcı parametreleridir.** `on_list_tools=` ve `on_call_tool=`, `Server(...)` çağrısına gider. Burada dekoratör yoktur ve her işleyici aynı biçimdedir: `async (ctx, params) -> result`.
* **Girdi şemasını siz yazarsınız.** `Tool.input_schema`, düz bir JSON Schema `dict`'idir. Kimse onu tür ipuçlarından türetmez, çünkü türetilecek tür ipucu yoktur.
* **Sonucu siz oluşturursunuz.** `CallToolResult(content=[TextContent(...)])`, elle. Hiçbir şey sarmalanmaz, dönüştürülmez ya da bir dönüş anotasyonundan çıkarsanmaz.

`params` ayrıştırılmış istektir: `CallToolRequestParams` size `.name` ve `.arguments` verir. `ctx` bir `ServerRequestContext`'tir: istemciyle geri konuşmak için `ctx.session`, `ctx.lifespan_context`, `ctx.request_id` ve isteğin gelen `_meta`'sı olan `ctx.meta`.

!!! info
    FastAPI kullandıysanız bu ilişkiyi zaten biliyorsunuz. `MCPServer`, dekoratörler ve tür ipuçları katmanıdır; `Server` ise alttaki Starlette'tir. Rakip değiller: `MCPServer` bir `Server` oluşturur ve üzerine tam da bunlar gibi işleyiciler kaydeder.

### Deneyin {#try-it}

Bunun için Inspector yok: `mcp dev` ve `mcp run` yalnızca `MCPServer` kabul eder. Bellek içi `Client` bunu umursamaz; düşük seviyeli bir `Server`'ı tıpkı bir `MCPServer`'ı aldığı gibi alır:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

`@mcp.tool()` sürümünün ürettiği metnin aynısı. İki gerçek fark var:

* `result.structured_content` değeri `None`. Yüksek seviyeli sunucu `-> str` dönüş türünü sizin yerinize `{"result": ...}` içine sarmalar; burada sizin oluşturmadığınızı kimse oluşturmaz.
* `list_tools`, **sizin** yazdığınız şemayı karakteri karakterine döndürür. Yüksek seviyeli sürümde her özellikte `"title": "Query"`, kökte de `"title": "search_booksArguments"` vardı: Pydantic'in bıraktığı izler. Burada ise ağa giden bir şey varsa onu oraya siz koymuşsunuzdur.

## Sizin yerinize hiçbir şey denetlenmez {#nothing-is-checked-for-you}

`MCPServer`, çağrıyı kendi ürettiği şemaya göre doğrulayarak hatalı bir argümanı fonksiyonunuz daha çalışmadan reddeder (**[Araçlar](../servers/tools.md)**).

`Server` bunu yapmaz. `input_schema`'nız istemciye *duyurulur*; `params.arguments`'a asla *uygulanmaz*.

!!! check
    `search_books`'u `limit` olmadan çağırın; `args["limit"]` ifadeniz `KeyError` fırlatır. İstemci şunu görür:

    ```text
    MCPError: Internal server error
    ```

    `-32603` kodlu, mesajı kasıtlı olarak genel tutulmuş bir JSON-RPC hatası: SDK, traceback'inizi uzaktaki bir çağırana sızdırmaz. Model neyi yanlış yaptığını asla öğrenemez, bu yüzden yeniden deneyemez. (Testte `raise_exceptions=True` bunun yerine gerçek istisnayı yüzeye çıkarır; bkz. **[Test etme](../get-started/testing.md)**.)

Bu genellenebilir. Düşük seviyeli bir işleyiciden fırlatılan istisna **her zaman** bir protokol hatasıdır, asla `is_error=True` taşıyan bir araç sonucu değildir. Modelin hatayı okuyup toparlanmasını istiyorsanız `params.arguments`'ı kendiniz doğrulayın ve `CallToolResult(content=[TextContent(...)], is_error=True)` döndürün. Bu iki hata türü **[Hataları ele alma](../servers/handling-errors.md)** sayfasının konusu.

## İki araç, tek işleyici {#two-tools-one-handler}

`on_call_tool`, sunucudaki her araç için tek giriş noktasıdır. Yönlendirmeyi `params.name`'e göre yaparsınız:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` ikisini de duyurur. `call_tool` ada göre yönlendirir.
* `else` dalı önemlidir: `Server`, hiç listelemediğiniz bir ad için gelen `tools/call` isteğini hiç sorgulamadan doğrudan işleyicinize iletir. Orada istisna fırlatmak çağrıyı yukarıdakiyle aynı `-32603` hatasına çevirir.

## Yapılandırılmış çıktı, elle {#structured-output-by-hand}

`Tool` üzerinde `output_schema` bildirin ve sonuca `structured_content` koyun. İkisi de sizin:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Çağırın; sonuç iki gösterimi de taşır:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

`_meta` bloğu sunucunun kimlik damgasıdır: SDK bunu 2026 neslinden her sonuca, yapıcıdan gelen `version` ile birlikte ekler (hiç sürüm belirtmeyen bir sunucu boş bir dize bildirir). Kendini tanıtmaması gereken bir sunucu bu anahtarı bir middleware (ara katman) ile çıkarabilir; middleware döndürdüğü sonuçların sahibidir.

Sunucu bu iki alanı asla karşılaştırmaz. Bu SDK'nın `Client`'ı karşılaştırır: bildirdiğiniz `output_schema`'yı karşılamayan bir `structured_content` döndürün, `call_tool` `Invalid structured content returned by tool search_books` ile başlayıp `jsonschema` hatasını alıntılayarak devam eden bir `RuntimeError` fırlatır. Bir şema vaat etmek ucuzdur; sözünüzü tutmak size kalır. Dönüş türleri ve şemaların tüm basamakları **[Yapılandırılmış çıktı](../servers/structured-output.md)** sayfasında.

## `_meta`: model için değil, uygulama için {#\_meta-for-the-application-not-the-model}

`content`, yanıtın modelin okuduğu kısmıdır. `structured_content`, aynı yanıtın tür bilgisi taşıyan veri halidir. `_meta` üçüncü kanaldır: yanıtın hiçbir şekilde parçası olmadan, **istemci uygulama** için sonuçla birlikte yolculuk eden veri.

Kayıt kimlikleri, iz kimlikleri, kullanıcı arayüzünüzün ihtiyaç duyup prompt'unuzun duymadığı her şey için kullanın:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* Onu ağ üzerindeki adıyla, `_meta=` olarak oluşturursunuz. İstemci onu `result.meta` olarak geri okur.
* Anahtarlarınıza ad alanı verin (`bookshop/record_ids`). `io.modelcontextprotocol/*` anahtarları protokole ayrılmıştır.

!!! warning
    `_meta`, sizinle istemci uygulama arasındaki bir uzlaşıdır; modele neyin ulaştığına dair
    bir garanti değildir. Neyi göstereceğine host karar verir. Bir araç sonucunun hiçbir yerine asla sır koymayın.

## Yetenekler işleyicilerinizi izler {#capabilities-follow-your-handlers}

Bir `Server`, tam olarak işleyici verdiğiniz metot ailelerini duyurur. Yukarıdaki `Bookshop`, `on_list_tools` ile `on_call_tool`'u geçirir, başka hiçbir şey geçirmez; dolayısıyla ona bağlanan bir istemci şunu görür:

```json
{"tools": {"listChanged": false}}
```

`resources` yok, `prompts` yok: arkalarında duracak bir şey yok. `on_list_prompts` geçirin, `prompts` belirir; `on_completion` geçirin, `completions` belirir.

`MCPServer`, siz kaydetmiş olun olmayın araçları, kaynakları ve prompt'ları her zaman duyurur; çünkü yöneticileri her zaman vardır. Burada ise beyan, yapıcı çağrısının *ta kendisidir*.

## Lifespan jenerik parametresi {#the-lifespan-generic}

`Server`, lifespan'inin (yaşam döngüsü) ürettiği türe göre jeneriktir. Bir kez tür açıklaması ekleyin; nesne ortaya çıktığı her yerde tür bilgisi taşır:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* Lifespan, `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]` türündedir; bir `async` üreteç üzerindeki `@asynccontextmanager` size tam olarak bunu verir.
* `yield` ettiği her neyse `ctx.lifespan_context` olur; işleyiciler `ServerRequestContext[Catalog]` olarak açıklandığı için de `.search(...)` otomatik tamamlanır ve tür denetiminden geçer.
* Sunucu başlarken bir kez girilir, dururken bir kez çıkılır. Başlatma, kapatma ve aynı fikrin `MCPServer` sürümü **[Lifespan](../handlers/lifespan.md)** sayfasında.

`lifespan=` olmadan `ctx.lifespan_context` boş bir `dict`'tir.

## Kendinize ait bir metot {#a-method-of-your-own}

Yapıcı, MCP'nin tanımladığı metotları kapsar. `add_request_handler` geri kalan her şeyi kapsar:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* İlk argüman metot dizesidir. Bildirimlerin bir ikizi vardır: `add_notification_handler`.
* `params_type`, gelen `params`'ın işleyiciniz çalışmadan **önce** doğrulandığı modeldir; yani özel metotlar, araçların almadığı doğrulamayı *alır*. `_meta` alanının diğer her metotta olduğu gibi ayrıştırılması için `RequestParams`'tan alt sınıf türetin.
* İşleyici bir `BaseModel`, bir `dict` ya da `None` döndürür. SDK bunu JSON-RPC sonucuna serileştirir.

Dürüst bir uyarı: yüksek seviyeli `Client`'ta yalnızca MCP'nin tanımladığı metotlar için fiiller vardır, yani `client.reindex()` diye bir şey yoktur. Satıcıya özel bir metot, varlığından zaten haberdar olan bir eş içindir: sizin de dağıttığınız bir istemci ya da JSON-RPC konuşan başka bir servisiniz.

Sahiplenemeyeceğiniz tek bir metot var:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

El sıkışma çalıştırıcıya aittir. `server/discover`, `ping` ve diğer tüm yerleşik metotları dilediğiniz gibi değiştirebilirsiniz.

!!! tip
    O hatada adı geçen `Server.middleware`, `initialize` dahil gelen **her** mesajı sarmalar. İstediğiniz yeni bir metodu yanıtlamak değil de trafiği gözlemlemek ya da yeniden yazmaksa **[Middleware](middleware.md)** sayfasından başlayın.

## Diğer işleyiciler {#the-other-handlers}

Bunların her biri, artık kavramlarını bildiğiniz birer fikir; her birinin kendi sayfası var.

* `on_call_tool`, `on_get_prompt` ve `on_read_resource`, çağrıyı duraklatıp istemciden girdi istemek için normal sonuçları yerine bir `InputRequiredResult` döndürebilir; bkz. **[Çok turlu istekler](../handlers/multi-round-trip.md)** (multi-round-trip). Bu katmanın ruhuna uygun olarak sizin için hiçbir şey kurulmaz: `MCPServer` varsayılan olarak `requestState`'i mühürlerken burada ayarladığınız `request_state`, siz `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` ile katılana kadar ağı tam yazıldığı gibi geçer: `MCPServer`'ın yaptığı mühürleme ve doğrulamanın aynısı için tek satır (iki ad da `mcp.server.request_state`'ten içe aktarılır) (**[`requestState`'i koruma](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion`, diğer ilkel öğeler için aynı `(ctx, params) -> result` biçimidir.
* `on_subscriptions_listen`, 2026-07-28 `subscriptions/listen` akışını sunar. Bir `SubscriptionBus` üzerine kurulu bir `ListenHandler` geçirin ve olayları diğer işleyicilerinizden veri yoluna yayımlayın; bileşimin tamamı için bkz. **[Abonelikler](../handlers/subscriptions.md)**.
* `server.streamable_http_app()`, `MCPServer`'ınkiyle aynı Starlette uygulamasını döndürür; onu **[Sunucunuzu çalıştırma](../run/index.md)** sayfasının herhangi bir ASGI uygulamasını dağıttığı gibi dağıtın. Burada `server.run(transport=...)` yoktur: `server.run(read_stream, write_stream, server.create_initialization_options())` bir akış çifti üzerinden tek bir bağlantıyı yürütür ve bu tek satır işin tamamıdır.

## Özet {#recap}

* Düşük seviyeli `Server`, işleyicilerini `on_*` **yapıcı parametreleri** olarak alır; her işleyici `async (ctx, params) -> result` biçimindedir.
* `input_schema` sözlüğünü siz yazar, `CallToolResult`'ı siz oluşturursunuz. Sizin yerinize hiçbir şey türetilmez, sarmalanmaz ya da doğrulanmaz.
* İşleyicideki bir istisna `-32603` protokol hatasıdır. Modelin okuyabileceği bir araç hatası, **sizin** döndürdüğünüz `is_error=True` taşıyan bir `CallToolResult`'tır.
* Sonuçtaki `_meta` modele değil, istemci uygulamaya yöneliktir.
* `Server[T]`, lifespan'inin ürettiği şeye göre jeneriktir; `ctx.lifespan_context` tür bilgisi taşıyan bir `T`'dir.
* `add_request_handler(method, params_type, handler)` her metodu sunar. `initialize` ayrılmıştır.
* Bir `Server`'ın duyurduğu yetenekler, hangi işleyicileri kaydettiğinizden türetilir.

`Client(server)` iki sunucuya da aynı davrandı, çünkü ikisi aynı protokolün *ta kendisi*; bütün mesele de bu. Bir alt katman ise bir sınıf bile değil: **[Middleware](middleware.md)**.
