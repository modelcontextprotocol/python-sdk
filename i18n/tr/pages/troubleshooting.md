---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Sorun giderme {#troubleshooting}

Bu sayfadaki her başlık, SDK'nın ürettiği bir hatanın birebir metnidir; ardından ne anlama geldiği ve tek hamlelik çözümü gelir. Traceback'inizin (veya sunucu log'unuzun) son satırını tarayıcınızın sayfada bul özelliğiyle burada arayın ve yalnızca o girdiyi okuyun.

Girdilerin birkaçı şu tek sunucuya karşı çalışır. Bir araç ve bir şablonlu kaynak; her biri tanımadığı bir şehir için istisna fırlatır:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Bu sayfanın alıntıladığı hatalar gerçektir: SDK'nın kendi test paketi her birini yeniden üretir.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Bu bir MCP hatası değil. anyio gürültüsüdür ve asıl hatanız yapıştırdığınız metnin **son satırıdır**.

`Client.__aenter__` bir görev grubu başlatır. anyio, görev grubundan çıkan her şeyi bir `ExceptionGroup` içine sarar; bu yüzden bir `async with Client(...)` bloğundan kaçan *her* istisna, ne olursa olsun, böyle bir grubun içinde gelir:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

Bununla yapılacak iki şey var:

1. **En altı okuyun.** Hata `MCPError: No forecast for 'Atlantis'.` satırıdır; bu sayfada *onun* metnini arayın.
2. **Bloğun içinde yakalayın.** `ExceptionGroup` yalnızca istisna `async with` bloğundan *çıktığında* ortaya çıkar. İçeride yakalandığında aynı hata düz bir `MCPError`'dır; ortada hiçbir grup yoktur:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    *Bağlantı* sırasındaki bir hata (yanlış bir URL, çalışmayan bir sunucu, bu sayfanın
    ilerisindeki `421`) `async with`'in kendisinden kaçar; dolayısıyla onu yakalayacak bir
    "içerisi" yoktur. Bunlar için grubun en altını okuyun.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` yalnızca nesneyi kurar. `async with`'e kadar hiçbir şey bağlanmaz; bu yüzden her yöntem reddeder:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

İçine girin. Bağlantının kendisi `__aenter__`'dır:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` ise bağlantının kesilmesidir; unutulacak bir `client.close()` olmamasının nedeni de budur. **[Test etme](get-started/testing.md)** tam olarak bu kalıp üzerine kuruludur.

## `Error executing tool <name>: <message>` ve `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Okuduğunuz şey bir istisna değil, bir **sonuç**. `call_tool` istisna fırlatmadı ve başarısız olan bir araç için hiçbir zaman fırlatmaz.

`forecast`'i sunucunun tanımadığı bir şehir için çağırın; fırlattığı istisna, istek *başarılı* olarak işaretlenmiş halde geri döner:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast`, sunucunun hiç kaydetmediği bir ad için aynı biçimdir; hatalı bir argüman da aynı şekilde, fonksiyonunuz daha hiç çalışmadan, aracın girdi şemasına göre reddedilir.

Çözüm istemcinizde: **`result.is_error`'ı kontrol edin**. `call_tool` etrafındaki bir `try/except` bunların hiçbirini yakalamaz, çünkü yakalanacak bir şey yoktur. Bu kasıtlıdır ve bu sayfada içselleştirilecek en yararlı tek şeydir: çağrıyı *model* seçti, bu yüzden mesajı ve yeniden deneme şansını da model alır. Ayrıntıların tamamı, *gerçekten* istisna fırlatan `MCPError` yolu dahil, **[Hataları ele alma](servers/handling-errors.md)** sayfasında.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

`@mcp.tool()` yerine `@mcp.tool` yazdınız. `tool()` bir dekoratör *fabrikasıdır*: parantezler olmadan Python, fonksiyonunuzu onun `name=` parametresine verir.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Parantezleri ekleyin. `@mcp.resource(...)` ve `@mcp.prompt()` de aynı sürçme için aynı şeyi söyler.

!!! note
    Bu, herhangi bir istemci bağlanmadan önce, modül **içe aktarıldığında** fırlatılır. Yani
    sunucunuzu sıfır araçla bağlı olarak değil de *başlatılamadı* (veya *bağlantı kesildi*)
    olarak gösteren bir host bu biçimdedir: `python server.py` komutunu kendiniz çalıştırın ve
    traceback'i okuyun. Bir tür denetleyicisi de bunu yakalar: bir fonksiyon geçerli bir
    `name=` değildir.

## `Tool already exists: <name>` {#tool-already-exists-name}

İki kayıt aynı araç adını kullandı. **İlki** kazanır, ikincisi sessizce düşürülür ve *sunucu log'undaki* bu uyarı tek işarettir:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` tek bir `forecast` bildirir ve o da `forecast_today`'dir. Birinin adını değiştirin. `MCPServer(..., warn_on_duplicate_tools=False)` sonucu değiştirmeden uyarıyı susturur; bu yüzden açık bırakın. Kaynaklar ve prompt'lar için de aynı kural ve aynı log satırı geçerlidir (`Resource already exists:`, `Prompt already exists:`).

## Host'um sıfır araç listeliyor {#my-host-lists-zero-tools}

Bunun bir hata metni yoktur; aranmasının zor olmasının nedeni de tam olarak budur. SDK kayıtlı bir aracı `tools/list`'ten asla düşürmez; bu yüzden içeriden dışarıya doğru ilerleyin:

* **Sunucu hiç başladı mı?** Parantezsiz `@mcp.tool` içe aktarma sırasında fırlatır ve çökmüş bir sunucu bazı host'larda boş bir sunucuya çok benzer. `python server.py` komutunu kendiniz çalıştırın.
* **Araç, host'un çalıştırdığı `mcp` üzerinde mi?** Başka bir modüldeki ikinci bir `MCPServer(...)` farklı, boş bir sunucudur. Host'un komutunun gerçekte hangi nesneyi içe aktardığını kontrol edin.
* **İki araç aynı adı mı paylaştı?** O zaman biri gitmiştir. Sunucu log'unda `Tool already exists:` satırını arayın.
* **Host'un listesi eski mi?** Başlangıçtan sonra eklenen bir araç yalnızca `notifications/tools/list_changed` bildirimini işleyen istemcilere ulaşır. Host'u yeniden başlatmak kaba ama kesin çözümdür.
* **Yönlendirilen pencerenin dışında bir şey `stdout`'a mı yazdı?** SDK hizmet verirken başıboş ve *flush edilmiş* stdout çıktısını stderr'e yönlendirir (elinden geldiğince: standart akışları değiştiren bir ortama olduğu gibi hizmet verilir). Ancak daha önce stdout'a flush edilmiş çıktı (echo yapan bir sarmalayıcı betik, tamponsuz bir süreçte içe aktarma sırasında çalışan bir `print()`) veya yorumlayıcı çıkışında boşaltılan tamponlanmış bir `print()` protokol akışına düşer ve tek bir çöp satır host'un bağlantıyı kesmesine yol açabilir; bazı host'lar bunu içinde hiçbir şey olmayan bir sunucu olarak gösterir. Bunun yerine `logging` modülüyle log tutun. Host tarafı kontrol listesinin geri kalanı **[Gerçek bir host'a bağlanma](get-started/real-host.md)** sayfasında.

"Geçersiz" bir araç adı bu listede *değildir*: kurala uymayan bir ad log'a bir uyarı yazar, ancak araç yine de kaydedilir ve listelenir.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

Sunucu HTTP isteğini, JSON-RPC olmayan bir gövdeyle doğrudan reddetti; bu yüzden python `Client`'ın size gösterebileceği bu yer tutucudan daha iyi bir şey yok.

Açık ara en yaygın neden, yeni dağıtılmış bir Streamable HTTP sunucusudur. `transport_security=` verilmeyen `streamable_http_app()` (ve `mcp.run("streamable-http")`) varsayılan olarak **DNS rebinding koruması** uygular: yalnızca `Host` başlığı localhost olan istekleri kabul eder. Bu, dizüstü bilgisayarınızda doğru varsayılandır; gerçek bir ana bilgisayar adının arkasında ise yanlış:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Bunu dağıtın, bir istemciyi ona yönlendirin; bağlantı el sıkışmada başarısız olur:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

Sunucunun gerçekte gönderdiği sözcükler, `421` ve `Invalid Host header`, size asla ulaşmaz: 421 gövdesinde `Content-Type: application/json` yoktur, bu yüzden istemci onu ayrıştıramaz. Bunlar **sunucunun log'undadır**; bir sonraki bakılacak yer de orasıdır:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

Çözüm `transport_security=`. Gerçekte hizmet verdiğiniz ana bilgisayar adını izin listesine ekleyin:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    Değişikliğin tamamı bu. Aynı istemci artık bağlanır, `2026-07-28` üzerinde anlaşır ve
    `forecast`'i çağırır.

**[Dağıtım ve ölçekleme](run/deploy.md)** her alanın ne anlama geldiğini, ters vekil sunucu durumunu ve dağıtım sırasında değişen diğer her şeyi ele alır. Hemen aşağıdaki `421 Misdirected Request` / `Invalid Host header` ise aynı hatanın öbür taraftan görünüşüdür.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

Bu, python `Client` *olmayan* herhangi bir yerden görülen `Server returned an error response`'tır: curl, bir tarayıcının ağ sekmesi, bir ters vekil sunucunun erişim log'u veya başka bir SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request`, HTTP'nin bu durum kodu için kendi gerekçe ifadesidir; `Invalid Host header` SDK'nın yanıt gövdesidir; python `Client` ise aynı olayı `Server returned an error response` olarak gösterir. Üçü de tek bir rettir. Denetim, sunucunun bağlandığı adrese değil, **isteğin taşıdığı `Host` başlığına** karşı çalışır; bu yüzden genel ana bilgisayar adını ileten bir ters vekil sunucu, ona tıpkı doğrudan bir istemci gibi takılır.

Çözüm, `Server returned an error response` altında gösterilen aynı `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`. İki ince noktasını adlandırmaya değer:

* Bir `allowed_hosts` girdisi birebir bir dizedir. `"mcp.example.com"` yalın bir `Host` başlığıyla, `"mcp.example.com:*"` ise açıkça belirtilmiş herhangi bir portla eşleşir. İkisini de listeleyin.
* Gövdesi `Invalid Origin header` olan bir `403`, `Origin` başlığı üzerindeki kardeş denetimdir. Yalnızca tarayıcılar için tetiklenir (başka hiçbir şey `Origin` göndermez) ve onun izin listesi de `allowed_origins=` parametresidir.

Denetimi kapatmanın dürüst yapılandırma olduğu durumlar dahil, konunun tamamı **[Dağıtım ve ölçekleme](run/deploy.md)** sayfasında.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

MCP uygulamanız başka bir ASGI uygulamasının içine bağlanmış (mount edilmiş) ve **oturum yöneticisini** hiçbir şey başlatmamış.

`mcp.streamable_http_app()`, kendi lifespan'i (yaşam döngüsü) yöneticiyi başlatan bir Starlette uygulaması döndürür ve `uvicorn server:app` bu lifespan'i sizin için çalıştırır. Ancak Starlette **bağlanmış bir alt uygulamanın lifespan'ini asla çalıştırmaz**; bu yüzden uygulama bir `Mount` içine girdiği anda yönetici hiç başlamaz ve ilk istek patlar:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

Sunucu başlar. Rota çözümlenir. Ardından `uvicorn` her istek için şunu yazdırır:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

İstemci bir 500 görür. Çözüm, **ana** uygulamada `mcp.session_manager.run()`'a giren bir lifespan'dir:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

Bunun sayfası, tek uygulamada birden fazla sunucu ve FastAPI dahil, **[Mevcut bir uygulamaya ekleme](run/asgi.md)**. Aynı sınıftan iki komşu metin:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` Yönetici tek kullanımlıktır; aynı uygulamanın lifespan'ine iki kez girmek buna çarpar.
* `mcp.session_manager` yalnızca `streamable_http_app()` çağrıldıktan **sonra** var olur; bu yüzden önce rotaları kurun ve yöneticiye yalnızca lifespan'in içinde dokunun.

## `MCPError: Session not found` {#mcperror-session-not-found}

Sunucu, istemcinizin gönderdiği `Mcp-Session-Id`'yi tanımıyor; bunun nedeni neredeyse her zaman sunucunun **yeniden başlamış** olmasıdır (ya da farklı bir örneğe yönlendirilmişsinizdir). Oturumlar o tek sürecin belleğinde yaşar.

Bulunacak bir sunucu hatası yok. HTTP yanıtı, gövdesi JSON-RPC *olan* bir `404`'tür; bu yüzden yukarıdaki `421`'in aksine python `Client` bunu size birebir gösterir:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

Çözüm yeniden bağlanmaktır: `async with Client(...)` bloğundan çıkın ve yeni bir oturum üzerinde anlaşan yeni bir bloğa girin. Uzun ömürlü bir istemci için bu, çağrılarınızın etrafında `MCPError`'ı yakalamak ve ölü bir oturumun içinde yeniden denemek yerine bu mesajda yeniden bağlanmak demektir.

Bu, yeniden başlatma *olmadan* oluyorsa, yapışkan oturumlar olmadan birden fazla worker çalıştırıyorsunuz demektir: her worker kendi oturum tablosunu tutar, bu yüzden yanlış olana yönlendirilen bir istek buraya düşer. Bu konu ve iki çözümü (yapışkan yönlendirme veya `stateless_http=True`) **[Dağıtım ve ölçekleme](run/deploy.md)** ile **[Eski nesil istemcilere hizmet verme](run/legacy-clients.md)** sayfalarında.

Sunucu operatörü için eşleşen log satırı `Rejected request with unknown or expired session ID: <id>`'dir. `INFO` düzeyinde log'a yazılır; bu yüzden olağan `WARNING` eşiğinde görünmez. Bir dağıtımın hemen ardından bunu öbekler halinde görmek normaldir; bağlı her istemci yeniden bağlanıyordur.

## `MCPError: Method not found` {#mcperror-method-not-found}

Bir taraf, diğer tarafın işleyicisi olmayan bir JSON-RPC isteği gönderdi ve `e.error.data` yöntemin adını verir. Olağan neden bir **nesil uyuşmazlığıdır**: bir protokol sürümünde olup diğerinde olmayan bir yöntemin yanlış sürümdeki bir eşe gönderilmesi; örneğin `2025` neslinden bir `resources/subscribe`'ın bir `2026-07-28` bağlantısına ulaşması ya da `mode="legacy"` değerine sabitlenmiş bir istemcinin yalnızca `2026`'da var olan `subscriptions/listen`'ı göndermesi. Hangi tarafın ne konuştuğunun haritası **[Protokol sürümleri](protocol-versions.md)** sayfasıdır; diğer dürüst neden (hiç işleyici kaydetmediğiniz isteğe bağlı bir yetenek) ise **[Tamamlamalar](servers/completions.md)** sayfasında.

Modern protokolün kaldırdığı bir istek olmasına rağmen bu hatayı **üretmeyen** bir şey var: bir `2026-07-28` bağlantısında `ctx.elicit()` çağıran bir araç. Sunucu o isteği *göndermeyi* baştan reddeder; bu yüzden bunun yerine, bu sayfanın ilerisindeki `Cannot send 'elicitation/create': ...` hatasını alırsınız.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Sunucunuz kullanıcıya bir şey sormak istiyor ve bu istemci kendisine soru sorulabileceğini hiç söylemedi.

Bir elicitation (kullanıcıdan bilgi isteme) çözümleyicisi, bağlı istemci form elicitation'ı bildirmediğinde baştan reddeder ve `e.error.data` tam olarak neyin eksik olduğunu adlandırır:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

`Client(...)`'a `elicitation_callback=` geçirin. Callback'i kaydetmek yetenek bildiriminin *ta kendisidir*; ikinci bir anahtar yoktur:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[İstemci callback'leri](client/callbacks.md)** diğerlerini listeler (`sampling_callback`, `list_roots_callback`); her biri aynı şekilde bir bildirimdir.

!!! info
    `-32021`, `MISSING_REQUIRED_CLIENT_CAPABILITY`'dir; 2026-07-28 spesifikasyonunun eklediği
    üç hata kodundan biridir. Hiçbiri bir istisna sınıfı değildir: hepsi `MCPError` olarak
    gelir ve bakılacak yer `e.error.code`'dur. Sabitleri `mcp.types` dışa aktarır. Diğer ikisi
    `-32020` `HEADER_MISMATCH` (bir HTTP başlığı eşlik ettiği istek gövdesiyle uyuşmuyor) ve
    `-32022` `UNSUPPORTED_PROTOCOL_VERSION`'dır (istek, bu sunucunun konuşmadığı bir sürümü
    belirtmiş). Uyumlu bir SDK istemcisi ikisini de üretemez; bu yüzden birini görürseniz,
    istemcinizle sunucunuz arasında istekleri yeniden yazan şey her neyse ona bakın.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

`Client did not declare the form elicitation capability ...` ile aynı boşluk; bu kez baştan denetim yapmayan yolların ifadesiyle: sunucunun bir elicitation'ın yanıtlanmasına ihtiyacı vardı ve bağlı istemci hiçbir `elicitation_callback` kaydetmemişti.

Bunu eski nesil bir bağlantıda `ctx.elicit()`'ten görürsünüz; herhangi bir bağlantıda ise onu yanıtlayacak callback'i olmayan bir istemciye ulaşan, döndürülmüş bir çok turlu (multi-round-trip) sorudan (**[Çok turlu istekler](handlers/multi-round-trip.md)**). Çözüm aynıdır: `Client(...)`'a `elicitation_callback=` geçirin. "Kullanıcıya sorulmadı" durumunun, aracınıza `decline` olarak ulaşan bir hâli yoktur; soru sorulamayan bir istemci başarısız bir çağrı demektir, araçlarınızı buna göre tasarlayın.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

İşleyiciniz, isteğin ortasında istemciye ulaşmaya çalıştı; hem de çağrısının sunucudan gelen bir isteği taşıyabilecek hiçbir kanalı olmayan bir bağlantıda. Bir çağrıyı bu duruma sokan üç sunucu yapılandırması var.

**Bir `2026-07-28` bağlantısı: her aktarımda, her zaman.** Modern protokolde sunucunun başlattığı istek diye bir şey hiç yoktur; bu yüzden sunucu daha hiçbir şey gönderilmeden reddeder. Bununla karşılaşmanın klasik yolu bir aracın içindeki `ctx.elicit()`'tir (hem de daha ilk bellek içi testte, çünkü `Client(server)` sorulmadan `2026-07-28` üzerinde anlaşır) ve `elicitation_callback=` geçirmek hiçbir şeyi değiştirmez, çünkü istemciye yanıtlayacağı bir istek hiç ulaşmaz:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**`stateless_http=True` bir sunucuda eski nesil bir bağlantı.** Durumsuzluk, her isteğin kendi dünyası olması demektir: oturum yok, sunucudan istemciye akış yok; dolayısıyla bunlara sahip olan nesil için bile bir `elicitation/create` (veya `sampling/createMessage` ya da `roots/list`) gönderecek hiçbir yer yok:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**`json_response=True` bir sunucuda eski nesil bir bağlantı.** `POST` tek bir JSON gövdesiyle yanıtlanır ve tek bir gövde yalnızca yanıtı taşır; bu yüzden isteğin ortasındaki bir `ctx.elicit()`'in ihtiyaç duyduğu istek kapsamlı akış burada da yoktur. Oturum, onun `Mcp-Session-Id`'si ve bağımsız akışı hâlâ yerindedir; giden yalnızca istek kapsamlı kanaldır.

Mesaj, gönderemediği yöntemin adını verir. Sunucunun fırlattığı sınıf `NoBackChannelError`'dır, ancak ağ üzerinden yalnızca temel `MCPError` taşınır; bu yüzden traceback'inizin son satırı sınıf adı değil, yukarıdaki cümledir.

Bir `2026-07-28` istemcisi için çözüm üçünde de aynıdır: çağrının ortasında geriye uzanmayın. Soruyu bir **çözümleyiciye** taşıyın (ya da kendiniz bir `InputRequiredResult` döndürün); böylece soru, her bağlantının taşıyabildiği *yanıtın* bir parçası olur:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Aynı soru, istemcide aynı `elicitation_callback`. Fark arka plandadır: çözümleyici, sunucunun soruyu itmek yerine çağrıdan *döndürmesini* sağlar; böylece sunucudan istemciye hiçbir şey akmaz. Bu, sunucu üç yapılandırmanın hangisinde olursa olsun her `2026-07-28` istemcisini kurtarır. *Eski nesil* bir istemciyi ise tek başına bu yeniden yazım kurtarmaz: `2025-11-25`'te bir soruyu döndürmenin yolu yoktur; bu yüzden eski nesil bir bağlantıda çözümleyici `elicitation/create`'i yine istek kapsamlı kanaldan gönderir ve yine bu kanalı koruyan bir sunucuya ihtiyaç duyar: ne `stateless_http=True` ne de `json_response=True`. Çözümleyicileri **[Elicitation](handlers/elicitation.md)** sayfası, ağ üzerinde neler olduğunu ise **[Çok turlu istekler](handlers/multi-round-trip.md)** sayfası ele alır.

!!! check
    `ctx.elicit()` kullanan araç yanlış değil, *2026 öncesi*. Ne `stateless_http=True` ne de
    `json_response=True` olan bir sunucuya `mode="legacy"` ile (klasik `initialize` el
    sıkışması, spesifikasyon `2025-11-25` ve öncesi) bağlanın; çalışır, çünkü orada sunucudan
    istemciye kanal vardır.
    Her sürümde nelerin olduğunu anlatan sayfa **[Protokol sürümleri](protocol-versions.md)**.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

Sunucu, istemcinizin geri yansıttığı `requestState` token'ını doğrulayamadı; bu yüzden turu reddetti.

`requestState`, **[çok turlu](handlers/multi-round-trip.md)** bir çağrının ayaklar arasında taşıdığı opak devam token'ıdır. `MCPServer` onu çıkışta mühürler ve her yansımayı doğrular; üstelik `tools/call`, `prompts/get` ve `resources/read` üzerindeki gelen *her* `request_state`'i, hiç token üretmeyen bir işleyici için bile doğrular. Bu yüzden bu sürecin mühürlemediği bir token nereye düşerse düşsün reddedilir:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

Mesaj kasıtlı olarak sabittir: ağ üzerinden hangi denetimin başarısız olduğu asla açığa çıkmaz. Neden **sunucu log'una** gider ve onu okumak teşhisin tamamıdır:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Gerçekte göreceğiniz nedenler:

* **`unknown key`** önemli olandır. Varsayılan mühürleme anahtarı süreç başlangıcında üretilir; bu yüzden **farklı bir worker'a**, yük dengeleyici arkasındaki farklı bir örneğe ya da **yeniden başlatma sonrası** aynı sunucuya düşen bir yeniden deneme, bu sürecin hiç sahip olmadığı bir anahtarla mühürlenmiştir. Bu bir saldırgan değildir; varsayılanın birden fazla süreçle karşılaşmasıdır.
* **`audience`**: token'ı *farklı bir sunucu adına* sahip bir örnek mühürlemiş. Ad, mührün varsayılan audience claim'idir; bu yüzden bir filonun anahtarların yanı sıra adı da paylaşması (ya da açık bir `RequestStateSecurity(audience=...)` ayarlaması) gerekir.
* **`expired`**: tur, mührün `ttl` süresinden uzun sürdü; bu süre 600 saniyedir ve çağrı başına değil, tur başınadır.
* **`malformed`** / **`codec error`**: token yolda değiştirilmiş ya da hiçbir zaman mühürlü bir token olmamış.
* **`request binding`**: token farklı bir araçla, farklı argümanlarla ya da farklı bir yöntemle geri geldi.

Çok süreçli çözüm tek bir argüman (her örnekte *aynı* `keys`) artı argüman bile olmayan bir şeydir: aynı sunucu *adı* (ya da açıkça paylaşılan bir `audience=`).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` mühürler; listedeki her anahtar doğrular; kesintisiz rotasyonu mümkün kılan da budur. Mührün neyi koruduğunu ve rotasyon sırasını **[Çok turlu istekler](handlers/multi-round-trip.md#protecting-requeststate)** açıklar; **[Dağıtım ve ölçekleme](run/deploy.md)** ise iki worker'lı hatanın tamamını ve iki parçalı çözümünü adım adım anlatır.

!!! tip
    `keys=[...]` zayıf bir anahtarı, alışılmadık derecede yardımcı bir mesajla hemen reddeder:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Dediğini yapın.

## Hâlâ takıldınız mı? {#still-stuck}

* SDK'nın ürettiği bir mesaj bu sayfada yoksa, bu başlı başına bildirmeye değer bir dokümantasyon hatasıdır.
* [Issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues)'da arama yapın; orada görünen hata metinlerinin çoğunu birileri çoktan yazıya dökmüştür.
* Hiçbir şey bulamadınız mı? Tam traceback ile [bir issue açın](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) ya da [MCP Contributors Discord'undaki #python-sdk-dev kanalında](https://discord.gg/6CSzBmMkjX) sorun.

## Özet {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` hiçbir zaman asıl hata değildir. **Son satırı** okuyun; `MCPError`'ı `async with Client(...)` bloğunun *içinde* yakalamak sarmalamayı tamamen atlar.
* `call_tool` başarısız olan bir araç için istisna fırlatmaz. `Error executing tool ...` ve `Unknown tool: ...` birer sonuçtur: `result.is_error`'ı kontrol edin.
* `Client must be used within an async context manager` -> `async with` kullanın. `Use @tool() instead of @tool` -> parantezleri ekleyin.
* Sunucu log'undaki `Tool already exists:`, aynı adlı iki aracın teke indiğinin tek işaretidir.
* Tek 421, üç yazım: `Server returned an error response` (python `Client`), `421 Misdirected Request` / `Invalid Host header` (geri kalan her şey), `Invalid Host header: <host>` (sunucu log'u). Çözüm: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> ana uygulamanın lifespan'i `mcp.session_manager.run()`'a hiç girmemiş, bağlanmış bir uygulama.
* `Session not found` -> sunucu yeniden başladı; yeniden bağlanın.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` sunucudan istemciye bir kanala ihtiyaç duyar: bir `2026-07-28` bağlantısında hiç yoktur, `stateless_http=True` eski nesil olanı, `json_response=True` ise istek kapsamlı olanı ortadan kaldırır. Bir çözümleyici kullanın (eski nesil bir istemci için ayrıca kanalı koruyan bir sunucu gerekir). Komşusu `Method not found`, karşı tarafın protokol sürümünde olmayan bir yöntem için yapılmış bir istektir.
* `Client did not declare the form elicitation capability ...` ve `Elicitation not supported` -> istemcide `elicitation_callback=` eksik.
* `Invalid or expired requestState` nedenini ağ üzerinde asla söylemez. Sunucu log'u söyler; `unknown key`, `RequestStateSecurity(keys=[...])`'i worker'lar arasında paylaşın demektir.
