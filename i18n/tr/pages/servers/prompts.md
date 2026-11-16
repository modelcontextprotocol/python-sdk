---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# Prompt'lar {#prompts}

**Prompt**, kullanıcının seçtiği bir mesaj şablonudur.

Araçlar model içindir. Prompt ise tam tersi: kullanıcı istemcisindeki bir menüden (bir slash komutu, bir düğme) birini seçer, argümanlarını doldurur ve ortaya çıkan mesajlar sanki kendisi yazmış gibi konuşmaya eklenir.

Metni döndüren bir fonksiyonun üzerine `@mcp.prompt()` koyarak bir prompt tanımlarsınız.

## İlk prompt'unuz {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK, bir araçtan okuduğu aynı üç şeyi okur:

* **Ad**, fonksiyonun adıdır: `review_code`.
* İstemcinin gösterdiği **açıklama** docstring'dir: `Review a piece of code.`
* **Argümanlar** parametrelerden gelir. `code` için varsayılan değer yok, bu yüzden zorunludur.

Bir istemci `prompts/list` çağrısından şunu alır:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Burada JSON Schema yok. Prompt argümanları **adlandırılmış dize değerlerinden** oluşan düz bir listedir: bir modelin kurduğu bir veri yükü değil, bir insanın doldurduğu bir form.

### Şablonu işleme {#rendering-it}

İstemci, argümanları geçirerek şablonu `prompts/get` ile işler. Fonksiyonunuz çalışır ve döndürdüğünüz `str` **tek bir kullanıcı mesajına** dönüşür:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

Bir prompt'un tüm yaşamı bu: adıyla listelenir, istendiğinde işlenir, sohbete bırakılır.

!!! check
    `required`, fonksiyonunuz çalışmadan önce uygulanır. `review_code`'u `code` olmadan işleyin;
    isteğin kendisi bir JSON-RPC hatasıyla (kod `-32603`) başarısız olur:

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Bir modele geri verilecek araç tarzı bir hata sonucu yoktur, çünkü döngüde bir model yoktur:
    çağrı bir istisna fırlatır. Nedeni (`Missing required arguments: {'code'}`) sunucunuzun log'una düşer.

### Deneyin {#try-it}

Sunucuyu MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

**Prompts** sekmesini açın ve `review_code`'u seçin. Inspector, tek bir zorunlu `code` alanı olan bir form çizer. Doldurun, işleyin; geriye tam olarak yukarıdaki kullanıcı mesajı döner.

## Birden fazla mesaj {#more-than-one-message}

Bir kod incelemesi tek bir mesajdır. Bir hata ayıklama oturumu ise bir konuşmadır ve bir prompt bu konuşmanın tamamının temelini atabilir.

`str` yerine bir mesaj listesi döndürün:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` ve `AssistantMessage`, `mcp.server.mcpserver.prompts.base` modülünden gelir. Onlara bir `str` verin, sizin için `TextContent` içine sararlar. Rol, sınıfın adıdır.
* `Message` ortak temel sınıflarıdır. Dönüş tür açıklaması olarak onu kullanın.

`debug_error` işlendiğinde artık sırasıyla üç mesaj üretilir:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Sonuncusuna dikkat edin. Bir `assistant` turunu önceden doldurmak, yönlendirmeyi kullanıcıya yazdırmadan modelin *bir sonraki* yanıtını yönlendirmenin yoludur.

## Başlıklar ve argüman açıklamaları {#titles-and-argument-descriptions}

`review_code` bir etiket değil, bir fonksiyon adıdır. İstemciye düğmeye koyacak daha iyi bir şey verin ve formun kendini açıklaması için her argümanı tanımlayın:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` insan tarafından okunabilir addır; tıpkı bir aracın `title`'ı gibi.
* `Annotated[str, Field(description=...)]`, **[Araçlar](tools.md)** sayfasının bir aracın parametrelerini açıklamak için kullandığı kalıbın aynısıdır. Burada açıklama bir şemaya değil, argümanın üzerine düşer.
* `language` için bir varsayılan değer var, bu yüzden artık zorunlu değildir.

`prompts/list` girdisi artık bir istemcinin iyi bir form çizmek için ihtiyaç duyduğu her şeyi taşır:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    **[Araçlar](tools.md)** sayfasını okuduysanız buraya kadarki her şeyi zaten biliyorsunuz. Aynı dekoratör,
    açıklama olarak aynı docstring, aynı `Annotated`/`Field`. Değişen tek şey onu kimin
    tetiklediği (kullanıcı) ve sonucun nereye gittiğidir (konuşmaya).

## Metinden fazlası {#more-than-text}

`UserMessage` ve `AssistantMessage`, `str` kabul ettikleri her yerde bir içerik bloğunu ya da bir `Image` / `Audio` yardımcısını da kabul eder. Prompt'larda iki durum öne çıkar: bir belge eklemek ve bir resim eklemek.

### Dosya gömme {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* Stil kılavuzu `style://python` adresindeki bir kaynaktır (bunları **[Kaynaklar](resources.md)** sayfası anlatır) ve `server.py` dosyasının yanındaki `style-guide.md` dosyasından okunur. Oraya herhangi bir Markdown dosyası koyun.
* Her ikisi de `mcp.types` modülünden gelen `EmbeddedResource(resource=TextResourceContents(...))`, dosyayı URI'si ve MIME türüyle birlikte ilk mesaj olarak taşır; ona atıfta bulunan istek düz metin olarak ardından gelir.
* Kılavuzu f-string'e yapıştırmak yerine gömmek, istemcinin onu bir ek olarak göstermesini ve `style://python` kaynağını daha sonra yeniden açabilmesini sağlar; model de dosyayı olduğu gibi alır. İkili bir dosya için base64 `blob` içeren `BlobResourceContents` kullanın.

İşlendiğinde ilk mesajın `content` alanı bir `resource` bloğudur:

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### Görsel ekleme {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image`, **[Görseller, ses ve simgeler](media.md)** sayfasındaki yardımcıdır. Prompt işlendiğinde `UserMessage` onu bir `ImageContent` bloğuna dönüştürür (dosya base64 ile kodlanır, MIME türü `.png` uzantısından tahmin edilir); `Audio` da aynı şekilde bir `AudioContent` olur.
* `server.py` dosyasının yanına `architecture.png` adında herhangi bir PNG koyun. Prompt argümanları dizedir, bu yüzden resim her zaman sunucudan gelir; `component` yalnızca sözcükleri sağlar.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## Listeyi çalışma zamanında değiştirme {#changing-the-list-at-runtime}

İstemciler bağlıyken prompt eklenebilir; örneğin bir kullanıcının bir talimatı kendine ait bir menü girdisi olarak kaydetmesine izin vermek için. Prompt'u kaydedin, ardından bildirin:

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` bir fonksiyonu tıpkı `@mcp.prompt()`'un yapacağı gibi kaydeder; `mcp.remove_prompt(name)` ise bunun tersidir. `add_prompt` aynı ada sahip mevcut bir girdinin üzerine yazmak yerine onu korur; bu yüzden araç, kaydetmenin değiştirme anlamına gelmesi için önce varsa eskisini kaldırır. `prompts/list` değişikliği hemen yansıtır.
* `await ctx.notify_prompts_changed()`, bir `subscriptions/listen` akışını dinleyen her `2026-07-28` istemcisine `notifications/prompts/list_changed` gönderir (**[Abonelikler](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()` ise çağıran istemci 2026 öncesiyse bildirimi ona gönderir (**[Eski nesil istemcilere hizmet verme](../run/legacy-clients.md)**). İkisini de çağırın; haber verecek kimse yoksa her biri hiçbir şey yapmaz.
* Bildirimi alan bir istemci `prompts/list`'i yeniden çağırır. Python `Client`'ında bu, bir `PromptsListChanged` olayı üreten `async with client.listen(prompts_list_changed=True) as sub:` biçimindedir.

## Özet {#recap}

* Bir fonksiyonun üzerindeki `@mcp.prompt()` onu bir prompt yapar. Ad fonksiyondan, açıklama docstring'den gelir.
* Prompt'lar **kullanıcı denetimindedir**: istemci bunları listeler, kullanıcı birini seçer ve argümanları doldurur.
* Argümanlar adlandırılmış dizelerden oluşan düz bir listedir (şema yok). Varsayılanı olan bir parametre isteğe bağlıdır.
* Bir `str` döndürün, tek bir kullanıcı mesajına dönüşür. Çok turlu bir konuşmanın temelini atmak için `UserMessage` / `AssistantMessage` listesi döndürün.
* `title=` ve `Field(description=...)`, bir istemcinin arayüzüne koyduğu şeylerdir.
* Eksik bir zorunlu argüman isteğin tamamını başarısız kılar. Prompt'a özgü bir hata sonucu yoktur.
* Bir belge veya resim eklemek için bir `EmbeddedResource` ya da `Image` nesnesini `UserMessage` içine sarın.
* Çalışma zamanında `mcp.add_prompt(...)` / `mcp.remove_prompt(...)` ile prompt ekleyin veya kaldırın, ardından `await ctx.notify_prompts_changed()` ve `await ctx.session.send_prompt_list_changed()` çağırın.

Bir prompt'un (veya bir kaynak şablonunun) argümanları için sunucu tarafı otomatik tamamlama **[Tamamlamalar](completions.md)** sayfasındadır.
