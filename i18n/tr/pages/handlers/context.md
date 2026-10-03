---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Context nesnesi {#the-context}

Bir aracın argümanları modelden gelir. Geri kalan her şey (hizmet verdiğiniz istek, içinde yaşadığınız sunucu, istemciye geri konuşmanın bir yolu) tek bir nesneden gelir: **`Context`**.

Onu siz oluşturmazsınız, yapılandırmazsınız da. Yalnızca istersiniz.

## İsteyin {#ask-for-it}

Herhangi bir araca `Context` ile işaretlenmiş bir parametre ekleyin:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* SDK her istek için yeni bir `Context` oluşturur ve onu içeri geçirir.
* Parametrenin **adı önemli değildir**. `ctx`, `context`, `c`: SDK onu tür işaretinden bulur.
* Kaynaklar ve prompt'lar da aynı şekilde bir tane bildirebilir.
* `ctx.request_id`, fonksiyonunuzun şu anda hizmet verdiği isteğin kimliğidir.

!!! info
    FastAPI kullandıysanız bu hareketi görmüşsünüzdür: bir parametreyi çatının kendi türüyle
    (orada `Request`, burada `Context`) bildirirsiniz ve çatı onu sağlar. Kaydedilecek bir şey yok,
    yapılandırılacak bir şey yok: mekanizmanın tamamı tür işaretinden ibarettir.

### Model için görünmez {#invisible-to-the-model}

İçselleştirilmesi gereken kısım burası. `tools/list`'in `search_books` için bildirdiği girdi şeması şöyle:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Tek bir özellik. `ctx` bir argüman değildir: şemada asla görünmez, modele asla söylenmez ve hiçbir istemci onu dolduramaz. Sizinle SDK arasındaki bir sözleşmedir, iletilen veride görünmez.

### Deneyin {#try-it}

Sunucuyu MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

`search_books` formunda tek bir `query` alanı var. Onu `dune` ile çağırın:

```text
[request 3] Found 3 books matching 'dune'.
```

Sayı, bu isteğin denk geldiği sıra numarasıdır. Aracı yeniden çağırın, değişir: her istek kendi `Context`'ini alır.

## Size ne sağlar {#what-it-gives-you}

Enjekte edilen nesne küçüktür. `request_id` dışında:

* `await ctx.read_resource(uri)`: bir aracın içinden sunucunun **kendi** kaynaklarından birini okur. Bir sonraki bölüm.
* `await ctx.report_progress(progress, total, message)`: uzun bir çağrı sırasında çağırana ilerlemeyi akış halinde bildirir. Ayrıntıların tamamı **[İlerleme](progress.md)** sayfasında.
* `await ctx.elicit(message, schema)` ve `await ctx.elicit_url(...)`: aracı duraklatır ve kullanıcıya bir soru sorar. Bu da **[Elicitation](elicitation.md)**.
* `ctx.session`: bu istemciyle konuşmanın sunucu tarafı. İstemciye gönderdiğiniz bildirimler burada yaşar; son bölüm onu kullanır.
* `ctx.headers`: aktarımın taşıdığı istek başlıkları, stdio'da ise `None`. Özel bir başlığı `(ctx.headers or {}).get("x-...")` ile okuyun. Başlıklar istemcinin sağladığı girdidir; bir yerel ayar ya da özellik bayrağı için uygundur, kimlik için asla.
* `ctx.request_context`: istek başına tutulan ham kayıt. Elinizin gideceği alan `lifespan_context`'tir, yani başlangıç kodunuzun yield ettiği nesne (bkz. **[Lifespan](lifespan.md)**).

Log tutma bu listede bilerek yok. Bir sunucu, diğer her Python programı gibi Python'ın `logging` modülüyle log tutar. **[Log tutma](logging.md)** bunun nedenini anlatan kısa sayfadır.

!!! tip
    Enjeksiyon yalnızca kaydettiğiniz fonksiyon için gerçekleşir. Aracınızın çağırdığı bir yardımcı
    fonksiyon kendi `Context`'ini almaz; `ctx`'i sıradan bir argüman olarak aşağıya geçirin. Başka bir
    yerden alınabilecek ortamda asılı bir "geçerli bağlam" yoktur.

## Kendi kaynaklarınızı okuma {#read-your-own-resources}

Bir sunucunun kaynakları yalnızca istemciler için değildir. Bir araç da onları okuyabilir:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource`, URI'yi `resources/read`'e hizmet veren aynı kayıt defteri üzerinden çözümler; böylece araç, istemcinin alacağının aynısını alır: içerik bloğu başına bir tane olmak üzere `ReadResourceContents` öğelerinden oluşan yinelenebilir bir nesne. Bu URI için bir tane var:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content`, `genres()`'in döndürdüğünün ta kendisidir. Tek bir doğruluk kaynağı: istemci kaynağa göz atar, araçlarınız onu tüketir, kimse dizgeyi kopyalamaz.
* `describe_catalog`'un tek parametresi `Context`'tir, bu yüzden girdi şemasında **hiçbir özellik yoktur**. Model onu `{}` ile çağırır.

## İstemciye listenin değiştiğini söyleme {#tell-the-client-the-list-changed}

Bir sunucunun sundukları içe aktarma anında sabitlenmez. Çalışma zamanında bir araç kaydedin, ardından istemciye söyleyin:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` düz bir fonksiyonu araç olarak kaydeder: ad, açıklama ve şema tam olarak `@mcp.tool()`'un yapacağı gibi türetilir.
* `await ctx.session.send_tool_list_changed()`, `notifications/tools/list_changed` bildirimini gönderir. Onu alan bir istemci `tools/list`'i yeniden çağırır ve `recommend_book`'u görür.

Kardeşleri `send_resource_list_changed()`, `send_prompt_list_changed()` ve belirli tek bir kaynaktaki değişiklik için `send_resource_updated(uri)`'dir.

Bir 2026-07-28 bağlantısında istemciler değişiklik bildirimlerini yalnızca kendilerinin açtığı bir `subscriptions/listen` akışı üzerinden alır; bu yüzden yukarıdaki `send_*` yöntemleri o akışlara ulaşmaz. `Context`'in yayımlama yöntemleri abone olunmuş tüm akışlara aynı anda iletir: `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()` ve `await ctx.notify_resource_updated(uri)`. Kopyalar arasında ölçekleme dahil ayrıntıların tamamı **[Abonelikler](subscriptions.md)** sayfasında.

!!! check
    Kimse `enable_recommendations`'ı çalıştırmadan önce, vaat ettiğiniz araç mevcut değildir. Yine de
    çağırın; sonuç, modelin okuyabileceği bir hatadır:

    ```text
    Unknown tool: recommend_book
    ```

    `enable_recommendations`'ı çalıştırın, aynı çağrı bu kez başarılı olur. Araç listesi gerçekten
    dinamiktir: `tools/list`, *tam şu anda* ne kayıtlıysa onu yansıtır.

## Özet {#recap}

* Bir parametreyi `Context` ile işaretleyin (bir araçta, kaynakta ya da prompt'ta), SDK onu enjekte eder. Ad size kalmış.
* Model için görünmezdir: girdi şeması yalnızca gerçek argümanlarınızı içerir.
* `ctx.request_id` isteği tanımlar; `ctx.request_context.lifespan_context` başlangıç kodunuzun yield ettiği şeydir.
* `await ctx.read_resource(uri)`, bir aracın sunucunun kendi kaynaklarını okumasını sağlar.
* `ctx.session` istemciye giden geri kanaldır: `send_tool_list_changed()` ve kardeşleri, değiştirdiğiniz bir listeyi yeniden çekmesini söyler.
* İlerleme bildirme ve elicitation da `Context`'ten başlar; her birinin kendi sayfası var.

Modelin asla görmediği, kendi fonksiyonlarınızın doldurduğu parametreler **[Bağımlılıklar](dependencies.md)** sayfasında.
