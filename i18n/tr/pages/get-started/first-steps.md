---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# İlk adımlar {#first-steps}

**[Giriş sayfası](../index.md)** hızlı ilerler: bir sunucu yazın, çalıştırın, bir araç çağırın.

Bu sayfa ise ağırdan alır: bir sunucunun sunabileceği üç şeyin hepsini ele alır ve yol boyunca her şeye bir ad verir.

## Host, istemci ve sunucu {#host-client-and-server}

Bundan sonraki her sayfada göreceğiniz üç sözcük:

* **Host**, LLM uygulamasıdır: Claude, bir IDE, bir ajan çalışma zamanı. Kullanıcının konuştuğu şey odur.
* **İstemci**, host'un içinde yaşar ve MCP konuşur. Host, bağlandığı her sunucu için bir istemci çalıştırır.
* **Sunucu**, bu SDK ile sizin oluşturduğunuz şeydir. İstemcilere bir şeyler sunar. Modelle hiçbir zaman doğrudan konuşmaz.

Sunucuyu siz yazarsınız. Host'lar başkasının ürünüdür. SDK size bir de `Client` verir. Onu sunucularınızı test etmek için kullanırsınız; bu sayfanın ilerisinde karşınıza çıkar.

## Üç temel öğe {#the-three-primitives}

Bir sunucu tam olarak üç tür şey sunar. Onları birbirinden ayıran, **kullanılmalarına kimin karar verdiğidir**:

| Temel öğe      | Kontrol eden    | Nedir                                                         | Örnek                                         |
|----------------|-----------------|---------------------------------------------------------------|-----------------------------------------------|
| **Araçlar**    | Model           | Modelin bir eylemde bulunmak için çağırdığı fonksiyon          | Bir API çağrısı, bir veritabanı yazma işlemi   |
| **Kaynaklar**  | Uygulama        | Host'un modelin bağlamına yüklediği veri                       | Bir dosyanın içeriği, bir API yanıtı           |
| **Prompt'lar** | Kullanıcı       | Kullanıcının adıyla çağırdığı, yeniden kullanılabilir mesaj şablonu | Bir slash komutu, bir menü girdisi        |

"Kontrol eden", bu ayrımın özüdür. Bir araç, **model** onu çağırmaya karar verdiği için çalışır. Bir kaynak, **uygulama** modelin ona ihtiyacı olduğuna karar verdiği için eklenir. Bir prompt, **kullanıcı** onu seçtiği için çalışır.

!!! info
    Daha önce bir web API'si geliştirdiyseniz sezginin çoğu zaten sizde var: **kaynak** bir `GET`'tir
    (veri yükler, hiçbir şeyi değiştirmez), **araç** ise bir `POST`'tur (iş yapar ve yan etkileri
    olabilir). **Prompt**'un HTTP'de karşılığı yoktur; kullanıcının adıyla çalıştırdığı kayıtlı bir
    sorguya daha yakındır.

## Tek sunucu, üçü birden {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Üç sade fonksiyon, üç dekoratör. Her dekoratör kaydın tamamıdır:

* `@mcp.tool()`, `add`'i bir **araç** yapar.
* `@mcp.resource("greeting://{name}")`, `greeting`'i bir **kaynak şablonu** yapar: URI içindeki `{name}`, fonksiyonun parametresidir.
* `@mcp.prompt()`, `summarize`'ı bir **prompt** yapar. Döndürdüğü dize bir kullanıcı mesajına dönüşür.

Geri kalan her şeyi (adı, açıklamayı, argüman şemasını) SDK fonksiyonun kendisinden okur: adından, docstring'inden, tür ipuçlarından. Hiçbirini ayrıca bildirmediniz.

!!! tip
    SDK'nın iki yarısının iki ayrı import yolu vardır: `from mcp import Client` ve
    `from mcp.server import MCPServer`. `from mcp import MCPServer` diye bir şey yoktur.

### Deneyin {#try-it}

MCP Inspector ile çalıştırın:

```console
uv run mcp dev server.py
```

Yazdırdığı URL'yi açın. Inspector'da her temel öğe için bir sekme var; sırayla üzerinden geçin.

**Tools.** Tek bir girdi: `add`, açıklaması *Add two numbers.* Formda `a` için zorunlu bir tamsayı alanı, `b` için de bir tane daha var. Doldurun, çağırın; sonuç `3`. Inspector bu formu `a: int, b: int` ifadesinden oluşturdu. Diğer tüm istemciler de öyle yapar.

**Resources.** *Resources* listesi boş. `greeting`, **Resource Templates** altında; çünkü `greeting://{name}` bir parametre içerir: biri bir `name` verene kadar listelenecek tek bir kaynak yoktur. Ona `World` verin ve okuyun:

```text
Hello, World!
```

**Prompts.** Tek bir girdi: tek bir zorunlu `text` argümanı olan `summarize`. Biraz metinle getirin; `role: user` taşıyan ve içeriği işlenmiş dizeniz olan tek bir mesaj alırsınız. Bir prompt'un hepsi budur: mesaj oluşturan bir fonksiyon.

Inspector sunucunuzu **stdio** üzerinden çalıştırdı; bu, bir MCP sunucusunun konuşabileceği aktarımlardan biridir. Henüz bir tane seçmiyorsunuz; bunun sayfası **[Sunucunuzu çalıştırma](../run/index.md)**.

## Yetenekler {#capabilities}

Inspector'da üç sekme gördünüz. Üç tane olduğunu nereden bildi?

Bir istemci bağlandığında sunucu **yeteneklerini** beyan eder: hangi istek ailelerini yanıtlayacağını. İstemci, neyi isteyeceğine karar vermek için bu beyanı kullanır. Bunu siz hiç yazmadınız; `MCPServer` sizin yerinize beyan eder.

Kendiniz bakın. SDK'nın `Client`'ı sunucu nesnesini doğrudan kabul eder ve ona **bellek içinde** bağlanır (alt süreç yok, port yok):

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

Bu sözlük, sunucunuzun beyan ettiği **yeteneklerdir**. Bağlanan her istemcinin öğrendiği ilk şey budur:

| Yetenek     | İstemci artık şunları çağırabilir                               |
|-------------|----------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                      |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read`  |
| `prompts`   | `prompts/list`, `prompts/get`                                   |

`MCPServer` üç temel öğenin hepsini sunar; bu yüzden üçü de her zaman beyan edilir.

Orada ne olmadığına dikkat edin. `completions` (kaynak şablonları ve prompt'lar için argüman otomatik tamamlama) sizin yazacağınız bir işleyici gerektirir; bu sunucuda yok, dolayısıyla yetenek de yok ve uslu bir istemci sormaz. İsteğe bağlı her şey için kural budur: şeyi kaydedin, yetenek belirir; **[Tamamlamalar](../servers/completions.md)** bunu kanıtlar.

!!! info
    `Client(mcp)`, bu belgelerdeki her örneğin test edildiği aynı bellek içi istemcidir;
    sizinkileri de böyle test edeceksiniz. Kendine ait koca bir sayfası var: **[Test etme](testing.md)**.

## Yazmadıklarınız {#what-you-did-not-write}

Bu sayfaya dönüp bir bakın. Üç küçük Python fonksiyonu yazdınız. Şunları **yazmadınız**:

* Bir JSON Schema. `a: int, b: int`, `add` şemasının *ta kendisidir*.
* Bir istek işleyici. `tools/list`, `resources/read`, `prompts/get`: hepsi sizin yerinize sunulur.
* Bir yetenek beyanı. `MCPServer` onu sizin yerinize yaptı.
* Tek satır protokol. Sürüm anlaşması, JSON-RPC çerçevelemesi, yetenek değiş tokuşu: hepsi `mcp dev` ve `Client(mcp)` içinde oldu ve siz hiçbirini görmediniz.

SDK'nın bütün meselesi bu oran.

## Özet {#recap}

* **Host** LLM uygulamasıdır, **istemci** onun MCP konuşan yarısıdır, **sunucu** ise sizin oluşturduğunuz şeydir.
* Araçları **model**, kaynakları **uygulama**, prompt'ları **kullanıcı** kontrol eder.
* Her temel öğe için bir dekoratör: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Ad, açıklama ve şema fonksiyondan gelir.
* İçinde `{param}` olan bir URI, somut kaynaklardan ayrı listelenen bir kaynak **şablonu** oluşturur.
* Sunucunun **yetenekleri** sizin yerinize beyan edilir ve bir istemci yalnızca sunucunun beyan ettiklerini ister.
* `Client(mcp)` sunucu nesnesine bellek içinde bağlanır: ilk günden test düzeneğiniz.

Sırada **[Gerçek bir host'a bağlanma](real-host.md)** var: bu sunucu, gerçekten, Claude Desktop'ın ya da bir IDE'nin içinde. Ardından **[Test etme](testing.md)**: bir sayfa, bir bellek içi istemci ve çalışıp çalışmadığını bir daha asla tahmin etmek zorunda kalmazsınız. Ondan sonra her temel öğenin kendi sayfası var; modelin yönettiğiyle başlıyoruz: **[Araçlar](../servers/tools.md)**.
