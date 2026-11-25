---
translation:
  sections: [7be05607887e6853, e7375894888d9750, c36f73fc7e3af13b, 2fec2d7e129e62fe, 809b0e0a7c27295a, b4395a04d2a5d906, 1a436007f5f54779, c6b2078ed1e63ba5]
  tool: 1
---
# Hataları ele alma {#handling-errors}

Bir araç üç şekilde başarısız olabilir ve SDK her birini farklı ele alır.

`ToolError` fırlatırsanız mesajınızı **model** görür. `MCPError` fırlatırsanız bunu **protokol** görür. Başka herhangi bir şey fırlatırsanız bu bir çökmedir: model yalnızca çağrının başarısız olduğunu öğrenir, traceback ise log'unuza düşer.

Bu sayfa, hangisini seçeceğinizle ilgili.

## Modelin düzeltebileceği bir hata {#an-error-the-model-can-fix}

Bir şeyi arayıp bulan bir araç düşünün; arama sonuçsuz kalsın:

```python title="server.py" hl_lines="2 12-13"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`mcp.server.mcpserver.exceptions` içindeki `ToolError`, bir aracın modele bir şeylerin ters gittiğini söyleme yoludur.

Katalogda olmayan bir başlıkla çağırın ve sonuca bakın:

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* İstek **başarılı oldu**. Ortada bir sonuç var; çağıran tarafta hiçbir şey fırlatılmadı.
* `is_error` değeri `True`; mesajınız (başına araç adı eklenmiş olarak) `content`'te, tam da modelin okuduğu yerde.
* `structured_content` değeri `None`. Başarısız bir çağrının yapılandırılacak bir dönüş değeri yoktur.

Bu bir **araç hatasıdır** ve neredeyse her zaman istediğiniz şey de budur.

Aracınızı çağıran modeldir. Argümanları o seçti. Bu yüzden araç hatası, konuşmada bir tur demektir: model *"No book titled 'Nothing' in the catalog."* mesajını okur, başlığı yanlış tahmin ettiğini anlar ve daha iyi bir başlıkla tekrar çağırır. Tek bir `raise` yazdınız ve kendi kendini düzelten bir ajan elde ettiniz.

Sunucuda bir `ToolError`, log'da tek bir `INFO` satırıdır; traceback yoktur. Bunu zaten bekliyordunuz, bu yüzden araştırılacak bir şey yok.

!!! tip
    Bir araçtan hata mesajını asla `return` ile döndürmeyin. Döndürülen bir dizenin `is_error=False`
    değeri vardır; bu yüzden modele (ve her istemci arayüzüne) araç çalışmış ve yanıt o dizeymiş gibi görünür.
    `raise` kullanın. Sinyali veren bayraktır.

## Modelin düzeltemeyeceği bir hata {#an-error-the-model-cannot-fix}

Şimdi `ToolError` yerine `MCPError` koyun.

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError`, SDK'nın **protokol hatasıdır**. Araç sarmalayıcısının *yakalamadığı* tek istisna budur: yayılır ve `tools/call` isteğinin tamamı bir sonuç yerine JSON-RPC hatasıyla başarısız olur.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **Sonuç yoktur**. `content` yok, `is_error` yok: modelin okuyacağı hiçbir şey yok.
* Hatayı bunun yerine **host** uygulama alır; tıpkı araç hiç var olmasaydı alacağı gibi.
* `code`, `message` ve `data` bozulmadan ulaşır. `INVALID_PARAMS` sabiti `-32602` değerini taşır; `mcp.types` onu ve diğer JSON-RPC hata kodlarını (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...) sabit olarak dışa aktarır, böylece hiçbir zaman sihirli bir sayı yazmazsınız.

!!! check
    Aynı arama, aynı sonuçsuzluk; ama bu kez çağrı istemci tarafında döndürmek yerine *fırlatır*:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    İlk sürüm modele tepki verebileceği bir cümle vermişti. Bu sürüm ona hiçbir şey vermez.
    `get_author` için bu kesinlikle daha kötüdür; bir sonraki bölümün konusu da budur.

## Hangisini fırlatmalı {#which-one-to-raise}

İki yol, iki farklı soruyu yanıtlar.

* *Yürütme* başarısızlığı için **`ToolError` fırlatın**: aracınızın yapmaya çalıştığı şey işe yaramadı. Çağrıyı model seçti, bu yüzden sonucunu da model görmeli ve toparlanma şansı bulmalı. Yanlış yazılmış bir başlık, zaman aşımına uğrayan bir dış API, var olmayan bir satır: hepsi araç hatası.
* *İsteğin kendisi* reddedilmesi gerektiğinde **`MCPError` fırlatın**: istemcide aracınızın bağımlı olduğu bir yetenek eksik, sunucu kimseye hizmet verecek durumda değil, çağıran taraf zorunlu bir adımı atlamış. Modelin hiçbir yeniden denemesi bunları düzeltmez; bu yüzden mesajı ona vermenin bir kazancı yok.

Kararı tek bir soru verir: **daha akıllı bir model bundan kaçınabilir miydi?** Evet -> `ToolError`. Hayır -> `MCPError`.

Bu ölçüte göre `get_author`'ın ikinci sürümü yanlış seçim yaptı: daha iyi bir başlık sorunu çözer, yani model mesajı görmeyi hak ediyordu. O sürüm size mekanizmayı göstermek için orada, onu önermek için değil.

!!! info
    `MCPError`, `from mcp import MCPError` ile içe aktarılır ve `code`, `message` ile isteğe bağlı
    bir `data` yükü alır. Bunlara ne koyarsanız istemci onu alır: SDK, fırlatılan bir
    `MCPError`'ı temizlemek yerine olduğu gibi iletir.

## Başka herhangi bir istisna {#any-other-exception}

Şimdi denetimi çıkarın ve sözlük aramasının kendi kendine başarısız olmasına izin verin:

```python title="server.py" hl_lines="11"
--8<-- "docs_src/handling_errors/tutorial004.py"
```

`CATALOG[title]`, `KeyError` fırlatır. Bunu planlamadınız, bu yüzden SDK onu bir çökme olarak ele alır:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool get_author")]
```

Çağrı yine `is_error=True` döndürür; yani model başarısız olduğunu bilir ve yoluna devam edebilir. Almadığı şey istisnanın metnidir: kodunuzdan gelen bir `KeyError` ya da üç kütüphane alttaki bir sürücüden gelen bir yığın SQL, sunucunuzun iç yapısını ele verebilir; bu yüzden sunucudan asla çıkmaz.

Onu siz alırsınız. Sunucu çökmeyi tam traceback ile `ERROR` düzeyinde, `Tool 'get_author' raised an unexpected exception` olarak log'a yazar. Bu yüzden `WARNING` düzeyindeki bir üretim log'u her `ToolError` boyunca sessiz kalır ve bir şey gerçekten bozulduğu anda sesini çıkarır.

## Var olmayan bir kaynak {#a-resource-that-doesnt-exist}

Kaynaklar da aynı çizgiyi çeker ve yaygın durum için adlandırılmış bir istisna sunar.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` bir **şablondur**. *Her* başlıkla eşleşir; bu yüzden "URI düzgün biçimli" ile "kitap var" iki farklı sorudur ve ikincisini yalnızca fonksiyonunuz yanıtlayabilir.

Yanıtlayamadığında `ResourceNotFoundError` fırlatın. SDK bunu, spesifikasyonun eksik bir kaynağa atadığı protokol hatasına dönüştürür: `data`'da istenen URI ile birlikte `-32602`; böylece istemci *hangi* okumanın başarısız olduğunu bilir.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

Burada `is_error=True` taşıyan yarım bir sonuç olmadığına dikkat edin. Bir kaynak okuması ya içerik döndürür ya da başarısız olur: kaynakların yalnızca protokol yolu vardır. `ResourceError`, "bulunamadı" olmayan bir başarısızlık için aynı şeydir (`-32603`, sizin mesajınız); ikisi de log'unuzda tek bir `INFO` satırıdır. `MCPError` dışındaki diğer her istisna bir çökmedir: istemci yalnızca URI'yi belirten `-32603` alır, traceback ise `ERROR` düzeyinde log'unuza gider. Şablonlar ve kaynaklarla ilgili diğer her şey **[Kaynaklar](resources.md)** sayfasında.

## Hiç fırlatmadığınız hatalar {#errors-you-never-raise}

Hatalı bir argüman fonksiyonunuza asla ulaşmaz.

`get_author`'a dize olmayan bir `title` gönderin; SDK sizi çağırmadan **önce** onu girdi şemasına göre reddeder. Bu da modelin okuyup düzeltebileceği türden, aynı `is_error=True` araç hatasıdır. **[Araçlar](tools.md)** sayfası aynı reddi bir `Field(le=50)` kısıtıyla gösterir.

Bu, yazmadığınız koca bir `raise` ifadesi sınıfı demektir: kendi tür ipuçlarınızı yeniden doğrulamayın.

!!! info
    Bu sayfada bir **istemcinin** gördüğü her şeyi, testleri yazarken kullanacağınız bellek içi
    `Client` da görür. `raise_exceptions=True` bile başarısız olan bir
    aracın istisnasını çağırana geri vermez: o bayrak devreye girebilecek noktaya geldiğinde istisnanız çoktan
    `is_error=True` sonucuna dönüşmüştür. Doğrulamayı sonuç üzerinde yapın. Bir çökmenin traceback'ine ihtiyacınız varsa o
    sunucunun log'undadır ve pytest'in `caplog`'u onu yakalar. **[Test etme](../get-started/testing.md)** sayfası bu kalıbı anlatır.

## Özet {#recap}

* Bir araçta **`ToolError`** fırlatın -> çağrı, mesajınız `content`'te olacak şekilde `is_error=True` döndürür. Model bunu okur ve yeniden deneyebilir.
* **`MCPError`** fırlatın -> çağrının kendisi bir JSON-RPC hatasıyla başarısız olur. Model hiçbir şey görmez; bununla host ilgilenir. `code`, `message` ve `data` bozulmadan ulaşır.
* Belirleyici soru: *daha akıllı bir model bundan kaçınabilir miydi?* Evet -> `ToolError`. Hayır -> `MCPError`.
* Diğer **her istisna** bir çökmedir -> model için yalnızca `Error executing tool <name>` içeren `is_error=True`, sizin için ise traceback'li bir `ERROR` kaydı.
* Bir kaynak işleyicisinden `ResourceNotFoundError` -> protokolün `-32602` kodu, URI `data`'da.
* Hatalı argümanlar, fonksiyonunuz çalışmadan önce şemaya göre reddedilir; bunlar için `raise` yazmazsınız.
* İçe aktarmalar: `from mcp import MCPError`, `from mcp.server.mcpserver.exceptions import ToolError, ResourceError, ResourceNotFoundError` ve `mcp.types`'tan hata kodu sabitleri.

Hatalar halloldu. Bir sunucunun *sunduğu* her şey bu kadar. Her işleyicinin çalışırken neleri okuyabildiği ve istemciye geri neler yapabildiği bir sonraki bölümde: **[İşleyicinin içinde](../handlers/index.md)**.

En sık karşılaşacağınız SDK hatalarının tam metni, her birinin ne anlama geldiği ve her biri için tek hamlelik çözüm **[Sorun giderme](../troubleshooting.md)** sayfasında.
