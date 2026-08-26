---
translation:
  sections: [3d1663c18edc824c, d4fd37009a13f03d, af9f398a5a8b679a, 470c2dd144294d69, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# Eski nesil istemcilere hizmet verme {#serving-legacy-clients}

MCP'nin iki protokol nesli var: `2025-11-25` spesifikasyon sürümüne kadar uzanan `initialize` el sıkışması nesli ve modern nesil olan `2026-07-28`. Bu ayrımın kendisini anlatan sayfa **[Protokol sürümleri](../protocol-versions.md)**.

Bu sayfa o ayrımın sunucu tarafını ele alır ve yanıt tek bir cümleye sığar: **zaten dağıttığınız `streamable_http_app()` her ikisine de hizmet verir.**

SDK her isteği `MCP-Protocol-Version` başlığına göre yönlendirir. `2026-07-28` belirten bir istek modern işleyiciye gider. El sıkışması neslinden bir sürüm belirten ya da hiç başlık taşımayan bir istek (2026 öncesi bir istemcinin `initialize` isteği tam da böyle gelir), o istemcilerin beklediği aktarıma gider: `initialize` el sıkışması, oturumlar, hepsi. Bu, istek başına, kodunuzdan önce ve o tek uygulama üzerinde olur.

Yani eski nesil istemci, *ona göre* bir şey inşa ettiğiniz bir hedef değil. Zaten yazdığınız sunucuya *bağlanan* bir şey. Hiçbir şey yapılandırmazsınız.

!!! note
    Kelimenin tam anlamıyla hiçbir şey. `legacy=` diye bir seçenek yok, sürüm izin listesi yok,
    bir nesli reddetmenin ya da devre dışı bırakmanın yolu yok: ne `streamable_http_app()`
    üzerinde, ne `run()` üzerinde, ne de oturum yöneticisinde. İki nesil de her zaman açık. O
    imzada nesle özgü bir anahtara en yakın şey `stateless_http`, ve bu sayfanın büyük kısmı da
    ondan ibaret.

## Tek işleyici, iki nesil {#one-handler-both-eras}

İşte kullanıcıya bir şey sorması gereken bir araç ve onu çağıran her iki nesilden istemci:

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve`, modelin sağlamadığı tek bir şeye ihtiyaç duyar: kaç kopya. Bir araç bunu `Annotated[..., Resolve(ask_quantity)]` ile bildirir (ayrıntıların tamamı **[Bağımlılıklar](../handlers/dependencies.md)** sayfasında). `reserve` içinde hiçbir şey bir sürüm adı vermez, bir yetenek kontrol etmez ya da dallanmaz.

İki istemci **aynı anda**, aynı `mcp` nesnesi üzerinde açıktır. `mode="legacy"`, `initialize` el sıkışmasını çalıştırır: 2026 öncesi bir istemcinin açtığı bağlantının ta kendisi. Diğeri varsayılanı alır ve `2026-07-28` sürümünde karar kılar.

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

Aynı sunucu, aynı işleyici, aynı yanıt. Özelliğin tamamı bu.

*Nasıl* olduğu üzerinde durmaya değer, çünkü iki istemciye aynı soru bambaşka iki yoldan soruldu. `2026-07-28` bağlantısında sunucunun istek gönderebileceği bir kanal yoktur; bu yüzden `Resolve` soruyu araç sonucunun içinde döndürdü ve istemci çağrıyı yanıtla birlikte yeniden denedi (**[Çok turlu istekler (multi-round-trip)](../handlers/multi-round-trip.md)**). `2025-11-25` bağlantısında böyle bir şey yoktur; orada `Resolve`, çağrının ortasında canlı bir `elicitation/create` isteği gönderdi ve bekledi. İkisini de siz yazmadınız. `Resolve` bağlantının anlaşılan sürümünü okur ve seçer; araç gövdeniz her iki durumda da bir `AcceptedElicitation` görür.

!!! tip
    Nesiller arası bu taşınabilirlik, `Resolve`'un üzerine inşa edilecek API olmasının
    *nedenidir*. Eski kardeşi `ctx.elicit()`
    (**[Elicitation (kullanıcıdan bilgi isteme)](../handlers/elicitation.md)**) yalnızca
    `elicitation/create` gönderir; dolayısıyla yalnızca eski nesil bir bağlantıda çalışır.
    `2026-07-28` bağlantısında çağrı başarısız olur. Bir araç hâlâ onu kullanıyorsa çözüm bir
    sürüm kontrolü değil, yukarıda gördüğünüzdür.

## Eski nesil bir oturumun size maliyeti {#what-a-legacy-session-costs-you}

Yönlendirme bedava. Oturum değil.

`2026-07-28` bağlantısı **oturumsuzdur**: her istek tek başına durur ve modern işleyici asla `Mcp-Session-Id` vermez. Eski nesil bağlantı bunun tam tersidir. 2026 öncesi bir istemci `initialize` gönderdiği anda SDK bir `Mcp-Session-Id` üretir, onu bir yanıt başlığında döndürür ve istemcinin sonraki isteklerinin bulabilmesi için arkasında canlı bir kayıt tutar: anlaşılan sürüm, açık akışlar, oturumu yürüten bir arka plan görevi.

Bu kayıt **süreç içi, düz bir `dict`'tir**. Dağıtık bir oturum deposu yoktur ve bir tane takmanın yolu da yoktur.

Tek worker'da bu görünmez. İki worker'da ise sorunun tamamı budur: `Mcp-Session-Id` taşıyan ve onu üretmemiş bir worker'a düşen bir istek o dict'te hiçbir şey bulamaz ve yanıt araç sonucu değil, bir `404` (`Session not found`) olur. Yani birden fazla worker çalıştırdığınız anda **eski nesil istemciler yapışkan yönlendirmeye (sticky routing) ihtiyaç duyar**: bir oturumdaki her istek, onu başlatan sürece ulaşmak zorundadır. Modern istemcilerin buna hiç ihtiyacı olmaz; yapışacakları bir oturumları yoktur. Yapışkanlığı ve bunlardan birden fazlasını çalıştırmaya dair geri kalan her şeyi **[Dağıtım ve ölçekleme](deploy.md)** sayfası ele alır.

!!! warning
    `event_store=` çözüm gibi görünür ama değildir. O bir oturum deposu değil,
    **devam ettirilebilirliktir** (kaçırılan SSE olaylarını *aynı* oturuma yeniden bağlanan bir
    istemciye yeniden oynatmak). Bir oturumu asla başka bir süreçten erişilebilir kılmaz.

## Tek ayar düğmesi: `stateless_http` {#the-one-knob-stateless_http}

Yapışkanlık ödemeyi reddettiğiniz bir bedelse, değiştirebileceğiniz tam olarak tek bir şey var.

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

Bu, sayfanın başındaki sunucuya tek bir anahtar sözcük eklenmiş hali. `stateless_http=True`, eski nesil kolun bunun yerine istek başına, kullan-at bir oturum kurmasını sağlar: `Mcp-Session-Id` verilmez, istekler arasında hiçbir şey hatırlanmaz; böylece herhangi bir worker herhangi bir isteğe hizmet verebilir ve yük dengeleyici canı ne isterse onu yapabilir.

Onunla ilgili iki şey, ne yaptığından daha önemli.

**Yalnızca eski nesil kola dokunur.** İstekler, `stateless_http` okunmadan *önce* sürüm başlığına göre yönlendirilir; bu yüzden modern yol onu hiç görmez. `2026-07-28` bağlantısı zaten oturumsuzdur ve her iki değerde de tıpatıp aynıdır.

**O kolda sunucudan istemciye giden her iki kanala da mal olur.** Tek bir `POST` boyunca yaşayan bir oturumun, sunucunun istek itebileceği bir akışı da bildirim itebileceği bağımsız bir akışı da yoktur. Sunucunun başlattığı her istek `NoBackChannelError` fırlatır: `ctx.elicit()`, emekliye ayrılmış örnekleme (sampling) ve kök dizinler (roots) çağrıları (**[Kullanım dışı özellikler](../deprecated.md)**) ve evet, *eski nesil* bir istemciye sorusunu soran `Resolve` da. Bildirimler bir hata bile almaz; sessizce düşürülür.

!!! note
    `json_response=True` o düğme değildir ama aynı bedelin yarısını *her* eski nesil oturumda
    öder: tek bir JSON gövdesiyle yanıtlanan bir `POST`'un istek kapsamlı kanal için akışı
    yoktur; bu yüzden istek ortasındaki bir `ctx.elicit()` aynı `NoBackChannelError` istisnasını
    fırlatır ve istekle ilişkili bildirimler düşürülür. Oturumun bağımsız akışına dokunulmaz:
    ilgisiz bildirimler gelmeye devam eder.

!!! check
    Yanlış olanı yapın. `reserve`, az önce iki istemciye de hizmet veren aracın ta kendisi. Onu
    `stateless_http=True` ile dağıtın, aynı iki istemciyi HTTP üzerinden bağlayın ve her birinden
    çağırın.

    Modern istemci hâlâ `Reserved 2 of 'Dune'.` alır. Modern kol değişmedi.

    Eski nesil istemcinin çağrısı, modelin okuyabileceği bir `is_error` sonucu olarak geri
    dönmez. İsteğin tamamı, üst düzey bir protokol hatası olarak başarısız olur:

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` sizi kurtarmadı. `2025-11-25` bağlantısında `elicitation/create` göndermek
    *zorundadır* ve ihtiyaç duyduğu kanal, `stateless_http=True`'nun elden çıkardığı şeyin ta
    kendisidir. Nesiller arası taşınabilir kod, geri kanala (back-channel) ihtiyaç duymayan kod
    demek değildir.

Yani bu gerçek bir ödünleşmedir ve yalnızca eski nesil kolda vardır: **oturumlu ve yapışkan, ya da durumsuz ve tek yönlü.** Araçlarınız hiçbir zaman istemciye geri çağrı yapmıyorsa `stateless_http=True` bedavadır ve almalısınız. Yapıyorlarsa oturumları koruyun ve yönlendirmeyi yapışkan tutun.

## Kodunuzun gerçekten çatallandığı yer {#where-your-code-actually-forks}

Neredeyse hiçbir yerde.

Araçlar, kaynaklar, prompt'lar, yapılandırılmış çıktı, ilerleme, hatalar: hiçbiri hangi neslin çağırdığını umursamaz. `initialize` el sıkışması, `Mcp-Session-Id`, bağımsız akış, bir oturumu bitiren `DELETE`: hepsinin sahibi SDK'dır ve bir işleyici bunların hiçbirini görmez. Etkileşimli girdi, nesillerin iletilen veride gerçekten ayrıştığı *tek* yerdir ve `Resolve` bunun sizin sorununuz olmaması için vardır: az önce tek bir aracın ikisine de hizmet verdiğini izlediniz.

Geriye tam olarak tek bir şey kalıyor, o da **değişiklik bildirimleri**; çünkü iki nesil farklı borulardan dinler:

* `2026-07-28` istemcisi bir `subscriptions/listen` akışı açar ve abonelik veri yolunu okur. `ctx.notify_resource_updated()` (ve `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`) oraya, ve *yalnızca* oraya yayımlar. Bunun sayfası **[Abonelikler](../handlers/subscriptions.md)**.
* Eski nesil bir istemci, oturumunun açık tuttuğu bağımsız akışı okur. `ctx.session.send_resource_updated()` (ve `send_tool_list_changed()` ile benzerleri) isteği taşıyan *bağlantıya* yazar: eski nesil bir oturum için bu, onun bağımsız akışıdır. Modern bir bağlantıda bunun yeri yoktur: HTTP üzerinde böyle bir kanal yoktur, stdio üzerinde ise dört değişiklik bildirimi türü yalnızca `subscriptions/listen` akışlarında taşınır; bu yüzden modern bir bağlantıda bildirim sessizce düşürülür.

HTTP üzerinde iki çağrı da diğer neslin istemcilerine ulaşmaz. Herkese haber vermek için ikisini de çağırın:

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

İki satır, `if` yok, sürüm kontrolü yok, ve işiniz bitti. Eski nesil bir istemci var diye bir işleyicinin farklı yaptığı şeylerin listesinin tamamı bu.

## Özet {#recap}

* Tek bir `streamable_http_app()` iki protokol nesline de hizmet verir. SDK her isteği `MCP-Protocol-Version` başlığına göre yönlendirir; yapılandırılacak bir şey ve aranacak bir nesil düğmesi yoktur.
* Eski nesil bir istemci size bir oturuma mal olur: arkasında dağıtık bir depo olmayan, süreç içi bir `Mcp-Session-Id` kaydı. Birden fazla worker **yapışkan yönlendirme** demektir; aksi halde yanlış worker `404 Session not found` yanıtını verir. Çoklu worker'a dair ayrıntıların tamamı **[Dağıtım ve ölçekleme](deploy.md)** sayfasında.
* Tek düğme `stateless_http=True`'dur ve **yalnızca eski nesil kolu etkiler**. Eski nesil istemciler için bedava yük dengelemeyi, o koldaki sunucudan istemciye giden her iki kanal pahasına satın alır: sunucunun başlattığı istekler `NoBackChannelError` fırlatır (istemcide `is_error` sonucu değil, üst düzey bir hata) ve bildirimler düşürülür.
* `2026-07-28` bağlantısı her durumda oturumsuzdur. `stateless_http` ona hiç dokunmaz.
* İşleyici kodunuz nesle göre tam olarak tek bir yerde çatallanır: değişiklik bildirimleri. `ctx.notify_*` `subscriptions/listen` istemcilerine ulaşır; `ctx.session.send_*` eski nesil oturumlara ulaşır. İkisini de çağırın.
* Geri kalan her şey (`Resolve` aracılığıyla kullanıcıdan girdi istemek dahil) tasarımı gereği nesiller arası taşınabilirdir. Modern olanı bir kez yazın.
