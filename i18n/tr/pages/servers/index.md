---
translation:
  sections: [09defc170a0da89d]
  tool: 1
---
# Sunucular {#servers}

Bir `MCPServer`, bağlı bir istemciye üç temel yapı taşı sunar. Aralarındaki fark, onları kullanmaya kimin karar verdiğidir:

* **[Araç](tools.md)**, *modelin* seçip çağırdığı bir eylemdir. Çoğu kişinin
  önce görmek istediği sayfa budur;
  **[Yapılandırılmış çıktı](structured-output.md)** ise onun başvuru
  eşlikçisidir: bir aracın döndürdüğü şeyin biçimiyle ilgili her şey orada.
* **[Kaynak](resources.md)**, *uygulamanın* okumayı seçtiği salt okunur
  veridir. **[URI şablonları](uri-templates.md)** onun başvuru
  eşlikçisidir: adresleme sözdiziminin tamamı ve yol güvenliği kuralları.
* **[Prompt](prompts.md)**, bir *kişinin* menüden ya da eğik çizgi
  komutuyla adıyla çağırdığı bir mesaj şablonudur.

Bu üç yapı taşının etrafında, bir sunucunun bildirdiği diğer her şey yer alır:

* **[Tamamlamalar](completions.md)**, prompt ve kaynak şablonu argümanları
  için sunucu tarafında otomatik tamamlamadır.
* **[Görseller, ses ve simgeler](media.md)**, bir aracın metin dışında
  döndürebileceği her şeyi ve bir istemcinin sunucunuzun yanında gösterdiği
  simgeleri kapsar.
* **[Hataları ele alma](handling-errors.md)**, modelin toparlayabileceği bir
  hata ile asla görmemesi gereken bir hata arasındaki farkı açıklar.

Buradaki her sayfa kendi başına okunabilir; doğrudan ihtiyacınız olana geçin. Henüz
bir sunucu oluşturmadıysanız bunun yerine **[İlk adımlar](../get-started/first-steps.md)** sayfasıyla başlayın.

Kaydettiğiniz fonksiyonların *içinde* olup bitenler (`Context`, bağımlılık enjeksiyonu,
çağrının ortasında kullanıcıdan ek girdi isteme) bir sonraki bölümün konusu:
**[İşleyicinin içinde](../handlers/index.md)**.
