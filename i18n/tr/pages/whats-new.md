---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# v2'deki yenilikler {#whats-new-in-v2}

v2'de iki şey aynı anda oldu. **SDK yeniden inşa edildi**: hem istemcinin hem sunucunun altında yeni bir motor, birinci sınıf bir `Client` ve bir v1 kod tabanının daha ilk import'unda karşılaştığı bir dizi yeniden adlandırma. Ve **protokol ilerledi**: v2, MCP'nin 2026-07-28 revizyonunu konuşur; bu revizyon bağlantı el sıkışmasını, oturumu ve sunucunun başlattığı her isteği kaldırır, üstelik hâlihazırda sahip olduğunuz istemcileri yarı yolda bırakmadan.

Bu sayfa her iki yarının da turu: her başlık için bir bölüm, her biri konunun asıl sahibi olan sayfaya çıkar. Taşıma el kitabı değildir. O, **[Geçiş kılavuzu](migration.md)**: uyumluluğu bozan her değişiklik, öncesi ve sonrası koduyla.

!!! note "v2 kararlı sürüm hattıdır"
    `pip install mcp` 2.x sürümünü kurar; kopyalayıp yapıştırabileceğiniz kurulum satırı
    **[Kurulum](get-started/installation.md)** sayfasında. v2'de herhangi bir şey bozulur, sizi şaşırtır
    ya da yavaşlatırsa [bize bildirin](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

## SDK: v1'den v2'ye {#the-sdk-v1-to-v2}

### `FastMCP` artık `MCPServer` {#fastmcp-is-now-mcpserver}

Üst düzey sunucu sınıfının adı değişti, modülü de onunla birlikte. Her v1 sunucusunun ilk çarptığı şey budur; çünkü eski import yolu kullanım dışı bırakılmadı, doğrudan kaldırıldı:

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

Dekoratörlerle kurulmuş bir sunucu için taşıma işinin büyük kısmı da budur. `@mcp.tool()`, `@mcp.resource()` ve `@mcp.prompt()` v1'de ne kabul ediyorsa onu kabul eder (`@mcp.resource()` isteğe bağlı bir `security=` anahtar sözcüğü ekler) ve girdi şeması hâlâ tür ipuçlarınızdan gelir. Kenarda köşede kalanlar: `mcp.server.fastmcp.*` altındaki her şey artık `mcp.server.mcpserver.*` altında, `ctx.fastmcp` artık `ctx.mcp_server`, `get_context()` kaldırıldı (yerine bir `ctx: Context` parametresi bildirin) ve istisna taban sınıfı `FastMCPError` artık `MCPServerError`. Import tablosu **[Geçiş kılavuzu](migration.md#fastmcp-renamed-to-mcpserver)** sayfasında.

### `Resolve`: kullanıcıdan girdi istemenin yeni yolu {#resolve-the-new-way-to-ask-the-user-for-input}

Bir aracın ihtiyaç duyduğu her şey modelden gelmek zorunda değil. v2 ile gelen yenilik: `Resolve(fn)` ile işaretlenmiş bir araç parametresini, modele görünmeden, sizin yazdığınız bir fonksiyon doldurur ve bu fonksiyon kullanıcının önüne bir soru koymak için `Elicit(...)` döndürebilir. Çağrı ortasında istemciden herhangi bir şey almanın tercih edilen yolu budur: SDK soruyu bağlantının desteklediği mekanizma hangisiyse onun üzerinden taşır (eski nesil bir istemci için canlı bir elicitation (kullanıcıdan bilgi isteme) isteği, 2026-07-28'de çok turlu (multi-round-trip) bir istek); böylece tek bir araç gövdesi her iki nesle de hizmet eder. İlgili sayfa **[Bağımlılıklar](handlers/dependencies.md)**.

!!! note
    Diğer iki biçim, ihtiyaç duyduğunuzda hâlâ yerinde: `ctx.elicit()` eski nesil bağlantılardaki
    istemciler için çalışmaya devam eder (**[Elicitation](handlers/elicitation.md)**) ve bir işleyici
    `InputRequiredResult`'ı kendisi döndürüp turları elle yürütebilir; örnekleme (sampling) ve
    kök dizinler (roots) istekleri de 2026-07-28'de bu yoldan gider (**[Çok turlu istekler](handlers/multi-round-trip.md)**).

### Birinci sınıf bir `Client` {#a-first-class-client}

v1 size iç içe üç katman veriyordu: ham akışlar üreten bir aktarım bağlam yöneticisi, bunların etrafına sarılmış bir `ClientSession` ve elle çağrılan bir `await session.initialize()`. v2'de tek bir nesne var:

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` bir sunucu nesnesi (bellek içi, aktarım yok: test senaryosu), bir URL (Streamable HTTP) ya da `stdio_client(...)` gibi herhangi bir aktarım bağlam yöneticisi alır. `async with` bloğuna girmek bağlantıyı kurar ve sunucu hangi nesli konuşuyorsa ona göre protokol sürümünde anlaşır; ardından `client.server_capabilities` ve `client.protocol_version` hazırdır, sunucu kendini tanıttığında `client.server_info` da öyle (artık `Implementation | None` türünde, çünkü 2026 neslinde kimlik isteğe bağlı). v1'de kaydettiğiniz örnekleme ve elicitation callback'leri hâlâ çalışır (gövdeleri, bu sayfadaki her şey gibi aynı snake_case öznitelik yeniden adlandırmasını görür); artık 2026 tarzı sonuç-içinde-isteklere de (aşağıda) yanıt verirler ve teker teker değil eşzamanlı çalışırlar. Düşük düzey yüzeyi isteyenler için `ClientSession` hâlâ altta duruyor ve `client.session` onu size verir; o da taşındı (yeni dispatcher motoru üzerinde çalışır ve kendi imzalarından bazıları değişti), bu yüzden aşağı inmeden önce **[Geçiş kılavuzu](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)** sayfasını okuyun.

**[Client](client/index.md)** sayfası onu tanıtır, **[İstemci aktarımları](client/transports.md)** üç bağlantı biçimini anlatır, **[İstemci callback'leri](client/callbacks.md)** callback'lerin kendisini ele alır ve **[Test etme](get-started/testing.md)** v1'in `create_connected_server_and_client_session()` yardımcısının yerini alan bellek içi kalıbı gösterir.

### Düşük düzey `Server` yeniden adlandırılmadı, yeniden inşa edildi {#the-low-level-server-was-rebuilt-not-renamed}

JSON-RPC katmanında çalışıyorsanız, v2'nin "her şey farklı" kısmı burası. İşte tek araçlı aynı sunucunun iki hâli; nelerin değiştiğini görmek için işaretçilere tıklayın.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. İşleyiciler dekoratörlerle (parantezli, çağrılarak) kaydedilir; sunucu var olduktan sonra herhangi bir zamanda.
2. Yalın bir `list[Tool]` döndürürsünüz, SDK onu bir `ListToolsResult` içine sarar.
3. Alanlar Python'da camelCase'tir ve şema **zorunlu tutulur**: SDK, fonksiyonunuz çalışmadan önce `call_tool` argümanlarını jsonschema ile bu şemaya göre doğrular; aşağıdaki `arguments["query"]` bu yüzden güvenlidir.
4. Tek bir `call_tool` işleyicisi tüm araçlara hizmet eder; araç adını ve zaten doğrulanmış argümanları açılmış hâlde alır, asla `None` değildir.
5. Bir v1 aracı başarısızlığı istisna fırlatarak bildirir: her istisna yakalanır ve metni `str(e)` olan bir `CallToolResult(isError=True)` olarak döndürülür; çağıran model bu mesajı okur ve yeniden deneyebilir.
6. Bağlam, istek ortasında sunucu nesnesi üzerinden erişilen ortamdaki bir ContextVar'dan gelir.
7. Yalın içerik blokları sizin için bir `CallToolResult` içine sarılır.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Alanlar artık snake_case ve şema **ilan edilir ama asla uygulanmaz**: işleyiciniz çalışmadan önce argümanları hiçbir şey denetlemez.
2. Her işleyici aynı biçimdedir: `async (ctx, params) -> result`. Bağlam ilk argümandır (`ctx.session`, `ctx.request_id`, `ctx.protocol_version` onun üzerinde yaşar); `server.request_context` buraya taşındı.
3. Tam `ListToolsResult`'ı kendiniz kurarsınız. Yalın bir liste döndürmek artık SDK'nın sardığı bir şey değil, sunucu tarafında bir `TypeError`.
4. Tipli parametreler girer (`params.name`, `params.arguments`), tam bir sonuç çıkar. Sizin için hiçbir şey açılmaz, sarılmaz ya da dönüştürülmez.
5. Aynı denetim, farklı fiil. Buradaki bir `ValueError` modele opak bir `-32603` olarak ulaşırdı (aşağıya bakın); bu yüzden kasıtlı bir protokol hatası `MCPError` olarak fırlatılır: kodu ve mesajı bozulmadan geçer ve bu metinle `-32602`, bilinmeyen bir araç için spesifikasyonun kendi yanıtıdır.
6. `params.arguments` `None` olabilir; v1 onu kodunuz görmeden önce varsayılan olarak `{}` yapıyordu. İşleyicinin önünde doğrulama olmadığından bu satır yük taşır.
7. Burada fırlatılan beklenmedik bir istisna **arındırılmış** bir protokol hatasına, `-32603` `"Internal server error"`'a dönüşür: model mesajı asla görmez. Modelin okuyup tepki vermesi gereken bir başarısızlık için `CallToolResult(is_error=True, ...)` döndürün.
8. İşleyiciler kurucu argümanlarıdır; bu yüzden sunucunun yüzeyi var olduğu anda tamamdır. `add_request_handler()` kuruluş sonrası kaçış kapağı ve özel metotlara açılan kapıdır.

Örnek, kalıbın ta kendisi. Daha genel olarak: her işleyici aynı biçimdedir, tipli parametreler girer ve tam bir sonuç türü çıkar; araç argümanlarının eski jsonschema denetimi kalktı; bir istisna protokol hatasıdır, asla `is_error=True` bir araç sonucu değildir; ortamdaki `server.request_context` ContextVar'ı da kalktı. Sağlayıcı ad alanlı özel metotlar, gelen parametreleri işleyiciniz çalışmadan önce modelinize göre doğrulayan `add_request_handler(method, params_type, handler)` sayesinde birinci sınıftır. Ve (bilerek geçici olarak işaretlenmiş) bir `middleware` listesi gelen her mesajı sarar; eskiden insanların ezdiği özel `_handle_*` metotlarının yerini alır.

Altta, v1'in `BaseSession` alma döngüsünün yerini artık istemci ile sunucunun paylaştığı bir dispatcher motoru aldı; bu sayfadaki birkaç şeyi aynı anda doğru kılan da odur: tek bir `Server` nesnesi her iki protokol nesline de hizmet eder, `Client(server)` JSON-RPC çerçevelemesi olmadan süreç içinde yönlendirir ve zaman aşımına uğrayan bir istemci isteği artık sunucu tarafındaki işleyiciyi gerçekten iptal eder.

İlgili sayfa **[Düşük düzey Server](advanced/low-level-server.md)**; **[Geçiş kılavuzu](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** kaldırılan her kancayı tek tek anlatır. `MCPServer`'ın altına hiç inmediyseniz bunların hiçbiri sizi etkilemez.

### Protokol türleri `mcp-types` paketine taşındı, her alan artık snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

Protokol türleri artık kendi dağıtım paketlerinde, `mcp-types` içinde yaşıyor. pydantic ve typing-extensions dışında hiçbir şeye bağımlı değildir; bu yüzden bir ağ geçidi, vekil sunucu ya da kod üreteci bir HTTP yığını kurmadan MCP'nin protokol veri biçimlerini tüketebilir: böyle bir proje `mcp-types` paketini kurar ve `mcp_types`'ı import eder. `mcp`'nin kendisi bu pakete tam sürümle bağımlıdır ve onu yeniden dışa açar; dolayısıyla SDK'ya bağımlı kod `import mcp.types as types` ve `from mcp.types import Tool` yazmaya devam eder (kalıcı bir takma ad, her ad aynı nesne) ve yalnızca tek gerçek bağımlılığını, `mcp`'yi bildirir. Pratik kural: hangi pakete gerçekten bağımlıysanız onun üzerinden import edin.

Bu türlerde her Python özniteliği artık snake_case: `result.is_error`, `tool.input_schema`, `listing.next_cursor`. İletilen JSON tam eskisi gibi camelCase; yalnızca özniteliklerin yazımı değişti. İki sıkı varsayılan da beraberinde gelir: bilinmeyen alanlar geri döndürülmek yerine yok sayılır (fazlalıkları `_meta`'ya koyun) ve her iki taraf da trafiği üzerinde anlaştıkları protokol sürümüne göre doğrular. Yeniden adlandırma tablosu için **[Geçiş kılavuzu](migration.md#field-names-changed-from-camelcase-to-snake_case)** sayfasına bakın.

### Aktarım yapılandırması `run()`'a taşındı {#transport-configuration-moved-to-run}

`MCPServer(...)` sunucunuzun *ne olduğuyla* ilgilidir: adı, talimatları, lifespan'i (yaşam döngüsü), kimlik doğrulaması. Nasıl *sunulduğu* artık `run()`'a ve uygulama kurucularına ait; `host`, `port`, `stateless_http`, `json_response`, endpoint yolları ve `transport_security` oraya gitti (`MCPServer("x", port=9000)` bir `TypeError`'dır). Aşırı yüklemeler aktarıma göre tiplendirilmiştir; böylece editörünüz `stdio`'nun hangi seçenekleri aldığını, `streamable-http`'nin hangilerini aldığını söyler. Bilmeye değer bir kaldırma: `mount_path` gitti; bir önek altında sunmanın desteklenen yolu ASGI uygulamasını bağlamaktır (mount).

Seçenekleri **[Sunucunuzu çalıştırma](run/index.md)**, bağlamayı **[Mevcut bir uygulamaya ekleme](run/asgi.md)** sayfası anlatır.

### Import hatası vermeden değişen davranışlar {#behavior-that-changes-without-an-import-error}

Yeniden adlandırmalar kendini belli eder. Bunlar etmez:

* **Senkron fonksiyonlar bir işçi iş parçacığında çalışır.** Bir `def` aracı (ya da kaynağı, prompt'u veya çözümleyicisi) artık olay döngüsünü engellemez; bunun bedeli, gövdesinin artık olay döngüsü iş parçacığının *üzerinde* çalışmamasıdır ve bu, iş parçacığına bağlı kod için önemlidir. `async def` işleyicilere dokunulmadı. **[Geçiş kılavuzu](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**.
* **Bir aracın içinde fırlatılan `MCPError` (v1'deki `McpError`) artık bir protokol hatasıdır.** Model onu asla görmez. Diğer her istisna hâlâ modelin okuyup tepki verebileceği `is_error=True` bir sonuca dönüşür. Ayrım **[Hataları ele alma](servers/handling-errors.md)** sayfasında.
* **Sonuçlar çıkmadan önce doğrulanır.** `input_schema`'sı `{}` olan elle kurulmuş bir `Tool` artık `tools/list` çağrısında başarısız olur (spesifikasyon `"type": "object"` gerektirir). `@mcp.tool()` üzerine kurulu sunucular bunu asla görmez; şemalarını SDK yazar.
* **İstemciniz aldığını doğrular.** `list_tools()` ve `call_tool()` sunucunun yanıtını üzerinde anlaşılan protokol sürümüne göre denetler; bu yüzden v1'in hoşgörülü ayrıştırmasının idare ettiği tam geçerli olmayan bir sunucu artık `pydantic.ValidationError` fırlatır. Kontrol etmediğiniz sunuculara bağlanıyorsanız onları bulan kişi olmayı bekleyin; ayrıntılar **[Geçiş kılavuzu](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)** sayfasında.
* **URI şablonları artık gerçek RFC 6570.** `{+path}`, `{?query}` ve benzerleri çalışır, eşleştirme regex gevşekliğinde değil birebirdir ve çıkarılan değerlerdeki yol geçişi (path traversal) varsayılan olarak reddedilir. Daha sıkı şablonlar ilk istekte değil, dekoratör uygulanırken başarısız olur. **[URI şablonları](servers/uri-templates.md)**.
* **Streamable HTTP lifespan'i bir kez çalışır**, başlangıçta; durumu da her oturum ve istek tarafından paylaşılır. v1'de oturum başına bir kez, `stateless_http=True` altında ise istek başına bir kez çalışıyordu. Bir lifespan'de kurulan havuzlar ve önbellekler çarpıcı biçimde ucuzlar; orada bağlantı başına bir kaynak edinen her şeyin yeri artık işleyici gövdesi. **[Lifespan](handlers/lifespan.md)**.
* **`mcp dev` ve `mcp install` başlattıkları ortamı** kurulu SDK sürümünüze sabitler. Her iki komut da sunucunuzu yeni bir `uv run --with ...` ortamında çalıştırır; bu ortam eskiden `mcp`'yi geliştirme yaptığınız sürüme değil en yeni kararlı sürüme çözümlerdi. **[Geçiş kılavuzu](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**.
* **HTTP istemcisi artık `httpx` değil, `httpx2`.** Bağımlılık değişimi kodunuzun neyi yakalayıp neyi geçirdiğini (`httpx2.AsyncClient`, `httpx2.ConnectError`) ve TLS sertifikalarının nasıl doğrulandığını değiştirir: `httpx2`, certifi'nin paketlenmiş CA listesi yerine `truststore` üzerinden işletim sisteminin güven deposuna göre doğrular. Çoğu ortam bunu hiç fark etmez; sistem CA deposu olmayan minimal bir konteyner ya da yalnızca certifi paketinin bildiği özel bir CA, TLS el sıkışmasında başarısız olmaya başlar. `SSL_CERT_FILE`/`SSL_CERT_DIR` ayarlayın veya istemcinize `verify=ssl_context` geçirin. **[Geçiş kılavuzu](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**.

### Tamamen kaldırılanlar {#removed-outright}

Bunların her biri **[Geçiş kılavuzu](migration.md)** içinde bir bölüm:

* **WebSocket aktarımı**, iki tarafta da, ve `mcp[ws]` ekstrası. Hiçbir zaman MCP spesifikasyonunun parçası olmadı.
* **Deneysel Tasks** API'si (`mcp.*.experimental`). 2026-07-28, görevleri çekirdek protokolden çıkarıp resmi bir uzantıya taşır ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)); bu SDK onu henüz uygulamıyor.
* Import yolu olarak `mcp.shared.version`, `mcp.shared.progress` ve `mcp.shared.session` (v1 `message_handler` tür açıklamalarının import ettiği `RequestResponder` taslağıyla birlikte). (`mcp.types` *kaldırılmadı*: bağımsız `mcp_types` paketi için kalıcı bir takma ad olarak kalır.)
* Kullanım dışı `streamablehttp_client` yazımı ve `streamable_http_client`'tan `get_session_id` callback'i (artık tam olarak iki akış üretir).
* `McpError`; doğrudan `(code, message, data)` kurucusuyla **`MCPError`** olarak yeniden adlandırıldı.
* `MCPServer.get_context()`, `mount_path=` ve düşük düzey `Server`'ın dekoratör metotları, ContextVar'ı ve işleyici dict'leri.

## Protokol: 2025-11-25'ten 2026-07-28'e {#the-protocol-2025-11-25-to-2026-07-28}

v2, 2026-07-28 revizyonunu uygular ve **her iki** revizyona birden hizmet verir: aynı `streamable_http_app()` (ve aynı stdio sunucusu) yapılandırılacak hiçbir şey, çevrilecek bir bayrak ve ayrı bir dağıtım olmadan hem 2025 neslinden bir istemcinin `initialize` isteğini hem de 2026 neslinden bir istemcinin isteklerini yanıtlar. Yeni revizyonu sunmak eskisindeki bir istemciyi yarı yolda bırakmaz. Aşağıda yeni revizyonun kendisinin neleri değiştirdiği var.

### El sıkışma yok, oturum yok {#no-handshake-no-session}

Bir 2026-07-28 istemcisi bağlantı açıp anlaşıp sonra konuşmaz. Her istek protokol sürümünü, istemci bilgisini ve istemci yeteneklerini `_meta` içinde taşır; tek keşif çağrısı olan `server/discover` da diğerleri gibi düz bir istektir. `Client` varsayılan olarak doğru olanı yapar: `server/discover`'ı bir kez yoklar ve sunucu daha eskiyse `initialize` el sıkışmasına geri döner.

Streamable HTTP üzerinde 2026 yolunda `Mcp-Session-Id` yoktur; operasyonel manşet de budur: **modern bir isteği bir işçiye bağlayan hiçbir şey yok**, dolayısıyla düz bir round-robin yük dengeleyicinin arkasındaki herhangi bir kopya onu yanıtlayabilir. İki dürüst çekince. 2025 neslinden istemcileriniz (bugün istemcilerin çoğu bu) hâlâ oturum açar ve v1'de ne kadar yapışkanlığa ihtiyaç duyuyorlarsa o kadarına hâlâ ihtiyaç duyar; onlar için hiçbir şey değişmez. Ve *çok turlu* bir yeniden denemenin işçiler arasında taşıması gereken tek şey mühürlü `request_state`'idir; varsayılan anahtarı süreç başına üretildiğinden ölçeklenmiş bir dağıtım `RequestStateSecurity(keys=[...])` geçirir. (`stateless_http=True` bununla ilgisiz: yalnızca 2025 neslinden istemcilere nasıl hizmet verildiğini etkiler ve 2026 trafiği onu asla okumaz; v1'de zaten ayarladıysanız hiçbir şey değişmez.)

Bunun istemci tarafı **[Protokol sürümleri](protocol-versions.md)** sayfasında, işletmecinin denetim listesi (Host izin listesi, `request_state` anahtarı, kopyalar arası bildirimler) **[Dağıtım ve ölçekleme](run/deploy.md)** sayfasında, iki nesle birden hizmet verme hikâyesi ise **[Eski nesil istemcilere hizmet verme](run/legacy-clients.md)** sayfasında.

### Sunucu istemciyi çağıramaz: çok turlu istekler {#the-server-cannot-call-the-client-multi-round-trip-requests}

2026-07-28'de sunucunun başlattığı her istek kalktı: itme (push) tarzı elicitation, örnekleme, `roots/list`. 2026 bağlantısında bunlar için bir kanal yoktur; bu yüzden `ctx.elicit()` ve `ctx.session.create_message()` orada `NoBackChannelError` ile başarısız olur (eski nesil istemciler için hâlâ çalışırlar).

Yerine gelen çözüm çağrıyı tersine çevirir. Kullanıcıdan bir şeye ihtiyaç duyan araç soruyu *döndürür* (`InputRequiredResult`), istemci onu her zamanki callback'leriyle yanıtlar ve çağrı yanıtlar eklenmiş hâlde yeniden denenir. Bu döngüyü sizin için `Client` yürütür. Sunucuda sonucu nadiren kendiniz kurarsınız, çünkü bunu bir **[bağımlılık](handlers/dependencies.md)** yapar: bir parametreyi `Resolve(ask_quantity)` ile işaretleyin (`ask_quantity` sizin yazdığınız sıradan bir fonksiyondur), SDK de bağlantının desteklediği mekanizma hangisiyse onun üzerinden sorar: eski nesil bir oturumda canlı bir elicitation isteği, 2026'da çok turlu bir istek. Tek araç gövdesi, iki nesil birden:

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

Bu dosya tüm vaadin tek yerde özeti: bir sunucu, `Resolve` destekli bir araç ve ikisi de yanıtını bellek içinde alan bir eski nesil istemci ile bir modern istemci. **[Çok turlu istekler](handlers/multi-round-trip.md)** mekanizmayı açıklar (SDK'nın sizin için mühürleyip doğruladığı `request_state` dâhil); sorma kısmı **[Elicitation](handlers/elicitation.md)** sayfasında.

!!! warning "Taşınmış bir v1 sunucusunun davranış değiştirdiği tek yer burası"
    Buna ilk sizin testleriniz çarpar: `Client(mcp)` v2 sunucunuzla varsayılan olarak 2026-07-28
    üzerinde anlaşır; bu yüzden `ctx.elicit()` çağıran bir araç, v1'de geçen bir testte başarısız olur.
    Soruyu bir `Resolve(...)` parametresine taşıyın (nesiller arası taşınabilir) ya da itme davranışını
    gerçekten istiyorsanız test istemcisini `mode="legacy"` ile sabitleyin.

### Kök dizinler, örnekleme ve protokol log kaydı kullanım dışı; `ping` kaldırıldı {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) üç *yeteneği* bütünüyle, her protokol sürümünde kullanım dışı bırakır: kök dizinler, örnekleme ve MCP düzeyinde log kaydı (`ctx.info()` ve benzerleri). Bu, yukarıdaki eksik geri kanaldan (back-channel) ayrı bir eksen; kullanım dışı olmak tavsiye niteliğindedir, her şey 2025 neslinden oturumlara karşı çalışmaya devam eder ve iletilen veride hiçbir şey değişmez. Fark edeceğiniz şey `MCPDeprecationWarning`'dir; bir `UserWarning` olduğu için varsayılan olarak yazdırılır. Yükseltmeden sonraki ilk `ctx.info(...)` çağrınızın bunu söylemesini bekleyin.

`ping` daha katı: kullanım dışı bırakılmadı, protokolden kaldırıldı. Kullanım dışı özelliklerin bağımsız metotlarından ikisi, `logging/setLevel` ve istemcinin `notifications/roots/list_changed` bildirimi, 2026-07-28'de aynı şekilde kaldırıldı; ilerleme bildirimleri de artık yalnızca sunucudan istemciye gider.

Tablonun tamamı, her birinin yerine geçen çözüm ve eski nesil istemcilere hizmet verirken sessiz bir log'a ihtiyacınız varsa tek satırlık filtre **[Kullanım dışı özellikler](deprecated.md)** sayfasında.

### Değişiklik bildirimleri tek bir akışa dönüşüyor {#change-notifications-become-one-stream}

2026-07-28'de bağımsız HTTP GET akışının ve `resources/subscribe`'ın yerini `subscriptions/listen` alır: istemci uzun ömürlü tek bir akış açar ve istediği bildirim türlerini adlandırır. `MCPServer` bunu varsayılan olarak sunar; `await ctx.notify_resource_updated(uri)` ile (ve `notify_tools_changed()` vb. ile) yayımlarsınız, bir middleware (ara katman) dinleme isteğini çağıran bazında reddedebilir ve çok kopyalı dağıtımlar paylaşılan bir `SubscriptionBus` takar. İstemcide `async with client.listen(...)` akışı açar: filtre anahtar sözcük argümanları olarak girer, tipli değişiklik olayları geri gelir ve `sub.honored` sunucunun teslim etmeyi kabul ettiği alt kümedir.

Yayımlama ve sunma **[Abonelikler](handlers/subscriptions.md)** sayfasında, izleyen uç **[istemci tarafındaki ikizinde](client/subscriptions.md)**, bus ise **[Dağıtım ve ölçekleme](run/deploy.md)** sayfasında.

### Geri kalanlar, kısaca {#the-rest-quickly}

* **Kimlik isteğe bağlı, mesaj başına bir üstveridir.** İstek tarafındaki `clientInfo` `_meta` anahtarı isteğe bağlıdır (zorunlu ikili `protocolVersion` + `clientCapabilities`) ve `serverInfo`, `server/discover` sonuç gövdesinden çıktı: sunucular artık onu 2026 neslinden her sonucun `_meta`'sına damgalar ([spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). SDK her zaman damgalar; bir sunucu kendini tanıtmadığında (örneğin bir middleware anahtarı çıkardığında) `client.server_info` `None` olur. Damganın iletilen verideki hâlini **[Düşük düzey Server](advanced/low-level-server.md)** gösterir.
* **İstekler gövde ayrıştırılmadan yönlendirilebilir.** Modern HTTP istekleri `Mcp-Method` taşır (ve araç benzeri üç çağrı için `Mcp-Name`); `x-mcp-header` ile işaretlenmiş bir araç girdi şeması özelliği bir `Mcp-Param-*` başlığına yansıtılır ve sunucu bunu çapraz denetler ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). Ağ geçitleri ve hız sınırlayıcılar yalnızca başlıklara bakarak yönlendirebilir; kurallar **[Geçiş kılavuzu](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)** sayfasında.
* **Sonuçlar önbellek ipuçları taşır.** Listeleme ve okuma sonuçları `ttlMs` ve `cacheScope` bildirir ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)); bunları metot başına `cache_hints=` ile ayarlarsınız, `Client` da yerleşik bir yanıt önbelleğiyle onlara uyar. Hiç ipucu göndermeyen bir sunucu (2026 öncesi her sunucu) birebir aynı, önbelleksiz trafik görür. **[Önbellek ipuçları](client/caching.md)**.
* **Uzantılar birinci sınıf.** Sunucular ve istemciler ters DNS tanımlayıcıları altında isteğe bağlı yetenek paketleri bildirir ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)); yerleşik `Apps` uzantısı (MCP Apps) referans örnektir. **[Uzantılar](advanced/extensions.md)** ve **[MCP Apps](advanced/apps.md)**.
* **Hata kodları standartlaştı.** Eksik bir kaynak, URI `error.data` içinde olmak üzere `-32602`'dir; spesifikasyonun ayırdığı yeni kodlar da `-32020` (başlık uyuşmazlığı), `-32021` (gerekli yetenek eksik) ve `-32022` (desteklenmeyen protokol sürümü) olarak görünür. **[Sorun giderme](troubleshooting.md)** tam mesaj metinlerine göre düzenlenmiştir.
* **Yetkilendirmeyi yanlış kullanmak zorlaştı.** İstemci, yetkilendirme koduyla dönen `iss` değerini doğrular ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207); `callback_handler`'ınız artık bir `AuthorizationCodeResult` döndürür), kayıt olurken `application_type` gönderir ve kimlik bilgilerini asla farklı bir yetkilendirme sunucusuna karşı yeniden oynatmaz. Kurumsal köşedeki yenilik: [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) kimlik beyanı (identity assertion) akışı. **[Geçiş kılavuzu](migration.md)** her OAuth değişikliğini listeler; ilgili sayfalar **[İstemciler için OAuth](client/oauth-clients.md)** ve **[Kimlik beyanı](client/identity-assertion.md)**.
* **Her sunucu izlenebilir.** OpenTelemetry varsayılan olarak açık, middleware biçiminde gelir: her istek bir sunucu span'i alır ve süreç bir dışa aktarıcı (exporter) yapılandırana kadar hiçbir maliyeti yoktur. İki uç da SDK'yı çalıştırdığında istemci W3C izleme bağlamını `_meta` içinde de yayar; böylece izler birleşir. **[OpenTelemetry](run/opentelemetry.md)**.

## v1'den mi yükseltiyorsunuz? {#upgrading-from-v1}

* Neyi değiştireceğinizin eksiksiz ve kesin listesi **[Geçiş kılavuzu](migration.md)**; bu sayfa nedenini anlattı.
* **v1.x bir yere gitmiyor.** Bakım moduna geçer, kritik düzeltmeleri ve güvenlik yamalarını almaya devam eder ve 2026-07-28 spesifikasyon sürümündeki hiçbir şey onu bozmaz; belgeleri [/v1/](https://py.sdk.modelcontextprotocol.io/v1/) adresinde. `mcp`'ye bağımlı bir kütüphane yayımlıyor ve geçişe hazır değilseniz bir üst sınır koruyun (örneğin `mcp>=1.28,<2`); böylece sabitlenmemiş bir çözümleme 1.x'te kalır.
* Pürüzlü, kafa karıştırıcı ya da bozuk bir şey mi var? **[v2 geri bildirimi gönderin](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**; hepsi okunuyor.
