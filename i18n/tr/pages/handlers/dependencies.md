---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# Bağımlılıklar {#dependencies}

Bir aracın argümanları modelden gelir. Bazı değerlerse asla modelden gelmemelidir: kayıtlarınızdan bakılan bir fiyat, yalnızca bir insanın verebileceği bir onay, modelin uydurarak yanlış yapabileceği her şey.

**Bağımlılıklar**, kendi fonksiyonlarınızın doldurduğu parametrelerdir. Parametreye tür açıklamasını eklersiniz, fonksiyonu belirtirsiniz; SDK da araç çalışmadan önce onu çağırır.

## Bir bağımlılık bildirme {#declare-one}

Parametrenin türünü `Annotated[...]` içine sarın ve `Resolve(fn)` ekleyin:

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` bir **çözümleyicidir**: SDK'nın `reserve_book`'tan önce çalıştırdığı, dönüş değeri `stock` argümanı hâline gelen sıradan bir fonksiyon.
* `title` parametresi, aracın kendi `title` argümanıdır ve **ada göre** eşleştirilir. Çözümleyici, araç gövdesinin göreceği doğrulanmış değerin aynısını görür.
* Araç gövdesi, zaten var olan bir `Stock` ile işe başlar. Araçta arama kodu yok, "ya yoksa" diye başlayan bir giriş yok.

!!! info
    FastAPI kullandıysanız bu, `Depends`'in karşılığıdır. Aynı hamle, aynı gerekçe: fonksiyon
    neye ihtiyacı olduğunu bildirir, framework bunu sağlar ve bağlantı tür açıklamasında durur.

### Modele görünmez {#invisible-to-the-model}

`tools/list`'in `reserve_book` için bildirdiği giriş şeması şöyle:

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

Tek bir özellik. **[Context nesnesi](context.md)** sayfasındaki `Context` gibi, çözümlenmiş bir parametre de sizinle SDK arasındaki bir sözleşmedir: `stock` şemada yer almaz, modele ondan hiç söz edilmez ve yine de bir `stock` değeri gönderen istemci yok sayılır. Aracınızın alabileceği tek değer çözümleyicinin değeridir.

Asıl mesele de bu son kısım. Modelin sağlayamadığı bir parametre, modelin yanlış yapamayacağı bir parametredir.

### Deneyin {#try-it}

Sunucuyu MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

`reserve_book` formunda tek bir `title` alanı var. `stock` hiçbir yerinde yok. `Dune` ile çağırın:

```text
Reserved 'Dune' (6 copies left).
```

Araç gövdesi hiçbir şey aramadı: önce `check_stock` çalıştı, döndürdüğü `Stock` da argüman olarak geldi. `Neuromancer`'ı deneyin; aynı çözümleyici araca sıfır verir.

!!! tip
    Araç gövdesinde doğrudan `check_stock(title)` da çağırabilirdiniz. Değer bir yardımcı fonksiyon
    çağrısından fazlasını hak ettiğinde onu bağımlılık olarak bildirin: stok bilgisine ihtiyaç duyan
    her araç aynı parametreyi bildirir ve kaç tanesi bildirirse bildirsin SDK çözümleyiciyi çağrı
    başına en fazla bir kez çalıştırır. Sonraki bölümler geri kalanını ekler: birbirine bağımlı
    çözümleyiciler ve kullanıcıya soru soran çözümleyiciler.

## Bağımlılıkların bağımlılıkları {#dependencies-of-dependencies}

Bir çözümleyici, aynı tür açıklamasıyla kendi bağımlılıklarını bildirebilir:

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery`, `check_stock`'a bağımlıdır. SDK grafiği sırayla çalıştırır: önce stok, sonra tahmin, sonra araç.
* Hem `stock` hem `delivery` sonuçta `check_stock`'a ihtiyaç duyar, ama o **çağrı başına bir kez** çalışır. Tek bir envanter sorgusu, iki tüketici.
* Kaydedilecek hiçbir şey yok. Grafik, tür açıklamalarının *ta kendisidir*.

!!! check
    Çağrı başına bir kez çalıştığına körü körüne inanmayın. `check_stock`'un içine bir `print` koyun
    ve Inspector'dan `order_book`'u çağırın: çağrı başına tek satır. İki tüketici, tek sorgu.

SDK grafiği araç çağrıldığında değil, kaydedildiğinde analiz eder. Sınıflandıramadığı bir parametre (ne `Context`, ne `Resolve(...)`, ne de bir araç argümanının adı) ve çözümleyiciler arasındaki bir döngü, her ikisi de başlangıçta `InvalidSignature` fırlatır. Sunucu, daha hiçbir istemci bağlanmadan başarısız olur; hataya yol açan parametre veya çözümleyici hata mesajında adıyla belirtilir.

Bir çözümleyicinin parametreleri tıpkı bir aracınkiler gibi çözümlenir: başka bir `Resolve(...)`, ada göre aracın kendi argümanları veya `Context` (`ctx.headers`, lifespan (yaşam döngüsü) nesnesi, hepsi).

!!! warning
    HTTP aktarımlarında `Context`, `ctx.headers`'ı da içerir. Başlıklar, her araç argümanı gibi
    **istemcinin sağladığı girdidir**: bir yerel ayar veya özellik bayrağı için uygundur, kimlik için
    asla. Çağıranın kim olduğu, herkesin ayarlayabileceği bir başlıktan değil, yetkilendirme
    katmanınızdan gelir (**[Yetkilendirme](../run/authorization.md)**).

!!! tip
    *Çağrı başına bir kez* tam olarak bunu ifade eder: bir sonraki `tools/call`, `check_stock`'u
    yeniden çalıştırır. Bir istekten uzun yaşaması gereken bir kaynağın (bir veritabanı havuzu, bir
    HTTP istemcisi) yeri **[Lifespan](lifespan.md)** sayfasıdır; bir çözümleyici ona
    `ctx.request_context.lifespan_context` üzerinden ulaşabilir.

## Yalnızca gerektiğinde sormak {#ask-when-you-must}

Bir çözümleyici yanıtı bilmek zorunda değildir. `Elicit(message, Model)` döndürebilir; SDK da kullanıcıya sorar. Bu, sizin yerinize çalıştırılan **[Elicitation](elicitation.md)** (kullanıcıdan bilgi isteme) mekanizmasıdır:

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* Stokta varsa: `confirm_backorder` doğrudan bir `Backorder` döndürür. **Soru yok, gidiş-dönüş yok.** Kullanıcı yalnızca yanıtı önemli olduğunda rahatsız edilir.
* Stokta yoksa: SDK elicitation'ı gönderir, yanıtı `Backorder`'a göre doğrular ve enjekte eder. Çözümleyiciniz protokole hiç dokunmaz.
* Araç, `backorder.confirm`'ü diğer argümanlar gibi okur. **Hayır** yanıtı da bir yanıttır: elicitation `confirm=False` ile kabul edilir, araç çalışır ve sipariş verilmez. Sormak, araç gövdesindeki bir tesisat işi değil, bir ön koşul hâline geldi.

Peki ya kullanıcı hiç yanıt vermezse, yani soruyu reddeder veya iptal ederse?

!!! check
    `Neuromancer` için `order_book`'u çalıştırın ve soruyu reddedin. Tür açıklaması
    `Annotated[Backorder, Resolve(...)]` biçiminde yazıldığında araç gövdesi hiç çalışmaz; çağrı,
    modelin okuyabileceği bir hata sonucuyla başarısız olur:

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

Bir ön koşul için doğru varsayılan budur: yanıt yoksa sipariş de yok. Reddetme, aracınızın ele almak istediği bir sonuçsa (ön siparişi atlayıp yine de başka bir kitap önermek gibi) tür açıklamasını bunun yerine `ElicitationResult[Backorder]` olarak yazın; araç, dallanabileceği tam accept/decline/cancel sonucunu alır. **[Elicitation](elicitation.md)** sayfası bu biçimi ve sormaya dair diğer her şeyi gösterir: şema kuralları, üç yanıt, konuşmanın istemci tarafı.

!!! info
    Framework, sorunun aktarımını anlaşılan protokol sürümüne göre seçer; yukarıdaki kod her
    ikisinde de aynıdır. **2026-07-28** ve sonrasında soru, çok turlu (multi-round-trip) bir
    `tools/call` içinde taşınır: sunucu soruyu döndürür, istemcinin `elicitation_callback`'i
    yanıtlar ve `Client` çağrıyı sizin yerinize yeniden dener
    (**[Çok turlu istekler](multi-round-trip.md)**). **2025-11-25** ve öncesinde ise çağrının
    ortasında senkron bir elicitation isteğidir. Her soru çağrı başına tam olarak bir kez sorulur;
    bu, çözümleyici hakkında değil soru hakkında bir garantidir. Çok turlu biçimde, çağrı bir sorudan
    sonra her sürdüğünde herhangi bir çözümleyici yeniden çalışabilir; dolayısıyla
    `return Elicit(...)` satırından önceki kod bu turların her birinde çalışır. Kaydedilmiş yanıt,
    tekrarlanan soruyu kullanıcıya yeniden sormadan karşılar. Kaydedilmiş bir yanıta yalnızca
    çözümleyici soru sorduğunda başvurulur; `check_stock` gibi *sormadan* yanıt veren bir
    çözümleyici her zaman kendi hesapladığı değeri sağlar. Her yanıt kendi sorusuyla
    eşleştirildiğinden, elicitation yapan bir çözümleyici sorusunu aracın argümanlarından ve önceki
    yanıtlardan deterministik olarak türetmelidir. Çağrı başına üretilen bir değer (bir
    `default_factory` kimliği, bir zaman damgası) her turda yeniden türetilir ve yanıtın bağlanması
    gereken bir soruda yer almamalıdır. Bu tür uçucu verilerden kurulan bir soru, kaydedilmiş her
    yanıtı bayat gösterir; bu yüzden sunucu, istemcinin tur sınırı çağrıyı sonlandırana kadar
    soruyu her turda yeniden sorar.

## Kullanıcıya değil, istemciye sormak {#ask-the-client-not-the-user}

Elicitation, bir çözümleyicinin sorabileceği üç sorudan biridir ve çok turlu akış başkasına izin vermez. Diğer ikisi kullanıcıya değil **istemciye** gider: istemci üzerinden bir LLM çağrısı çalıştırmak için `Sample(...)` (bir `sampling/createMessage` isteği), istemcinin güncel kök dizinlerini (roots) almak için `ListRoots()` döndürün. Hiçbirinin accept/decline sonucu yoktur; tüketici, tür açıklaması olarak doğrudan sonuç türünü yazar: `CreateMessageResult` (istek `tools` veya `tool_choice` taşıdığında `CreateMessageResultWithTools`) ya da `ListRootsResult`:

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* Framework bunları tıpkı `Elicit` gibi yönlendirir: **2026-07-28** sürümünde çok turlu `tools/call` içinde, **2025-11-25** sürümünde bağımsız sunucu->istemci isteği üzerinden. Bildirilmemiş bir yetenek, çağrıyı `-32021` protokol hatasıyla reddeder (`sampling`, `roots`, form kipinde `elicitation`; istek `tools` veya `tool_choice` taşıdığında `sampling.tools`).
* Yukarıdaki bilgi kutusunun sorular hakkında söylediği her şey aynen geçerlidir: bir `Sample` isteği, kaydedilmiş sonucuyla birebir gösterimine göre eşleştirilir; bu yüzden onu aracın argümanlarından ve önceki yanıtlardan deterministik olarak kurun. Böylece istemci, LLM çağrısının bedelini tur başına değil araç çağrısı başına bir kez öder. Kaydedilmiş sonuç çağrının geri kalanında `request_state` içinde taşınır; bu nedenle çok büyük bir tamamlama, kalan her gidiş-dönüşü ağırlaştırır.
* Bağımsız örnekleme (sampling) ve kök dizinler *özellikleri* 2026-07-28 itibarıyla kullanım dışı bırakıldı (SEP-2577). İstemcinin modeline ihtiyaç duyan yeni sunucular bu taşıyıcı üzerinden sorar; duymayanlar doğrudan bir LLM sağlayıcısıyla entegre olmalıdır. `"none"` dışındaki `include_context` değerlerinin kendisi de kullanım dışıdır; bunları kullanmayın.

## Özet {#recap}

* Bir araç parametresinde `Annotated[T, Resolve(fn)]`: SDK `fn`'i çalıştırır ve dönüş değerini enjekte eder.
* Çözümlenmiş bir parametre modele görünmez; istemci de onu sağlayamaz. Modelin uydurmaması gereken değerlerin (fiyatlar, kimlikler, izinler) yeri burasıdır.
* Bir çözümleyicinin parametreleri de aynı şekilde çözümlenir: `Context`, başka bir `Resolve(...)` veya ada göre bir araç argümanı. Grafik, kaç tüketicisi olursa olsun her çözümleyiciyi tur başına en fazla bir kez çalıştırır; her soru tam olarak bir kez sorulur ve çağrı bir sorudan sonra sürdüğünde herhangi bir çözümleyici yeniden çalışabilir.
* Hatalı grafikler çağrı ortasında değil, kayıt sırasında `InvalidSignature` ile başarısız olur.
* Kullanıcıya sormak için, yalnızca mecbur kaldığınızda, `Elicit(message, Model)` döndürün. Sarmalanmamış tür açıklamaları reddedildiğinde çağrıyı iptal eder; `ElicitationResult[T]` aracın dallanmasına izin verir.
* İstemciden bir LLM tamamlaması veya kök dizin listesi istemek için `Sample(...)` ya da `ListRoots()` döndürün; yalın sonuç enjekte edilir.

Sunucunuzun başlangıçta bir kez kurduğu durum ve bir işleyicinin ona nasıl ulaştığı **[Lifespan](lifespan.md)** sayfasının konusudur.
