---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# İstemci {#the-client}

**`Client`**, bir Python programının bir MCP sunucusuyla konuşmasını sağlayan nesnedir.

Tek bir yaşam döngüsü olan tek bir nesnedir: oluşturun, `async with` bloğuna girin, yöntemleri çağırın. Her protokol fiili (araçları listeleme, birini çağırma, bir kaynağı okuma, bir prompt'u oluşturma) bu nesne üzerinde, türü belirli bir sonuç döndüren bir `async` yöntemdir.

## İlk istemciniz {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

Üstteki sunucu yalnızca bağlanacak bir şeyiniz olsun diye orada. İstemci, vurgulanan beş satırdan ibaret.

* `Client(mcp)` çağrısına **sunucu nesnesinin kendisi** verilir. Bu, bellek içi aktarımdır: alt süreç yok, port yok, HTTP yok. Bu sayfadaki her örnek ve yazdığınız her test böyle bağlanır.
* `async with` **yaşam döngüsüdür**. Bloğa girdiğinizde bağlantı kurulur ve anlaşma yapılır; çıktığınızda bağlantı kesilir. `connect()` / `close()` çifti yoktur ve blok bittikten sonra bir `Client` yeniden kullanılamaz.
* Bloğun içinde bağlantı bilgileri düz özellikler olarak zaten hazırdır.

### `Client`'a geçirebilecekleriniz {#what-you-can-pass-to-client}

`Client` tek bir konumsal argüman alır ve aktarımı onun türünden çözümler:

* Bir `MCPServer` (veya düşük seviyeli `Server`) örneği: **süreç içinde** bağlanır.
* Bir URL dizesi (`Client("http://localhost:8000/mcp")`): Streamable HTTP, yani üretim yolu.
* Bir **aktarım**: `async with ... as (read, write)` ile kullanabileceğiniz herhangi bir şey; örneğin bir alt süreci saran `stdio_client(...)`.

Bu sayfadaki geri kalan her şey üçünde de aynıdır. Başlıklar, alt süreçler, zaman aşımları ve `Transport` protokolünün kendi sayfası var: **[İstemci aktarımları](transports.md)**.

### Bağlı bir istemcide bulunanlar {#whats-on-a-connected-client}

Bloğa girdiğiniz anda doldurulan dört salt okunur özellik:

* `client.server_info`: sunucunun kimliği; kimlik bildirmeyen 2026 neslinden bir sunucu için `None` (python-sdk sunucuları varsayılan olarak bildirir). Burada `server_info.name` `"Bookshop"`, `server_info.version` ise sunucu ne bildiriyorsa odur.
* `client.server_capabilities`: sunucunun neler yapabildiği (`tools`, `resources`, `prompts`, `completions`, ...). Sunucuda olmayan bir yetenek `None` olur.
* `client.protocol_version`: iki tarafın üzerinde anlaştığı protokol sürümü. Burada `"2026-07-28"`.
* `client.instructions`: sunucunun `instructions=` dizesi; sunucu bir tane ayarlamadıysa `None`.

Hiç protokol sürümü seçmediniz. Varsayılan olarak `Client` sunucuyu yoklar ve eski sunucularda klasik el sıkışmaya geri döner; böylece tek bir istemci her nesilden sunucuyla çalışır. Bunu denetlemeniz gerektiğinde ayrıntıların tamamı **[Protokol sürümleri](../protocol-versions.md)** sayfasında.

!!! tip
    `client.session`, alttaki `ClientSession`'dır; düşük seviyeli kaçış kapısı.
    Bu sayfadaki hiçbir şey için ona ihtiyacınız olmaz.

## Araçları listeleme {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` bir `ListToolsResult` döndürür; araçlar `.tools` içindedir. Her biri, bir host'un modele vereceği eksiksiz tanımdır:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

`tool.input_schema` ise sunucunun fonksiyonun tür ipuçlarından türettiği JSON Schema'dır:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Bu şema, bir arayüzün argüman formu oluşturması için gereken her şeydir; bir modelin geçerli argümanlar üretmesi için gereken her şey de odur.

!!! tip
    `title` isteğe bağlıdır; bu yüzden araçları bir insana gösteren arayüzün seçim yapması gerekir: varsa `title`,
    yoksa `name`. `from mcp.shared.metadata_utils import get_display_name` tam olarak bunu yapar;
    araçlar, kaynaklar, kaynak şablonları ve prompt'lar için.

## Bir aracı çağırma {#calling-a-tool}

`call_tool(name, arguments)` aracı çalıştırır ve size bir `CallToolResult` geri verir.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

Sunucunun `lookup_book` aracı bir Pydantic `Book` döndürür. İstemcinin gördüğü şudur:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Tek dönüş değeri, okunacak üç şey. Her birinin tüketicisi farklı.

### `content`: modelin okuduğu {#content-what-the-model-reads}

`content`, **içerik bloklarından** oluşan bir `list`'tir ve bir içerik bloğu bir birleşim (union) türüdür: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` veya `EmbeddedResource`. Bir araç farklı türlerden birkaç tane döndürebilir.

`main`'in `block.text`'e dokunmadan önce `isinstance(block, TextContent)` ile türü daraltmasının nedeni budur. `isinstance` dışında hiç `.text` olmadığına dikkat edin: tür denetleyicisi buna izin vermez, çünkü `ImageContent`'te `.text` değil `.data` vardır. Birleşim türü, bir aracın size ne gönderebileceği konusunda dürüsttür; kodunuz da öyle olmalı.

### `structured_content`: uygulamanızın okuduğu {#structured_content-what-your-application-reads}

`structured_content`, aracın JSON olarak dönüş değeridir ve aracın bildirdiği `output_schema` ile eşleşir. Dize ayrıştırma yok, tahmin yürütme yok.

İkisi de varsa aynı şeyi bilerek iki kez söylerler: `content` model için, `structured_content` kod içindir. Yapılandırılmış yarının nereden geldiği ve nasıl denetleneceği **[Yapılandırılmış çıktı](../servers/structured-output.md)** sayfasında.

### `is_error`: aracın başarısız olup olmadığı {#is_error-whether-the-tool-failed}

İstisna fırlatan bir araç, istemcinizde istisna **fırlatmaz**. `is_error=True` taşıyan sıradan bir sonuç olarak geri döner.

!!! check
    `lookup_book`'tan `"Solaris"`'i isteyin (katalogda olmayan bir başlık); fonksiyon
    `ValueError` fırlatır. Çağrı yine de normal biçimde döner:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    İstisnanın mesajı `content`'e düştü; **model** onu orada okuyup yeniden deneyebilir. Bu
    kasıtlıdır: bir araç hatası çökme değil, konuşmanın bir parçasıdır. `structured_content`'e
    güvenmeden önce her zaman `is_error`'a bakın.

!!! warning
    `is_error=True`, kendi `raise`'inizden fazlasını kapsar. Sunucuda hiç olmayan bir araç isteyin
    (`call_tool("does_not_exist", {})`); hiçbir şey fırlatılmaz. Aynı şekil geri gelir:
    `content`'te `Unknown tool: does_not_exist` ile birlikte `is_error=True`. Bir `Client` yöntemi
    yalnızca sunucu sonuç yerine bir JSON-RPC **hatası** ile yanıt verdiğinde `MCPError` fırlatır;
    sunucunun hangisini ne zaman ürettiği **[Hataları ele alma](../servers/handling-errors.md)** sayfasında.

## Kaynaklar {#resources}

Kaynak fiilleri çift gelir: listelemenin iki yolu, okumanın tek yolu.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` **somut** kaynakları, yani sabit URI'si olanları döndürür. Burada: `['catalog://genres']`.
* `list_resource_templates()` **parametreli** olanları döndürür. Burada: `['catalog://genres/{genre}']`. İki ayrı liste olmalarının nedeni, bir şablonun siz onu doldurana kadar okunabilir olmamasıdır.
* `read_resource(uri)` düz bir `str` URI alır ve ikisinde de çalışır: `"catalog://genres/poetry"` geçirin, sunucu onu şablonla eşleştirir.

`read_resource`, `TextResourceContents` veya `BlobResourceContents` öğelerinden oluşan bir liste olan `contents` döndürür. Araç içeriğiyle aynı fikir: `isinstance` ile daraltın, sonra `.text`'i (veya `.blob`'u) okuyun.

Bir istemciye bir kaynağın ne zaman değiştiği de bildirilebilir. 2025 neslinden bağlantılarda bu, `subscribe_resource(uri)` / `unsubscribe_resource(uri)` çiftidir; `MCPServer`'ın uygulamadığı bir yöntem çifti olduğundan, 2026-07-28 sürümündeki bağlantıda (bu fiillerin artık var olmadığı yerde) istek `-32601`, *Method not found* ile yanıtlanır. 2026'daki karşılığı, `MCPServer`'ın gerçekten *sunduğu* bir `subscriptions/listen` akışıdır (orada `server_capabilities.resources.subscribe` değeri `True`'dur) ve onu `client.listen(...)` ile tüketmek bu bölümün **[Abonelikler](subscriptions.md)** sayfasının konusudur.

## Prompt'lar {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` size sunucunun neler sunduğunu ve her prompt'un neye ihtiyaç duyduğunu söyler:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` onu oluşturur. Argümanlar sözlüğü `str -> str` biçimindedir: prompt argümanları her zaman dizedir. Sonuç `messages`'dır; her biri bir `role` ve bir `content` bloğu taşıyan `PromptMessage` öğelerinden oluşan bir liste:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Host bu mesajları doğrudan modele verir. Özelliğin tamamı bu.

## Tamamlamalar {#completions}

Tamamlama işleyicisi olan bir sunucu, kullanıcı yazdıkça prompt ve kaynak şablonu argümanlarını otomatik tamamlayabilir.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref`, *hangi* prompt'u veya şablonu doldurduğunuzu söyler: bir `PromptReference` ya da `ResourceTemplateReference`.
* `argument`, `{"name": ..., "value": ...}` biçimindedir: argüman ve kullanıcının şimdiye kadar yazdığı.

Yanıt `result.completion.values` içindedir. `"p"` yazın, sunucu `['poetry']` ile döner. Sunucu tarafı ve bir işleyicinin önerilerini daraltmak için önceden doldurulmuş *diğer* argümanları nasıl kullandığı **[Tamamlamalar](../servers/completions.md)** sayfasında.

## Sayfalama {#pagination}

Her `list_*` yöntemi bir `cursor=` anahtar sözcüğü alır ve her sonuç bir `next_cursor` taşır. `next_cursor` `None` olduğunda her şeyi almışsınız demektir.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Bu döngü her sunucuya karşı doğrudur. `MCPServer` her şeyi tek sayfada döndürür; bu yüzden `next_cursor` `None` olur ve döngü bir kez çalışır. Çoğu kodun bunu hiç yazmamasının nedeni budur. Gerçekten sayfalayan sunucular ve imleçlerin uyduğu kurallar **[Sayfalama](../advanced/pagination.md)** sayfasında.

## Testlerde {#in-tests}

Süreç ve port olmadan `Client(mcp)`, sunucunuz için zaten bir test düzeneğidir.

Bunun için yapılmış tek bir kurucu bayrağı var: `Client(mcp, raise_exceptions=True)`. Yalnızca bellek içi bağlantılarda etkisi olur; onu açıklayan ve bütün kalıbı onun etrafında kuran sayfa ise **[Test etme](../get-started/testing.md)**.

## Özet {#recap}

* `Client(x)` bir sunucu nesnesine bellek içinden, bir URL dizesine Streamable HTTP üzerinden, geri kalan her şeye de bir aktarım aracılığıyla bağlanır.
* `async with` yaşam döngüsünün tamamıdır. İçinde `server_capabilities` ve `protocol_version` zaten doludur; sunucu sağladığında `server_info` ve `instructions` da öyle.
* `list_tools()` size her aracın `name`, `title`, `description` ve `input_schema` değerlerini verir.
* `call_tool()` model için `content`, kodunuz için `structured_content` ve `is_error` döndürür. İstisna fırlatan bir araç istisna değil, sonuçtur.
* `content` blok türlerinin bir birleşimidir; okumadan önce `isinstance` ile daraltın.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` ve `complete` fiilleri tamamlar.
* Her `list_*` `cursor=` alır; `next_cursor` `None` olana kadar döngüye devam edin.

Bir sunucunun *istemciden* isteyebilecekleri ve bunları nasıl yanıtlayacağınız **[İstemci callback'leri](callbacks.md)** sayfasında.
