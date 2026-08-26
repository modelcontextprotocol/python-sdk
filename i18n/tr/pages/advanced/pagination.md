---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# Sayfalama {#pagination}

Çoğu sunucunun buna hiç ihtiyacı olmaz.

`MCPServer`, her `list_*` isteğini elindeki her şeyle, tek sayfada, `next_cursor=None` ile yanıtlar. Birkaç düzine araç, kaynak veya prompt için doğru yanıt budur ve yapılandıracak bir şey yoktur.

Sayfalama, kaynak listesi aslında bir veritabanı olan sunucu içindir: tek yanıtta serileştirmeyi reddettiği binlerce satır. Protokolün buna yanıtı **imleç**tir (cursor): sunucu bir sayfa ile birlikte opak bir token döndürür, istemci de sonraki sayfayı almak için bu token'ı geri gönderir.

`@mcp.resource()`'ta bunların hiçbiri için bir kanca yoktur. Sayfalamak için liste işleyicisini **[düşük seviyeli Server](low-level-server.md)** üzerinde kendiniz yazarsınız.

## Sayfalayan bir sunucu {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* Düşük seviyeli bir `Server`'da işleyiciler dekoratör değil, kurucu argümanlarıdır. `on_list_resources` her `resources/list` isteğini yanıtlar; bağlantının tamamı bu.
* Sayfalanan her işleyicinin türü `params: PaginatedRequestParams | None`'dır ve örnek ikisini de kabul eder. Ancak bir bağlantı üzerinden SDK size hiçbir zaman `None` vermez (`params` üyesi olmayan bir istek, işleyiciye varsayılan değerleriyle model olarak ulaşır); bu yüzden önemli olan sinyal `params.cursor is None`'dır: **en baştan başla**.
* Bir imlecin *ne olduğuna* siz karar verirsiniz. Burada dizge olarak yazılmış bir ofsettir. Bir zaman damgası, bir birincil anahtar, bir base64 blob'u: çıkışta üretebileceğiniz ve dönüşte tanıyabileceğiniz herhangi bir şey.
* `next_cursor=None`, "bu son sayfaydı" demenin yoludur. Sayaç yok, toplam yok, `has_more` yok. Sinyalin tamamı `None`'dır.

!!! tip
    10'luk bir `PAGE_SIZE` örneği okunur kılar. Kendinizinkini endpoint başına seçin:
    tek satırlık kaynaklardan oluşan bir liste 500'lük bir sayfayı kaldırır; şişkin prompt
    şablonlarından oluşan bir liste kaldıramaz. İstemcinin bu konuda söz hakkı yoktur ve bu bilinçli bir tasarımdır.

### Deneyin {#try-it}

`Client(server)`, düşük seviyeli bir `Server`'a bellek içinde, bir `MCPServer`'a bağlandığı gibi bağlanır.

`list_resources()`'ı argümansız çağırın. `book-1`'den `book-10`'a kadar on kaynak alırsınız ve `next_cursor`, `"10"` dizgesidir.

Bunu `list_resources(cursor="10")` ile geri verin; ilk kaynak `book-11`, yeni `next_cursor` ise `"20"` olur.

Onuncu sayfa, `next_cursor` değeri `None` olarak döner. Bitti.

## İstemci döngüsü {#the-client-loop}

`Client` üzerindeki her `list_*` metodu (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) bir `cursor=` anahtar kelimesi alır. Sayfalanmış bir listeyi sonuna kadar okumak tek bir `while True`'dur:

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor`, `None` olarak başlar; bu yüzden ilk istek imleç taşımaz.
* `next_cursor`'a bakmadan **önce** listeyi genişletin: son sayfada da kaynaklar vardır.
* Çıkış koşulu `next_cursor is None`'dır. Bunun dışındaki her şey, dokunulmadan doğrudan `cursor=`'a geri gider.

`main()`'ini çalıştırın; `100 resources` yazdırır: on tane onluk sayfa, on sayfa olduğundan hiç haberi olmayan bir döngü tarafından birleştirilmiş.

Bu, **[İstemci](../client/index.md)** sayfasının her `list_*` fiili için gösterdiği döngünün aynısıdır ve sayfalamayan bir sunucuya karşı hiçbir maliyeti yoktur: ilk yanıtta `next_cursor`, `None` olur ve döngü bir kez çalışır.

## Üç kural {#the-three-rules}

**İmleçler opaktır.** Bir istemci bir imleci asla ayrıştırmamalı, oluşturmamalı veya tahmin etmemelidir. Bir imlecin tek meşru kaynağı, bir önceki sayfanın `next_cursor`'ıdır; harfi harfine.

**Sayfa boyutunu sunucu seçer.** Protokolde `limit=` yoktur. Farklı bir sayfa boyutuna ihtiyacınız varsa sunucuyu değiştirirsiniz.

**Sayfalamayı yok sayan bir istemci yine de çalışır.** `list_resources()`'ı bir kez çağırır, ilk onu alır ve attığı `next_cursor`'ı hiç fark etmez. Hiçbir şey bozulmaz; yalnızca daha azını görür.

!!! check
    Opak, opak demektir. Bir imleç uydurursanız (`list_resources(cursor="page-2")`) protokolün
    sizin için yapabileceği hiçbir şey yoktur. Bu sunucu `int("page-2")`'yi dener, işleyici istisna fırlatır
    ve istemciye dönen şudur:

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    Sunucudan almadığınız bir imleç bir hatadır, bir özellik isteği değil.

## Özet {#recap}

* `MCPServer` her şeyi tek sayfada döndürür. Sayfalama isteğe bağlıdır ve buna düşük seviyeli `Server` üzerinde geçersiniz.
* `on_list_resources` (ve `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) `PaginatedRequestParams | None` alır; ilk sayfa için `params.cursor`, `None`'dır.
* Bir sayfa ile birlikte `next_cursor` döndürürsünüz: sonradan tanıyacağınız herhangi bir dizge ya da geriye bir şey kalmadığında `None`.
* İstemci döngüsü: `cursor=` geçirin, biriktirin, `next_cursor is None` olana kadar tekrarlayın.
* İmleçler opaktır, sayfa boyutu sunucunundur ve sayfalamayan bir istemci yine de birinci sayfayı alır.

Elle yazılan `Server` API'sinin geri kalanı (`on_call_tool`, `input_schema` dict'leri, `_meta`) **[Düşük seviyeli Server](low-level-server.md)** sayfasında.
