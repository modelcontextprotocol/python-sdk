---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
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
    **[Araçlar](tools.md)** sayfasını okuduysanız bu sayfadaki her şeyi zaten biliyorsunuz. Aynı dekoratör,
    açıklama olarak aynı docstring, aynı `Annotated`/`Field`. Değişen tek şey onu kimin
    tetiklediği (kullanıcı) ve sonucun nereye gittiğidir (konuşmaya).

## Özet {#recap}

* Bir fonksiyonun üzerindeki `@mcp.prompt()` onu bir prompt yapar. Ad fonksiyondan, açıklama docstring'den gelir.
* Prompt'lar **kullanıcı denetimindedir**: istemci bunları listeler, kullanıcı birini seçer ve argümanları doldurur.
* Argümanlar adlandırılmış dizelerden oluşan düz bir listedir (şema yok). Varsayılanı olan bir parametre isteğe bağlıdır.
* Bir `str` döndürün, tek bir kullanıcı mesajına dönüşür. Çok turlu bir konuşmanın temelini atmak için `UserMessage` / `AssistantMessage` listesi döndürün.
* `title=` ve `Field(description=...)`, bir istemcinin arayüzüne koyduğu şeylerdir.
* Eksik bir zorunlu argüman isteğin tamamını başarısız kılar. Prompt'a özgü bir hata sonucu yoktur.

Bir prompt'un (veya bir kaynak şablonunun) argümanları için sunucu tarafı otomatik tamamlama **[Tamamlamalar](completions.md)** sayfasındadır.
