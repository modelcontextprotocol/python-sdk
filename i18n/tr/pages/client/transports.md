---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# İstemci aktarımları {#client-transports}

Her `Client`, sunucusuyla bir **aktarım** üzerinden konuşur: mesajları fiilen taşıyan şey budur.

Aktarımı hiçbir zaman ayrıca yapılandırmazsınız. `Client` tek bir konumsal argüman alır ve aktarımı bu argümanın türünden çıkarır.

Her birinin *sunucu* tarafı (`mcp.run()`'ın ne yaptığı ve neyi dağıttığınız) **[Sunucunuzu çalıştırma](../run/index.md)** sayfasında.

## Bellek içinde {#in-memory}

Sunucu nesnesinin kendisini geçirin:

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

Alt süreç yok, port yok, ağ üzerinde tek bir bayt yok. İstemci ve sunucu aynı süreçteki iki nesnedir; yine de çağrı gerçek protokol katmanından geçer: `search_books`, HTTP üzerinden nasıl olacaksa tam olarak öyle listelenir, doğrulanır ve çağrılır.

Bu, onu aynı anda iki şey yapar:

* **Bir test düzeneği.** Bu belgelerdeki her örnek bu şekilde çalıştırılır ve **[Test etme](../get-started/testing.md)** sayfası tüm deseni bunun üzerine kurar.
* **Bir gömme API'si.** Sunucuyu oluşturan bir uygulamanın, araçlarını çağırmak için ağ üzerinden bir sıçrama yapmasına gerek yoktur.

## Streamable HTTP {#streamable-http}

Bir URL dizesi geçirin; arkasına dağıtım yaptığınız aktarım olan **Streamable HTTP**'yi elde edersiniz:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

Üretim istemcisinin tamamı bu. `Client`, URL'yi sizin için `streamable_http_client(...)` ile sarar; bunu da MCP'nin gerektirdiği şekilde yapılandırılmış bir `httpx2.AsyncClient` üzerine kurar: `follow_redirects=True`, connect/write/pool için 30 saniyelik zaman aşımı ve sunucu bir yanıt akışını açık tutabileceği için 300 saniyelik okuma zaman aşımı.

!!! check
    Oluşturduğunuz bir `Client` bağlı **değildir**. Oluşturma yalnızca aktarımı seçer;
    onu açan `async with`'tir. İçine girmeden bağlantıya uzanırsanız SDK bunu size söyler:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    `Client("http://...")` yazdığınızda hiçbir şey çözümlenmedi, getirilmedi ya da başlatılmadı. O satır bedava.

### Kendi `httpx2.AsyncClient`'ınızı getirme {#bring-your-own-httpx2asyncclient}

Bir `Authorization` başlığına, bir çereze, bir vekil sunucuya, mTLS'e ya da farklı bir zaman aşımına ihtiyaç duyduğunuz anda `httpx2.AsyncClient`'ı kendiniz oluşturun ve `streamable_http_client`'a verin:

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

Dikkat edilecek iki şey:

* `httpx2.AsyncClient`'ın sahibi sizsiniz, bu yüzden içine **siz** girer ve **siz** çıkarsınız. SDK, kendi oluşturmadığı bir istemciyi asla kapatmaz.
* `streamable_http_client(url, http_client=...)` bir aktarım döndürür ve `Client(transport)` onu diğer her şey gibi kabul eder.

TLS ile ilgili bir not: `httpx2`, sertifikaları paketle gelen bir CA listesine göre değil, işletim sisteminin güven deposuna göre doğrular (
[`truststore`](https://pypi.org/project/truststore/) aracılığıyla). Kullanılabilir bir sistem CA deposu olmayan bir ortamda (bazı minimal kapsayıcılar) standart `SSL_CERT_FILE`/`SSL_CERT_DIR`
ortam değişkenlerini ayarlayın ya da `httpx2.AsyncClient`'ınıza açıkça bir `verify=ssl_context` geçirin
(arka plan bilgisi için
[`httpx` ve `httpx-sse`'nin yerini `httpx2` aldı](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

!!! warning
    `streamable_http_client` eskiden `headers=` ve `timeout=` parametrelerini doğrudan alırdı. Artık almıyor:
    tek parametreleri `url`, `http_client` ve `terminate_on_close`. Alışkanlıkla `headers=`'a
    uzanırsanız şunu alırsınız:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    HTTP'yle ilgili her şey artık geçirdiğiniz o tek `httpx2.AsyncClient` üzerinde bulunur.

!!! info
    `httpx2`, tanıdık `httpx` API'sini korur; yani `httpx`'i biliyorsanız kimlik doğrulama,
    vekil sunucular, olay kancaları, yeniden denemeler ve bağlantı sınırlarının burada nasıl yapılacağını zaten biliyorsunuz. SDK üzerine hiçbir şey eklemez,
    hiçbir şeyi de eksiltmez. OAuth'un takıldığı yer de burası:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. Bu akışın tamamı **[OAuth istemcileri](oauth-clients.md)** sayfasında.

## stdio {#stdio}

Bir **stdio** sunucusu bir alt süreçtir. İstemci onu başlatır, stdin'ine JSON-RPC yazar ve stdout'undan JSON-RPC okur. Bir masaüstü host'un makinenizde bir sunucuyu çalıştırma biçimi budur: bir host, bu kod artı bir kullanıcı arayüzü*dür* ve **[Gerçek bir host'a bağlanma](../get-started/real-host.md)**, aynı ilişkinin host'un tarafından, bir yapılandırma dosyası olarak görülen halidir.

Süreci `StdioServerParameters` ile tanımlayın, `stdio_client` ile bir aktarıma dönüştürün ve `Client`'a *onu* verin:

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client`, parametre nesnesini tek başına kabul etmez. `StdioServerParameters` yapılandırmadır; `stdio_client(server)` ise ondan bir süreç başlatmayı bilen aktarımdır. Her zaman sarın.

`async with` bloğundan çıkmak alt süreci de kapatır: stdin'i kapat, bekle, oyalanıyorsa sonlandır. Onu hiçbir zaman kendiniz temizlemezsiniz.

!!! warning
    Alt süreç ortamınızı **devralmaz**. Minimal bir izin listesi alır (POSIX'te `HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` ve `USER`); böylece sizin yazmamış olabileceğiniz bir sürece hassas hiçbir şey
    sızmaz.

    Bir API anahtarına ihtiyaç duyan bir sunucu onu orada bulamaz. `env=` ile açıkça geçirin; bu
    değişkenler izin listesinin üstüne birleştirilir. Yukarıda `BOOKSHOP_API_KEY`'in yaptığı budur.

## SSE {#sse}

`mcp.client.sse` içindeki `sse_client(url)`, Streamable HTTP'nin yerini aldığı HTTP aktarımıdır. Hâlâ onu konuşan bir sunucuyla konuşmak için aynı şekilde sarın, `Client(sse_client("http://localhost:8000/sse"))`, ve üzerine yeni hiçbir şey kurmayın.

## `Transport` protokolü {#the-transport-protocol}

`Client` için yukarıdakilerin hepsi aynı şeydir.

Bir **aktarım**, `(read, write)` mesaj akışı çifti veren herhangi bir asenkron bağlam yöneticisidir: resmi olarak `mcp.client` içindeki `Transport` protokolü. `Client`, argümanını türüne göre çözümler: bir sunucu nesnesi süreç içinde bağlanır, bir `str` `streamable_http_client(url)` olur ve geri kalan her şeye doğrudan bir aktarım olarak girilir. `stdio_client(...)`, `streamable_http_client(...)` ve `sse_client(...)`'in hepsinin aynı yuvaya oturmasının ve kendinizinkini yazabilmenizin nedeni bu son kuraldır.

## Özet {#recap}

* `Client(mcp)` (sunucu nesnesi) bellek içinde bağlanır. Testler ve gömme için kullanın.
* `Client("http://.../mcp")` (bir URL), üretim aktarımı olan Streamable HTTP üzerinden bağlanır.
* Başlıklar, kimlik doğrulama, vekil sunucular ve zaman aşımları, `streamable_http_client(url, http_client=...)`'a geçirdiğiniz bir `httpx2.AsyncClient` üzerinde yer alır. `headers=` anahtar sözcüğü yoktur.
* stdio `Client(stdio_client(StdioServerParameters(...)))`'tır; asla tek başına parametre nesnesi değil.
* Alt süreç sizinkini değil, izin listesine göre oluşturulmuş bir ortam alır; `env=` buna ekleme yapar.
* Bir aktarım, `async with x as (read, write)` yapabildiğiniz herhangi bir şeydir. `Client`, sunucu nesnesi ya da URL olmayan her şeyi doğrudan bu protokole verir.
* Bir `Client` oluşturmak aktarımı seçer. Onu `async with` açar.

Aktarım açıldıktan sonra iki tarafın bir protokol sürümünde anlaşması gerekir. Normalde bunu hiç düşünmezsiniz; düşünmeniz gerektiğinde gidilecek sayfa **[Protokol sürümleri](../protocol-versions.md)**'dir.
