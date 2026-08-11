---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# Önbellekleme ipuçları {#caching-hints}

2026-07-28 protokolünde bir sunucunun `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` ve `server/discover` için döndürdüğü her sonuç iki alan taşır: `ttlMs`, istemcinin sonucu kaç milisaniye boyunca taze sayabileceğini; `cacheScope` ise önbelleğe alınmış bir sonucun kullanıcılar arasında paylaşılıp paylaşılamayacağını (`"public"`) yoksa tek bir yetkilendirme bağlamına mı ait olduğunu (`"private"`) belirtir.

Sunucu hiçbir şeyi önbelleğe almaz. Bu alanlar bir *beyandır*: "bu araç listesi herkes için aynı ve bir dakika boyunca değişmeyecek." Bunun üzerine bir istemci (ya da önünüzdeki bir ağ geçidi) turu atlayabilir. İpuçlarına uymak istemcinin tercihidir; onları yayımlamak sunucunun işidir ve bunu sizin yerinize SDK yapar.

Varsayılan olarak her sonuç `ttlMs: 0, cacheScope: "private"` der: anında bayat, asla paylaşılmaz. Bu her zaman güvenli ve her zaman uyumludur. Listeleriniz gerçekten kararlıysa ve tüm çağıranlar için aynıysa, bunu oluşturma sırasında belirtin:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* Eşleme **yöntem adına** göre anahtarlanır ve geçerli anahtarlar yalnızca önbelleğe alınabilir altı yöntemdir. Parametrenin türü `Mapping[CacheableMethod, CacheHint]` olduğundan düzenleyiciniz anahtarları otomatik tamamlar ve bir yazım hatasını siz çalıştırmadan önce işaretler; tür denetleyicisinden kaçan her şey oluşturma sırasında istisna fırlatır.
* Anmadığınız bir yöntem varsayılanları korur. Eşleme bir manifesto değil, bir geçersiz kılma kümesidir.
* `CacheHint(ttl_ms=5_000)` `scope`'u ayarlamadı, bu yüzden `"private"` kalır: çağıran başına beş saniyelik tazelik. Kapsam ve TTL birbirinden bağımsız kararlardır.
* `"server/discover"` da geçerli bir anahtardır, çünkü keşif sonucu herhangi bir liste gibi önbelleğe alınabilir.

!!! warning
    `cacheScope: "public"`, önbelleğe alınmış yanıtınızın *herkese* sunulabileceği anlamına gelir.
    Paylaşımlı bir ağ geçidi, istek kimliği doğrulanmış olsa bile, bir kullanıcının sonucunu başka
    birine rahatlıkla verir. Bir sonucu yalnızca her çağıran için aynı olduğunda `"public"` olarak
    işaretleyin ve `cacheScope`'u asla erişim denetimi olarak kullanmayın: o bir etikettir, kilit değil.

## İşleyici başına geçersiz kılma {#per-handler-override}

Alt düzey `Server`'da işleyiciler sonuçlarını elle oluşturur ve `ttl_ms` / `cache_scope` sonuç modellerindeki sıradan alanlardır. Bunları açıkça ayarlayan bir işleyici, alan alan, her zaman oluşturucu eşlemesine üstün gelir:

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

İşleyici `ttl_ms=1_000` dedi, kapsam hakkında ise hiçbir şey söylemedi. İletilen veride: `ttlMs: 1000` (eşlemenin `60_000`'i değil, işleyicininki) ve `cacheScope: "public"` (eşlemeninki, çünkü işleyici onu ayarlamadı). Açık olan yapılandırılanı, yapılandırılan da varsayılanı yener. Bu alan başına geçerlidir; yani bir işleyici bir alanı sabitleyip diğerini sunucu genelindeki politikaya bırakabilir.

Bu aynı zamanda oluşturucunun bilemeyeceği dinamikler için kaçış kapısıdır: `resources/read`'i kullanıcıya göre filtreleyen bir işleyici, geri kalanı public olan bir sunucudan tek bir URI için `cache_scope="private"` döndürebilir.

Sayfalandırılmış listelerle ilgili bir uyarı: protokol bir listenin **her sayfasında aynı `cacheScope`'u** şart koşar. Oluşturucu eşlemesi bunu yapısı gereği sağlar, çünkü sayfaya değil yönteme göre anahtarlanır. Ancak kapsamı kendisi geçersiz kılan bir işleyici bu tutarlılıktan kendisi sorumludur: kapsamı *her* sayfada geçersiz kılın, asla yalnızca bir imleç varken değil; yoksa birinci sayfa ile ikinci sayfa çelişir.

## İstemcinin gördükleri {#what-the-client-sees}

2026-07-28 oturumunda `Client` ipuçlarına sizin yerinize uyar: varsayılan olarak açık, yerleşik bir yanıt önbelleği vardır. `ttlMs` taşıyarak gelen bir sonuç saklanır ve o TTL içinde yapılan özdeş bir çağrı hiç tur atılmadan önbellekten sunulur. *Hiç* ipucu taşımayan bir sonuç önbelleğe alınmaz: ipucu taşımayan sonuçlar `CacheConfig.default_ttl_ms` değerini alır, bu da varsayılan olarak `0`'dır (anında bayat); dolayısıyla hiçbir şey beyan etmeyen bir sunucu, her zaman gördüğü çağrı başına bir istek trafiğinin aynısını görür.

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

Dört çağrı, üç getirme. İkinci çağrı taze bir girdi buldu ve sunucuya hiç ulaşmadı; (enjekte edilen) saati TTL'nin ötesine ilerletmek üçüncünün yeniden getirmesine yol açtı; dördüncü `cache_mode="refresh"` dedi. Bu anahtar sözcük argümanı önbellekleme yapan beş fiilde bulunur (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`):

* `"use"` (varsayılan) varsa taze bir girdiyi sunar, yoksa getirilen sonucu saklar.
* `"refresh"` asla önbellekten sunmaz: sonucu getirir ve saklar, önbellekte ne varsa onun yerine koyar.
* `"bypass"` önbelleğe hiç dokunmadan turu atar: ne okuma ne yazma.

`"use"`'un üzerinde bir kural vardır: **`meta` taşıyan çağrılar her zaman sunucuya ulaşır.** `meta` ayarlanmış bir istek (bir ilerleme token'ı, izleme alanları) ağ üzerinde gerçek bir istek bekler; bu yüzden `cache_mode="use"` altında `"refresh"` gibi ele alınır: önbellek okuması atlanır ve getirilen sonuç yine de önbellekteki girdinin yerine geçer. `"bypass"` ve açık bir `"refresh"` her zamanki gibi davranır.

Önbelleklemeyi tamamen kapatmak için `Client(server, cache=None)` ile oluşturun: her çağrı yeniden bir tur olur ve `cache_mode` hâlâ kabul edilse de hiçbir şey yapmaz.

Kapsama da otomatik olarak uyulur: `"private"` girdiler önbelleğin *bölümüne* (partition, aşağıda) göre anahtarlanır, `"public"` olanlar ise daha geniş paylaşıma katılmayı seçebilir. Ayrıca **bildirimler TTL'yi yener**, ama yalnızca tam olarak adlandırdıkları girdiler için: bir `list_changed` bildirimi eşleşen önbellekteki listeyi çıkarır, `resources/updated` ise tam olarak kendi URI'si altında saklanan önbellekteki okumayı çıkarır; ne kadar taze olurlarsa olsunlar. 2026-07-28 bağlantısında bu bildirimler `client.listen(...)` ile açtığınız bir `subscriptions/listen` akışı üzerinden gelir ve çıkarma, izleyiciniz olayı görmeden önce tamamlanır; bunun sayfası **[Abonelikler](subscriptions.md)**.

`resources/updated` ile ilgili bir uyarı: çıkarma yalnızca tam URI eşleşmesiyle olur. Depo sözleşmesinde listeleme ya da tarama işlemi yoktur (referans TypeScript gerçekleştirimiyle aynı); bu yüzden bir *alt* kaynak URI'si taşıyan bir bildirim, üst kaynağının önbellekteki okumasını çıkarmaz. Sunucunuz alt kaynakları bu şekilde bildiriyorsa üst kaynağı `cache_mode="refresh"` ile yeniden getirin.

### Yapılandırma: `CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`: girdilerin yaşadığı yer. Varsayılan, istemci başına yeni bir bellek içi depodur; bir önbelleği istemciler ya da süreçler arasında paylaşmak için kendi `ResponseCacheStore` gerçekleştiriminizi (örneğin Redis destekli) geçirin. Sözleşme türleri (`ResponseCacheStore`, `CacheKey`, `CacheEntry` ve varsayılan `InMemoryResponseCacheStore`) `mcp.client`'tan içe aktarılabilir. Bir arama depoya art arda en fazla iki `get` gönderebilir (önce private kol, sonra public olan); uzak bir deponun gecikme beklentilerini buna göre belirleyin. Özel bir depo açık bir `partition` **gerektirir**.
* `partition`: paylaşımlı bir depo içinde bir principal'ın `"private"` girdilerinin başka birine sunulmasını engelleyen yetkilendirme bağlamı etiketi.
* `target_id`: özel aktarımlar ve süreç içi sunucular için açık sunucu kimliği (aşağıda).
* `default_ttl_ms`: `ttlMs` ipucu taşımayan sonuçlara uygulanan TTL. Varsayılan `0`, ipucu taşımayan sonuçları önbelleğe almadan bırakır.
* `share_public`: sunucunun `"public"` olarak bildirdiği girdileri bölümler arasında sunar (aşağıda). Varsayılan olarak kapalıdır.
* `clock`: epoch saniyesi cinsinden duvar saati kaynağı. Yukarıdaki örnekte olduğu gibi bir tane enjekte edin; böylece süre dolumu testlerinde uyumaya gerek kalmaz.

!!! warning "Partition = doğrulanmış principal"
    `partition`'ı, doğrulanmış bir token'ın subject'i gibi **doğrulanmış bir kimlik bilgisinden** türetin. Onu asla istekle gelen veriden türetmeyin, sunucu URL'sinden de asla (sunucu kimliği ayrı bir anahtar eksenidir). SDK kendi kimlik doğrulaması olmayan bir kütüphanedir: güven çıpası `CacheConfig`'i kim oluşturuyorsa odur; bu da kiracı değil, dağıtımdır. Çok kiracılı bir ağ geçidi, kimliği doğrulanmış her principal için bir `CacheConfig` üretir.

    Bölüm ayrıca `Client`'ın ömrü boyunca sabittir. Bağlantının yetkilendirme bağlamı oturum ortasında değişirse (örneğin farklı bir principal olarak yeniden kimlik doğrulama), önbellek bunu takip etmez; yeni principal için yeni bir `Client` oluşturun.

Önbellek anahtarları ayrıca **sunucunun kimliğini** de taşır: bağlandığınız URL dizesi, varsa `user:pass@` kullanıcı bilgisi çıkarılmış ve bunun dışında bayt bayt aynı hâliyle. Büyük/küçük harf katlama yok, sorgu yeniden sıralama yok, sondaki eğik çizgi temizliği yok. Az normalleştirmek yalnızca paylaşımdan ödün verir, aşırı normalleştirmek ise iki kiracıyı birleştirebilir (`?tenant=a` ve `?tenant=b`); bu yüzden yüzeysel olarak farklı URL'ler girdi paylaşmaz, o kadar. URL olmadığında (süreç içi bir sunucu ya da bir `Transport` örneği) istemci bunun yerine örnek başına rastgele bir kimlik alır; sunucuya ad vermek için `CacheConfig.target_id`'yi ayarlayın (özel bir depoyla bu zorunludur ve oluşturma bunu söyler). Kimlik, anahtar malzemesine girmeden önce sha256 ile özetlenir; dolayısıyla sorgu dizesinde sır taşıyan bir URL depo anahtarlarında asla görünmez. Özet öncesi hâlini siz de loglamayın.

!!! warning "`share_public` sunucuya tüm filo genelinde güvenir"
    Varsayılan olarak `"public"` girdiler bile kendi bölümlerinde kalır. `share_public=True`, sunucunun `cacheScope: "public"` olarak işaretlediği girdileri depoyu kullanan **her** bölüme sunar; sunucunun sınıflandırmasına hepsi adına güvenir. Kiracıya özgü veriye (hata ya da kötü niyet sonucu) `"public"` damgası vuran bir sunucu, o zaman bir kiracının yanıtını diğerlerine sızdırır. Bayrak bilerek yalnızca oluşturucu düzeyindedir: çağrı başına `cache_mode` önbelleklemeyi daraltabilir, ama çağrı başına hiçbir şey paylaşımı genişletemez.

### Önbelleğin asla yapmadıkları {#what-the-cache-never-does}

* **Oturum katmanındaki çağrılar onu atlar.** `client.session.list_tools()` ve benzerleri her zaman turu atar; önbellek `Client` fiillerinde yaşar.
* **`server/discover` bunun dışında kalır.** Keşif sonucu bir kez, bağlanırken teslim edilir ve `ttlMs` taşısa bile asla yanıt önbelleğine girmez. Yeniden bağlanma yoklamasını atlamak için birini kendiniz kalıcı olarak saklarsanız ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), tazeliğinin takibi size kalır: `DiscoverResult` tam da bu amaçla, zaten ayrıştırılmış `ttl_ms` ve `cache_scope` alanlarını taşır.
* **Devam sayfaları asla önbelleğe alınmaz.** Yalnızca imleçsiz çağrılar katılır. Süresi dolmuş bir imleç nedeniyle reddedilen bir devam sayfası ise önbellekteki listeyi *çıkarır*, çünkü liste onun altında değişmiştir.
* **Çok turlu (multi-round-trip) okumalar asla önbelleğe alınmaz.** `input_responses`/`request_state` ile tohumlanan ya da girdi turları üzerinden çözümlenen bir `read_resource` asla önbelleğe girmez (belirtimde bir MUST).
* **Bildirimle çıkarma için bildirim gerekir.** Çıkarma ancak aktarımın teslimi kadar iyidir ve modern süreç içi yol (varsayılan `mode="auto"` ile `Client(server)`) bugün bağımsız bildirimleri teslim etmez.
* **Çıkarma anlık değil, er geç gerçekleşir.** Ağ yolundan gelen bildirimler ayrı başlatılan görevlerden dağıtılır; bu yüzden bir bildirimin gelişiyle yarışan bir çağrıya çıkarma öncesi girdi bir kez daha sunulabilir. Pencere dağıtım gecikmesiyle sınırlıdır ve çıkarma yine de gerçekleşir.
* **stale-if-error yok.** Süresi dolmuş bir girdi, yeniden getirme başarısız oldu diye asla sunulmaz; hata yayılır.
* **Erken yeniden getirme yok.** Saklanan bir girdi TTL'si dolana kadar sunulur ve ondan sonraki ilk çağrı turun bedelini öder; arka planda hiçbir şey yenilenmez.
* **Birleştirme yok.** Eşzamanlı iki özdeş çağrı iki getirme demektir.
* **24 saati aşan TTL yok.** Daha büyük bir `ttlMs`, ister sunucudan gelsin ister yapılandırılmış olsun, saklanırken kırpılır (`mcp.client.caching.MAX_TTL_MS`); bu da ipucu ne kadar cömert olursa olsun herhangi bir girdinin ne kadar süre sunulabileceğini sınırlar.
* **Paylaşımlı bir depoda** istemciler birbirleriyle yarışır. Her istemci, bir çıkarma yoldaki getirmeyi geçtiğinde kendi yazmasını düşürür; ancak *komşu kiracı* bir istemci, hiç görmediği bir çıkarmanın kaldırdığı bir girdiyi yine de geri yazabilir. Bu yarış takibinin kendisi de sınırlıdır: izlenen 4096 anahtarı geçince önce en eski anahtarın koruması düşürülür. Her iki pencere de kabul edilmiştir ve yukarıdaki TTL üst sınırıyla kapatılır.
* **Protokol nesilleri arasında sunum yok.** Girdiler anlaşılan protokol sürümüyle kapsamlanır: paylaşımlı kalıcı bir depoda bir oturum, farklı bir anlaşılan sürüm altında yazılmış bir girdiyi asla sunmaz (aynı liste nesle göre gerçekten farklıdır, çünkü SDK eski oturumlar için 2026 alanlarını çıkarır). Çıkarma da aynı şekilde yalnızca geçerli neslin girdilerine dokunur; başka bir neslin girdileri TTL ile kendiliğinden eskiyip gider.

### İpuçlarını kendiniz okuma {#reading-the-hints-yourself}

Yerleşik önbelleğin üzerine (ya da yerine) kendi takibinizi katmanlamak isterseniz, ipuçları her önbelleğe alınabilir sonuçta ayrıca düz alanlar olarak da bulunur (`result.ttl_ms` ve `result.cache_scope`, zaten ayrıştırılmış).

**Daha eski bir sunucuya** karşı (2026 öncesi protokol) alanlar iletilen veride yoktur, o kadar; modeller de ihtiyatlı varsayılanlarını gösterir: `ttl_ms == 0` ve `cache_scope == "private"`, bayat ve paylaşılmamış; hiçbir şey beyan etmemiş bir sunucu için doğru varsayım. Önbellek eski nesil bir oturumu aynı şekilde ele alır: orada ipuçlarına asla bakılmaz (iletilen veride hangi anahtarlar görünürse görünsün), yalnızca `default_ttl_ms` uygulanır ve onun varsayılanı `0` hiçbir şeyi önbelleğe almaz; böylece 2026 öncesi bir bağlantı tam olarak önbellek var olmadan önceki gibi davranır. "Sunucu 0 dedi" ile "sunucu hiçbir şey demedi" arasında ayrım yapmanız gerekiyorsa `"ttl_ms" in result.model_fields_set` ifadesini kontrol edin: yalnızca alan gerçekten geldiğinde ayarlıdır.

## Daha eski istemciler {#older-clients}

2026 öncesi protokol sürümlerindeki istemciler iki alanı da asla görmez; SDK bu bağlantılar için onları serileştirme sırasında çıkarır. İpuçlarınızı bir kez yapılandırın; sürüme özgü yazılacak hiçbir şey yok.

## Özet {#recap}

* Altı yöntem `ttlMs`/`cacheScope` taşır; SDK bunları varsayılan olarak `0`/`"private"` yapar: bayat ve paylaşılmamış, her zaman güvenli.
* Oluşturma sırasında `cache_hints={method: CacheHint(...)}` (hem `MCPServer` hem `Server`) yöntem başına sunucu genelinde değerler ayarlar.
* Alanları sonucunda ayarlayan bir işleyici eşlemeyi alan bazında geçersiz kılar.
* `"public"`, sonucun her çağıran için aynı olduğuna dair bir sözdür. Erişim denetimi değildir.
* `Client` ipuçlarına otomatik olarak uyar: yanıt önbelleği varsayılan olarak açıktır, yeniden getirmek yerine taze girdileri sunar ve ipucu sağlamayan sunucular (ya da oturumlar) için hiçbir şeyi önbelleğe almaz.
* Çağrı başına `cache_mode="refresh"` yeniden getirir, `"bypass"` önbelleği atlar; oluşturma sırasında `cache=None` onu tamamen kapatır.
