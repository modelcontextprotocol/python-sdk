---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# Uzantılar {#extensions}

**Uzantı**, tek bir tanımlayıcının arkasında toplanmış, isteğe bağlı olarak etkinleştirilen bir MCP davranışı paketidir.

Sunucuda araç, kaynak ve yeni istek metotları katkısında bulunabilir, `tools/call` isteğini sarmalayabilir. İstemcide ek `tools/call` sonuç biçimlerini sahiplenebilir ve satıcıya özgü bildirimleri gözlemleyebilir. Her iki taraf da kendi `capabilities.extensions` alanı altında duyuru yapar ve bunu istememiş hiç kimse için hiçbir şey değişmez. Sözleşme budur ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)) ve tek bir altın kuralı var: **uzantılar varsayılan olarak kapalıdır**.

## Bir uzantı kullanma {#using-an-extension}

Örnekleri oluşturma sırasında geçirin:

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

Bu kadar. Sunucu artık `capabilities.extensions` altında `io.modelcontextprotocol/ui` duyurur ve uzantının katkıda bulunduğu her şeyi sunar.

`Apps` yerleşik başvuru uzantısıdır ve kendi sayfası var: **[MCP Apps](apps.md)**.

!!! note
    Uzantılar oluşturma sırasında sabitlenir. Sonradan çağrılacak bir `add_extension` yoktur: istemciler bağlıyken bir sunucunun yetenek eşlemesi değişmemelidir.

Yetenek eşlemesi `server/discover` ile taşınır; bu da bir **2026-07-28** yoludur. Eski nesil `initialize` el sıkışmasında onu koyacak bir yer yoktur, bu yüzden eski nesil bir istemci uzantıyı görmez. Tasarımınızı buna göre yapın: bir uzantı sunucuyu *zenginleştirir*; sunucunun kullanılabilir olmasının tek yolu olmamalıdır.

## Kendi uzantınızı yazma {#writing-your-own}

`Extension`'dan alt sınıf türetin ve yalnızca ihtiyaç duyduklarınızı geçersiz kılın. Her metodun bir varsayılanı var.

### Tanımlayıcı {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

Tanımlayıcı, spesifikasyonun `_meta` anahtar dilbilgisini izleyen bir `vendor-prefix/name` dizesidir: noktayla ayrılmış etiketler (her biri bir harfle başlar, bir harf veya rakamla biter), bir eğik çizgi, ardından ad. **Sınıf tanımlandığında** doğrulanır; yani bir yazım hatası sunucunun açılmasını beklemez:

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

Önek olarak denetiminizdeki bir alan adı kullanın. `io.modelcontextprotocol/*`, MCP projesinin kendisinin belirlediği uzantılar içindir.

### Araç katkısında bulunma {#contributing-tools}

İşe yarar en küçük uzantı, bir araç ve bir ayarlar eşlemesidir:

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()`, `ToolBinding`'ler döndürür. Sunucu her birini, `mcp.add_tool(...)` çağrısını kendiniz yapmışsınız gibi kaydeder: aynı şema üretimi, aynı `Context` enjeksiyonu, her şey aynı.
* `settings()`, `capabilities.extensions["com.example/stamps"]` konumunda duyurulan değerdir. Uzantıyı ayarsız duyurmak için `{}` (varsayılan) döndürün.
* Uzantı sunucuyu hiçbir zaman almaz. Katkıları veri olarak beyan eder; bunları `MCPServer` tüketir. Değiştirilecek bir `self.server` yoktur.

Kanıtı da `main()`: doğrudan `mcp`'ye bağlanan bellek içi bir istemci:

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### Kendi metotlarınızı sunma {#serving-your-own-methods}

Bir uzantı **yeni istek metotları** kaydedebilir: spesifikasyonunkilerin yanında sunulan kendi fiilleri:

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams`, `RequestParams`'tan türer; böylece 2026 `_meta` zarfı tek biçimde ayrıştırılır ve işleyiciniz ham bir dict değil, her zaman doğrulanmış parametreler alır. İstemcinin denetlediği şeyi sınırlayın: `Field(ge=1, le=100)`, kodunuz onun için herhangi bir şey ayırmadan önce saçma bir `limit` değerini reddeder.
* `require_client_extension(ctx, EXTENSION_ID)` kontrol noktasıdır: uzantıyı beyan etmemiş bir istemci, spesifikasyonun istediği makine tarafından okunabilir `requiredCapabilities` yüküyle birlikte `-32021` (gerekli istemci yeteneği eksik) hatasını alır.
* `protocol_versions=frozenset({"2026-07-28"})` metodu tek bir protokol sürümüne sabitler. Başka herhangi bir sürümde istemci `METHOD_NOT_FOUND` alır; sanki metot orada hiç yokmuş gibi. O istemci için gerçekten de yoktur.

Metotlar **yalnızca ekleme niteliğindedir**. SDK bunu çalışma zamanında değil, oluşturma sırasında uygular:

* Spesifikasyonda tanımlı bir metot (`tools/list`, `completion/complete`, ...) için bir `MethodBinding`, bağlama oluşturulurken `ValueError` fırlatır. Çekirdek fiiller sunucuya aittir.
* Aynı metodu bağlayan iki uzantı, ikincisi kaydolurken hata fırlatır. Son yazan kazanır yaklaşımı, eklentilerin birbirini bozmasının yoludur; biz bunu yapmayız.
* Boş bir `protocol_versions` kümesi de hata fırlatır: hiçbir zaman sunulamayacak bir metot bir yapılandırma değil, bir hatadır.

### İstemci tarafı {#the-client-side}

Aynı dosyadaki `main()`, istemci tarafının tamamıdır; iki yarısıyla birlikte:

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` uzantıyı beyan eder. Beyanlar `ClientCapabilities.extensions` hâline gelir: 2026-07-28 bağlantısında eşleme istek başına `_meta` zarfında taşınır, böylece sunucu onu **her** istekte görür; eski nesil bir bağlantıda `initialize` el sıkışmasıyla taşınır. Sunucu kodu hangisi olduğuyla ilgilenmez: `require_client_extension(ctx, ...)` ve `ctx.session.check_client_capability(...)` her iki yolda da doğru kaynağı okur.
* Satıcıya özgü metotlar bir katman aşağıya, `client.session.send_request(...)` düzeyine iner; `Client` yalnızca spesifikasyon fiilleri için birinci sınıf metotlar kazanır. `send_request` herhangi bir `Request` alt sınıfını kabul eder, bu yüzden satıcıya özgü istek olduğu gibi geçer.

### `tools/call` isteğini yakalama {#intercepting-toolscall}

Yakalayıcı nitelikteki tek kanca. Bir araç çağrısını gözlemlemek, kısa devre yapmak veya veto etmek için `intercept_tool_call`'u geçersiz kılın:

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params`, doğrulanmış `CallToolRequestParams` nesnesidir: ham JSON'a dokunmadan `params.name` ve `params.arguments` elinizdedir. Hangi araç çağrısının çalışacağına karar veren de odur: `call_next` üzerinden yeniden yazılmış bir bağlam geçirmek, araç çağrısını değil, işleyicinin `ctx` üzerinde gözlemlediğini değiştirir. İletim düzeyinde istek yeniden yazımı [Middleware](middleware.md) sayfasının konusudur.
* `call_next(ctx)` zincirin geri kalanını çalıştırır ve işleyicinin sonucunu döndürür. Onu değiştirmeden döndürün (gözlemleme), başka bir şey döndürün (değiştirme) ya da bir `MCPError` fırlatın (reddetme). Ne döndürürseniz döndürün, 2026 neslinin `serverInfo` kimlik damgası dâhil, herhangi bir işleyici sonucu gibi serileştirilir; bu yüzden kısa devre yapan bir yakalayıcı hiçbir zaman anonim veya şema dışı bir yanıt üretmez.
* Birden fazla uzantı olduğunda yakalayıcılar kayıt sırasına göre iç içe geçer: `extensions=[...]` içindeki ilk uzantı en dıştadır.
* Varsayılan gerçekleştirim doğrudan geçirir; uzantıları bu kancayı hiç geçersiz kılmayan bir sunucu, yalın `tools/call` işleyicisini olduğu gibi korur. Kullanmadığınız şeyin bedelini ödemezsiniz.

Kanca `tools/call` isteğini sarmalar, başka hiçbir şeyi değil. Her iletiyi ilgilendiren konular için [Middleware](middleware.md) kullanın. Onun işi budur.

## Bir istemci uzantısı kullanma {#using-a-client-extension}

**İstemci uzantısı**, aynı sözleşmenin tüketen taraftan görünüşüdür: tek bir tanımlayıcının arkasında toplanmış bir istemci tarafı davranış paketi. Örnekleri `Client(extensions=[...])` ile geçirin ve araçları normal şekilde çağırın:

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)`, diğer her çağrı gibi düz bir `CallToolResult` döndürür. Uzantının değiştirdiği şu: sunucu artık `buy` çağrısını nihai bir sonuç yerine `receipt` adlı bir **sonuç biçimiyle** yanıtlayabilir ve `Receipts`, `call_tool` dönmeden önce onu tamamlar (burada makbuzu bir takip çağrısıyla kullanarak). Çağrı yerinde hiçbir şey değişmez.

Uzantıyı çıkarırsanız bunların hiçbiri olmaz: sunucunun kontrol noktası onu beyan etmemiş bir istemciyi reddeder (hata -32021) ve kontrolü atlayan bir sunucudan gelen sahiplenilmiş bir biçim, spesifikasyonun tanınmayan bir `resultType` için gerektirdiği gibi doğrulamadan geçemez. Bağlantının her iki ucunda da varsayılan olarak kapalı.

İstemci tarafında **hiçbir** davranışı olmayan bir tanımlayıcıyı duyurmak için (sunucu yeteneği kontrol eder, istemci hiçbir şey yapmaz; yukarıdaki arama istemcisinde olduğu gibi) `advertise()` kullanın:

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## İstemci uzantısı yazma {#writing-a-client-extension}

`ClientExtension`'dan alt sınıf türetin ve yalnızca ihtiyaç duyduklarınızı geçersiz kılın. Her birinin varsayılanı olan üç katkı türü var: `settings()`, `claims()` ve `notifications()`.

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* Tanımlayıcı, sunucununkiyle aynı dilbilgisini izler ve sınıf tanımlandığında doğrulanır.
* `claims()`, `ResultClaim`'ler döndürür: iletilen veride bir etiket, onu ayrıştıran model ve onu tamamlayan çözümleyici. Model, etiketi `result_type: Literal["receipt"]` ile sabitlemelidir ve fiilin çekirdek sonuç türlerinden türememelidir; her ikisi de sahiplenme oluşturulurken uygulanır. `receipt_token` gibi satıcıya özgü alanlar ağ üzerinde olduğu gibi iletilir: yerine geçen bir biçim istemciye aynen ulaşır.
* Çözümleyici, ayrıştırılmış modeli ve bir `ClaimContext` alır; `ctx.session`, `client.session` ile aynı herkese açık tutamaçtır, bu yüzden takip çağrıları sıradan oturum çağrılarıdır. Fiilin normal `CallToolResult`'ını döndürür.
* `settings()`, `ClientCapabilities.extensions[identifier]` konumunda duyurulan değerdir; `Client` oluşturulurken bir kez okunur.

`notifications()`, gözlemlenecek satıcıya özgü sunucu bildirimlerini beyan eder:

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

İşleyici doğrulanmış parametreleri gönderim sırasına göre tek tek alır. Gözlemler; veto edemez ve yanıt veremez.

İki sessiz kural. Sahiplenmeler yalnızca 2026-07-28 bağlantılarında etkindir ve yetenek duyurusu da onları izler: eski nesil bir bağlantıda sahiplenmeler ortadan kalkar, tanımlayıcı da onlarla birlikte duyurudan düşer; böylece istemci, biçimlerini reddedeceği bir uzantıyı asla duyurmaz. Sahiplenilen biçimi çözümleyici yerine kendiniz istediğinizde ise `client.session.call_tool(..., allow_claimed=True)` çağırın; bu bayrak olmadan, oturum katmanındaki bir çağırana ulaşan sahiplenilmiş bir biçim `UnexpectedClaimedResult` fırlatır.

### Uzantı fiilleri {#extension-verbs}

Bir uzantının kendi istek metotları istemci tarafında kayıt gerektirmez. Satıcıya özgü bir istek türü `mcp.types.Request`'ten türer ve [Kendi metotlarınızı sunma](#serving-your-own-methods) bölümündeki gibi `client.session.send_request` üzerinden gider. Tek bir ekleme var: bir params anahtarının `Mcp-Name` başlığında taşınması gerektiğinde (tasks gibi uzantı spesifikasyonları kendi fiilleri için bunu şart koşar) istek türü `name_param` beyan eder:

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

Oturum, `params["jobId"]` değerini her gönderim yolunda `Mcp-Name` başlığına yansıtır; eksik bir değer ise gerekli bir başlığı sessizce atlamak yerine açıkça hata verir.

## Bir uzantının yapamayacakları {#what-an-extension-cannot-do}

Katkı yüzeyi bilerek **kapalıdır**. Sunucuda: ayarlar, araçlar, kaynaklar, metotlar, bir `tools/call` yakalayıcısı. İstemcide: ayarlar, sonuç sahiplenmeleri, bildirim bağlamaları. Bir uzantı şunları yapamaz:

* **Barındıran nesneye erişemez.** Veri beyan eder; sunucu veya istemci referansı tutmaz.
* **Çekirdek davranışın yerine geçemez.** Spesifikasyon metotları ve çekirdek sonuç etiketleri oluşturma sırasında reddedilir (`initialize` doğrudan çalıştırıcı tarafından ayrılmıştır); çekirdek söz dağarcığının gölgelediği bir bildirim bağlaması ise bir uyarıyla sessizce devre dışı kalır.
* **Geç kayıt olamaz.** `MCPServer(...)` veya `Client(...)` döndükten sonra uzantı kümesi neyse odur.

Bu duvarlarla boğuşuyorsanız bir uzantı yazmıyorsunuz. Bir fork yazıyorsunuz. Duvarlar özelliğin ta kendisidir: `extensions=[Apps(), Stamps()]` satırını okuyan bir kullanıcı, bu ikisinin dokunmuş olabileceği *her şeyi* bilir.
