---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# Başlık parametreleri {#header-parameters}

Çoğu sunucunun buna hiç ihtiyacı olmaz.

Sunucunun önündeki bir ağ geçidi veya yük dengeleyici, yalnızca gövdeyi ayrıştırmadan okuyabildiği bilgilere göre yönlendirme yapabilir. Bir araç argümanını `x-mcp-header` ile işaretleyin; `2026-07-28` **[protokol sürümünü](../protocol-versions.md)** kullanan istemciler bu argümanın değerini HTTP başlığı olarak da gönderir.

## Bir argümanı işaretleme {#mark-an-argument}

İşaret, argümanın JSON Schema'sındaki fazladan tek bir anahtardır. `MCPServer`'da bunu oraya `Field` koyar:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* `2026-07-28` sürümünde Streamable HTTP üzerinden istemci, gövdeyle birlikte `Mcp-Param-Region` başlığını da gönderir; ikisi uyuşmazsa sunucu çağrıyı reddeder.
* Aracı listelememiş bir istemci işareti hiç görmemiştir: başlık göndermez ve çağrı reddedilir. Bu SDK'nın `Client`'ı bunun üzerine araçları listeler ve çağrıyı bir kez yeniden gönderir; yani önce listelemek yalnızca bir gidiş-dönüş kazandırır.
* Diğer tüm bağlantılar bu ek açıklamayı yok sayar.

Fonksiyonunuz değişmez: `region` yine argüman olarak gelir.

## İşaretlenebilecek argümanlar {#what-can-be-marked}

`str`, `int` ve `bool` argümanlar. Bunların dışındaki her şey, araç kaydedilirken `InvalidSignature` ile reddedilir.

Tek bir türü olmayan `str | None` da buna dahildir. İsteğe bağlı bir argümanın şeması, pydantic'in `WithJsonSchema`'sıyla açıkça yazılmalıdır:

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## Düşük seviyeli `Server`'da {#on-the-low-level-server}

Orada `input_schema`'yı elle yazarsınız, bu yüzden anahtar doğrudan içine yazılır:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* Ek açıklamayı sizin yerinize hiçbir şey denetlemez: geçersiz olanı da sunulur ve `2026-07-28` istemcileri aracı listelerine almaz.

### Ada göre şemalar {#schemas-by-name}

Başlığı denetlemek için SDK'nın, çağrıyı iletmeden önce aracın girdi şemasına ihtiyacı vardır. `get_tool_input_schema` yoksa SDK bu şemayı, herhangi bir araç işaretli olsun olmasın, argüman taşıyan her çağrıda `on_list_tools` işleyicinizi çalıştırarak alır.

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* Elinizde zaten olan bilgiden yanıt vermek için fonksiyonu geçirin.
* Denetlenecek bir şeyi olmayan araç için `None` döndürün.

## Özet {#recap}

* Bir araç argümanındaki `x-mcp-header`, `2026-07-28` istemcilerinin bu argümanı `Mcp-Param-*` HTTP başlığı olarak yinelemesini sağlar.
* Sunucu, başlığı ile gövdesi uyuşmayan çağrıyı reddeder.
* Yalnızca `str`, `int` ve `bool` argümanlar işaretlenebilir. `MCPServer`, bunların dışındaki her şey için `InvalidSignature` fırlatır.
* Düşük seviyeli `Server` hiçbir şeyi denetlemez; istemciler de ek açıklaması geçersiz olan aracı eler.
* `get_tool_input_schema`, düşük seviyeli `Server`'ın her çağrıda `on_list_tools`'u çalıştırmasını önler.

Elle yazılan `Server` API'sinin geri kalanı **[Düşük seviyeli Server](low-level-server.md)** sayfasında.
