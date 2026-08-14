---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# Sunucunuzu çalıştırma {#running-your-server}

`mcp.run()` sunucuyu başlatır.

Vermeniz gereken tek karar **aktarım**: sunucunuzla istemcisi arasındaki baytların gerçekte nasıl taşındığı.

## Aktarım seçme {#pick-a-transport}

| Aktarım | Ne olduğu | Ne zaman |
|---|---|---|
| `stdio` | Host, dosyanızı bir alt süreç olarak başlatır ve onunla stdin ve stdout'u üzerinden konuşur. | Yerel sunucular. Varsayılan. |
| `streamable-http` | Bir portu dinleyen gerçek bir HTTP sunucusu. | Dağıttığınız her şey. |
| `sse` | Eski HTTP aktarımı. | Hiçbir zaman. |

!!! warning
    SSE, 2025-03-26 protokol sürümünde yerini Streamable HTTP'ye bıraktı.
    `mcp.run(transport="sse")` kendi `sse_path=` ve `message_path=` seçenekleriyle hâlâ çalışır,
    ancak yalnızca henüz geçiş yapmamış istemciler için vardır. Üzerine yeni bir şey inşa etmeyin.

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` senkrondur. Sunucunun ömrü boyunca bloke kalır.
* Argüman verilmezse aktarım `stdio` olur.
* `if __name__ == "__main__":` altında durur, çünkü sunucunuzu yükleyen her şey (`mcp dev`, `mcp run`, `mcp install`, testleriniz) bu dosyayı **içe aktarır**. Bu koruma, bir içe aktarmanın çalışan bir sunucuya dönüşmesini engeller.

### stdio {#stdio}

Yapılandırılacak hiçbir şey yok. Host, dosyanızı bir alt süreç olarak başlatır, istekleri stdin'ine yazar ve yanıtları stdout'undan okur.

Kendiniz çalıştırın, sonucunu görürsünüz:

```console
python server.py
```

Hiçbir şey yazdırmaz ve geri dönmez. Bir host'un ilk sözü söylemesini stdin'de bekliyordur.

Bu aynı zamanda stdout'un **iletişim hattının ta kendisi** olduğu anlamına gelir. Hizmet verirken SDK bu hattı özel bir dosya tanımlayıcısına taşır ve stdout'a *flush edilen* çıktıyı (miras aldığı stdout'a yazan bir alt süreç, flush edilmiş bir `print()`) akışı bozamayacağı stderr'e yönlendirir. Hizmet başlamadan *önce* stdout'a flush edilen çıktı (echo yapan bir sarmalayıcı betik, import sırasında tamponlanmadan yapılan bir print) yine hatta düşer; yorumlayıcı çıkışta boşaltana kadar tamponda kalan bir `print()` de öyle. Gerçekten istediğiniz çıktı için doğru araç `logging` modülüdür: işleyicisi her kaydı oluştuğu anda stderr'e flush eder. Ayrıntıların tamamı **[Log tutma](../handlers/logging.md)** sayfasında.

### Deneyin {#try-it}

```console
uv run mcp dev server.py
```

Inspector, gerçek bir host'un yaptığının aynısını yapar: `server.py` dosyasını bir alt süreç olarak başlatır ve ona stdio üzerinden bağlanır.

Ona hiç port vermediniz. Zaten yok.

## Streamable HTTP {#streamable-http}

Aynı sunucuyu bunun yerine bir porta koymak için aktarımı (ve seçeneklerini) `run()` içinde belirtin:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

Bu tek satır bir Starlette uygulaması kurar ve onu uvicorn ile sunar. İstemciler `http://127.0.0.1:3001/mcp` adresine bağlanır.

Her aktarımın kendi anahtar sözcük argümanları vardır ve hepsi `run()` üzerindedir:

* `host` / `port`: nerede dinleneceği. Varsayılanlar `127.0.0.1` ve `8000`.
* `streamable_http_path`: MCP endpoint'inin bulunduğu yol. Varsayılan `/mcp`.
* `json_response=True`: her POST'a SSE akışı yerine tek bir JSON gövdesiyle yanıt verir. Bu gövdede yanıttan başka hiçbir şeye yer yoktur; bu yüzden istek sırasında istemciye geri çağrı yapan bir araç (`ctx.elicit()`, örnekleme (sampling)) bu ayakta `NoBackChannelError` fırlatır ve sürmekte olan çağrıya bağlı bildirimler (`ctx.report_progress()` ile bildirilen ilerleme, çağrıya özel log mesajları) düşürülür; bağımsız `GET` akışı ilgisiz olanları taşımaya devam eder.
* `stateless_http=True`: istek başına yeni bir aktarım, oturum takibi yok.
* `max_request_body_size`: bayt cinsinden kabul edilen en büyük POST gövdesi. Varsayılan olarak 4 MiB;
  daha büyük istekler, ayrıştırma veya oturum oluşturma öncesinde HTTP 413 alır. Bunu yalnızca meşru
  MCP mesajları bu boyutu aştığında yükseltin.
* `event_store`, `retry_interval`, `transport_security`: kaldığı yerden devam edebilme ve DNS rebinding koruması. localhost dışında bir yere dağıtım yapana kadar bekleyebilirler; `transport_security` konusunu **[Dağıtım ve ölçekleme](deploy.md)** ele alır.

!!! warning
    Aktarım seçenekleri `run()`'a gider, `MCPServer(...)`'a **değil**. Kurucu, sunucunuzun ne
    *olduğunu* tanımlar: ad, sürüm, talimatlar. `run()` ise nasıl sunulduğunu tanımlar. Bunu
    tersine çevirirseniz, daha MCP devreye bile girmeden Python yanıt verir:

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` kısa yoldur. Daha fazlasına ihtiyaç duyduğunuz an (sunucunuzun mevcut bir uygulamanın içine mount edilmesi, tek süreçte iki sunucu, tarayıcı istemcileri için CORS) ASGI uygulamasını kendiniz kurar ve herhangi bir ASGI sunucusuna teslim edersiniz. Bu da **[Mevcut bir uygulamaya ekleme](asgi.md)** sayfasının konusu.

## Sunucu ayarları {#server-settings}

Çalıştırmayla ilgili birkaç şey aktarımla ilgili değildir. Bunlar kurucu argümanlarıdır:

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: `MCPServer(...)` kurulduğu anda `logging.basicConfig()` fonksiyonuna verilir. Bu, **kök** logger'ı yapılandırır; dolayısıyla yalnızca SDK'nınkilerin değil, kendi logger'larınızın düzeyini de belirler. Varsayılan `"INFO"`.
* `debug`: HTTP aktarımlarının kurduğu Starlette uygulamasına iletilir. Varsayılan `False`.

Her ikisi de çalışma zamanında geri okuyabileceğiniz `mcp.settings` üzerine yerleşir.

## `mcp` komutu {#the-mcp-command}

`[cli]` ekstrası tüm bunların etrafına küçük bir komut satırı aracı kurar.

`mcp dev`, sunucunuzu **MCP Inspector** altında çalıştırır:

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with`, kurduğu ortama paket ekler; `--with-editable` kendi paketinizi o ortama kurar. `PATH` değişkeninizde `npx` bulunmalıdır: Inspector bir Node.js uygulamasıdır.

`mcp run` dosyayı içe aktarır, sunucu nesnesini (modül düzeyinde bir `mcp`, `server` veya `app`) bulur ve üzerinde `run()` çağırır:

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

`:` soneki, nesnenin adı `mcp`, `server` veya `app` olmadığında onu belirtir.

`if __name__ == "__main__":` bloğunuz burada hiç çalışmaz: `mcp run`, `run()`'ı kendisi çağırır ve ilettiği tek seçenek `--transport` seçeneğidir.

`mcp install` sunucuyu **Claude Desktop**'a kaydeder; böylece uygulama onu sizin için başlatır:

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` ve `-f .env`, ortam değişkenlerini bu kayda işler. Claude Desktop sunucunuzu kendi sürecinde başlatır. Kabuğunuzun ortamı orada yoktur.

Claude Desktop, `mcp install` komutunun bildiği tek host'tur. Diğer tüm host'lar (Claude Code, Cursor, VS Code) aynı başlatma komutunu kendi yapılandırma dosyalarında alır; her biri **[Gerçek bir host'a bağlanma](../get-started/real-host.md)** sayfasında var.

`mcp version` kurulu SDK sürümünü yazdırır.

!!! tip
    `mcp dev` ve `mcp run` yalnızca `MCPServer`'ı anlar. Düşük seviyeli `Server` ile geliştiriyorsanız
    onu kendiniz çalıştırırsınız. Bkz. **[Düşük seviyeli Server](../advanced/low-level-server.md)**.

## Özet {#recap}

* **Aktarım**, baytların sunucunuza nasıl ulaştığıdır: yerel bir alt süreç için `stdio`, bir port için `streamable-http`. SSE'nin yerini yenisi aldı.
* `mcp.run()` aktarımı seçer. Argümansız `stdio`'dur ve bloke kalır.
* Her aktarım seçeneği (`host`, `port`, `streamable_http_path`, ...) `run()`'a verilen bir argümandır, asla `MCPServer(...)`'a değil.
* `run()`'ı `if __name__ == "__main__":` altında tutun. Sunucunuzu yükleyen her şey önce dosyayı içe aktarır.
* `log_level=` ve `debug=` kurucu argümanlarıdır; `mcp.settings` üzerine yerleşirler.
* Inspector için `mcp dev`, bir dosyayı çalıştırmak için `mcp run`, Claude Desktop için `mcp install`, sürüm için `mcp version`.
* Aktarım, sunucunuzun ne *olduğunu* asla değiştirmez: bu sayfadaki üç dosya da birebir aynı aracı sunar.

Sınır `run()`'ın kendisi olduğunda (sunucunuz zaten var olan bir uygulamanın içindeyse) adres **[Mevcut bir uygulamaya ekleme](asgi.md)**. Gerçek bir ana bilgisayar adı ve birden fazla worker **[Dağıtım ve ölçekleme](deploy.md)** sayfasında. İstemcilerinizden bazıları hâlâ 2025-11-25 veya daha eski bir spesifikasyon sürümündeyse, iyi haber **[Eski nesil istemcilere hizmet verme](legacy-clients.md)** sayfasında.
