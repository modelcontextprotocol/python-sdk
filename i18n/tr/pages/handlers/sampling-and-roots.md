---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# Örnekleme ve kök dizinler {#sampling-and-roots}

Bir işleyici, bağlı istemciden iki şey daha isteyebilir: istemcinin kendi modelinden bir tamamlama (**örnekleme (sampling)**) ve istemcinin çalışma alanı klasörleri (**kök dizinler (roots)**).

İkisi de SDK'nın konuştuğu her protokol sürümünde hâlâ çalışır. Ancak tasarımınızı bunların üzerine kurmadan önce uyarıyı okuyun:

!!! warning "2026-07-28 spesifikasyonuyla kullanım dışı bırakıldı"
    Örnekleme ve kök dizinler `2026-07-28` itibarıyla kullanım dışı bırakıldı ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). Tamamen işlevsel olmaya devam ederler ve kaldırılmaya aday hâle gelmeden önce en az on iki ay boyunca spesifikasyonda kalırlar; yine de yeni uygulamalar bunların üzerine kurulmamalıdır. Önerilen geçiş yolları: örnekleme yerine doğrudan LLM sağlayıcınızın API'siyle entegre olun; kök dizinler yerine dizinleri araç parametreleri, kaynak URI'leri veya sunucu yapılandırması üzerinden geçirin. SDK genelindeki liste **[Kullanım dışı özellikler](../deprecated.md)** sayfasında.

## Örnekleme: istemcinin modelini ödünç alma {#sampling-borrow-the-clients-model}

Bir çözümleyici `Sample(...)` döndürür ve araç tamamlamayı alır; bu, **[Bağımlılıklar](dependencies.md)** sayfasında `Elicit`'i çalıştıran bağımlılık mekanizmasının aynısıdır:

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)`, `sampling/createMessage` parametrelerini yansıtır. Enjekte edilen değer istemcinin `CreateMessageResult`'ıdır; `tools` veya `tool_choice` geçirirseniz bunun yerine bir `CreateMessageResultWithTools` olur.
* İstemcinin `sampling` yeteneğini bildirmiş olması gerekir (`tools` veya `tool_choice` geçiriyorsanız `sampling.tools`). Bildirmediyse çağrı, istemcinin işleyemeyeceği bir istek göndermek yerine `-32021` protokol hatasıyla başarısız olur. Geri kanalı (back-channel) olmayan 2026 öncesi bir oturum, gönderecek bir yer olmadığından her zamanki geri-kanal-yok hatasıyla başarısız olur.
* `2026-07-28`'de istek, çok turlu (multi-round-trip) akışın içinde iletilir (**[Çok turlu istekler](multi-round-trip.md)**); `2025-11-25`'te ise istemciye gönderilen bağımsız bir istektir. Kod her iki durumda da aynıdır, ancak çok turlu kurala dikkat edin: istek, yeniden deneme turları boyunca birebir aynı şekilde oluşmalıdır. Bu yüzden onu yalnızca aracın argümanlarından ve diğer kararlı verilerden oluşturun.
* `include_context`'e dokunmayın: `"none"` dışındaki değerlerin kendisi de kullanım dışı bırakıldı (SEP-2596) ve neredeyse hiçbir istemcinin bildirmediği bir yetenek gerektirir.

## Kök dizinler: bu nereye gitmeli? {#roots-where-should-this-go}

Kök dizinler, istemcinin sunucunun üzerinde çalışabileceğini söylediği klasörlerdir. Bilgilendirme amaçlı bir yönlendirmedir, erişim denetimi mekanizması değil. Bir çözümleyici `ListRoots()` döndürür:

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* Enjekte edilen `ListRootsResult`, bir `Root` listesi taşır: her biri bir `file://` URI'si ve isteğe bağlı bir görünen ad.
* Denetim örneklemeyle aynıdır: bildirilmiş bir `roots` yeteneği yoksa çağrı, isteği göndermek yerine `-32021` ile başarısız olur.

Bağlantının diğer ucunda istemci, her iki isteği de zaten sahip olduğu callback'lerle yanıtlar: **[İstemci callback'leri](../client/callbacks.md)** sayfasında anlatılan `sampling_callback` ve `list_roots_callback`.

## 2025 neslinden bağlantılarda {#on-2025-era-connections}

`ctx.session.create_message(...)` ve `ctx.session.list_roots()`, oturumu doğrudan yöneten kod için hâlâ mevcuttur. Yalnızca bir geri kanalın bulunduğu yerde (2025 neslinden, durumsuz olmayan bağlantılarda) çalışırlar ve çağrıldıklarında kullanım dışı bırakma uyarısı verirler. Desteklenen biçim yukarıdaki çözümleyici işaretçileridir: iletim yolunu anlaşılan sürüme göre seçerler ve uyarı vermezler.

## Özet {#recap}

* Bir çözümleyiciden `Sample(...)` veya `ListRoots()` döndürün; araç `CreateMessageResult`'ı veya `ListRootsResult`'ı diğer bağımlılıklar gibi alır.
* İstemcinin eşleşen yeteneği bildirmesi gerekir; aksi hâlde çağrı, bir istek gönderilmek yerine `-32021` ile başarısız olur.
* İki özellik de `2026-07-28`'de kullanım dışı bırakıldı: şimdilik tamamen işlevsel, ancak yeni tasarımlar için yanlış tercih. Örnekleme yerine sağlayıcı API'lerini, kök dizinler yerine açık parametreleri tercih edin.

Yavaş bir aracın ne kadar ilerlediğini bildirme: **[İlerleme](progress.md)**.
