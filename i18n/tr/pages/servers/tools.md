---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# Araçlar {#tools}

**Araç**, modelin çağırabildiği bir fonksiyondur.

Sıradan bir Python fonksiyonunun üstüne `@mcp.tool()` koyarak bir araç tanımlarsınız. API'nin tamamı bu.

## İlk aracınız {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

Yazdığınıza bir bakın. Şema yok, JSON yok, protokol yok; yalnızca bir fonksiyon. SDK ondan üç şey okur:

* Aracın **adı** fonksiyonun adıdır: `search_books`.
* Modelin gördüğü **açıklama** docstring'dir: `Search the catalog by title or author.`
* Modelin geçirmesine izin verilen **argümanlar** tür ipuçlarından gelir: `query: str` ve `limit: int`.

### Girdi şeması {#the-input-schema}

SDK bu tür ipuçlarından bir JSON Schema üretir ve `tools/list` sırasında istemciye gönderir:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

Hiçbirinin varsayılan değeri olmadığı için iki argüman da `required` içinde. Bunu birazdan düzelteceksiniz. (`title` anahtarları Pydantic'in ürettiği kalıntılardır; sözleşmeyi oluşturan şey özellikler, türleri ve `required`'dır.)

!!! tip
    Tür ipuçları burada dokümantasyon değildir. **Sözleşmenin ta kendisidir**. Bir istemci `"limit": "ten"`
    gönderirse SDK bunu, fonksiyonunuz daha çalışmadan reddeder.

### Modele dönen sonuç {#what-the-model-gets-back}

Aracı `{"query": "dune", "limit": 5}` ile çağırın; sonuç iki parçadan oluşur:

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content`, **modelin** okuduğu metindir. `structured_content` ise **istemci uygulama** için tür bilgisi taşıyan veridir. Dönüş türünü `-> str` olarak bildirdiğiniz için oradadır.

`structured_content`'i şimdilik dert etmeyin. Araçlarınızdan gerçek Python nesneleri döndürün, gerisi doğru şekilde halledilir; **[Yapılandırılmış çıktı](structured-output.md)** sayfası tamamen bununla ilgili.

### Deneyin {#try-it}

Sunucuyu MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

Yazdırdığı URL'yi açın, **Tools** sekmesine gidin ve `search_books`'u çağırın.

Inspector, zorunlu bir `query` metin alanı ve zorunlu bir `limit` sayı alanı içeren bir form gösterir. Bu formu tür ipuçlarınızdan oluşturdu. Diğer tüm MCP istemcileri de aynısını yapar.

## İsteğe bağlı argümanlar {#optional-arguments}

Bir parametreye varsayılan değer verin, zorunlu olmaktan çıkar. Hepsi bu. Bildiğiniz Python.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

Şema da buna uyar:

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

`limit`, `required` listesinden çıktı ve `"default": 10` kazandı. Onu göndermeyen bir istemci, tıpkı Python'da olacağı gibi `10` alır.

## `Field` ile daha zengin şemalar {#richer-schemas-with-field}

Tür ipuçları sizi epey ileri götürür, ancak bazen bir argümanı *açıklamak* ya da kısıtlamak istersiniz.

Türü `Annotated` içine sarın ve bir Pydantic `Field` ekleyin:

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

Üç yeni şey var, hepsi parametrelerin üzerinde:

* `Field(description=...)`: modelin docstring'le birlikte okuduğu, argümana özel bir açıklama.
* `Field(ge=1, le=50)`: sayısal sınırlar. Şemaya `"minimum": 1, "maximum": 50` olarak yansırlar.
* `Literal["fiction", "non-fiction", "poetry"]`: bir enum. Model yalnızca bunlardan birini seçebilir.

!!! check
    Kısıtlamalar süs değildir. Aracı `limit=999` ile çağırın; SDK, **fonksiyonunuz çalışmadan önce**
    bir araç hatasıyla yanıt verir:

    ```text
    Input should be less than or equal to 50
    ```

    Bu hata araç sonucu olarak modele geri döner; model onu okur ve geçerli bir değerle yeniden dener.
    `le=50` ifadesini bir kez yazdınız ve kendi kendini düzelten ajanları bedavaya elde ettiniz.

!!! info
    FastAPI veya Pydantic kullandıysanız bunların hepsini zaten biliyorsunuz. Aynı `Field`,
    aynı `Annotated`, aynı doğrulama. Burada MCP'ye özgü öğrenilecek hiçbir şey yok.

## Parametre olarak model {#a-model-as-a-parameter}

Bir araç birkaç taneden fazla argüman aldığında bunları bir Pydantic modelinde toplayın:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

`Book` şeması aracın girdi şemasının içine (bir `$defs` referansı olarak) yerleştirilir, model onu bir JSON nesnesi olarak doldurur ve fonksiyonunuz zaten doğrulanmış, `.title`, `.author` ve `.year` öznitelikleri olan **gerçek bir `Book` örneği** alır.

Dilediğiniz gibi karıştırabilirsiniz: model parametrelerinin yanında sıradan parametreler, iç içe modeller, model listeleri. Baştan sona Pydantic.

## `async def` {#async-def}

Bir araç G/Ç yapıyorsa (bir API çağırıyor, dosya okuyor, veritabanı sorguluyorsa) onu `async def` olarak bildirin ve içinde `await` kullanın. SDK onu await eder.

Sıradan bir `def` araç da çalışır: SDK onu bir iş parçacığında çalıştırır, böylece sunucuyu asla engellemez.

Yapılandırılacak başka bir şey yok.

## Adlar, başlıklar ve annotation'lar {#names-titles-and-annotations}

SDK'nın çıkarsadığı her şeyi dekoratörde geçersiz kılabilirsiniz:

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title`, arayüzler için insanların okuyabileceği bir addır. İstemciler `search_books` yerine *"Search the catalog"* gösterir.
* `annotations`, istemci için davranışsal **ipuçlarıdır**:
  * `read_only_hint=True`: bu araç hiçbir şeyi değiştirmez.
  * `open_world_hint=False`: açık web üzerinde değil, kapalı bir şeyler kümesi (bu katalog) üzerinde çalışır.
  * Diğer ikisi, `destructive_hint` ve `idempotent_hint`, *yazan* bir aracı tanımlar: bir şeyi
    silebilir mi, ve onu iki kez çağırmak bir kez çağırmakla aynı şey mi? Spesifikasyon her ikisini de
    yalnızca salt okunur olmayan araçlar için tanımlar; bu yüzden `search_books` üzerinde hiçbir şey ifade etmezler.

Kurallara uyan bir istemci bunları *"bunu çalıştırmadan önce kullanıcıya sormam gerekir mi?"* gibi kararlar vermek için kullanır. Bunlar ipucudur, güvenlik değil. Bir istemcinin bunlara uyacağına asla güvenmeyin.

!!! tip
    Adı ve açıklamayı fonksiyon adından ve docstring'den türetmek istemiyorsanız `@mcp.tool()`
    `name=` ve `description=` de kabul eder. Çoğu zaman türetmek istersiniz.

## Özet {#recap}

* Bir fonksiyonun üstündeki `@mcp.tool()` onu araç yapar. Ad fonksiyondan, açıklama docstring'den gelir.
* Tür ipuçları girdi şemasının **ta kendisidir**. Varsayılan değerler argümanları isteğe bağlı yapar.
* `Annotated[..., Field(...)]` açıklama ve kısıtlama ekler; `Literal` enum ekler.
* Yapılandırılmış bir "gövde" almanın yolu Pydantic model parametresidir.
* Hatalı argümanlar sizin yerinize reddedilir; hem de modelin okuyup toparlanabileceği bir hatayla.
* G/Ç için `async def`, geri kalan her şey için sıradan `def`.

`return` ettiğiniz değerin başına neler geldiği **[Yapılandırılmış çıktı](structured-output.md)** sayfasında.
