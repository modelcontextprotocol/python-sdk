---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "Bu belgeler, mevcut kararlı sürüm hattı olan v2'yi anlatır"
    v2'ye yeni mi başladınız, yoksa v1'den mi geliyorsunuz? **[v2'deki yenilikler](whats-new.md)** nelerin değiştiğine beş dakikalık bir bakış sunar, **[Geçiş kılavuzu](migration.md)** ise uyumluluğu bozan her değişikliği ele alır.
    Hâlâ v1.x'te misiniz? Onun belgeleri [v1.x belgeleri](https://py.sdk.modelcontextprotocol.io/v1/) adresinde.
    Pürüzlü ya da kafa karıştırıcı bir şey mi var? [Bize bildirin](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

**Model Context Protocol (MCP)**, uygulamaların LLM'lere standart bir biçimde bağlam sağlamasına olanak tanır; bağlam *sağlama* işini LLM etkileşiminin kendisinden ayırır.

Bu, onun resmi Python SDK'sı. Bununla şunları yapabilirsiniz:

* Herhangi bir MCP host'una araç, kaynak ve prompt sunan **MCP sunucuları oluşturun**.
* Herhangi bir MCP sunucusuna bağlanan **MCP istemcileri oluşturun**.
* Tüm standart aktarımları konuşun: stdio, Streamable HTTP ve SSE.

## Gereksinimler {#requirements}

Python 3.10+.

## Kurulum {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` eki size `mcp` komutunu kazandırır; geliştirme sırasında buna ihtiyacınız olacak.
Her bağımlılığın ne işe yaradığını görmek için [Kurulum](get-started/installation.md) sayfasına bakın.

## Örnek {#example}

### Oluşturun {#create-it}

`server.py` adında bir dosya oluşturun:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

Bu, eksiksiz bir MCP sunucusu.

Bir **araç** (`add`) ve bir şablonlu **kaynak** (`greeting://{name}`) sunar.

### Çalıştırın {#run-it}

```console
uv run mcp dev server.py
```

Bu komut sunucuyu başlatır ve onu kurcalamanız için etkileşimli bir arayüz olan [MCP Inspector](https://github.com/modelcontextprotocol/inspector)'ı açar. Yazdırdığı URL'yi açın.

!!! note
    Inspector bir Node.js uygulaması olduğundan `mcp dev`, `PATH`'inizde `npx` bulunmasını gerektirir.

### Deneyin {#try-it}

Inspector'da **Tools** sekmesine gidin ve `add` aracını `a=1`, `b=2` ile çağırın.

Geriye `3` döner. ✨

Inspector bu formu (`a` için zorunlu bir tamsayı alanı, `b` için bir diğeri) tür ipuçlarınızdan oluşturdu. Claude da, diğer tüm MCP host'ları da aynısını yapar.

Şimdi **Resources** sekmesine gidin ve `greeting://World` kaynağını okuyun:

```text
Hello, World!
```

### Özet {#recap}

Neleri **yazmadığınıza** bir daha bakın:

* JSON Schema yok. `a: int, b: int` şemanın *ta kendisi*.
* İstek ayrıştırma yok, serileştirme yok, doğrulama kodu yok.
* Protokol işleme hiç yok.

Tür ipuçları ve bir docstring içeren iki Python fonksiyonu yazdınız. Gerisini SDK halleder.

## Sırada ne var {#where-to-go-next}

* **[Başlarken](get-started/index.md)** sizi kurulumdan çalışan, test edilmiş bir sunucuya götürür.
* MCP sunucularını *kullanan* bir uygulama mı geliştiriyorsunuz? **[İstemciler](client/index.md)** ile başlayın.
* Hâlihazırda bir FastAPI veya Starlette uygulamanız mı var? **[Mevcut bir uygulamaya ekleme](run/asgi.md)** sayfası içine bir MCP sunucusu bağlar.
* Belirli bir hata mesajının peşinde misiniz? **[Sorun giderme](troubleshooting.md)** sayfası birebir metne göre düzenlenmiştir.
* v2'de nelerin değiştiğini mi merak ediyorsunuz? **[v2'deki yenilikler](whats-new.md)** beş dakikalık bir tur.
* v1'den mi geçiyorsunuz? **[Geçiş kılavuzu](migration.md)** ile başlayın.
* Belirli bir imzanın peşinde misiniz? **[API referansı](api/mcp/index.md)** kaynak koddan üretilir.
* Bir LLM ile mi okuyorsunuz? Bu belgeler [llms.txt](https://llmstxt.org/) biçiminde de yayımlanır:
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) sayfaların bir dizinidir,
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) ise tüm sayfaları tek bir dosyada içerir.
