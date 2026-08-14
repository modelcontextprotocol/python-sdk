---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# İstemci callback'leri {#client-callbacks}

MCP'de neredeyse her istek tek yöne gider: istemciden sunucuya.

Sunucu da **istemciden** bir şeyler isteyebilir: kullanıcıya soru sormasını, kullanıcının modelinden örnekleme yapmasını, kullanıcının çalışma alanı klasörlerini listelemesini. Bu istekleri `Client(...)`'a **callback'ler** (geri çağırma işlevleri) geçirerek yanıtlarsınız.

## Soru soran bir sunucu {#a-server-that-asks}

İşte aracı kendi başına tamamlanamayan bir sunucu:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)`, **istemciye** bir `elicitation/create` isteği gönderir ve bekler.
* Araç, birisi (form dolduran bir kişi ya da kodunuz) bir `name` sağlayana kadar dönmez.

Bu, işin sunucu tarafı; ona **[Elicitation](../handlers/elicitation.md)** sayfası bakar. Bu sayfa ise hattın öteki ucu.

## Elicitation callback'i {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* Bir elicitation (kullanıcıdan bilgi isteme) callback'i `async (context, params) -> ElicitResult` biçimindedir.
* `params.message` sorudur. `params.requested_schema`, sunucunun beklediği yanıtın JSON Schema'sıdır. Gerçek bir istemci bundan bir form üretir; buradaki ise otomatik doldurur.
* `ElicitResult(action="accept", content={...})` döndürürsünüz; ya da `action="decline"` veya `action="cancel"`. Bunların dışındaki tek seçenek, isteği reddedip çağrının tamamını başarısız kılan `ErrorData(...)`'dır.
* `context` bir `ClientRequestContext`'tir: canlı `session`, sunucunun `request_id`'si ve eklediği her türlü `meta`.

!!! tip
    `params`, iki elicitation kipinin birleşimidir (union). Burada `params.mode` değeri `"form"`; bir `"url"`
    isteği ise şema yerine `params.url` taşır. Tek callback ikisini de karşılar; `params.mode` üzerinden dallanın.
    Kalıbın tamamı **[Elicitation](../handlers/elicitation.md)** sayfasında.

### Deneyin {#try-it}

`issue_card`'ı çağırın ve iki ucu da izleyin.

Callback'iniz sunucunun sorusunu hazır ayrıştırılmış olarak alır:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

Yanıt verir, `ctx.elicit(...)` aracın içinde kaldığı yerden devam eder ve araç tamamlanır:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

Sizden tek bir `tools/call`, sunucudan geriye tek bir `elicitation/create`, onu yanıtlayan da sizin fonksiyonunuz; hepsi tek bir araç çağrısının içinde.

!!! info
    `Client(...)` çağrısındaki `mode="legacy"` gerçekten iş yapıyor. Varsayılan olarak `Client(...)` modern
    protokol yolunu müzakere eder ve o yolda sunucudan istemciye gelen istekler için bir geri kanal (back-channel)
    yoktur: `ctx.elicit`, callback'iniz daha çalışmadan başarısız olur. Buna aktarım karar vermez; müzakere edilen
    protokol karar verir, bellek içinde de bir URL üzerinden de aynı şekilde. İstemcinizin böyle bir isteği
    yanıtlaması gerektiğinde `mode="legacy"`'yi sabitleyin; bu sayfanın arkasındaki her test bunu yapar.
    Ayrıntıların tamamı **[Protokol sürümleri](../protocol-versions.md)** sayfasında.

    Bir 2026-07-28 oturumunda callback ölü değildir, yalnızca farklı beslenir: bir araç, `ElicitRequest` taşıyan bir
    `InputRequiredResult` döndürdüğünde `Client` o girdiyi aynı `elicitation_callback`'e yönlendirir ve çağrıyı
    sizin adınıza yeniden dener. Bu akış **[Çok turlu istekler](../handlers/multi-round-trip.md)** sayfasında.

## Callback bir yetenektir {#a-callback-is-a-capability}

İstemcinizin elicitation isteklerini yanıtlayabildiğini sunucuya hiç söylemediniz. SDK söyledi.

Bir istemci bağlandığında `capabilities`'ini, yani sunucununkinin aynadaki yansımasını bildirir. O nesneyi siz yazmazsınız. **Callback'i kaydetmek bildirimin ta kendisidir.**

| geçirdiğiniz | istemcinin bildirdiği |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| hiçbiri | `{}` |

Tek ince ayar örnekleme alt yetenekleridir: örnekleyiciniz `tools` / `tool_choice` parametrelerini işliyorsa `sampling_callback`'in yanında `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` geçirin. Sunucular bunları gönderebilmek için önce `sampling.tools`'un bildirildiğini görmelidir.

`logging_callback` ve `message_handler` tabloda yok. Onlar bildirimleri işler ve bildirimler yetenek gerektirmez.

Sunucu bildirimi `ctx.session.check_client_capability(...)` ile geri okur. Bunu yapan bir araç ekleyin:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

Yalnızca `elicitation_callback` ile bağlanın ve aracı çağırın:

```python
result.structured_content  # {'result': ['elicitation']}
```

Üç callback'i de geçirirseniz `['elicitation', 'sampling', 'roots']` alırsınız. Hiçbirini geçirmezseniz `[]` alırsınız.

!!! check
    Şimdi yanlış olanı yapın: `elicitation_callback` **olmadan** bağlanın ve yine de `issue_card`'ı çağırın.

    Sunucunun `elicitation/create` isteği yine istemcinize ulaşır ve SDK onu sizin yerinize yanıtlar; ama bir hatayla,
    çünkü bunu karşılayabileceğinizi hiç söylemediniz. O hata çağrının tamamını batırır.
    `call_tool` bir `is_error` sonucu döndürmez; istisna fırlatır:

    ```text
    MCPError: Elicitation not supported
    ```

    Bu bir araç hatası değil, bir protokol hatasıdır (`-32600`, *invalid request*): modelin okuyup yeniden
    deneyebileceği bir şey yoktur. `client_features`'ın değerli olmasının nedeni de bu: uslu bir sunucu
    sormadan önce kontrol eder.

## Kullanım dışı ikili {#the-deprecated-pair}

`sampling_callback`, `sampling/createMessage`'ı yanıtlar: sunucunun *sizin* modelinizden bir şeyi tamamlamasını istemesi. `list_roots_callback`, `roots/list`'i yanıtlar: sunucunun hangi dizinlerde çalışabileceğini sorması.

İkisi de çalışır. İkisi de yukarıdaki kurala uyar. Ve ikisi de **2026-07-28 spesifikasyonunun kaldırdığı** RPC'lere hizmet eder: modern bir sunucu istek ortasında istemcinizi geri çağırmaz, isteği araç sonucunun bir parçası olarak size geri verir (**[Çok turlu istekler](../handlers/multi-round-trip.md)**). Callback'lerin kendisi ölü değildir. Bir `InputRequiredResult`, `CreateMessageRequest` veya `ListRootsRequest` taşıdığında `Client`'ın otomatik döngüsü onu burada kaydettiğiniz aynı `sampling_callback` veya `list_roots_callback`'e yönlendirir. Listenin tamamı **[Kullanım dışı özellikler](../deprecated.md)** sayfasında.

Henüz geçiş yapmamış sunucularla konuşmak için callback'lere hâlâ ihtiyacınız var. İmzalar:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* Bir örnekleme (sampling) callback'i `CreateMessageRequestParams`'ın tamamını (`messages`, `model_preferences`, `max_tokens`) alır ve bir `CreateMessageResult` döndürür. Modeli *siz* çalıştırırsınız, nasıl isterseniz öyle; SDK yalnızca isteği taşır.
* Bir kök dizinler (roots) callback'i hiç parametre almaz ve bir `ListRootsResult` döndürür.
* Her ikisi de reddetmek için bunun yerine `ErrorData(...)` döndürebilir.

Bunları `Client(...)`'a tıpkı `elicitation_callback` gibi geçirin.

## Bildirim callback'leri {#the-notification-callbacks}

İki tane daha. Hiçbiri bir şey bildirmez.

`logging_callback`, sunucunun gönderdiği `notifications/message`'ı `LoggingMessageNotificationParams` (`level`, `logger`, `data`) olarak alır. Protokol log'lamasının kendisi 2026-07-28 spesifikasyonuyla kullanım dışı bırakıldı (yerine ne yapılacağı **[Log kaydı](../handlers/logging.md)** sayfasında); bu yüzden bu callback, hâlâ bunu yayan sunucular için var. 2026 neslinden bir bağlantıda callback tek başına size hiçbir şey kazandırmaz, çünkü 2026 sunucuları log mesajlarını yalnızca bunu talep eden isteklere gönderir: bu talebi her isteğe damgalamak ve o düzey ile üstünü almak için `Client(...)`'a `log_level="info"` (veya başka bir düzey) geçirin. 2026 öncesi sunucular bunu yok sayar ve `logging/setLevel` davranışlarını sürdürür.

`message_handler` her şeyi yakalayandır: oturumun yüzeye çıkardığı her sunucu bildirimi ona ulaşır (kendi özel callback'inin yanı sıra), akış tabanlı bir aktarımda aktarım düzeyindeki her `Exception` da öyle. İkisi asla ulaşmaz: `notifications/cancelled` yüzeye çıkarılmak yerine SDK tarafından uygulanır ve canlı bir `listen()` akışının abonelik onayı o akış tarafından tüketilir. Parametreye `IncomingMessage` (`ServerNotification | Exception`, `mcp.client`'tan dışa aktarılır) tür ipucunu verin. Bilmeye değer tek kalıp `if isinstance(message, Exception): raise message`'dır; böylece kopan bir bağlantı sessizce kaybolmak yerine gürültüyle başarısız olur.

## Özet {#recap}

* Sunucu istemciye istek gönderebilir. Bunları `Client(...)`'a geçirdiğiniz callback'lerle yanıtlarsınız.
* Güncel olan elicitation callback'idir: `async (context, params) -> ElicitResult`, hem form hem URL kipi için tek fonksiyon.
* **Callback'i kaydetmek yeteneği bildirmektir.** O olmadan SDK sunucunun isteğini sizin adınıza reddeder ve çağrının tamamı `MCPError` ile başarısız olur.
* Sunucu, sormadan önce `ctx.session.check_client_capability(...)` ile öğrenir.
* `sampling_callback` ve `list_roots_callback` aynı şekilde çalışır ama kullanım dışı özelliklere hizmet eder; modern sunucular bunun yerine çok turlu istekler (multi-round-trip) kullanır.
* `logging_callback` ve `message_handler` bildirimleri alır. Hiçbir şey bildirmezler.

`Client(...)`'ın ilk argümanı bir aktarım nesnesidir. **[İstemci aktarımları](transports.md)** her türünü ele alır.
