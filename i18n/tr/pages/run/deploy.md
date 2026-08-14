---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# Dağıtım ve ölçekleme {#deploy-scale}

Sunucunuz çalışıyor. Şimdi ona gerçek bir ana bilgisayar adı ve arkasında birden fazla worker gerekiyor.

Bunların neredeyse hiçbiri MCP'nin işi değil. ASGI sunucusunu, süreç yöneticisini, yük dengeleyiciyi siz getirirsiniz. Bu sayfada olan, gerçekten MCP'nin işi *olan* şeylerin kısa listesi: her dağıtımın önünde duran tek bir ayar ve "birden fazla worker" ifadesinin SDK'nın davranışını değiştirdiği iki yer.

## Her şeyden önce: Host izin listesi {#before-anything-else-the-host-allowlist}

`streamable_http_app()` hangi ana bilgisayar adının arkasında sunulacağını bilemez, bu yüzden en güvenli yanıtı varsayar: localhost. `transport_security=` verilmediğinde uygulama **DNS-rebinding korumasını** açar ve bir isteği yalnızca `Host` başlığı `127.0.0.1:<port>`, `localhost:<port>` veya `[::1]:<port>` ise kabul eder. `Origin` başlığı varsa, aynısının `http://` biçimi olmak zorundadır. Kendi makinenizde bu tam olarak doğru davranıştır: kötü niyetli bir web sayfasının, `127.0.0.1`'e yeniden bağladığı bir DNS adı üzerinden yerel sunucunuzu yönetmesini engeller.

Gerçek bir ana bilgisayar adının arkasına dağıtıldığında, aynı varsayılan siz aksini söyleyene kadar **her isteği** reddeder. Denetim, MCP'ye benzeyen herhangi bir şey çalışmadan önce yapılır; yani sizin yazdığınız hiçbir şeye danışılmaz bile:

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

Çözüm `transport_security=`. Gerçekten sunduğunuz şeyi izin listesine alın:

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* `allowed_hosts` girdileri tam eşleşen dizgelerdir: `"mcp.example.com"` yalın bir `Host` başlığıyla, `"mcp.example.com:*"` ise herhangi bir portla eşleşir. İkisini de listeleyin.
* `allowed_origins` yalnızca tarayıcılar için önemlidir, çünkü başka hiçbir şey `Origin` göndermez. **[Mevcut bir uygulamaya ekleme](asgi.md)** sayfasındaki CORS yapılandırmasının sunucu tarafındaki ikizidir.
* `Host` başlığını zaten denetleyen bir ters vekil sunucunun arkasında, dürüst yapılandırma denetimi kapatmaktır: `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.
* localhost dışında bir `host=` geçirmek (örneğin `host="mcp.example.com"`) o ana bilgisayar adını izin listesine **almaz**. Yalnızca localhost varsayılanının korumayı devreye sokmasını engeller; bu da her Host ve Origin'in kabul edilmesi demektir. Bunun yerine ne demek istediğinizi `transport_security=` ile söyleyin.

!!! check
    `transport_security=security` argümanını silin ve uygulamayı yine de dağıtın. Başlar, `/mcp`
    yönlendirilir ve her istek (düz bir `curl` dahil) şöyle döner:

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    Bu sözcükleri istemci tarafında bulamazsınız. `421`, bir JSON-RPC hatası değil, düz metin bir
    HTTP yanıtıdır; bu yüzden MCP istemcisi genel bir aktarım hatası fırlatır. Beğenmediği ana
    bilgisayar adı yalnızca **sunucunun** log'unda, tek bir uyarı olarak görünür. Yeni dağıtılmış ve
    her bağlantıyı reddeden bir sunucu, aksi kanıtlanana kadar bir Host izin listesi sorunudur.
    **[Sorun giderme](../troubleshooting.md)** de buradan başlar.

## Worker'lar ve kimin yapışkan olması gerektiği {#workers-and-who-has-to-be-sticky}

Ana bilgisayar adı yanıt vermeye başladıktan sonra, arkasına birden fazla worker koyun. Bunun için SDK'da bir ayar yoktur; bir Starlette uygulamasını, herhangi bir ASGI uygulamasını ölçeklediğiniz gibi ölçeklersiniz: nesneyi, fork etmeyi bilen bir şeye verirsiniz:

```console
uvicorn server:app --workers 4
```

Dört süreç, tek bir soket. Ve şimdi her dağıtımın yanıtlaması gereken soru: **bir isteğin, bir öncekini gören worker'a ulaşması gerekiyor mu?**

**2026-07-28** protokolünü konuşan bir istemci için, hayır. Modern bir istek, kendi içinde eksiksiz tek bir POST'tur: önünde `initialize` el sıkışması yok, yanıtta `Mcp-Session-Id` yok, ikinci bir isteğin geri *döneceği* hiçbir şey yok. Herhangi bir worker'a yönlendirin.

Bu, açtığınız bir kip değildir. `stateless_http=True` öyle olmalıymış gibi görünür, ancak aktarım `MCP-Protocol-Version` istek başlığına göre yönlendirme yapar, modern bir isteği modern işleyiciye verir ve **döner**. `stateless_http`'yi okuyan satır bu dönüşten *sonra* gelir. Mesele bayrağın 2026-07-28 yolunda yok sayılması değil; o satıra hiç ulaşılmamasıdır. `stateless_http` yalnızca **eski nesil** bacak için bir ayardır; modern yol ise yapısı gereği oturumsuzdur.

Spesifikasyonun 2025-11-25 veya daha eski bir sürümündeki eski nesil bir istemci için yanıt o bayrağa bağlıdır:

| İstemcinin protokol sürümü | Oturum | Yük dengeleyicinin yapması gereken |
| --- | --- | --- |
| **2026-07-28** | Yok. `Mcp-Session-Id` hiçbir zaman ayarlanmaz. | Hiçbir şey. Herhangi bir worker herhangi bir isteğe hizmet verir. |
| **2025-11-25 ve öncesi** (varsayılan) | `Mcp-Session-Id`, tek bir worker'ın belleğinde tutulur. | **Yapışkan oturumlar.** Farklı bir worker'a ulaşan bir devam isteği `404` *"Session not found"* alır. |
| **2025-11-25 ve öncesi**, `stateless_http=True` ile | Yok. | Hiçbir şey. Bedeli, sunucudan istemciye geri kanal (back-channel) (örnekleme (sampling), itmeli elicitation, `roots/list`) ve devam ettirilebilirliktir. |

Yapışkan oturumlar ve eski nesil bacağın bedeli kendi sayfasında: **[Eski nesil istemcilere hizmet verme](legacy-clients.md)**; iki neslin kendisi ise **[Protokol sürümleri](../protocol-versions.md)** sayfasında. Burada önemli olan yanıtın biçimi: *2026-07-28'de zaten durumsuzsunuz ve yapılandırılacak hiçbir şey yok.*

Sayfanın geri kalanı, durumsuz olmanın size **sağlamadığı** iki şey.

## Worker'lar arasında `requestState` {#requeststate-across-workers}

**[Çok turlu](../handlers/multi-round-trip.md)** (multi-round-trip) bir araç, istemcinin gidip alması gereken bir şeye (bir onay, bir seçim, bir kimlik bilgisi) ihtiyaç duyar; bu yüzden bir yanıt yerine bir soru döndürür ve yeniden denemede işini bitirir. İki tur arasında istemci, sunucunun bastığı opak bir `request_state` token'ı tutar. Yeniden denemede sunucunun o token'ı yeniden açması gerekir.

*Hangi anahtarla mühürlenmiş?* Varsayılan olarak, sunucunun oluşturulurken `os.urandom(32)` ile ürettiği bir anahtarla. `--workers 4` altında bu, dört süreçte dört oluşturma demektir: dört farklı anahtar, hiçbir yere yazılmamış, hiç paylaşılmamış, yeniden başlatmada kaybolan.

İşte hiçbir şey yapılandırmayan bir sunucuda, harekete geçmeden önce soran bir araç:

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

İlk tur worker A'ya ulaşır. Worker A, `refund:120` değerini **kendi** anahtarıyla mühürler ve token'ı döndürür. İstemci soruyu bir insanın önüne koyar, evet yanıtını alır ve yeniden dener. Yeniden deneme yepyeni bir HTTP isteğidir.

!!! check
    O yeniden denemenin worker B'ye ulaşmasına izin verin. B, kendisinin basmadığı bir token'ın
    mührünü açmaya çalışır, açamaz ve turun tamamını reddeder. `refund` hiç çağrılmaz; istemci bir
    JSON-RPC hatası alır:

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    Bu mesaj **sabittir**. Süresi dolmuş, kurcalanmış, farklı argümanlara karşı yeniden oynatılmış
    ya da (gerçek bir dağıtımda açık ara en yaygın neden) kardeş bir worker tarafından mühürlenmiş
    olsun: istemciye her seferinde aynı şey söylenir, böylece iletilen veri hangi denetimin başarısız
    olduğunu asla açığa vurmaz. Gerçek neden, sunucunun log'unda tek bir `WARNING` satırıdır:

    ```text
    requestState rejected on tools/call: unknown key
    ```

    Tek worker'la çalışıp ikide *ara sıra* başarısız olmaya başlayan çok turlu bir araç budur. İki
    turun yine de aynı sürece ulaşması gerekir; bu yüzden tam olarak yük dengeleyicinizin onları
    ayırdığı sıklıkta başarısız olur.

İki tur iki bağımsız HTTP isteğidir ve onları birbirinden ayıran birçok sıradan şey vardır: istek başına dengeleyen bir vekil sunucu, arada kopan bir bağlantı, bir dağıtım ya da yeniden başlatma, `request_state`'i kalıcı olarak saklamış ve bambaşka bir süreçten devam eden bir istemci (**[Döngüyü kendiniz yürütme](../handlers/multi-round-trip.md#driving-the-loop-yourself)**). Bunların her biri "farklı bir worker" demektir.

Çözüm tek bir argüman. Ancak **iki** yarısı var.

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** herkesin bulduğu yarıdır. Her örneğe aynı gizli anahtarı (en az 32 bayt) verin; böylece her örnek, herhangi bir kardeşinin bastığı şeyin mührünü açabilir. `keys[0]` mühürler, listedeki her anahtar mühür açar; bu döndürme halkasıdır. Onu kesinti olmadan nasıl çevireceğiniz **[Anahtarları döndürme](../handlers/multi-round-trip.md#rotating-keys)** bölümünde.
* **Sunucunun adı** neredeyse kimsenin bulamadığı yarıdır ve anahtarı paylaştıktan sonra örnekler arası yeniden denemelerin hâlâ başarısız olmasının nedenidir. Her mühürlü token, sunucunun `name` değerini bir **audience claim** olarak taşır ve dönüşte katı biçimde denetlenir. Aynı koddan oluşturulmuş iki örneğin adı aynıdır ve bunu hiç fark etmezler. Onlara farklı adlar verin (`MCPServer(f"billing-{POD}")` iyi bir gözlemlenebilirlik alışkanlığı gibi okunur) ve her örnekler arası yeniden deneme, anahtar paylaşılmış olsun olmasın, tam olarak yukarıdaki gibi reddedilir. Log `unknown key` yerine `audience` der; istemci aradaki farkı anlayamaz.

Gizli anahtarı bir kez basın ve her örneğe aynı değeri verin. 32 bayttan az geçirirseniz SDK'nın kendi hata mesajının çalıştırmanızı söylediği komut budur:

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "Aynı anahtarlar *ve* aynı ad"
    Çok örnekli bir dağıtım ikisini de paylaşmak zorundadır. Örnek başına adlar sizin için
    vazgeçilmezse, filoya bunun yerine tek bir açık audience verin: `RequestStateSecurity(keys=[...], audience="billing")`.
    Böylece her örnek, adı ne olursa olsun `"billing"` altında basar ve kabul eder.

Mühürle ilgili geri kalan her şey **[`requestState`'i koruma](../handlers/multi-round-trip.md#protecting-requeststate)** bölümünde: neyi bağladığı, tur başına `ttl` (varsayılan olarak 600 saniye), kendi codec'inizi getirme, yapılandırılmamış varsayılanın `stdio` üzerinde neden tam olarak doğru olduğu. Bu sayfanın tüm katkısı iki maddelik bir denetim listesi: *aynı anahtarlar, aynı ad.*

!!! info
    Hiç `InputRequiredResult` yazmamış olsanız bile bu yoldasınız. Parametreleri `Resolve(...)`
    kullanan bir araç (**[Bağımlılıklar](../handlers/dependencies.md)**) çok turlu bir araçtır ve
    SDK onun `request_state`'ini onun adına basar ve mühürler. Aynı varsayılan anahtar, worker'lar
    arasında aynı başarısızlık, aynı çözüm.

## Replikalar arasında değişiklik bildirimleri {#change-notifications-across-replicas}

Bir istemcinin `subscriptions/listen` akışı uzun ömürlü tek bir yanıttır; bu yüzden tüm ömrü boyunca tek bir replikaya bağlı kalır. **Farklı** bir replikada yayımlanan bir `ctx.notify_resource_updated(...)` çağrısının ona ulaşması gerekir.

İkisi arasındaki bağlantı noktası `SubscriptionBus`'tır. Bir sunucuya hangi bus'ı verirseniz, her yayının gittiği ve her açık akışın dinlediği bus odur; bu yüzden her replikaya aynı bus'ı verin:

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

Dağıtım (fan-out) tarafında hiçbir şey, bir akışın hangi sunucu nesnesine bağlı olduğuyla ilgilenmez. Tek bir `InMemorySubscriptionBus` tutan iki sunucu zaten böyle davranır: birinde bir listen akışı açın, diğerinde `edit_note`'u çağırın ve akış bundan haberdar olur. O bellek içi bus yalnızca tek bir süreç içindeki sunucu nesnelerini kapsar; bu da onu dağıtım değil, model yapar:

* Gerçek süreçler arasında **SDK size yardımcı olabilecek hiçbir bus sunmaz.** `SubscriptionBus`, kendi pub/sub altyapınız (Redis, NATS, zaten çalıştırdığınız her neyse) üzerinde gerçeklediğiniz ve `MCPServer(subscriptions=...)` olarak geçirdiğiniz iki metotlu bir `Protocol`'dür (`publish` ve `subscribe`). Taslak ve sözleşme **[Abonelikler](../handlers/subscriptions.md#scaling-past-one-process)** sayfasında.
* Bus dört küçük tipli olay taşır, asla JSON-RPC taşımaz. Onaylama, filtreleme ve akış yaşam döngüsü SDK'da kalır; bu yüzden bus'ınız protokolü bozamaz, yalnızca olayları süreçler arasında taşıyabilir.
* Akışlar devam ettirilebilir **değildir** ve olaylar yeniden **oynatılmaz**. Bir replikayı kaybetmek akışlarını düşürür; istemciler yeniden dinler ve yeniden getirir. Paylaşılacak bir olay deposu ve yapılandırılacak başka bir şey yoktur. Ölçeklemenin gerçekten yalnızca aynısının fazlası olduğu tek yer burası.

## SDK'nın size vermedikleri {#what-the-sdk-does-not-give-you}

Bir `MCPServer` bir uygulama sunucusu değil, bir protokol gerçeklemesidir. Bundan sonra aramaya çıkacağınız dağıtım ayarları bilerek eksiktir:

* **`workers=` yok.** `mcp.run("streamable-http")` tam olarak bir uvicorn süreci başlatır ve başlatacağı tek şey de odur. Çoklu süreç, `streamable_http_app()`'in ASGI'yi zaten neyle dağıtıyorsanız ona verilmesidir: `uvicorn --workers`, gunicorn, platformunuzun süreç yöneticisi. Bu sayfa bilerek onların hiçbiri için bir öğretici değildir; kendi belgeleri, buradaki bir kopyanın olacağından daha iyidir.
* **Sağlık denetimi rotası yok.** `@mcp.custom_route("/health", methods=["GET"])` yanıtın tamamıdır ve sunucunun geri kalanı kimlik doğrulamalı olsa bile bu rota asla kimlik doğrulaması yapmaz. Bu, bir canlılık yoklaması için doğru, özel olan herhangi bir şey için yanlıştır. **[Mevcut bir uygulamaya ekleme](asgi.md#custom-routes)** bir örnek gösterir.
* **Üretim ayarları nesnesi yok.** `MCPServer` üzerinde zaman aşımlarını, TLS'yi, zarif kapanmayı ya da bağlantı sınırlarını yazabileceğiniz bir yer yoktur, çünkü bunların hiçbiri onun işi değildir. ASGI sunucunuza aittirler ve onları orada yapılandırırsınız. Yapıcının *aldığı* bir avuç ayar **[Sunucunuzu çalıştırma](index.md)** sayfasında.
* **Sunulan bir `EventStore` yok, 2026-07-28'de buna gerek de yok.** Devam ettirilebilirlik, eski nesil durumlu bacağın bir özelliğidir; modern bir alışveriş tek bir POST, tek bir yanıt ve devam ettirilecek hiçbir şeydir.

## Özet {#recap}

* Varsayılan olarak uygulama yalnızca localhost'a gönderilen istekleri yanıtlar. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` yayına çıkış kapısıdır: onu geçirene kadar gerçek bir ana bilgisayar adının arkasındaki her istek bir `421`'dir ve nedeni yalnızca sunucunun log'undadır.
* 2026-07-28'de oturum yoktur ve bir yük dengeleyicinin yapışacağı hiçbir şey yoktur. `stateless_http=True` yalnızca eski nesle ait bir ayardır, çünkü modern bir istek o bayrak hiç okunmadan yönlendirilir ve yanıtlanır.
* Varsayılan `requestState` anahtarı, süreç başına basılan `os.urandom(32)`'dir. Farklı bir worker'a ulaşan çok turlu bir yeniden deneme `-32602` *"Invalid or expired requestState"* ile başarısız olur.
* Çözüm `RequestStateSecurity(keys=[...])` **ve** her örnekte aynı sunucu adıdır. Ad, token'ın varsayılan audience claim'idir. Aynı anahtarlar, aynı ad.
* Değişiklik bildirimleri replikalar arasında paylaşılan tek bir `SubscriptionBus` üzerinden geçer. SDK'nın tek gerçeklemesi süreç içidir; kendi pub/sub'ınız üzerindeki iki metotlu `Protocol`'ü yazmak size düşer.
* `workers=` yok, sağlık rotası yok, üretim ayarları nesnesi yok. Kendi ASGI sunucunuzu getirin.

Gerçek bir ana bilgisayar adının önünde gereken diğer şey bir token: **[Yetkilendirme](authorization.md)**.
