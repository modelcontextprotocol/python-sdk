---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

Sunucunuz zaten izleniyor. Hiçbir şey eklemeniz gerekmez.

Oluşturduğunuz her sunucu, işlediği her mesaj için bir [OpenTelemetry](https://opentelemetry.io/) span'ı üretir. Bunu siz yazmadınız, içe de aktarmıyorsunuz. `MCPServer(...)`'ı çağırdığınız anda oradadır.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

Bu, eksiksiz ve izlenen bir sunucu. `search_books`'u çağırın, onun için bir span oluşturulur. Aynısı düşük seviyeli `Server` için de geçerlidir: izleme her ikisinde de bulunur.

## Elde ettikleriniz {#what-you-get}

Gelen her mesaj, adını yöntemden ve hedefinden alan bir `SERVER` span'ına dönüşür. Yani `search_books` için yapılan bir `tools/call`, `tools/call search_books` span'ıdır; yalın bir `tools/list` ise yalnızca `tools/list` olur.

Her span birkaç öznitelik taşır:

* `mcp.method.name` ve `mcp.protocol.version`, her span'da.
* `jsonrpc.request.id`, isteklerde (bildirimlerde yoktur).
* İstisna fırlatan bir işleyici span durumunu hata olarak ayarlar. `is_error=True` içeren bir araç sonucu da öyle.

Araç çağrılarını izlemek çok sık istenen bir şey olduğundan, `tools/call` span'ları OpenTelemetry'nin [GenAI anlamsal kurallarına](https://opentelemetry.io/docs/specs/semconv/gen-ai/) uyar:

* `gen_ai.operation.name`, `"execute_tool"` olarak ayarlanır.
* `gen_ai.tool.name`, çağrılan aracın adına ayarlanır.

Aynı mantıkla bir `prompts/get` span'ı `gen_ai.prompt.name` alır. Listeleme yöntemleri hiçbir `gen_ai.*` anahtarı taşımaz, çünkü adlandırılacak bir şey yoktur.

!!! tip
    Bir izleme arayüzünün araç çağrılarınızı başka herhangi bir ajanınkileri grupladığı gibi gruplamasının nedeni bu GenAI öznitelikleridir. Bu gruplama size bedelsiz gelir; fazladan kod gerekmez.

## Siz isteyene kadar hiçbir maliyeti yok {#it-costs-nothing-until-you-want-it}

"Varsayılan olarak açık" tercihini rahat bir varsayılan yapan kısım burası.

SDK yalnızca OpenTelemetry'nin hafif yarısı olan `opentelemetry-api` paketine bağımlıdır. OpenTelemetry SDK'sı ve bir exporter kurulu değilken span oluşturmak etkisiz bir işlemdir. Yani sunucunuzun şu anda ürettiği span'ların size maliyeti neredeyse sıfırdır ve onları kimse toplamıyor.

Onları *görmek* istediğiniz gün diğer yarıyı kurar ve bir yere yönlendirirsiniz:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

Bir exporter'ı alışıldık OpenTelemetry yöntemiyle yapılandırın; SDK'nın sessizce oluşturduğu her span görünür hale gelir. Sunucu kodunuz değişmez. Tek bir satır bile.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) bu tür arka uçlardan biridir ve yapılandırmayı sizin yerinize yapar: `pip install logfire`, `logfire.configure()`, ardından MCP span'larınız canlı görünümde belirir. OpenTelemetry üzerine kuruludur, bu yüzden aşağıdaki her şey onun için de geçerlidir.

## Ağı aşan izler {#traces-that-cross-the-wire}

Bir iz en çok, bir isteği istemciden sunucunun içine kadar tek ve bağlantılı bir resimde takip ettiğinde işe yarar.

İstemci de sunucu da SDK'yı çalıştırıyorsa bu bağlantı otomatik kurulur. İstemci [W3C iz bağlamını](https://www.w3.org/TR/trace-context/) isteğe ekler, sunucu da onu geri okur; böylece sunucu span'ı aynı iz içinde istemci span'ının altına yerleşir. Bunun adı [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414) ve siz istemeden gelir.

Gelen mesaj iz bağlamı taşımıyorsa, örneğin SDK olmayan bir istemciden gelen bir istekte, sunucu span'ı yepyeni ve sahipsiz bir iz başlatmak yerine sunucuda o an geçerli olan span'ın altına bağlanır.

## Kapatma {#turning-it-off}

İzleme bir middleware'dir (ara katman); sunucunuzun listesindeki ilk middleware. Hiç span üretmeyen bir sunucuyu gerçekten istiyorsanız onu listeden çıkarın:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    Bu içe aktarmanın başında bir alt çizgi var ve bu bilerek böyle. Sınıf, tıpkı [`Server.middleware`](../advanced/middleware.md) gibi geçicidir; bu yüzden içe aktarma yolunun değişmesini beklemelisiniz. Buna neredeyse hiç ihtiyacınız olmaz: exporter kurulu değilken span'lar bedavadır, bu yüzden olağan yanıt onları açık bırakıp exporter kurmamaktır.

## Özet {#recap}

* Her `MCPServer` ve her düşük seviyeli `Server`, varsayılan olarak gelen mesaj başına bir `SERVER` span'ı üretir. Siz hiçbir şey yazmazsınız.
* Span'lar `mcp.method.name` ve `mcp.protocol.version` taşır; `tools/call` ve `prompts/get` ayrıca GenAI öznitelikleri taşır, böylece araç çağrılarınız başka herhangi bir ajanınkiler gibi gruplanır.
* Bir OpenTelemetry SDK'sı ve bir exporter kurana kadar hiçbir maliyeti yoktur; kurduğunuzda ise sunucunuzda hiçbir değişiklik olmadan görünür hale gelir.
* Her iki taraf da SDK'yı çalıştırdığında iz bağlamı istemciden sunucuya otomatik olarak yayılır.

Bir isteğin çalışıp çalışmayacağına karar veren şey ise **[Yetkilendirme](authorization.md)**.
