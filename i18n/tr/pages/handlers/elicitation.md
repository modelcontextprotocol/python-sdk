---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# Elicitation {#elicitation}

İşinin yarısına gelmiş ve tek bir yanıtı eksik olan bir aracın başarısız olması gerekmez.

**Elicitation** (kullanıcıdan bilgi isteme) onun sormasını sağlar. Araç çağrısının ortasında kullanıcıya bir soru gelir ve verdiği yanıt aynı fonksiyon çağrısına geri döner.

İki mod var:

* **Form modu**: bir değere ihtiyacınız vardır (bir onay, bir tarih, bir miktar). Alanları siz tanımlarsınız, formu istemci çizer.
* **URL modu**: kullanıcının başka bir yere gitmesi gerekir (bir OAuth onay ekranı, bir ödeme sayfası). Orada yaptığı hiçbir şey protokolden geçmez.

Sormanın da iki yolu var. İlk başvurmanız gereken bir **çözümleyicidir**: soruyu bir parametreye asarsınız ve SDK sorar; hangi bağlantı olursa olsun, istemci hangi protokol neslini konuşursa konuşsun. Doğrudan yol olan `await ctx.elicit(...)`, *sunucudan* *istemciye* giden bir istektir; bu kanal yalnızca eski nesil bir bağlantıdaki (spesifikasyon sürümü 2025-11-25 veya öncesi) istemciler için vardır. İkisi de bu sayfada; çözümleyiciyle başlayın.

## Çözümleyiciyle sorma {#ask-with-a-resolver}

Aracın tamamının önünde duran bir soru (*emin misiniz? eşleşen üç hesaptan hangisi?*) araç gövdesinden çıkarılıp bir **çözümleyiciye** taşınabilir; soruyu sizin yerinize framework sorar.

`Annotated[T, Resolve(fn)]` ile işaretlenmiş bir parametre, araç gövdesinden önce `fn` çalıştırılarak doldurulur. Çözümleyici değeri zaten biliyorsa doğrudan döndürür; framework'ün sormasını istiyorsa `Elicit(...)` döndürür:

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete`, aracın kendi `path` argümanını adıyla okur, klasörü listeler ve **yalnızca gerektiğinde sorar**: boş bir klasör, istemciye hiç gidip dönmeden `Confirm(ok=True)` olarak çözümlenir.
* `delete_folder`, `ElicitationResult[Confirm]` tür ipucunu kullanır; bu yüzden framework sonucun tamamını enjekte eder ve araç her durumu `match` ile ele alır: kabul edip onaylama, kabul edip tutma (`ok=False`), reddetme, iptal.
* `confirm` parametresi aracın girdi şemasında hiç görünmez: `path`'i istemci sağlar, `confirm`'ü çözümleyici.

Aracın dallanması gerekmiyorsa bunun yerine sarmalanmamış modeli işaretleyin (`Annotated[Confirm, Resolve(confirm_delete)]`): kabulde modeli alır, ret veya iptalde ise çağrı bir hatayla sonlanır.

Çözümleyici **her** bağlantıda çalışır. Eski nesil bağlantıdaki bir istemciye SDK soruyu doğrudan gönderir; **2026-07-28** bağlantısında ise SDK soruyu çağrıdan *döndürür* ve istemcinin bir sonraki denemesi yanıtı taşır. Çözümleyiciniz aradaki farkı hiçbir zaman bilmez; arka planda olan biten **[Çok turlu istekler](multi-round-trip.md)** (multi-round-trip) sayfasında.

Sormak, bir çözümleyicinin yapabileceklerinden yalnızca biri. Genel mekanizma (sormadan hesaplayan bağımlılıklar, bağımlılıkların bağımlılıkları, modelin neyi sağlayıp neyi sağlayamayacağı) **[Bağımlılıklar](dependencies.md)** sayfasında.

## Aracın içinden sorma {#ask-from-inside-the-tool}

Bir araç kendi gövdesinin ortasında durup da sorabilir.

!!! warning
    `ctx.elicit()` ve `ctx.elicit_url()`, *sunucudan* *istemciye* giden isteklerdir; bu kanal
    yalnızca eski nesil bir bağlantıdaki (spesifikasyon sürümü **2025-11-25** veya öncesi)
    istemciler için vardır. **2026-07-28** bağlantısında sunucunun başlattığı istek yoktur,
    bu yüzden bu çağrılar başarısız olur. Çözümleyici ikisinde de çalışır. Ayrıntıların tamamı
    **[Protokol sürümleri](../protocol-versions.md)** sayfasında.

`await ctx.elicit()` bir mesaj ve bir Pydantic modeli alır:

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* Size `ctx.elicit`'i veren **`Context`** parametresidir; her araç bir tane alabilir. Bu nesnenin kendi sayfası var: **[Context nesnesi](context.md)**.
* `AlternativeDate`, istediğiniz yanıtın **şemasıdır**.
* Araç `async def`. Öyle olmak zorunda: ortada durup bir insanı bekler.
* Başka herhangi bir tarihte araç hemen döner. Yalnızca mecbur kaldığında sorar.
* Kullanıcının kabul ettiği tarih yine `book_table`'ın kendisinden geçer. Yanıt da diğerleri gibi bir girdidir: kendisi de tamamen dolu olan bir alternatif körlemesine onaylanmaz, yeniden sorulur.

### İstemcinin aldığı {#what-the-client-receives}

İstemci mesajınızı ve yanında modelden üretilmiş bir JSON Schema alır:

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

Bu şema formun kendisidir. `Field(description=...)` etikettir; bir varsayılan değer girdiyi önceden doldurur ve alanı isteğe bağlı yapar. Bu, **[Araçlar](../servers/tools.md)** sayfasının bir aracın argümanları için anlattığı Pydantic'ten JSON Schema'ya dönüşüm mekanizmasının aynısıdır.

!!! warning
    Bir elicitation şeması, bir aracın girdi şeması kadar ifade gücüne sahip değildir. Yalnızca
    düz, ilkel alanlar: `str`, `int`, `float`, `bool` veya dizelerden oluşan bir `Literal`
    (bir `enum`'a dönüşür). Modelin içine bir model koyarsanız `ctx.elicit`, istemciye hiçbir
    şey gönderilmeden önce istisna fırlatır:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    Bir insanı işinin ortasında bölüyorsunuz. Yanıt iç içe yapı gerektiriyorsa, o zaten
    aracın bir argümanı olmalıydı.

### Üç yanıt {#the-three-answers}

`result.action` kullanıcının ne yaptığını söyler ve tam olarak üç olasılık vardır:

* `"accept"`: formu gönderdi. `result.data`, zaten doğrulanmış bir `AlternativeDate` örneğidir.
* `"decline"`: hayır dedi.
* `"cancel"`: seçim yapmadan soruyu kapattı.

`result.data` yalnızca `"accept"` durumunda vardır; örneğin önce `result.action`'ı denetlemesinin nedeni budur. Tür denetleyiciniz bu sırayı zorunlu kılar: `result.action == "accept"` sonrasında `result.data` bir `AlternativeDate`'tir; öncesinde `.data` diye bir şey hiç yoktur.

Ret bir hata değildir. Reddetmenin ne anlama geldiğine araç karar verir (burada: rezervasyon yok) ve modele normal şekilde yanıt verir.

!!! tip
    Yanıt, kodunuz görmeden önce modelinize göre doğrulanır. Bir `bool` için `"maybe"` gönderen
    bir istemci rezervasyonunuzu bozmaz: çağrı bir şema uyuşmazlığı hatasıyla başarısız olur,
    `if`'iniz hiç çalışmaz.

## Kullanıcıyı bir URL'ye gönderme {#send-the-user-to-a-url}

Bazı şeyler modelden veya istemciden geçmemelidir: kimlik bilgileri, kart numaraları, OAuth onayı. Bunlar için veri istemezsiniz; kullanıcıdan bir yere gitmesini istersiniz:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()`; mesajı, ziyaret edilecek **URL**'yi ve sizin seçtiğiniz bir `elicitation_id`'yi alır: sunucunuz içinde bu elicitation'ı tanımlayan herhangi bir dize.
* Sonuçta bir eylem vardır, başka hiçbir şey yoktur. `"accept"`, kullanıcının URL'yi açmayı kabul ettiği anlamına gelir; öbür taraftaki işi bitirdiği anlamına **gelmez**.
* Ödeme bant dışında, kullanıcının tarayıcısı ile ödeme sağlayıcınız arasında gerçekleşir. MCP üzerinden hiçbir içerik geri gelmez.

İkinci araca bakın. Sunucunuz bant dışı akışın bittiğini öğrendiğinde (bir webhook, bir yoklama; burada ikinci bir araç olarak modellenmiş), `ctx.session.send_elicit_complete(...)` aynı `elicitation_id` ile `notifications/elicitation/complete` gönderir. İstemci, *"ödeme bekleniyor..."* göstermeyi bırakabileceğini böyle anlar. Bu olmadan istemci yalnızca tahmin yürütebilir.

## İstemci tarafı {#the-client-side}

Sunucular sorar. İstemciler `Client(...)`'a bir **`elicitation_callback`** geçirerek yanıtlar:

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* Tek bir callback iki modu da ele alır. `params`, `ElicitRequestFormParams` ile `ElicitRequestURLParams`'ın bir birleşimidir; dallanma `isinstance` ile yapılır.
* URL için `params.url`'yi kullanıcıya gösterir ve seçtiği eylemi döndürürsünüz. Asla `content` yok.
* Form için gerçek bir uygulama `params.requested_schema`'yı çizer ve kullanıcının girdisini `content` olarak döndürür. Buradaki ise hazır bir yanıtla her zaman evet der; bir testte tam da istediğiniz callback budur.
* Callback'i geçirmek aynı zamanda **yetenek bildirimidir**: sunucu bu istemciye soru sorulabileceğini böyle öğrenir. Bir istemcinin sunucu adına yanıtlayabileceği diğer şeyler **[İstemci callback'leri](../client/callbacks.md)** sayfasında.

!!! info
    Elicitation *sunucudan* *istemciye* giden bir istektir ve bunlar yalnızca klasik
    el sıkışmalı bir oturumda vardır; bu istemcinin `mode="legacy"` geçirmesinin nedeni budur.
    **2026-07-28** bağlantısında bir araç bunun yerine soruyu çağrıdan *döndürerek* sorar;
    o akış **[Çok turlu istekler](multi-round-trip.md)** sayfasında.

### Deneyin {#try-it}

Form modundaki `ctx.elicit` kullanan `server.py` dosyasını (`book_table` olanı) Streamable HTTP üzerinde başlatın (tek satırlık komut **[Sunucunuzu çalıştırma](../run/index.md)** sayfasında), ardından istemcinin `main()` fonksiyonunu çalıştırın ve `book_table`'dan Noel günü için rezervasyon isteyin.

Callback kendisine gönderilen soruyu yazdırır:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

`{"accept_alternative": True, "date": "2025-12-27"}` ile yanıt verir ve bunca zamandır `await ctx.elicit(...)` içinde bekleyen araç rezervasyonu tamamlar:

```text
Booked a table for 2 on 2025-12-27.
```

Şimdi URL modundaki `server.py` dosyasına geçin ve aynı `main()`'i `pay_deposit`'e yöneltin: aynı callback diğer dala girer, ödeme bağlantısını yazdırır ve araç *"Complete the payment in your browser."* ile geri döner. Çağrının ortasında, iki yönde de tek bir tur.

!!! check
    Şimdi `Client`'tan `elicitation_callback=` parametresini kaldırın ve `book_table`'ı Noel günü
    için yeniden çağırın. Çağrının tamamı bir protokol hatasıyla başarısız olur:

    ```text
    Elicitation not supported
    ```

    Hiç callback kaydetmemiş bir istemci `elicitation` yeteneğini hiç bildirmemiştir, dolayısıyla
    soracak kimse yoktur. Aracınız `"decline"` almadı; bir istisna aldı. Buna göre tasarlayın:
    her elicitation'ın "ya soramazsam?" sorusuna mantıklı bir yanıtı olmalı.

## Özet {#recap}

* `Annotated[T, Resolve(fn)]` ile işaretlenmiş bir parametreyi bir çözümleyici doldurur; çözümleyici sorması gerektiğinde `Elicit(...)` döndürür. Her bağlantıda çalışır.
* Şema düz bir Pydantic modelidir: yalnızca ilkel alanlar, dönüşte doğrulanır.
* `result.action`; `"accept"`, `"decline"` veya `"cancel"` olur; `result.data` yalnızca kabulde vardır.
* `await ctx.elicit(message, schema=Model)` araç gövdesinin içinden sorar; `await ctx.elicit_url(message, url, elicitation_id)` ise modelden geçmemesi gereken her şey içindir (`ctx.session.send_elicit_complete(elicitation_id)` bant dışı kısmın bittiğini söyler). İkisi de sunucudan istemciye giden isteklerdir: istemcinin eski nesil bir bağlantıda olmasını gerektirirler.
* İstemci, params türüne göre dallanan tek bir `elicitation_callback` ile yanıtlar; yeteneği bildiren şey onu kaydetmektir.
* 2026-07-28 bağlantısında sunucu soruyu itmek yerine döndürür; aynı callback'i **[Çok turlu istekler](multi-round-trip.md)** besler.

O dönüşün altında yatan her şey (yeniden deneme döngüsü, `requestState`'i koruma, akışı kendiniz yürütme) **[Çok turlu istekler](multi-round-trip.md)** sayfasında.
