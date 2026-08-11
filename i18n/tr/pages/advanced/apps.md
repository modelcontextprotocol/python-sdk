---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

Bir **MCP App**, yüzü olan bir araçtır: araç, verisinin yanında host'un etkileşimli bir yüzey olarak çizdiği bir HTML belgesine de işaret eder.

İki parça, her zaman iki parça:

1. İşi yapan ve veri döndüren **bir araç**, tıpkı diğer araçlar gibi.
2. Host'un onun için gösterdiği HTML'i içeren **bir `ui://` kaynağı**.

Araç, kaynağa işaret eden bir `_meta.ui.resourceUri` referansı taşır. Host onu `resources/read` ile getirir, **korumalı (sandboxed) bir iframe** içinde çizer ve aracın sonucunu `postMessage` aracılığıyla bu iframe'e iter. Sunucu hiçbir `ui/*` mesajı göndermez ve almaz: bu trafik host ile iframe arasındadır. Siz bir araç ve bir HTML belgesi sunarsınız; gösteriyi host sahneler.

SDK bunu yerleşik `Apps` uzantısı (`io.modelcontextprotocol/ui`) olarak sunar. [Uzantılar](extensions.md) size yeniyse önce o sayfaya göz atın. Bir dakika, sonra geri dönün.

## Yüzü olan bir saat {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

Dört hamle:

* `Apps()`: tek bir örnek, UI'ya bağlı araçlarınızı ve onların kaynaklarını tutar.
* `@apps.tool(resource_uri="ui://clock/app.html")`: sıradan bir araç, artı `_meta.ui.resourceUri` damgası. `@mcp.tool()`'un kabul ettiği her şey (name, title, description, ...) aynen geçer.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: eşleşen kaynak, `text/html;profile=mcp-app` olarak sunulur. Bir host'a "bu bir uygulama, çiz" diyen şey tam olarak bu MIME türüdür.
* `MCPServer("clock", extensions=[apps])`: katılımı açın. Sunucu artık `capabilities.extensions` altında `io.modelcontextprotocol/ui` duyurur.

HTML'in kendisi host'un `postMessage`'ını dinler ve sonucu gösterir. Gerçek uygulamalar için HTML'inizin içinde resmi [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps) tarayıcı SDK'sını kullanın. Ham mesaj olayları yerine size `ontoolresult`, `callServerTool`, `getHostContext` ve `onhostcontextchanged` verir.

## Zarifçe geri çekilme {#graceful-degradation}

Her istemci uygulamaları çizmez. Şartname bunun sizin için ne anlama geldiğini açıkça söyler:

> UI mevcut olsa bile araçlar anlamlı bir `content` dizisi **döndürmek ZORUNDADIR**.

Model `content`'i okur; iframe insanlar içindir. UI destekli bir host yine de metin sonucunu modele iletir, yalnızca metin destekleyen bir istemci ise *sadece* onu alır. Yani kanonik desen tek araç, iki yanıttır. `get_time`'a bir daha bakın:

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` yalnızca istemci `io.modelcontextprotocol/ui` uzantısını beyan ettiğinde **ve** `mimeTypes` ayarlarında `text/html;profile=mcp-app`'i listelediğinde `True` olur. Alan zorunludur, bu yüzden onu atlayan bir istemci sayılmaz. Aynı dosyadaki `main()` tam olarak bunu beyan eder: anlaşmanın istemci tarafı, ve zengin yanıt geri gelir.

!!! warning
    Tek içerik olarak asla `"[Rendered UI]"` gibi bir yer tutucu döndürmeyin. Yedek metin işe yaramazsa araç, yalnızca metin destekleyen her istemci için ve modelin kendisi için işe yaramaz. O cümleyi yazın.

## iframe'i kilitleme {#locking-the-iframe-down}

Güvenlik metaverisini kaynak tarafı taşır: iframe'in neleri yükleyebileceği, hangi tarayıcı izinlerini istediği, nasıl çerçevelenmek istediği:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` ve `permissions` sunucu davranışı değil, **host'a yapılan isteklerdir**. Host, iframe'in Content-Security-Policy ve Permissions-Policy değerlerini bunlardan oluşturur ve reddedebilir. İznin verildiğini varsaymak yerine JS kodunuzda özellik algılaması yapın.

`ResourceCsp`, alan alan (Python adı, iletilen verideki anahtar, host'un onunla ne yaptığı):

| Python | İletilen veri (`_meta.ui.csp`) | Denetlediği |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: `fetch`/XHR nereye gidebilir |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: statik varlıklar |
| `frame_domains` | `frameDomains` | `frame-src`: iç içe iframe'ler |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: `<base>` nereye işaret edebilir |

`ResourcePermissions`: her alan iframe için bir tarayıcı izni ister.

| Python | İletilen veri (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP ve izinler **kaynak** üzerinde yaşar, asla araç üzerinde değil. Şartnamenin araç metaverisinde bunlar için bir yer yoktur ve host'lar orada onları yok sayar. SDK bu hatayı ifade edilemez kılar: `@apps.tool()`'un `csp` parametresi yoktur.

### Görünürlük {#visibility}

Bir araçtaki `visibility=["app"]`, "bu, model için değil iframe için var" der:

* `"model"`: model onu çağırabilir.
* `"app"`: iframe onu çağırabilir (`callServerTool` aracılığıyla).
* Belirtilmezse: ikisi de, varsayılan budur.

Filtreleme **host'un** işidir. Sunucu yalnızca uygulamaya özel araçları `tools/list` içinde diğerleri gibi listeler; host onları modelden gizler. Sunucu tarafında filtrelemeyin.

## SDK'nın uyguladığı kurallar {#the-rules-the-sdk-enforces}

Bunların hepsi üretimde değil, başlangıçta hata verir:

* `ui://...` olmayan bir `resource_uri` veya kaynak URI'si, dekoratör/kayıt anında bir `ValueError`'dır.
* **Eşleşen kayıtlı bir kaynağı olmayan** bir URI'ye bağlanmış araç, `MCPServer(extensions=[apps])` uzantıyı tükettiğinde bir `ValueError`'dır. `resources/read`'de 404 dönen bir HTML duyuran araç bir yanlış yapılandırmadır, bu yüzden oluşturmayı reddeder.
* `@apps.tool()` üzerinde `meta={"ui": ...}` bir `ValueError`'dır. `_meta["ui"]` dekoratöre aittir; bunu `resource_uri=` ve `visibility=` ile söyleyin. Diğer `meta=` anahtarları yanına sorunsuzca birleşir.

Bugün ne TypeScript ext-apps SDK'sı ne de FastMCP bunların herhangi birini yakalar; bir host'tan önce sizin öğrenmenizi tercih ederiz.

## Satır içi HTML'in ötesi {#beyond-inline-html}

`add_html_resource` yaygın durumu karşılar: bir HTML dizesi. Bunun dışındaki her şey için (diskteki HTML veya üretilen içerik) kaynağı kendiniz oluşturup teslim edin:

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource`, kaynak açıkça bir MIME türü belirtmediğinde `text/html;profile=mcp-app` MIME türünü doldurur ve açık bir uyuşmazlığı reddeder: başka herhangi bir MIME türü altındaki `ui://` kaynağını hiçbir host çizmez.

!!! tip
    Hâlâ kullanım dışı bırakılmış düz `_meta["ui/resourceUri"]` anahtarını okuyan GA öncesi bir host'u mu hedefliyorsunuz? Kendiniz birleştirin:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    İç içe `ui` nesnesi şartnamedeki biçimdir; düz anahtar kaldırılma yolunda.

## Çalışırken görün {#see-it-run}

`examples/stories/` içindeki `apps` hikâyesi, bu sayfanın çalıştırılabilir bir çift hâlidir: UI'ya bağlı bir saat aracı olan bir sunucu ve Apps anlaşmasını yapan, aracın `_meta.ui.resourceUri` değerini okuyan, HTML'i getiren ve aracı çağıran bir istemci.

```bash
uv run python -m stories.apps.client
```
