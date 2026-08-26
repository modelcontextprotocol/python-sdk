---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# Tamamlamalar {#completions}

Sunucunuzun üzerine bir arayüz kuran bir istemci, kullanıcı yazdıkça argüman değerlerini otomatik tamamlamak ister: dil adları, depo adları, dosya yolları.

**Tamamlamalar**, sunucunuzun bu önerileri sağlama yoludur.

## Tamamlamaya değer bir şey {#something-worth-completing}

Tamamlamalar tam olarak iki şeye uygulanır: bir **prompt**'un argümanlarına ve bir **kaynak şablonunun** parametrelerine. O halde her birinden birer tane içeren bir sunucuyla başlayın:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

Burada henüz tamamlamalarla ilgili hiçbir şey yok.

* `review_code` bir `language` alır. Kullanıcı hangi yazımları kabul ettiğinizi tahmin etmek zorunda kalmamalı.
* `github_repo` bir `owner` ve bir `repo` alır. İkisi için de serbest metin kutuları kötü bir form olur.

## Tamamlama işleyicisi {#the-completion-handler}

`@mcp.completion()` ile dekore edilmiş **tek** bir fonksiyon ekleyin:

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* Sunucu başına tek bir işleyici vardır. Her tamamlama isteği buraya düşer; neyin tamamlandığına göre siz dallanırsınız.
* `async def` olmak zorundadır: SDK onu await eder.
* Üç argüman alır:
  * `ref`: *hangi* prompt veya kaynak şablonu olduğu; bir `PromptReference` ya da `ResourceTemplateReference` olarak gelir. İkisini `isinstance` ile ayırt edersiniz.
  * `argument`: `argument.name` tamamlanmakta olan argüman, `argument.value` ise kullanıcının şu ana kadar yazdığıdır.
  * `context`: hâlihazırda çözümlenmiş argümanlar. Şimdilik görmezden gelin.
* Bir `Completion(values=[...])` döndürürsünüz; sunacak bir şeyiniz yoksa `None`.

!!! tip
    `argument.value`, kullanıcının yazdığı ön ektir. SDK sizin yerinize filtreleme **yapmaz**:
    `values` içine ne koyarsanız arayüz onu gösterir. `startswith`'i yazmak size düşer.

### Deneyin {#try-it}

**[Test etme](../get-started/testing.md)** sayfasındaki bellek içi `Client` ile çalıştırın.
`client.complete()`'i `ref=PromptReference(name="review_code")` ve
`argument={"name": "language", "value": "py"}` ile çağırın:

```python
result.completion.values  # ['python']
```

* `ref`, işleyicinizin aldığı referans türünün aynısıdır.
* `argument`, tam olarak iki anahtarı (`name` ve `value`) olan düz bir dict'tir.

Boş bir `value` gönderin, listenin tamamı geri döner. `lang.startswith("")` her dil için doğrudur:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

`code` hakkında sorun (işleyicinizin tanımadığı bir argüman); `None` döndürür, SDK da bunu boş bir listeye çevirir:

```python
result.completion.values  # []
```

`None` *"öneri yok"* demektir, asla bir hata değildir. Arayüz düz bir metin kutusuna geri döner.

## Hiç bildirmediğiniz bir yetenek {#a-capability-you-never-declared}

İşleyiciyi kaydetmek bildirimin ta kendisidir. Bir istemci bağlayın ve bakın:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

`completions`'ı hiçbir yerde listelemediniz. SDK işleyiciyi gördü ve yeteneği sizin yerinize bildirdi. *İsteğe bağlı* her yetenek böyle çalışır: işleyici bildirimin kendisidir. (Üç temel yapı isteğe bağlı değildir: `MCPServer` işleyici olsun olmasın bunları her zaman bildirir.)

!!! check
    İlk `server.py` dosyasına (işleyicisi olmayana) dönün ve yine de sorun. Çağrı bir JSON-RPC
    hatasıyla başarısız olur:

    ```text
    Method not found
    ```

    Ve `client.server_capabilities.completions` `None` olur. Yeteneğin anlamı budur: düzgün
    davranan bir istemci bunu kontrol eder ve yanıtlayamayacağınız isteği hiç göndermez.

## Bağımlı argümanlar {#dependent-arguments}

`github://repos/{owner}/{repo}` kaynağının iki parametresi var ve `repo` için işe yarar değerler önce hangi `owner`'ın seçildiğine bağlı.

`context` tam da bunun için var. Kullanıcının **hâlihazırda çözümlediği** argümanları taşır:

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* Yeni dal, şablonun `repo` parametresi için devreye girer.
* `context.arguments`, şu ana kadar seçilen değerlerin (burada `owner`) bir `dict[str, str] | None`'ıdır.
* Henüz `owner` yoksa mantıklı öneri de yoktur; bu yüzden işleyici `None` döndürür.

İstemci bu çözümlenmiş değerleri `context_arguments=` ile gönderir. Bu kez `ref` bir
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")` olur. Boş bir `value` ile
`repo`'yu isteyin ve `context_arguments={"owner": "modelcontextprotocol"}` geçirin:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

`context_arguments=`'ı kaldırın, aynı çağrı `[]` döndürür. İşleyici, sahibi bilmeden hangi depoları önereceğini bilemez.

!!! info
    `Completion` ayrıca `total=` ve `has_more=` de alır. `values` daha uzun bir listenin bir dilimi
    olduğunda bunları ayarlayın; böylece arayüz *"ve 200 tane daha"* gösterebilir. Çoğu işleyicinin
    bunlara hiç ihtiyacı olmaz.

## Özet {#recap}

* Tamamlamalar, **prompt argümanları** ve **kaynak şablonu parametreleri** için önerilerdir. Başka bir şey değil.
* `@mcp.completion()` tek işleyiciyi kaydeder. İmzası `async def (ref, argument, context) -> Completion | None`'dır.
* `isinstance(ref, ...)` ve `argument.name` üzerinden dallanın. `argument.value`'ya göre filtrelemeyi kendiniz yapın.
* `None` boş bir listeye dönüşür. Asla bir hata değildir.
* `context.arguments` hâlihazırda çözümlenmiş değerleri tutar; istemci bunları `context_arguments=` olarak sağlar.
* `completions` yeteneği, işleyiciyi kaydettiğiniz anda ortaya çıkar. O olmadan istek `Method not found` olur.

Öneriler, kullanıcı bir prompt'u veya şablonu hâlâ *doldururken* işe yarar; bir araç çağrısının *ortasında* kullanıcıya soru sormak için **[Elicitation](../handlers/elicitation.md)** gerekir. Bir aracın metin dışında döndürebileceği her şey ise **[Görseller, ses ve simgeler](media.md)** sayfasında.
