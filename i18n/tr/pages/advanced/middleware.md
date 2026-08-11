---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

**Middleware** (ara katman), sunucunun aldığı her mesajı saran tek bir asenkron fonksiyondur.

Onu `async (ctx, call_next)` biçiminde yazar ve `server.middleware` listesine eklersiniz. API'nin tamamı bu.

!!! warning
    Middleware listesi kaynak kodda **geçici (provisional)** olarak işaretlidir: imzası ve anlamı
    bir 2.x ara sürümünde değişebilir. Onu mesajları *gözlemlemek* (zamanlama, log tutma, izleme) ve
    *reddetmek* için kullanın; sunucunuzun üzerinde durduğu temel haline getirmeyin.

`MCPServer` listeyi oluşturulurken alır (`MCPServer(name, middleware=[...])`) ve onu
`mcp.middleware` olarak sunar; alt düzey `Server` aynı listeyi `server.middleware` olarak sunar. Aşağıdaki
örnek alt düzey `Server`'ı kullanır; `Server(name, on_call_tool=...)` size yeniyse önce
**[Alt düzey Server](low-level-server.md)** sayfasını okuyun.

## Bir zamanlama middleware'i {#a-timing-middleware}

Bir sunucu, bir araç ve her mesajın ne kadar sürdüğünü loglayan bir middleware:

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx`, işleyicilerinizin aldığı `ServerRequestContext`'in aynısıdır. `ctx.method` ham
  metot dizgesidir; `ctx.params` ise herhangi bir doğrulamadan **önceki** ham parametrelerdir.
* `call_next(ctx)` zincirin geri kalanını çalıştırır: doğrulama, işleyici araması, işleyiciniz.
  Onun döndürdüğünü döndürürseniz yanıta dokunulmaz.
* `try`/`finally` bilinçli bir tercihtir: istisna fırlatan bir işleyicinin de süresi ölçülür, çünkü hata
  middleware'inize `call_next`'ten çıkan istisna olarak ulaşır.
* `server.middleware.append(...)` onu kaydeder. Liste dıştan içe doğru çalışır, yani
  `middleware[0]` ağ tarafına en yakın olandır.

### Deneyin {#try-it}

Bir istemci bağlayın, araçları listeleyin, birini çağırın. Logunuzda **üç** satır var:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

İki çağrı yaptınız ve üç satır elde ettiniz. İlki `server/discover`: siz herhangi bir şey
istemeden önce, istemcinin bağlantıyı kurmak için gönderdiği istek.

İşin özü de bu. Middleware gelen **her** mesajı sarar:

* Bağlantı kurulumu: `server/discover` ya da eski nesil bir oturumda `initialize` ve
  `notifications/initialized`.
* Her istek ve her bildirim. Bir bildirimde `ctx.request_id is None` olur,
  `call_next(ctx)` `None` döndürür ve sizin döndürdüğünüz her şey atılır.
* Sunucunun işleyicisi olmayan bir metot bile: `call_next`,
  `MCPError(-32601, "Method not found")` istisnasını istemciye giderken middleware'inizin *içinden* fırlatır.

## İçinde neler yapabilirsiniz {#what-you-can-do-inside-one}

Ne kadar tereddüt etmeniz gerektiğine göre artan sırayla:

* **Gözlemleyin.** Süresini ölçün, sayın, loglayın. Yukarıdaki örnek.
* **Reddedin.** `call_next(ctx)`'i çağırmak *yerine* bir `MCPError` fırlatın; o tek mesaj
  bir JSON-RPC hatasıyla yanıtlanır. Bağlantı ayakta kalır; sonraki mesaj geçer. Bir sunucu
  `subscriptions/listen`'ı çağıran başına böyle denetler:
  Abonelikler sayfasındaki **[Kimin izleyebileceğine karar verme](../handlers/subscriptions.md#deciding-who-may-watch)** bölümü
  bunu adım adım anlatır.
* **Yeniden yazın.** `ctx` bir dataclass'tır: `await call_next(dataclasses.replace(ctx, params=...))`
  zincirin geri kalanına istemcinin gönderdiğinden farklı parametreler verir. Bunu `initialize`
  için asla yapmayın: istemcinin geri aldığı sonuç sizin yeniden yazdığınız parametrelerden oluşturulur, ancak
  sunucu bağlantı durumunu ağdan gelen özgün parametrelere göre kaydeder. İki taraf
  el sıkışmayı neyi müzakere ettikleri konusunda anlaşamadan bitirebilir.
* **Yanıtlayın.** `call_next(ctx)`'i çağırmadan bir sonuç döndürün; bu sonuç istemciye sizin
  yanıtınız olarak gider. `call_next` size tamamlanmış iletim biçimini verir ve işlem hattı döndürdüğünüzü
  asla yamalamaz; bu yüzden zarfın tamamı sizindir: 2026 neslinden bir bağlantıda buna
  `serverInfo` `_meta` damgası da dahildir. SDK bu damgayı işleyici sonuçlarına ekler, sizinkilere eklemez.

!!! check
    `initialize`, middleware'in sardığı şeylerden biridir ve onun için elinizdeki *tek* kanca
    budur. Onu `add_request_handler` ile devralmaya çalışırsanız SDK reddeder:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` satır içinde ele alınır: middleware zinciriniz dönene kadar sunucu başka gelen
    mesaj okumaz. Bu yüzden `initialize`'ı işlerken sunucudan istemciye bir isteği (`ctx.session.send_request(...)`,
    bir elicitation) beklemek **bağlantıyı kilitler**: beklediğiniz
    yanıt asla okunamaz. Gönderip unutulan bildirimlerde sorun yoktur.

## Varsayılan olarak açık gelen tek middleware {#the-one-middleware-that-ships-on-by-default}

SDK tam olarak bir middleware ile gelir ve o zaten sunucunuzun listesindedir: her mesaj için
bir OpenTelemetry span'i yayan middleware. Onu siz eklemezsiniz ve çoğu zaman
aklınıza bile gelmez. Bir exporter kurana kadar hiçbir şey yapmaz ve kendi sayfası vardır:
**[OpenTelemetry](../run/opentelemetry.md)**.

!!! info
    ASGI middleware'i yazdıysanız bu yapıyı zaten biliyorsunuz. Starlette'in
    `(scope, receive, send)` üçlüsü `(ctx, call_next)` oldu ve aktarımdan *sonra*, ham
    HTTP isteği yerine çözülmüş mesaj üzerinde çalışır. İkisi birlikte kullanılabilir: `streamable_http_app()`
    üzerindeki Starlette middleware'i HTTP'yi görür; bu ise MCP'yi görür.

## Özet {#recap}

* Bir middleware `async (ctx, call_next) -> result` biçimindedir; `MCPServer(middleware=[...])` olarak geçirilir (ya da
  `mcp.middleware` listesine eklenir), alt düzey `Server`'da ise `server.middleware` listesine eklenir.
* Gelen **her** mesajı sarar (`server/discover`, `initialize`, istekler, bildirimler,
  bilinmeyen metotlar) ve dıştan içe doğru çalışır.
* Bir bildirimi bir istekten `ctx.request_id is None` ile ayırt edersiniz.
* Tek bir mesajı reddetmek için `call_next`'i çağırmak yerine istisna fırlatın; bağlantı ayakta kalır.
* SDK'nın kendi OpenTelemetry izlemesi de bir middleware'dir ve zaten listededir. Bkz.
  **[OpenTelemetry](../run/opentelemetry.md)**.
* Yüzeyin tamamı geçicidir. Onunla gözlemleyin; üzerine inşa etmeyin.

Bir isteği saran her şey bu kadar. İsteğin çalışıp çalışmayacağına karar veren ise
**[Yetkilendirme](../run/authorization.md)**.
