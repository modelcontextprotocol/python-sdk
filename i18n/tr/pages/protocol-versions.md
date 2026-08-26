---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# Protokol sürümleri {#protocol-versions}

MCP'nin iki nesli var.

2026-07-28'den önce yayımlanan sunucular her bağlantıyı **`initialize` el sıkışmasıyla** açar: istemci bir sürüm önerir, sunucu karşı teklif verir, istemci onaylar ve bunların hepsi ilk işe yarar istekten önce olur. **2026-07-28** neslindeki sunucular el sıkışmayı bırakır. İstemci tek bir **`server/discover`** sorgusu gönderir, sunucu da her şeyi tek bir sonuç içinde yanıtlar.

Bununla neredeyse hiç ilgilenmeniz gerekmez, çünkü anlaşmayı sizin yerinize `Client` yapar. Bu sayfa, bunu denetleyen tek yapıcı argümanı, yani `mode=` parametresini ve onu değiştireceğiniz üç durumu anlatır.

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

`mode` geçirmediniz, bu yüzden varsayılanı aldınız: `"auto"`. `async with` bloğuna girmek, bu SDK'nın konuştuğu en yeni sürümde tek bir `server/discover` sorgusu gönderir. Sonra:

* **Modern bir sunucu** sorguyu yanıtlar. İstemci sonucu benimser. Tek tur, iş biter.
* **Daha eski bir sunucu** `server/discover` diye bir şey duymamıştır ve hata döndürür. İstemci klasik `initialize` el sıkışmasına geri döner ve onun anlaştığı sürüm neyse onu alır.

Her iki durumda da bağlanmış olarak çıkarsınız ve hangisinin gerçekleştiğini `client.protocol_version` söyler:

```text
2026-07-28
```

Özelliğin tamamı bu. Tek bir `Client`, her nesilden sunucu, kodunuzda dallanma yok.

!!! info
    `MCPServer`, `server/discover` isteğini her aktarımda yanıtlar (bellek içi, stdio, Streamable
    HTTP); bu yüzden kendi sunucunuza karşı `auto` her zaman `2026-07-28`'e ulaşır. Geri dönüş
    yalnızca gerçek bir 2026 öncesi sunucuya karşı devreye girer, ki tam da o zaman bunu istersiniz.

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` hiçbir zaman sorgu göndermez. `initialize` el sıkışmasını çalıştırır; 2026 öncesi bir istemcinin açtığı bağlantının aynısını açar.

```text
2025-11-25
```

Aynı sunucu. `2026-07-28`'i gayet iyi konuşur; sormamasını istemciye siz söylediniz.

Bunu **push tarzı** özellikler için istersiniz.

Sunucunun başlattığı bir istek, sunucunun *sizi* çağırmasıdır: `ctx.elicit(...)` kullanıcınızın önüne bir form koyar, örnekleme (sampling) bir araç çağrısının ortasında modelinizden bir tamamlama ister. Bu kanal yalnızca el sıkışma neslinden bir oturumda vardır.

2026-07-28'de bu kanal yok. Sunucu sorularını *döndürür*, siz de çağrıyı yanıtlarla yeniden denersiniz (**[Çok turlu istekler](handlers/multi-round-trip.md)** (multi-round-trip)).

`mode="auto"` size yalnızca sunucu başka hiçbir şey için fazla eski olduğunda el sıkışma verir. `mode="legacy"` ise el sıkışmayı garanti eder. `Client(...)`'a bir `sampling_callback`, istek olarak yürütülmesini istediğiniz bir `elicitation_callback` ya da bir `message_handler` verdiğinizde buna başvurun. **[İstemci callback'leri](client/callbacks.md)** sayfası her birini tek tek ele alır.

## Sürümü sabitleme {#pinning-a-version}

`mode`, modern bir protokol sürümü dizgesini de kabul eder. Bugün bu küme tam olarak `["2026-07-28"]`.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

Sabitleme **hiçbir şey** göndermez. Sorgu yok, el sıkışma yok. İstemci `2026-07-28`'i yerel olarak benimser ve `async with` döndüğü anda bağlantı canlıdır.

Sabitleme *sizin* verdiğiniz bir sözdür: sunucunun o sürümü konuştuğunu zaten biliyorsunuzdur. İstemci kontrol etmez.

!!! check
    Sabitleme bir keşif değildir. `client.server_info` değerini yazdırın, bedeli hemen görürsünüz:

    ```text
    None
    ```

    İstemci sunucuya kim olduğunu hiç sormadı, bu yüzden `server_info` değeri `None`. `client.server_capabilities`
    için de durum aynı: her yetenek `None`. Araç çağrıları yine çalışır (protokolün bunların hiçbirine ihtiyacı yoktur);
    ne sunacağına karar vermek için `server_capabilities` okuyan kod ise çalışmaz.

    Çözüm bir sonraki bölümde.

Yalnızca modern sürümler sabitlenebilir. El sıkışma neslinden bir dizge, herhangi bir G/Ç yapılmadan önce, yapıcıda reddedilir ve hata size bunun yerine ne yazmanız gerektiğini söyler:

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## `prior_discover` ile yeniden bağlanma {#reconnecting-with-prior_discover}

Sorgu ucuzdur, ancak yine de her yeniden bağlanmada ödediğiniz bir turdur ve yanıt neredeyse hiç değişmez.

Öyleyse saklayın. Bir `auto` bağlantısından sonra `client.session.discover_result`, sunucunun gönderdiği `DiscoverResult`'ı olduğu gibi tutar: `supported_versions`, `capabilities`, `instructions` ve sunucunun sonucun `_meta` alanına işlediği kimlik. Bir sonraki sefer bunu `prior_discover=` olarak geri verin:

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

İkinci bağlantı **sıfır** anlaşma turu yaptı ve yine de kiminle konuştuğunu tam olarak biliyor. Sabitlenmiş modun doğru yapılmış hali budur: `mode=` sürümü adlandırır, `prior_discover=` kimliği sağlar. ✨

`DiscoverResult` bir Pydantic modelidir. `saved.model_dump_json()` bir dosyaya ya da önbelleğe gider; `DiscoverResult.model_validate_json(...)` onu bir sonraki süreçte geri getirir.

!!! tip
    `prior_discover=` yalnızca `mode` bir sürüm sabitlemesi olduğunda bir işe yarar. `"auto"` altında
    istemci sunucuyu zaten sorgular, `"legacy"` altında ise yok sayılır.

## Dört mod {#the-four-modes}

| Yazdığınız | Anlaşma trafiği | Elde ettiğiniz |
| --- | --- | --- |
| `Client(target)` | tek bir `server/discover` sorgusu; başarısız olursa `initialize` el sıkışması | her iki tarafın da konuştuğu en yeni sürüm, hangi nesilden olursa olsun |
| `Client(target, mode="legacy")` | `initialize` el sıkışması | el sıkışma neslinden bir sürüm; sunucunun başlattığı istekler çalışır |
| `Client(target, mode="2026-07-28")` | yok | o sürüm, sabitlenmiş, `server_info` değeri `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | yok | o sürüm, sabitlenmiş, *ve* geçen sefer kaydettiğiniz kimlik |

## Özet {#recap}

* MCP'nin bir el sıkışma nesli (`2025-11-25`'e kadar, `initialize` el sıkışması) ve bir modern nesli (`2026-07-28`, `server/discover`) var. `Client` ikisi arasında köprü kurar.
* `mode="auto"` varsayılandır: sorgula, geri dön. Diğer üç satırdan biri sizi anlatmıyorsa dokunmayın.
* "Ne elde ettim?" sorusunun yanıtı her zaman `client.protocol_version`.
* `mode="legacy"` el sıkışmayı zorunlu kılar. Sunucunun başlattığı istekler için gereken budur: örnekleme, push tarzı elicitation, `message_handler`.
* Sürüm sabitlemesi (`mode="2026-07-28"`) hiç anlaşma trafiği göndermez; bedeli `client.server_info` değerinin `None` olmasıdır.
* `prior_discover=` bu bedeli geri öder: `client.session.discover_result`'ı kaydedin, onunla yeniden bağlanın, ikisini de elde edin.

Modern bir bağlantıda push kanalı yok; peki bir 2026 sunucusu çağrının ortasında size nasıl soru sorar? Soruyu döndürür: **[Çok turlu istekler](handlers/multi-round-trip.md)**.
