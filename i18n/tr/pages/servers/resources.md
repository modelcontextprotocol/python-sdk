---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# Kaynaklar {#resources}

**Kaynak**, uygulamanın okuması için sunduğunuz veridir.

Ayrım bu. Araç, **modelin** çağırmaya karar verdiği şeydir. Kaynak ise **uygulamanın** yüklemeye (bir yapılandırma dosyası, bir kayıt, bir belge) ve bağlam olarak modelin önüne koymaya karar verdiği şeydir.

Bir kaynağı, sıradan bir Python fonksiyonunun üzerine `@mcp.resource(uri)` koyarak bildirirsiniz.

## İlk kaynağınız {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

Şekli bir araçla aynı, bir fazlası var: **URI**. Kaynaklara adla değil, adresle erişilir. İstemci `config://app` ister, asla `get_config` istemez.

SDK geri kalanını yine fonksiyondan okur:

* **Ad**, fonksiyonun adıdır: `get_config`.
* İstemcinin gördüğü **açıklama**, docstring'dir.
* **İçerik**, ne döndürürseniz odur.

`resources/list` sırasında istemci şunu alır:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

`config://app` kaynağını okuduğunda ise fonksiyonunuz çalışır ve dönüş değeri metin olarak geri gelir:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    Listeleme ucuzdur. Fonksiyonunuz `resources/list` sırasında **çağrılmaz**; yalnızca
    `resources/read` sırasında ve yalnızca istenen URI için çağrılır. Bin kaynak sunun,
    bedelini yalnızca birinin açtıkları için ödersiniz.

### Deneyin {#try-it}

Sunucuyu MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

Yazdırdığı URL'yi açın ve **Resources** sekmesine gidin. `config://app`, açıklamasıyla birlikte listede. Tıklayın, Inspector onu okur: iki satırlık yapılandırmanız karşınızda.

## Kaynak şablonları {#resource-templates}

Kayıt başına bir URI ölçeklenmez. URI'ye bir **yer tutucu**, fonksiyona da onunla eşleşen bir parametre koyun:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

URI'de `{user_id}`, fonksiyonda `user_id: str`. Sözleşmenin tamamı bu.

Bu artık bir **kaynak şablonu** ve yeri değişir: `resources/list` yanıtından çıkar, onun yerine `resources/templates/list` yanıtında görünür; bir adres olarak değil, bir desen olarak:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

İstemci yer tutucuyu doldurur ve somut bir URI okur: `users://42/profile`, `users://ada/profile`. Hepsine tek bir fonksiyon yanıt verir; eşleşen değer `user_id` olarak geçirilir:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

Sonuçtaki `uri` alanına dikkat edin. Bu, şablon değil, istemcinin istediği **somut** URI'dir.

!!! check
    Yer tutucular ile parametreler uyuşmak zorunda. URI hâlâ `{user_id}` derken fonksiyon
    parametresinin adını `user` olarak değiştirirseniz dekoratör, herhangi bir istemci yanına
    bile yaklaşmadan, **içe aktarma sırasında** reddeder:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    Bir uyuşmazlık ancak bir hata olabilir; bu yüzden SDK, sunucuyu böyle bir hatayla başlatmayı imkânsız kılar.

Yer tutucu sözdizimi [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) standardıdır: çok parçalı değerler için `{+path}`, isteğe bağlı sorgu parametreleri için `{?q,lang}` ve dahası. SDK ayrıca çıkarılan değerlere varsayılan olarak yol güvenliği denetimleri uygular. Tam başvuru için **[URI şablonları ve yol güvenliği](uri-templates.md)** sayfasına bakın.

`get_user_profile`, `Context` ile işaretlenmiş bir parametre de alabilir. SDK onu hiçbir zaman URI parametresi saymadan enjekte eder; size neler sağladığını **[Context nesnesi](../handlers/context.md)** sayfası anlatır.

## Döndürdükleriniz {#what-you-return}

`str` ile sınırlı değilsiniz. Her kaynağa bir `mime_type` verin ve neyi uygun görüyorsanız onu döndürün:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` bir `str` döndürür, bu yüzden olduğu gibi gönderilir. Yaygın durum budur.
* `catalog_stats` bir `dict` döndürür, bu yüzden SDK onu sizin için **JSON metnine** serileştirir:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` `bytes` döndürür, bu yüzden istemci `TextResourceContents` yerine bir `BlobResourceContents` alır; baytlarınız `blob` alanında base64 ile kodlanmış olarak yer alır.

Aynı kural JSON'a serileştirilebilen başka her şey için de geçerlidir: bir liste, bir Pydantic modeli, bir dataclass. `str` değilse ve `bytes` değilse JSON olur.

`mime_type`'ı siz bildirirsiniz; varsayılan olarak `text/plain`. SDK, bunu tahmin etmek için döndürdüğünüz şeyi asla incelemez; bu yüzden etiketlemediğiniz bir `dict` kaynağı yine düz metin olarak duyurulur.

!!! tip
    Bunları fonksiyondan türetmek istemediğinizde `@mcp.resource()`, `name=`, `title=` ve
    `description=` parametrelerini de kabul eder. Yazacak bir fonksiyon hiç olmadığında ise
    `mcp.server.mcpserver.resources` içinde, `mcp.add_resource(...)` ile kaydedeceğiniz hazır
    `Resource` sınıfları var (`TextResource`, `BinaryResource`, `FileResource`, `HttpResource`,
    `DirectoryResource`).

İstemci bir kaynağa **abone** de olabilir ve kaynak değiştiğinde bildirim alabilir; bu, hikâyenin istemci tarafı ve **[İstemci](../client/index.md)** sayfasında anlatılır.

## Özet {#recap}

* Bir fonksiyonun üzerindeki `@mcp.resource(uri)` onu kaynak yapar. URI adrestir, dönüş değeri içeriktir, docstring açıklamadır.
* URI'deki bir `{placeholder}` onu **şablon** yapar: `resources/templates/list` altında listelenir ve eşleşen her URI'ye tek bir fonksiyon hizmet verir.
* Yer tutucu adları fonksiyonun parametre adlarıyla aynı olmalıdır. Yanlış yaparsanız bunu üretimde değil, içe aktarma sırasında öğrenirsiniz.
* Fonksiyonunuz kaynak listelendiğinde değil, **okunduğunda** çalışır.
* `str` metin olur, `bytes` base64 blob olur, geri kalan her şey JSON metni olur. Etiketi `mime_type=` ile koyarsınız.
* Araçlar modelin eyleme geçmesi içindir. Kaynaklar uygulamanın okuması içindir.

Üçüncü temel yapı taşı, yani bir kişinin menüden seçtiği, **[Prompt'lar](prompts.md)**.
