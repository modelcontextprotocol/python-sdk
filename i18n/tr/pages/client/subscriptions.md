---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# Abonelikler {#subscriptions}

Bir sunucunun kataloğu sabit değildir. Çalışma zamanında yeni araçlar ortaya çıkar, bir kaynak URI'sinin arkasındaki içerik değişir. İstemci bundan `client.listen(...)` aracılığıyla haberdar olur: yanıtı akışın *kendisi* olan tek bir `subscriptions/listen` isteği. Akış açık kalır ve istemcinin istediği değişiklik bildirimlerini taşır.

Bu sayfa işin istemci tarafını anlatır: akışı açma, ana iş akışınızın yanında izleme ve sonlanmalarını ele alma. Değişiklikleri yayımlama, filtreleme ve yöntemi sunma ise hikâyenin sunucu tarafıdır; *İşleyicinin içinde* bölümündeki **[Abonelikler](../handlers/subscriptions.md)** sayfasında anlatılır. Buradaki örnekler orada kurulan sprint panosu sunucusuyla konuşur.

## Akışı izleme {#watching-the-stream}

Bir abonelik tek bir bağlam yöneticisidir. İçine girmek isteği gönderir (anahtar sözcük argümanlarınız abonelik filtresi olur) ve sunucunun onayını bekler; böylece blok başladığında akış canlıdır.

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Yineleme türü belli dört olay üretir: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged` ve `ResourceUpdated(uri=...)`.

Bir olay *neyin* değiştiğini söyler, asla *nasıl* değiştiğini değil. `follow_board`'un `read_resource` ve `list_tools`'u çağırmasının nedeni budur: olay, yeniden getirmek için bir işarettir. Hangi kaynağın değiştiğini varsaymak yerine `event.uri` alanını okuyun: bir filtre birkaç URI sayabilir ve sunucu bunlardan birinin alt kaynağındaki bir değişikliği bildirebilir.

Tüketilmeyi bekleyen yinelenen olaylar tek bir olaya indirgenir; yeniden getirdiğinizde yine güncel durumu alırsınız. Yalnızca özdeş olaylar birleşir: farklı URI'ler için iki `ResourceUpdated`, iki ayrı olaydır.

Tutamacın (handle) iki özelliği daha var:

* `sub.honored`, sunucunun onayladığı filtredir: geçirdiğiniz alanları taşıyan ve öznitelik olarak okunan bir `SubscriptionFilter` (`sub.honored.prompts_list_changed`). `MCPServer` istediğiniz her türü kabul eder, bu yüzden isteğinizi olduğu gibi geri yansıtır. Daha az tür destekleyen bir sunucu daha azını onaylar; onaylanmış bir tür yine de hiç tetiklenmeyebilir. Sunucu isteği onaylamak yerine tümüyle reddedebilir de (sunucu sayfasındaki [Kimin izleyebileceğine karar verme](../handlers/subscriptions.md#deciding-who-may-watch) bölümüne bakın); bu, isteğin hatası olarak yüzeye çıkar.
* `sub.subscription_id`, listen isteğinin kimliğidir; bu akışın her çerçevesine damgalanan kimlik budur. Aynı anda birkaç abonelik açık olabilir; her biri kendi kimliğiyle ayrıştırılır.

## Engellemeden izleme {#watching-without-blocking}

`follow_board`, sunucu akışı kapatana kadar çalışır, ki bu hiç olmayabilir; bu yüzden tek başına bırakıldığında programınızı ele geçirir. Gerçek istemciler izleyiciyi ana iş akışının *yanında* ister: bir izleyici bir önbelleği ya da arayüzü güncel tutarken ajan araçları çağırır.

Önce aboneliği açın, ardından izleyiciyi başlatın ve işinize devam edin.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py`, `BOARD` ve `read_board`'u ilk örnekten içe aktarır; bu depo o örneği
    `tutorial003.py` olarak saklar. Oluşturulan dosyaları `client.py` ve `app.py` adlarıyla yan yana
    kaydederseniz bunun yerine `from client import BOARD, read_board` yazın. Aşağıdaki `watch.py`
    örneği de `read_board`'u aynı şekilde içe aktarır.

Önemli olan sıradır. Hiçbir şey yeniden oynatılmaz; bu yüzden akışınız var olmadan önce yayımlanan bir olay kaçar. `client.listen(...)` bloğuna girmek onayı bekler; dolayısıyla o andan itibaren her değişiklik izleyicinize ulaşır ve blok içinde aldığınız anlık görüntü hiçbirini kaçıramaz.

Açık bir akışın yanında istekler, izleyici görevinden de başka herhangi bir görevden de, aynı istemci üzerinde serbestçe çalışır. Tüketilmemiş *yinelenen* olaylar birleştiği için, yoğun bir ana iş akışı üç yerine tek bir yeniden getirmeyle sonuçlanabilir. Farklı olaylar birleşmez: çok sayıda URI sayan bir filtre, URI başına bir bekleyen olayı kuyruğa alır.

İzlemeyi bırakmak için bloktan çıkın: `unsubscribe` diye bir çağrı yoktur. Bloğun sahibi olan görevi iptal etmek bunu sizin yerinize yapar; SDK da listen isteğini aktarımın beklediği biçimde iptal eder: Streamable HTTP üzerinde, o isteğin akışını kapatarak. Uygulamanızın ömrü boyunca çalışan bir izleyici kendiliğinden asla dönmez; bu yüzden kapanışta onu ya da görev grubunun kapsamını iptal edin.

## Akışların sona ermesi {#streams-end}

Bir akış iki yoldan biriyle sona erer; ikisi de sıradan denetim akışıdır. Sunucunun düzgün bir kapatması `async for` döngüsünü bitirir; ani bir kopma `SubscriptionLost` fırlatır.

Aradaki fark tanı amaçlıdır, sonra ne yapılacağıyla ilgili değildir: akış gitmiştir, hiçbir şey yeniden oynatılmamıştır ve hâlâ ilgilenen bir izleyici yeniden dinler ve yeniden getirir.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Sunucular akışları kendi gerekçeleriyle düzgünce kapatır; birikimi fazla büyüyen bir aboneyi bırakmak da bunlardan biridir. Bu yüzden temiz bir sonlanma, izlemeyi bırakma işareti değildir. Yeniden dinlemeden önce biraz bekleyin.

`SubscriptionLost`'un yerel bir nedeni de vardır. İstemci en fazla 1024 tüketilmemiş olay tutar; bu kadar geride kalan bir tüketici, sınırsızca büyümek yerine aboneliği kaybeder. `async for` gövdesini kısa tutun, yavaş işleri başka yerde yapın.

`keep_following` yalnızca `SubscriptionLost`'u yakalar. `listen()`'a girmek ayrıca `MCPError` (bağlantı başarısız oldu ya da sunucu yöntemi sunmuyor), `TimeoutError` (onay gelmedi) ve `ListenNotSupportedError` (2026 öncesi bir bağlantı) da fırlatabilir. İzleyicinizin bunlardan hangilerini yeniden denemesi gerektiğine karar verin: sonuncusu asla düzelmez.

## Özet {#recap}

* `async with client.listen(...)` bloğuna girin; giriş onayı bekler, bu yüzden ondan sonra yayımlanan hiçbir şey kaçmaz.
* `async for event in sub` ile yineleyin. Olaylar yeniden getirmek için birer işarettir, asla yük (payload) değildir.
* Aboneliği açın, ardından izleyiciyi bir görev olarak çalıştırın; araç çağrıları onun yanında akmaya devam eder.
* Temiz bir sonlanma döngüyü durdurur; kopma `SubscriptionLost` fırlatır. Her iki durumda da: yeniden dinleyin, yeniden getirin, ama önce biraz bekleyin.
* Bloktan çıkmak abonelikten çıkmaktır.

Bu olayları yayımlamak, filtreyi daraltmak ve tek bir sürecin ötesine ölçeklemek sunucunun hikâyesidir: **[Abonelikler](../handlers/subscriptions.md)**. Aynı olaylar istemci tarafındaki bir önbelleği de dürüst tutar; sıradaki sayfa **[Önbellekleme](caching.md)**.
