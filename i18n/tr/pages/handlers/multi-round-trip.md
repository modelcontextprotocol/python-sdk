---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# Çok turlu istekler {#multi-round-trip-requests}

Bazen bir araç işini tek turda bitiremez. Yalnızca kullanıcıda olan bir şeye ihtiyaç duyar: bir seçim, bir onay, bir kimlik bilgisi.

2026-07-28 öncesinde sunucu bunu **geri** çağırarak elde ederdi: asıl isteği işlemenin tam ortasında istemciye kendi isteğini, örneğin bir elicitation (kullanıcıdan bilgi isteme) ya da bir örnekleme (sampling) çağrısını açardı. 2026-07-28 spesifikasyonu bu geri kanalı (back-channel) emekliye ayırıyor.

Bunun yerine sunucu **döndürür**.

## Geri çağırmak yerine döndürme {#return-dont-call-back}

Sunucu `tools/call` isteğini `CallToolResult` yerine bir **`InputRequiredResult`** ile yanıtlar. İşi iki alanı yapar:

* **`input_requests`**: sunucunun hâlâ ihtiyaç duyduğu şeyler; anahtarları sunucunun seçtiği adlar olan bir dict. Her değer bir `ElicitRequest`, bir `CreateMessageRequest` ya da bir `ListRootsRequest` olur.
* **`request_state`**: opak bir token. İstemci yeniden denemede onu olduğu gibi geri yollar. Onu okuyan tek şey sunucunuzdur.

İstemci her isteği karşılar, ardından yanıtlarını `input_responses` içinde, token'ı da `request_state` içinde taşıyarak **aynı aracı yeniden** çağırır. Sunucunun eksiği artık tamamdır ve normal bir `CallToolResult` döndürür.

Protokolün tamamı bu. Her adım istemciden sunucuya giden sıradan bir istektir. Hiçbir şey ters yönde akmaz.

## Sunucu tarafı {#the-server-side}

`@mcp.tool()` üzerinde bunu elle kurmanız nadiren gerekir: kullanıcıya soran (`Elicit`), istemcinin LLM'inden örnekleme yapan (`Sample`) veya kök dizinlerini (roots) listeleyen (`ListRoots`) bir bağımlılık bildirin; SDK `InputRequiredResult`'ı sizin yerinize döndürür. Bu biçim **[Bağımlılıklar](dependencies.md)** sayfasının konusudur. İki biçim bir arada kullanılamaz: bir çağrının tek bir `input_responses`/`request_state` kanalı vardır, bu yüzden `Resolve(...)` parametreleri kullanan bir araç gövdesinden ayrıca `InputRequiredResult` döndüremez. Bildirilmiş bir `InputRequiredResult` dönüş türü kayıt sırasında reddedilir (`InvalidSignature`); bildirilmemiş olanı ise çağrıyı çalışma zamanında başarısız kılar. Elle kurulan biçim **düşük seviyeli** `Server`'dır; onun `on_call_tool` işleyicisi iki sonuç türünden herhangi birini döndürebilir:

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool`'un tür ipucu `-> CallToolResult | InputRequiredResult` şeklindedir. İkincisini döndürmek sunucu tarafı API'sinin tamamıdır.
* İlk çağrıda `params.input_responses` değeri `None`'dır; bu yüzden koruma koşulu devreye girer ve işleyici yanıtlamak yerine sorar.
* Yeniden denemede, istemcinin gönderdiği `ElicitResult`, sunucunun `input_requests` içinde kullandığı **aynı anahtarın** (`"region"`) altında durur.

O dosyadaki geri kalan her şey (açık `input_schema`, elle kurulan `CallToolResult`) sıradan düşük seviyeli `Server`'dır ve **[Düşük seviyeli Server](../advanced/low-level-server.md)** sayfasında anlatılır. Bu sayfa yalnızca ikinci dönüş türünü ekler.

## Araçların ötesi {#beyond-tools}

`tools/call` özel değildir: 2026-07-28 sürümünde bir sunucu `prompts/get` ve `resources/read` isteklerini de aynı şekilde yanıtlayabilir. `MCPServer` üzerinde bir `@mcp.prompt()` fonksiyonu (ya da bir `@mcp.resource()` **şablon** fonksiyonu) `InputRequiredResult`'ı kendisi döndürür ve yeniden denemenin yanıtlarını bağlamdan okur:

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* İlk tur `InputRequiredResult`'ı döndürür. Yeniden denemede `ctx.input_responses` yanıtları aynı anahtarlar altında tutar ve fonksiyon olağan sonucunu döndürür: burada prompt mesajları, bir şablon kaynak için kaynak içeriği.
* Ayarladığınız bir `request_state`, sunucudaki diğer her şey gibi, ağa çıkmadan önce mühürlenir ve geri geldiğinde doğrulanır; aşağıdaki **[`requestState`'i koruma](#protecting-requeststate)** bölümü mührün size ne sağladığını ve anahtarları ne zaman yapılandırmanız gerektiğini anlatır.
* Bağımlılık biçimi uymadığında bir `@mcp.tool()` fonksiyonu da sonucu aynı şekilde doğrudan döndürebilir.
* Statik `@mcp.resource()` fonksiyonları buna katılmaz: `Context` almazlar, dolayısıyla yeniden denemeyi hiçbir zaman okuyamazlar. Yalnızca şablon kaynaklar soru sorabilir.
* Aşağıdaki nesil kuralları aynen geçerlidir: 2026 öncesi bir oturumda `InputRequiredResult` döndürmek, uyarının anlattığı aynı `-32603` hatasıdır.

## İstemci tarafı {#the-client-side}

Döngüyü sizin yerinize `Client` çalıştırır.

Sunucunun isteyebileceği callback'leri (`elicitation_callback`, `sampling_callback`, `list_roots_callback`) kaydedin ve aracı çağırın. Bir `InputRequiredResult` geldiğinde `Client`, `input_requests` içindeki her girdiyi eşleşen callback'e yönlendirir, yanıtlar ve geri yollanan `request_state` ile yeniden dener ve bir `CallToolResult` dönene kadar devam eder:

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* Bu `elicitation_callback`, 2026 öncesi bir sunucunun geri kanal üzerinden gönderdiği `elicitation/create` isteğinin ulaşacağı callback'in aynısıdır. `sampling/createMessage` ile `sampling_callback`, `roots/list` ile `list_roots_callback` için de aynısı geçerlidir: 2026-07-28 sürümünde bağımsız sunucu->istemci RPC'leri artık yoktur, ancak birebir aynı `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` yükleri `input_requests` içinde taşınır ve aynı üç callback'e yönlendirilir. Tek bir callback seti her iki nesle de hizmet verir.
* `call_tool` düz bir `CallToolResult` döndürür. Aradaki turlar çağırana görünmez.
* `get_prompt` ve `read_resource` aynı döngüyü yürütür.

!!! check
    Callback'i kaydetmezseniz döngü ilk turda başarısız olur: SDK'nın yedek callback'i her
    elicitation'ı bir hatayla yanıtlar ve `call_tool`, *"Elicitation not supported"* mesajıyla
    `MCPError` fırlatır.

Döngü sınırlıdır. Varsayılan üst sınır `Client(..., input_required_max_rounds=10)` değeridir; bunu aştıktan sonra hâlâ `InputRequiredResult` döndüren bir sunucu `call_tool`'un hata fırlatmasına yol açar. Bir tur yalnızca `request_state` taşıyıp hiç `input_requests` taşımıyorsa `Client` yeniden denemeden önce kısa bir süre bekler (50 ms'den başlayıp iki katına çıkarak 250 ms tavanına ulaşır); böylece yalnızca *"henüz bitmedi"* diyen bir sunucu sürekli yoklanmaz.

### Döngüyü kendiniz yürütme {#driving-the-loop-yourself}

Otomatik döngü tek süreçli bir istemci için yeterlidir. Şu durumlarda döngüyü kendiniz üstlenin:

* İstemciniz **dağıtık** yapıdaysa: soruyu kullanıcıya gösteren süreç `call_tool`'u çağıran süreç değildir, bu yüzden yeniden denemeyi başka bir worker gönderir. `request_state`, kendi depolamanız üzerinden bu sınırın ötesine taşıdığınız kalıcı saklanabilir token'dır; `input_responses` ise karşı tarafın onunla birlikte geri gönderdiği şeydir.
* Her turu **incelemek** istiyorsanız: her `input_requests` girdisini loglamak ya da denetlemek, belirli istek türlerini reddetmek veya adımlar arasında kendi bekleme (backoff) stratejinizi uygulamak.
* Tur sayısına değil **gerçek süreye** dayalı bir sınır istiyorsanız: `input_required_max_rounds`'a güvenmek yerine kendi döngünüzü `anyio.fail_after(...)` içine sarın.

Alttaki oturuma inin; orada `allow_input_required=True` size birleşim türünü doğrudan verir:

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` dönüş türünü `CallToolResult | InputRequiredResult` olarak genişletir. Onu yeniden daraltan `isinstance` denetimidir.
* `request_state` artık sizin elinizde. Adımlar arasında onu bir yere yazın; konuşma yepyeni bir süreçten kaldığı yerden sürebilir.
* `input_requests` içindeki her girdi için `input_responses` içine **aynı anahtarla** bir `InputResponse` koyarsınız. Kullanıcı arayüzünüzün yeri `fulfil`'dir; buradaki, yanıtı sabit kodlar.
* Her adımda aynı araç adı, aynı `arguments`. Yeniden deneme yeni bir yöntem değil, asıl çağrının yeniden yapılmasıdır.

## `requestState`'i koruma {#protecting-requeststate}

Yukarıdaki her şey `request_state`'i bir yankı olarak ele alır; ağ üzerinde de bundan ibarettir. Ancak istemci onu adımlar arasında elinde tutar (süreçler arasında bir yere yazmak tam da önceki bölümün onayladığı şeydir), dolayısıyla geri gelen şey **istemcinin sağladığı girdidir**: değiştirilmiş, süresi dolmuş ya da bambaşka bir çağrıdan alınmış olabilir. Spesifikasyon, durumun yetkilendirmeyi, kaynak erişimini veya iş mantığını etkileyebildiği her yerde sunucuların bu durumun bütünlüğünü korumasını ve doğrulama başarısız olduğunda turu reddetmesini zorunlu kılar.

`MCPServer` onu varsayılan olarak korur. Her sunucu, süreç başlarken üretilen bir anahtar altında giden `requestState`'i mühürler ve gelen her yankıyı (çözümleyici durumunu da elle kurulan durumu da) doğrular. Hiçbir şey yapılandırmaz, düz metin yazar ve düz metin okursunuz; ağ üzerinde yalnızca opak, şifreli bir token taşınır.

Varsayılan anahtar süreçle birlikte doğar ve ölür; tek bir sürecin ötesine dağıtım yapmadan önce bilmeniz gereken tek şey budur:

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **Varsayılan (yapılandırma yok)** tek bir sürece uygundur: stdio ya da tam olarak bir HTTP worker'ı. Başka bir worker'a, yük dengeleyici arkasındaki başka bir örneğe ya da yeniden başlatma sonrası aynı sunucuya düşen bir yeniden deneme, o sürecin elinde olmayan bir anahtarla mühürlenmiştir; istemci aşağıdaki sabit ret yanıtını alır ve akışa baştan başlamak zorundadır.
* **`keys=[...]`**, bir yeniden denemenin **başka bir örneğe** ulaşabildiği (çok worker'lı `uvicorn`, yük dengelemeli HTTP) ya da yeniden başlatmalardan sağ çıkması gerektiği her durumda zorunludur: her örnek, herhangi bir kardeşinin ürettiğini doğrular. Aynı mekanizma; üretilmiş bir anahtar yerine sizin gizli anahtarınız.
* Kendi kriptografiniz için (örneğin bir KMS ya da mevcut bir token servisi) `keys` yerine `RequestStateSecurity(codec=...)` geçirin; aşağıdaki **[Kendi kriptografinizi getirme](#bring-your-own-crypto)** bölümü sözleşmeyi anlatır.

### Mührün taşıdıkları {#what-the-seal-carries}

Varsayılan da olsa yapılandırılmış da olsa, ağ üzerindeki `requestState` şifreli ve kimliği doğrulanmış bir token'dır. Kodunuz onu hiç görmez: işleyiciler ve çözümleyiciler düz metin yazar, düz metin okur (`ctx.request_state`); SDK çıkışta mühürler, girişte doğrular. Bütünlüğün ötesinde her token şunlara bağlanır:

* **Bir zaman penceresi.** Her tur yeni bir son kullanma süresiyle yeniden mühürler; bu yüzden `RequestStateSecurity(ttl=...)` (varsayılan 600 saniye) akışın tamamını değil, tur başına düşünme süresini sınırlar.
* **Kimliği doğrulanmış principal.** İstek, SDK'nın doğruladığı bir OAuth erişim token'ı taşıdığında durum, token'ın istemcisine, yayımcısına (issuer) ve öznesine (subject) bağlanır: bir kullanıcı için üretilmiş durum, iki kullanıcı aynı OAuth istemcisini paylaşsa bile başka bir kullanıcı altında başarısız olur. Özne sağlamayan bir doğrulayıcı, bağlamayı yalnızca istemci kimliğine indirger; URL tabanlı istemci kimliklerinde bu kimliği o istemci yazılımının tüm kullanıcıları paylaşır. Kimlik doğrulama SDK dışında sonlandırıldığında (öndeki bir vekil sunucu) ya da aktarımda kimlik doğrulama yoksa bağlanacak bir principal yoktur ve `RequestStateSecurity(bind_principal=...)` kendi kimlik sinyalinizden bir tane sağlamadıkça bu denetim etkisizdir. Token doğrulayıcınız hangi bileşenleri sağlıyorsa bunları tutarlı biçimde sağlamalıdır: bazı isteklerde özneyi ekleyip bazılarında atlayan bir doğrulayıcı, principal'ı akışın ortasında değiştirir ve süren turlar reddedilir.
* **Kaynaklandığı istek.** Yöntem, araç ya da prompt adı (veya kaynak URI'si) ve argümanların bir özeti (digest). Başka bir araca, başka argümanlara ya da başka bir yönteme karşı yeniden oynatılan bir token başarısız olur.
* **Sorulan sorunun ta kendisi.** Her çözümleyici yanıtı, hem ilk geldiği turda hem de kaydedilmiş bir yanıt sonradan yeniden kullanıldığında, istemciye gösterilen oluşturulmuş soruya sabitlenir. Mesajı yeniden yazılmış ya da şeması değişmiş bir sürümü dağıtırsanız sunucu bayat bir yanıtı tüketmek yerine yeniden sorar. Aynı sabitleme ters yönde de işler: mesajları çağrıya özgü verilerden değil, aracın argümanlarından türetin. Bir zaman damgasından ya da canlı bir kurdan kurulan mesaj her turda farklı oluşur; bu yüzden kaydedilmiş her yanıt bayat görünür ve sunucu, istemcinin tur sınırı çağrıyı sonlandırana kadar yeniden sorar.

Bunların hepsi SDK'nın işidir; sizin değil, kendinizinkini getirseniz bile codec'in de değil.

### Anahtar rotasyonu {#rotating-keys}

Yeni durumu `keys[0]` mühürler; listedeki her anahtar doğrular. Kesintisiz rotasyon, her biri bir sonrakinden önce tamamen yayılmış üç aşamadan oluşur:

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

Asla önce üreten anahtarı terfi ettirmeyin: bazı örneklerin henüz doğrulayamadığı bir anahtarla üretmek, yayılımın ortasında süren turları düşürür.

Anahtarların kapsamı tek bir servistir. Mühürlü zarf ayrıca sunucunun adını bir audience claim'i olarak taşır; bu yüzden tesadüfen aynı gizli anahtarı paylaşan başka bir servisin ürettiği token zaten reddedilir. Claim ancak ad kadar ayırt edicidir; bu yüzden açık bir politika verilen sunucunun gerçek bir adı olmalı ya da `RequestStateSecurity(audience=...)` ayarlamalıdır: adsız bir sunucu oluşturulurken istisna fırlatır. `audience=` ayrıca bir servisin başka bir servisin ürettiği durumu kabul etmesi gereken, bilinçli kurulmuş çok servisli topolojilere de hizmet eder. (Yapılandırmasız varsayılan muaftır: anahtarı süreçten hiç çıkmaz, dolayısıyla audience claim'inin ekleyeceği bir şey yoktur.)

### Kendi kriptografinizi getirme {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)`, `seal(bytes) -> str` ve `unseal(str) -> bytes` yöntemleri olan ve kendisinin üretmediği her token için `InvalidRequestState` fırlatan herhangi bir şeyi kabul eder. Klasik biçim, bir KMS üzerinden zarf şifrelemedir: başlangıçta bir veri anahtarını bir kez açar ve token başına kriptografiyi yerel tutarsınız:

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL, principal bağlama ve istek bağlama codec'in işi **değildir**: SDK bunları her codec için `seal`'den önce yüke damgalar ve `unseal`'den sonra yeniden doğrular. Bir codec'in tek yükümlülüğü bütünlük (kurcalanmışsa istisna fırlatmak) ve ideal olarak gizliliktir.

### Doğrulama başarısız olduğunda {#when-verification-fails}

Gelen her başarısızlık (kurcalanmış, süresi dolmuş, başka bir isteğe ya da principal'a karşı yeniden oynatılmış veya bu sunucunun bilmediği bir anahtarla mühürlenmiş olsun) aynı yanıtı alır:

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

Her neden için tek bir sabit mesaj; böylece ağ üzerinden hangi denetimin başarısız olduğu asla açığa çıkmaz, gerçek neden sunucu log'una gider. `tools/call`, `prompts/get` ve `resources/read` üzerinden gelen her `requestState` denetlenir; hiç durum üretmeyen bir işleyiciye gelen de buna dahildir. Pratikte en sık görülen ret bir saldırgan değildir: varsayılan, sürece özel anahtarın bir yeniden başlatma öncesinden ya da başka bir örnekten gelen bir yeniden denemeyle karşılaşmasıdır. İstemci akışı yeniden başlatır; bu önemli olduğunda çözüm `keys=[...]` kullanmaktır.

### Elle kurulan durum {#hand-built-state}

Kendiniz ayarladığınız bir `request_state`'i (bir araç, prompt ya da kaynak şablonu fonksiyonundan `InputRequiredResult` döndürerek), çözümleyici durumunu işleyen aynı mekanizma tek satır kod değişmeden mühürler ve doğrular: düz metin yazın, düz metin okuyun; yukarıdaki her bağlama geçerlidir.

SDK'nın, yapılandırılmış olsa bile sizin yerinize sabitleyemeyeceği tek şey soru kimliğidir: durumunuzdaki bir yanıtın *sizin* sorularınızdan hangisine ait olduğunu bilmez. Yanıtları soruya göre anahtarlayarak saklıyorsanız duruma kendi soru tanımlayıcınızı ekleyin ve yeniden denemede onu denetleyin.

Düşük seviyeli `Server` hiçbir şeyin hazır gelmediği katmandır: `MCPServer`'ın aksine, sınırı kendiniz ekleyene kadar hiçbir şey mühürlenmez ve bunu yapana kadar `request_state` ağ üzerinden tam yazıldığı gibi geçer. Tek satırlık katılım **[Düşük seviyeli Server](../advanced/low-level-server.md#the-other-handlers)** sayfasında gösterilir.

## 2026-07-28 sürümüne özgü bir sonuç {#a-2026-07-28-result}

`InputRequiredResult` yalnızca **2026-07-28** protokol sürümünde vardır. Bellek içi `Client(server)` onu sizin yerinize anlaşarak belirler; ağ üzerinde `mode="auto"` keşfeder. Bağlandıktan sonra `client.protocol_version` size ne elde ettiğinizi söyler.

!!! warning
    2026 öncesi bir oturumda `InputRequiredResult` koyacak bir yer yoktur. `mode="legacy"` bir
    bağlantıda işleyicinizden bir tane döndürürseniz çalıştırıcı onu anlaşılan sürüme
    serileştiremez; istemciye `-32603` *"Handler returned an invalid result"* hatası döner. Her iki
    nesle de hizmet veren bir sunucu, ona el atmadan önce `ctx.protocol_version` değerini
    denetlemelidir.

!!! info
    **URL kipinde elicitation**, 2026 bağlantısında tam olarak bu mekanizmayı kullanır.
    `input_requests` içindeki girdi, parametreleri `ElicitRequestURLParams` olan bir
    `ElicitRequest`'tir; kullanıcı bant dışı akışı tamamlar ve istemciniz çağrıyı yeniden dener.
    Aynı döngü, yeni API yok. Üst seviyeli sunucu tarafı **[Elicitation](elicitation.md)**
    sayfasındadır.

## Özet {#recap}

* 2026-07-28 sürümünde, çağrının ortasında girdiye ihtiyaç duyan bir sunucu `InputRequiredResult` **döndürür**. İstemciye asla istek açmaz.
* `input_requests` ihtiyaç duyduklarıdır. `request_state` yalnızca sunucunun okuduğu opak bir devam token'ıdır.
* Yeniden deneme döngüsünü `Client` sizin yerinize çalıştırır: `elicitation_callback` / `sampling_callback` / `list_roots_callback` kaydedin, `call_tool` düz bir `CallToolResult` döndürür. `input_required_max_rounds` (varsayılan 10) onu sınırlar.
* Turları incelemek ya da kalıcı saklamak için `client.session.call_tool(..., allow_input_required=True)` kullanın ve `while isinstance(result, InputRequiredResult)` döngüsünü kendiniz üstlenin.
* `@mcp.tool()` üzerinde, kullanıcıya soran bir bağımlılık bu sonucu sizin yerinize üretir (**[Bağımlılıklar](dependencies.md)**); elle kurulan biçim **düşük seviyeli** `Server`'dır.
* Prompt'lar ve kaynaklar da katılır: bir `@mcp.prompt()` ya da şablon `@mcp.resource()` fonksiyonu `InputRequiredResult`'ı kendisi döndürür ve yeniden denemede `ctx.input_responses`'ı okur.
* `requestState` istemcinin sağladığı girdi olarak geri gelir; bu yüzden `MCPServer` onu (çözümleyici durumunu da elle kurulan durumu da) varsayılan olarak sürece özel bir anahtar altında mühürler. Çok örnekli dağıtımlar, her örneğin bir kardeşinin ürettiğini doğrulayabilmesi için `RequestStateSecurity(keys=[...])` (ya da özel bir codec) geçirir. Mühür her token'ı bir zaman penceresine, kaynaklandığı isteğe ve (istek SDK'nın doğruladığı kimlik doğrulama bilgisini taşıdığında ya da `bind_principal=` kendi kimlik sinyalinizi sağladığında) kimliği doğrulanmış principal'a bağlar (**[`requestState`'i koruma](#protecting-requeststate)**).

Sunucunun başlattığı örneklemenin ve itme tarzı geri kanalın geri kalanının yerini alan mekanizma budur; **[Kullanım dışı özellikler](../deprecated.md)** sayfasına bakın.
