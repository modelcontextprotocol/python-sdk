---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# İleri düzey {#advanced}

Sıradan bir sunucunun ya da istemcinin ihtiyaç duyduğu her şeyin yukarıdaki bölümlerde konusuna göre bir yeri var.
Bu bölüm ise `MCPServer`'ın kolaylık katmanı size engel olduğunda başvuracağınız
kaçış yollarını içerir:

* **[Alt düzey Server](low-level-server.md)**: `MCPServer`'ın üzerine kurulduğu sınıf.
  Elle yazılmış şemalar, `on_*` işleyicileri, sizin yerinize denetlenen hiçbir şey yok
  ve kendinize ait özel JSON-RPC metotları.
* **[Sayfalama](pagination.md)** ve **[Middleware](middleware.md)**: *yalnızca*
  alt düzey `Server` üzerinde yapabileceğiniz iki şey.
* **[Uzantılar](extensions.md)** ve **[MCP Apps](apps.md)**: protokolün uzantı
  yüzeyi. Uzantı paketlerini bir sunucuda bir araya getirin ya da kendinizinkini yazın.

Burada aramanız gayet doğal olan birkaç konu ise aslında onları kullanacağınız yerde
duruyor:

* **Yetkilendirme**, **[Sunucunuzu çalıştırma](../run/index.md)** altında; çünkü
  bir sunucuyu dağıttığınız yerde korursunuz.
* **OAuth**, **kimlik beyanı**, **birden çok sunucuya** bağlanma ve yanıt
  **önbelleği**, hepsi **[İstemciler](../client/index.md)** altında.
* **Çok turlu istekler** (multi-round-trip) ve **Abonelikler**,
  **[İşleyicinin içinde](../handlers/index.md)** altında; çünkü ikisi de bir
  işleyicinin *yaptığı* şeyler.
* **URI şablonları**, **[Sunucular](../servers/index.md)** altında, Kaynaklar'ın hemen yanında.
* **[Protokol sürümleri](../protocol-versions.md)** ve
  **[Kullanım dışı özellikler](../deprecated.md)** sayfalarının her birinin kendi üst düzey sayfası var.

Bu bölüme ihtiyacınız olup olmadığından emin değilseniz, yok demektir.
