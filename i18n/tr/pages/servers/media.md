---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# Medya {#media}

Bir aracın döndürebileceği tek şey metin değildir.

SDK, ikili sonuçlar için iki yardımcı (**`Image`** ve **`Audio`**) ile sunucunuza, araçlarınıza, kaynaklarınıza ve prompt'larınıza istemcinin arayüzünde bir yüz kazandıran **`Icon`** türünü sunar.

## Görsel döndürme {#returning-an-image}

Dönüş türünü `Image` olarak belirtin, bir dosyaya yönlendirin ve döndürün:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image`, `path` (okunacak bir dosya) veya `data` (ham baytlar) argümanlarından tam olarak birini alır.
* İstemcinin gördüğü MIME türü dosya uzantısından tahmin edilir: `logo.png`, `image/png` olarak bildirilir.
* Burada logolara özgü hiçbir şey yok. `server.py` dosyasının yanındaki herhangi bir PNG iş görür: kodunuzun çizdiği bir grafik, bir diyagram, bir fotoğraf.

`Image` bir protokol türü değil, SDK'nın sağladığı bir kolaylıktır. İletilen veride dönüş değeriniz bir **`ImageContent`** bloğuna dönüşür (dosyanın base64 ile kodlanmış baytları ve MIME türü):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Dikkat edilecek iki nokta:

* `data` base64'tür. Baytlara hiç dokunmadınız; dosyayı SDK okudu ve kodlamayı yaptı.
* `structured_content` değeri `None`. Bir `Image`, uygulamanın ayrıştıracağı veri değil, modelin bakacağı içeriktir: çıktı şeması yoktur. (Dönüş tür ipucunun şemanın *ta kendisi* olduğu **[Yapılandırılmış çıktı](structured-output.md)** sayfasıyla karşılaştırın.)

!!! info
    `ImageContent` ve `AudioContent`, `mcp.types` modülünde, düz bir `str` sonucunun dönüştüğü
    `TextContent`'in hemen yanında yer alır (**[Araçlar](tools.md)**). Bir araç sonucu, içerik bloklarından oluşan bir listedir; `Image` ve `Audio`
    iki ikili türü üretmenin en kısa yoludur.

### Deneyin {#try-it}

`server.py` dosyasının yanına herhangi bir PNG koyun, adını `logo.png` yapın ve çalıştırın:

```console
uv run mcp dev server.py
```

**Tools** sekmesini açın ve `logo` aracını çağırın. Sonuç bir dize değil: bir `image` içerik bloğu ve Inspector resminizi görüntülüyor. Diskteki dosya ile ekrandaki pikseller arasındaki her şeyi SDK yaptı.

## Ses döndürme {#returning-audio}

`Audio` da aynı biçimdedir. `logo.png` dosyasını yerinde bırakın ve yanına herhangi bir WAV dosyasını `chime.wav` adıyla koyun:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

Sonuç bir **`AudioContent`** bloğudur:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

Aynı düzen: diskteki bir dosya girer, base64 ve bir MIME türü çıkar, çıktı şeması yok.

## Baytlar veya dosya {#bytes-or-a-file}

Her iki yardımcı da `path=` yerine `data=` (ham baytlar) kabul eder. Bu, hiçbir zaman kendi dosyasından gelmemiş baytlar içindir: bir veritabanı sütunu, bir HTTP yanıtı, Pillow'un az önce çizdiği bir şey:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

`path=` ile bildirilecek bir şey yoktur: dosya, sonuç oluşturulurken okunur ve MIME türü uzantıdan tahmin edilir:

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

Tanımadığı bir uzantı `application/octet-stream`'e geri düşer.

!!! check
    `data=` ile bir dosya adı yoktur, dolayısıyla tahmin yapılacak bir şey de yoktur. `format=`
    argümanını unutursanız SDK bir varsayılana geri düşer: görseller için `image/png`, ses için `audio/wav`.
    MP3 baytlarından bu şekilde bir `Audio` oluşturursanız istemciye `mime_type="audio/wav"`
    söylenir ve o da sadakatle çözmeyi başaramaz. `data=` geçirdiğinizde `format=` da geçirin.

## Simgeler {#icons}

`Icon` içerik değil, meta veridir. Görseli taşımaz; bir URI ile ona işaret eder ve istemci onu getirip sunucunuzun adının, bir aracın, bir kaynağın veya bir prompt'un yanında gösterebilir.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src`, istemcinin çözümleyebileceği bir URI'dir: `https:` veya simgeyi ek bir getirme olmadan gömmek isterseniz bir `data:` URI'si.
* `mime_type` ve `sizes` (`"48x48"` ya da ölçeklenebilir bir biçim için `"any"`), birkaç tane sunduğunuzda istemcinin doğru olanı seçmesini sağlar.
* `theme="light"` veya `theme="dark"`, bir simgeyi tek bir renk şeması için işaretler.

Aynı `icons=[...]` anahtar sözcüğünü `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()` ve `@mcp.prompt()` kabul eder.

### İstemcinin bunları gördüğü yer {#where-a-client-sees-them}

Simgeler, süsledikleri şeyle birlikte yolculuk eder. Sunucununkiler istemci bağlandığında `client.server_info` üzerinde gelir (2026 neslinden bağlantılarda isteğe bağlıdır, bu yüzden önce türünü daraltın):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

Bir aracın simgeleri `tools/list`'ten gelen `Tool` nesnesinde, bir kaynağınkiler `resources/list`'ten gelen `Resource`'ta, bir prompt'unkiler `prompts/list`'ten gelen `Prompt`'ta bulunur. Alanın adı her zaman `icons`'tur.

## Özet {#recap}

* Bir araçtan `Image` veya `Audio` döndürün; istemci bir `ImageContent` / `AudioContent` bloğu alır: base64 ile kodlanmış baytlarınız ve bir MIME türü.
* Bunu bir `path=` ile oluşturup MIME türünü uzantının belirlemesine bırakın ya da bellekteki `data=` ile açık bir `format=` kullanın.
* Medya sonuçları `structured_content` ve çıktı şeması taşımaz.
* `Icon` bir işaretçidir: bir `src` URI'si ile isteğe bağlı `mime_type`, `sizes` ve `theme`.
* `icons=[...]` sunucuda, araçlarda, kaynaklarda ve prompt'larda çalışır; istemciler bunları eşleşen nesnelerde bulur.

Bir aracın bir sonuca *koyabileceği* her şey bu kadar. Bir araç *başarısız olduğunda* ne olacağı (ve bundan kimin haberi olması gerektiği) **[Hataları ele alma](handling-errors.md)** sayfasında.
