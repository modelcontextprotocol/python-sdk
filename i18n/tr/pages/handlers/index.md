---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# İşleyicinin içinde {#inside-your-handler}

Bir işleyicinin argümanları istemciden gelir. Okuyabildiği *diğer* her şey ve
çalışırken yapabildiği her şey burada.

Okuyabildikleri:

* **[Context nesnesi](context.md)**, herhangi bir işleyicinin isteyebileceği
  tek ek parametredir: canlı istek, başlıkları, oturumu, ayrıca ilerleme ve
  değişiklik bildirimi eylemleri.
* **[Bağımlılıklar](dependencies.md)**, modelin hiç görmediği
  parametrelerdir; değerlerini `Resolve` ile kendi fonksiyonlarınız doldurur.
* **[Lifespan](lifespan.md)** (yaşam döngüsü), sunucunun başlangıçta bir kez
  oluşturduğu durumu ve bir işleyicinin bu duruma `Context` üzerinden nasıl
  ulaştığını ele alır.

Çalışırken yapabildikleri:

* **[Elicitation](elicitation.md)** (kullanıcıdan bilgi isteme) ve onu taşıyan
  2026-07-28 deseni olan **[Çok turlu istekler](multi-round-trip.md)**
  (multi-round-trip) ile kullanıcıdan ek girdi istemek.
* Kullanım dışı bırakılmış ama hâlâ sunulan
  **[Örnekleme (sampling) ve kök dizinler (roots)](sampling-and-roots.md)**
  ile istemciden bir LLM tamamlaması ya da çalışma alanı klasörlerini istemek.
* Yavaş bir işte **[İlerleme](progress.md)** bildirmek.
* **[Log tutma](logging.md)** ile log yazmak (sunucuyu kim işletiyorsa onun
  için, standart hataya).
* **[Abonelikler](subscriptions.md)** ile abone olmuş istemcilere bir şeyin
  değiştiğini bildirmek.

Henüz bir işleyici kaydetmediyseniz **[Araçlar](../servers/tools.md)**
sayfasıyla başlayın. Buradaki her sayfa bir işleyiciniz olduğunu varsayar.
