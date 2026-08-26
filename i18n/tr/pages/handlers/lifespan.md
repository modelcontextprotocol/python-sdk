---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Lifespan {#lifespan}

Gerçek sunucuların çoğu, ömürleri boyunca bir şeyi elde tutar: bir veritabanı havuzu, bir HTTP istemcisi, yüklenmiş bir model.

Bunu her çağrıda yeniden kurmak istemezsiniz, ama düzgünce kapatmak istersiniz. İşte **lifespan** (yaşam döngüsü) bunun için var.

## Türü belirli bir lifespan {#a-typed-lifespan}

Lifespan, sunucuyu alan ve **tek bir nesne** `yield` eden bir `@asynccontextmanager`'dır. Yield ettiğiniz şey, sunucu çalıştığı sürece her işleyicinin erişimindedir.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

Aşağıdan yukarıya okuyun:

* `app_lifespan`, `Database`'i `yield`'den **önce** bağlar, **sonra** da bir `finally` içinde bağlantısını keser. İşte başlatma ve kapatma.
* Bir `AppContext` yield eder: kurduğunuz şeyleri tutan düz bir dataclass. Bugün bir alan, yarın on.
* Bağlamanın tamamı `MCPServer("Bookshop", lifespan=app_lifespan)` satırından ibaret.
* Aracın içinde, yield edilen nesne `ctx.request_context.lifespan_context`'tir.

Lifespan **bir kez** çalışır. Sunucu başladığında (ilk istekten önce) içine girilir, sunucu durduğunda içinden çıkılır. Aradaki her istek aynı `AppContext`'i paylaşır.

!!! info
    Daha önce bir FastAPI `lifespan`'i yazdıysanız bunu zaten biliyorsunuz. Aynı dekoratör, aynı `yield`, aynı `finally`.

### Modelin gördüğü {#what-the-model-sees}

Yeni bir şey yok. `ctx` bir **Context** parametresidir; bu yüzden SDK onu enjekte eder ve girdi şemasına hiç ulaşmaz:

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

Modelin geçirebileceği tek argüman `genre`. Lifespan sunucunuzun kendi işidir.

`@mcp.resource()` ve `@mcp.prompt()` fonksiyonları da `ctx` parametresi alabilir; bir sonraki bölümün açıklayacağı bir nedenle bu parametre yalın `Context` olarak yazılır. `ctx`'in taşıdığı her şey **[Context nesnesi](context.md)** sayfasında.

### Gerçekten türü belirli {#it-really-is-typed}

Tür açıklamasına bir daha bakın: `ctx: Context[AppContext]`.

Tür denetleyiciniz için `ctx.request_context.lifespan_context`'in bir `AppContext` **olmasını** sağlayan işte bu tek tür parametresidir. `.db` otomatik tamamlanır; `.dbb` ise daha sunucuyu çalıştırmadan hata verir.

Bunun yerine yalın `Context` yazarsanız `lifespan_context`'in türü `dict[str, Any]` olur: tür denetleyicisinin, lifespan'inizin ne yield ettiğini bilmesinin yolu yoktur. Nesne çalışma zamanında yine oradadır; yalnızca yardımı kaybedersiniz.

!!! warning
    `Context[AppContext]` **yalnızca araçlara özgü** bir yazımdır. Bunu bir `@mcp.resource()` ya da
    `@mcp.prompt()` fonksiyonuna koyarsanız o işleyiciye yapılan her çağrı başarısız olur. İstemciye bir hata döner,
    sunucu log'u da nedenini gösterir:

    ```text
    Context is not available outside of a request
    ```

    Kaynaklarda ve prompt'larda yalın `ctx: Context` yazın. Lifespan'inizin yield ettiği nesne
    çalışma zamanında yine `ctx.request_context.lifespan_context`'tir; vazgeçtiğiniz şey nesne değil,
    tür parametresidir.

!!! tip
    Her zaman bir lifespan vardır. Siz bir tane geçirmezseniz SDK'nın varsayılanı boş bir `dict` yield eder;
    dolayısıyla `ctx.request_context.lifespan_context` `{}` olur, asla `None` değil. Yalın `Context`'in
    onu `dict[str, Any]` olarak türlendirmesinin nedeni de bu varsayılandır.

## İşleyişi gözlemleme {#watch-it-happen}

"Başlatma ilk istekten önce çalışır" cümlesi, körü körüne inanmak zorunda kalmamanız gereken türden bir cümle.

Sunucuyu yaşam döngüsüne kadar sadeleştirin: `Database`'e bir `connected` bayrağı verin, `connect()` ve `disconnect()` içinde değiştirin ve onu bildiren bir araç ekleyin.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database`'in modül düzeyinde durmasının tek bir nedeni var: ona sunucunun *dışından* bakabilmeniz.

!!! check
    Üç an, üç değer:

    * Sunucu başlamadan önce `database.connected` `False`'tur. Modülü içe aktarmak hiçbir şeyi bağlamadı.
    * Çalışırken `database_status` aracını çağırın; sonuç `"connected"` olur.
    * Sunucuyu durdurun, `finally` bloğu çalışır: `database.connected` yeniden `False` olur.

    İş tam olarak koyduğunuz yerde yapıldı: `yield`'in etrafında; ne içe aktarma sırasında ne de istek başına.

## Özet {#recap}

* `lifespan=`, sunucuyu alan ve tek bir nesne `yield` eden bir `@asynccontextmanager` alır.
* `yield`'den önceki kod başlatmadır. Sonrasındaki `finally` kapatmadır.
* İstek başına değil, sunucunun tüm ömrü boyunca bir kez çalışır.
* `yield` ettiğiniz şey her araçta, kaynakta ve prompt'ta `ctx.request_context.lifespan_context` olur.
* `ctx: Context[AppContext]` bu erişimi araçlarda tam tür bilgisiyle donatır. Kaynaklar ve prompt'lar yalın `Context` alır.
* `lifespan=` yoksa boş bir `dict` gelir, asla `None` değil.

Çağrının ortasında durup kullanıcıya yalnızca onun bildiği bir şeyi soran işleyici, **[Elicitation](elicitation.md)** (kullanıcıdan bilgi isteme) sayfasının konusu.
