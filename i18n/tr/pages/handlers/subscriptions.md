---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# Abonelikler {#subscriptions}

Bir sunucunun kataloğu sabit değildir. Çalışma zamanında yeni araçlar ortaya çıkar, bir kaynak URI'sinin ardındaki içerik değişir.

İstemci bunlardan **abonelikler** sayesinde haberdar olur. İstemci tek bir `subscriptions/listen` isteği gönderir ve bu isteğin yanıtı akışın *ta kendisidir*: açık kalır ve istemcinin istediği değişiklik bildirimlerini taşır.

## Değişikliği araçtan yayımlama {#publish-it-from-the-tool}

Size düşen tek satır: değişikliği yayımlayın.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` bu URI'ye abone olmuş her açık akışa ulaşır. Başka kimseye değil.
* `await ctx.notify_tools_changed()` araç listesi değişikliklerini isteyen her akışa ulaşır. Bunu alan istemci `tools/list`'i yeniden çağırır ve artık `sprint_report`'u görür.
* Kardeş metotlar `notify_prompts_changed()` ve `notify_resources_changed()`.
* Abone yoksa iş de yok. Boştaki bir sunucuda yayımlamak hiçbir şey yapmaz; bu yüzden kimsenin dinleyip dinlemediğini asla kontrol etmezsiniz. Neyin değiştiğini bildirirsiniz, o kadar.

`MCPServer`, `subscriptions/listen`'ı sizin yerinize sunar. Protokol düzeyindeki yükümlülükler (ilk çerçeve olarak onay, akış başına filtreleme, her çerçevede abonelik kimliği) SDK'nın işidir.

!!! check
    Ağ üzerinde, filtresinde `board://sprint` geçen bir akış `complete_task` çalıştıktan sonra şöyle görünür:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    Güncellemenin neyi *taşımadığına* dikkat edin: panonun kendisini. Her çerçeve, listen isteğinin JSON-RPC kimliğini `_meta` altında taşır ve bu kimlik abonelik kimliğidir. Onu istemci üretir: Python `Client`'ı `"listen-1"` gibi dizeler kullanır; başka istemciler tamsayı kullanabilir.

## Yalnızca istenenler {#only-what-was-asked-for}

Filtre bir sözleşmedir. Araç listesi değişikliklerini ve tek bir kaynak URI'sini isteyen bir akış bu iki türü alır, başka hiçbir şeyi almaz. Bir prompt değişikliği yayımlarsanız o akış sessiz kalır.

`MCPServer` kaynak URI'lerini birebir dize olarak eşleştirir; bu yüzden `board://sprint` URI'sini belirten bir akış `board://sprint/tasks/1` hakkında hiçbir şey duymaz. Belirtim, sunucunun abone olunan bir URI'nin alt kaynağındaki değişikliği bildirmesine izin verir; `MCPServer` bunu hiç yapmaz ama istemciler bunu bekleyecek şekilde yazılmıştır.

Akışın *olmadığı* iki şey:

* **Bir yeniden oynatma log'u değildir.** Kopan bir akış gitmiştir; kimse bağlı değilken yayımlanan olaylar kuyruğa alınmaz. İstemciler yeniden dinler ve yeniden getirir.
* **2025 yolu değildir.** `resources/subscribe` çağırmış istemcilere `ctx.session.send_resource_updated(uri)` hizmet verir. `notify_*` metotları yalnızca `subscriptions/listen` akışlarına ulaşır.

## Kimin izleyebileceğine karar verme {#deciding-who-may-watch}

Varsayılan olarak istenen her tür ve URI kabul edilir: her çağıran, yayımladığınız her URI'yi izleyebilir. Okuma işleyicinize hiçbir şey danışmaz, çünkü kimse okumuyordur. `files://{name}` işleyicinizin geri çevireceği bir çağıran yine de `files://payroll.csv` üzerinde bir akış açıp onun değiştiğini, hem de ne zaman değiştiğini öğrenebilir. İçeriği asla öğrenemez ve neyin var olduğunu yoklayamaz; çünkü bilinmeyen bir URI de kabul edilir ve yalnızca hiç tetiklenmez. Dar ama gerçek bir açık; bu yüzden çok kiracılı bir sunucudan kullanıcıya özel URI'ler yayımlamadan önce erişimi denetleyin.

Bu denetimi bir middleware (ara katman) üstlenir. `subscriptions/listen` isteğini SDK onaylamadan önce görür ve çağıran okuyamayacağı bir şey istediğinde isteği reddeder:

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` ham istektir; bu yüzden middleware onu `SubscriptionsListenRequestParams` olarak kendisi doğrular ve istemcinin istediği filtreyi okur.
* Reddetmek, `call_next(ctx)`'ten önce fırlatılan bir `MCPError` demektir: istemci o hatayı alır, akış almaz ve bağlantı devam eder. Mesajı tek tip tutun ve hiçbir URI adı vermeyin; böylece bir ret hangi URI'lerin korunduğunu asla doğrulamaz.
* Tek bir `can_access(user, uri)` her iki soruyu da yanıtlar. Kaynak işleyicisi ona `resources/read` sırasında sorar; middleware ise `subscriptions/listen` sırasında. Tabloyu bir veritabanıyla ya da RBAC sisteminizle değiştirin, ikisi de uyumlu kalır.
* Karar akışın ömrü boyunca geçerlidir. Olay başına yeniden denetim yoktur; bu yüzden bir çağıranın erişimi akış ortasında sona erebiliyorsa (süresi dolan bir token gibi), sona erdiğinde o çağıranın bağlantısını kapatın.

Middleware sözleşmesinin tamamı, başka neleri sardığı ve neden geçici (provisional) olarak işaretlendiği de dahil, **[Middleware](../advanced/middleware.md)** sayfasında.

## İstemci tarafı {#the-client-end}

İşte o akışın diğer ucunda, panoyu takip eden bir istemci:

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

`client.listen(...)`'a girmek isteği gönderir ve sizin onayınızı bekler; yani blok başladığında akış canlıdır ve türü belirli her olay bir yeniden getirme işaretidir, asla bir yük (payload) değildir. Sözleşmenin tamamı tek bir ekranda bu. İstemci tarafıyla ilgili geri kalan her şey kendi sayfasında: ana akışın yanında izleme, akış sonlanmaları ve yeniden dinleme. *İstemciler* altındaki **[Abonelikler](../client/subscriptions.md)** sayfasına bakın.

## Tek sürecin ötesine ölçekleme {#scaling-past-one-process}

Yayımlar, işleyicinizden açık akışlara bir `SubscriptionBus` üzerinden gider. Varsayılanı bellek içidir: tek süreç, içindeki tüm akışlar. Bir yük dengeleyicinin arkasında replikalar çalıştırana kadar doğru yanıt budur; çünkü o noktada bir istemcinin akışı tek bir replikaya bağlı kalır ve başka bir replikadaki yayımın ona ulaşması gerekir.

Bu birleşim noktasını siz uygularsınız: pub/sub arka ucunuzun üzerinde iki metot.

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` size aittir; her replikada gelen mesajların kodunu çözüp kayıtlı her dinleyiciyi çağıran okuyucu görev de öyle. Dinleyiciler senkrondur, istisna fırlatmamalıdır ve sunucunun olay döngüsünde çalışır.

Veri yolu türü belirli `ServerEvent` değerleri taşır (dört küçük dataclass), asla JSON-RPC değil. Damgalama, filtreleme ve akış yaşam döngüleri SDK'da kalır; bu yüzden bir veri yolu uygulaması protokolü bozamaz. Yalnızca olayları süreçler arasında taşıyabilir.

Bir isteğin dışından yayımlamak için veri yolunu kendiniz oluşturun ki referansı elinizde olsun. Hiçbir şey geçirmediğinizde `MCPServer` içeride bir tane kurar ve onu dışarı açmaz.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## Düşük düzeyli bileşim {#the-low-level-composition}

Düşük düzeyli `Server`'da önceden bağlanmış hiçbir şey yoktur; aynı parçalar üç satırda bir araya gelir:

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* Veri yolu sizindir; bu yüzden doğrudan ona yayımlarsınız: `await bus.publish(ResourceUpdated(uri=...))`. İşleyicilerinizin erişebileceği bir yere koyun: burada modül kapsamı, daha büyük bir uygulamada lifespan (yaşam döngüsü).
* `ListenHandler(bus)`, `MCPServer`'ın kaydettiği işleyicinin aynısıdır ve `on_subscriptions_listen=` sıradan bir işleyici yuvasıdır. Farklı bir anlam için o yuvaya kendi çağrılabilir nesnenizi koyun; o zaman belirtim yükümlülükleri size geçer: önce onaylayın, her çerçeveyi abonelik kimliğiyle damgalayın, filtrenin dışında hiçbir şey iletmeyin.
* `ListenHandler.close()` her açık akışı düzgünce sonlandırır. Her biri son çerçevesi olarak listen isteğinin sonucunu alır; bu, belirtimin sunucunun aboneliği bilerek sonlandırdığını söyleme biçimidir. Metot, bu akışlar boşaltmayı bitirmeden döner; bu yüzden aktarımı kapatmadan önce onlara kısa bir süre tanıyın. Onsuz, akışlar istemci bağlantıyı kestiğinde sona erer.

## Özet {#recap}

* İstemci tek bir `subscriptions/listen` isteğiyle katılır ve yanıt akışın kendisidir. Bunu sunmak yerleşiktir.
* `ctx.notify_*` ile yayımlarsınız; damgalama, filtreleme ve yaşam döngüsü işini SDK yapar.
* Olaylar işarettir, yük değil. Her iki uç da yeniden getirir.
* İstemci tarafı `async with client.listen(...)` bloğudur: ayrıntıları *İstemciler* altındaki **[Abonelikler](../client/subscriptions.md)** sayfasında.
* Düşük düzeyli `Server`'da aynı parçaları kendiniz birleştirirsiniz: bir veri yolu, `ListenHandler(bus)`, `on_subscriptions_listen` yuvası.
* Yatay ölçekleme, `SubscriptionBus`'ı (iki metot) uygulamak ve onu `MCPServer(subscriptions=...)` olarak geçirmek demektir.

Tüm bunları sunan sunucuyu ister tek replikanın ister yirmisinin arkasında çalıştırma konusu **[Dağıtım ve ölçekleme](../run/deploy.md)** sayfasında.
