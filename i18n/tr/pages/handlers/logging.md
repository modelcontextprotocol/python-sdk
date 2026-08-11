---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# Log tutma {#logging}

Bir araçtan log yazmak, başka herhangi bir Python fonksiyonundan log yazmaktan farksızdır: standart kütüphaneyle.

MCP'de protokol düzeyinde bir **logging yeteneği** vardır: bir sunucu, `Context` nesnesindeki metotlar aracılığıyla log mesajlarını istemciye bildirim olarak gönderebilir. Spesifikasyonun 2026-07-28 sürümü **bu yeteneği kullanım dışı bırakır ve yerine bir şey koymaz**; bu yüzden bu belgeler onu öğretmez. Nelerin kullanım dışı bırakıldığının ve bunların yerine ne yapılacağının tam listesi **[Kullanım dışı özellikler](../deprecated.md)** sayfasında.

Bunun yerine yapacağınız şey, diğer her Python programında yaptığınızdır: standart kütüphane.

## Log yazan bir araç {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` size modülünüzün adını taşıyan bir logger verir. Onu bir kez, en üstte oluşturun.
* Aracın içinde, başka herhangi bir fonksiyonda olduğu gibi `logger.info(...)`'yu çağırırsınız. Enjekte edilecek bir şey yok, `await` edilecek bir şey yok, MCP'ye özgü bir şey yok.

!!! check
    Aracı çağırın ve sonucun tamamına bakın:

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    Log satırı bunun hiçbir yerinde yok. Log tutma **sizin** içindir; sunucuyu işleten kişi için. Model
    onu asla görmez. Modelin okuması gereken bir şey varsa onu `return` edin.

## Nereye gider {#where-it-goes}

Bir **stdio** sunucusu için bu soru her zamankinden daha önemlidir. Host, sunucunuzu bir alt süreç olarak başlattı ve MCP mesajlarını sunucunun **stdout** akışından okuyor. Standart hata sizindir.

Standart kütüphane zaten doğru olanı yapar: log çıktısı varsayılan olarak `sys.stderr`'e gider. `logger.info(...)` satırlarınız terminale (ya da host alt sürecin stderr'ini nereye topluyorsa oraya) düşer ve protokol akışı temiz kalır.

!!! tip
    Bir stdio sunucusunda `print()` kullanmayın. `print`, **stdout**'a yazar ve stdout protokole aittir.
    SDK, hizmet verirken gerçekten *flush edilen* stdout çıktısını stderr'e yönlendirir; bu yüzden
    iletilen veriyi bozamaz. Ancak blok tamponlamalı bir süreçte `print()` çıktısı genellikle flush
    edilmeden `sys.stdout`'un tamponunda bekler; yorumlayıcı çıkışta tamponu boşaltınca da doğrudan
    protokol akışına dökülür. Yönlendirildiğinde bile satır, log çıktısının arasına ham hâlde düşer:
    düzeyi yoktur, logger adı yoktur, onu filtrelemenin bir yolu yoktur.

    `logger.debug("got here")` de aynı tek satırlık çabadır ve doğru yere gider.

## Düzey {#the-level}

`logging.basicConfig()`'i kendiniz çağırmanız gerekmez. Bir `MCPServer` oluşturmak bunu zaten yaptı: standart hataya yönlendirilmiş bir işleyiciyle, `log_level=` olarak geçirdiğiniz düzeyde. Yani `logger.debug(...)` satırlarınızı görmek için `MCPServer("Bookshop", log_level="DEBUG")` yeterlidir.

Varsayılan değer `"INFO"`.

`logging.basicConfig()` hâlihazırda var olan işleyicileri asla değiştirmez. Sunucuyu oluşturmadan önce log yapılandırmasını kendiniz yaparsanız sizin yapılandırmanız geçerli olur.

## Deneyin {#try-it}

Sunucuyu MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

**Tools** sekmesinden `search_books`'u çağırın. Inspector size sonucu gösterir: yalnızca dönüş değeri. Şu satır

```text
Searching for 'dune'
```

standart hataya gitti: terminale, iletilen veriye değil.

!!! info
    Asıl istediğiniz *izleme* (tracing) ise (her istek, ne kadar sürdüğü, başarısız olup olmadığı),
    log satırları değil span'ler istersiniz. Sunucunuz bunları zaten üretir: SDK varsayılan olarak her
    mesajı OpenTelemetry ile izler. **[OpenTelemetry](../run/opentelemetry.md)** sayfasına bakın.

## Özet {#recap}

* MCP protokolünün logging yeteneği 2026-07-28 spesifikasyonuyla kullanım dışı bırakıldı ve yerine bir şey konmadı. Üzerine bir şey inşa etmeyin.
* Modül düzeyinde `logger = logging.getLogger(__name__)`, aracın içinde `logger.info(...)`. Kalıbın tamamı bu.
* Log çıktısı modele asla ulaşmaz. Yalnızca `return` ettiğiniz değer ulaşır.
* Standart hata sizindir; stdout protokole aittir. SDK hizmet verirken flush edilmiş başıboş stdout çıktısını stderr'e yönlendirir, ancak flush edilmemiş bir `print()` yine de çıkışta iletilen veriye dökülebilir ve yönlendirilen satırlar etiketsiz gelir; her kaydı flush eden bir işleyicisi olan `logging`'i kullanın.
* `MCPServer(..., log_level="DEBUG")` düzeyi ayarlar; önceden yaptığınız bir log yapılandırmasına ise dokunulmaz.

Bağlı istemcilere sunucunuzda bir şeyin (araç listesi, bir kaynak) değiştiğini bildirmek **[Abonelikler](subscriptions.md)** sayfasının konusu.
