---
translation:
  sections: [f671b445b16e4f99, 3983a560eb2cece7, b5c8bd4f2b3903e5, c6e2debf1da06eb7, 81d412ed5f399f94]
  tool: 1
---
# Çeviriler {#translations}

Bu belgeler İngilizce yazılmıştır. Daha fazla kişinin yararlanabilmesi için makine çevirisiyle hazırlanmış sürümlerini de yayımlıyoruz. Bu sayfa, bunun sizin için ne anlama geldiğini ve çevirileri iyileştirmeye nasıl yardımcı olabileceğinizi açıklar.

## Mevcut çeviriler {#whats-available}

Çevrilmiş belgeler şu anda on iki dilde **önizleme** aşamasındadır: Deutsch, español, français, हिन्दी, 日本語, 한국어, português (Brasil), русский язык, Türkçe, українська мова, 简体中文 ve 繁體中文. Herhangi bir sayfanın üst kısmındaki dil seçiciden birini seçin. Bunlar kendini kanıtladıktan sonra başka diller de eklenebilir.

API başvurusu çevrilmez: çevrilmiş site, tek olan İngilizce başvuruya bağlantı verir.

## Esas alınan metin İngilizcedir {#english-is-the-source-of-truth}

Çevrilmiş bir sayfa ile İngilizce aslı çelişirse doğru olan İngilizce sayfadır. Çevrilmiş bir sitenin her sayfası, sayfanın durumunu belirten üç nottan biriyle başlar:

- **Makine çevirisi** — sayfa otomatik olarak çevrilmiştir ve İngilizce aslına bağlantı verir.
- **İngilizce sayfanın gerisinde kalan çeviri** — İngilizce aslı, sayfa çevrildikten sonra değişmiştir. Hâlâ o çeviriyi okuyorsunuz; bu yüzden çeviri yetişene kadar bazı bölümleri güncel olmayabilir. Not, güncel İngilizce sayfaya bağlantı verir.
- **İngilizce gösteriliyor** — sayfa henüz çevrilmemiştir; bu yüzden İngilizce metni okuyorsunuz.

## Çevirilerin hazırlanışı {#how-the-translations-are-made}

Çevrilmiş sayfaları, bu depodaki bir araç `docs/` altındaki İngilizce sayfalardan otomatik olarak üretir. Araca her dil için insan eliyle yazılmış iki girdi yol gösterir: bir stil kılavuzu (dil düzeyi, ton, tipografi, şakaların ve deyimlerin nasıl ele alınacağı) ve bir sözlükçe (hangi terimlerin İngilizce kalacağı, geri kalanlar için zorunlu ve yasak karşılıklar). Üretilen metin hiçbir zaman elle düzenlenmez. Her iyileştirme bunun yerine bu girdilere işlenir; böylece sayfalar bir sonraki kez yeniden üretildiğinde kaybolmaz.

## Çeviri sorunu bildirme {#reporting-a-translation-problem}

Yanlış bir terim, tuhaf bir cümle ya da İngilizcede olmayan bir şey söyleyen bir çeviri mi buldunuz? Dili, sayfayı ve ilgili bölümü belirterek [bir issue açın](https://github.com/modelcontextprotocol/python-sdk/issues); ana dili konuşanlardan gelen bildirimler özellikle değerlidir. Düzeltmeyi biliyorsanız, doğrudan [`i18n/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/i18n) altındaki ilgili dilin stil kılavuzuna (`instructions.md`) veya sözlükçesine (`glossary.json`) bir pull request olarak önerin. Düzeltme, çeviriler bir sonraki kez yeniden üretildiğinde etkilenen tüm sayfalara ulaşır. İngilizce metnin kendisindeki sorunlar ise diğer belge değişiklikleri gibi `docs/` altındaki sayfalarda düzeltilir.
