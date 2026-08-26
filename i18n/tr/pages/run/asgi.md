---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# Mevcut bir uygulamaya ekleme {#add-to-an-existing-app}

`mcp.run("streamable-http")` sizin için bir web sunucusu başlatır. Bazen bunu istemezsiniz: MCP sunucunuz daha büyük bir web uygulamasının bir parçasıdır ya da zaten bir ASGI dağıtımınız vardır.

Bunun için `mcp.streamable_http_app()` bir **Starlette uygulaması** döndürür.

Starlette uygulaması bir ASGI uygulamasıdır; dolayısıyla ASGI barındırabilen her şey (uvicorn, Hypercorn, başka bir Starlette, FastAPI) MCP sunucunuzu da barındırabilir.

## Uygulama {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` sıradan bir ASGI uygulamasıdır. Herhangi bir ASGI sunucusuna verin:

```console
uvicorn server:app
```

MCP endpoint'i `/mcp` yolundadır; yani istemci `http://127.0.0.1:8000/mcp` adresine bağlanır.

Uygulama hâlihazırda iki şey taşır:

* Tek bir rota, `/mcp`: Streamable HTTP endpoint'i.
* `mcp.session_manager`'ı başlatan bir **lifespan** (yaşam döngüsü); bu nesne, canlı her oturumun arka plan işlerinin sahibidir.

Uygulamayı tek başına çalıştırın (`uvicorn server:app`), ikisini de hiç düşünmeniz gerekmez.

!!! tip
    `streamable_http_app()`, `mcp.run("streamable-http", ...)` ile aynı anahtar sözcük argümanlarını
    alır; `port` hariç: port, uygulamayı sunan şeye aittir. `host` hâlâ kabul edilir ama burada
    hiçbir şeye bağlanmaz; gerçekte neyi denetlediğini **[Dağıtım ve ölçekleme](deploy.md)** açıklar.
    Seçeneklerin kendisi **[Sunucunuzu çalıştırma](index.md)** sayfasında.

`mcp.sse_app()` aynısını, yerini yenisine bırakmış SSE aktarımı için yapar.

## Siz aksini söyleyene kadar yalnızca localhost {#localhost-only-until-you-say-otherwise}

Varsayılan olarak uygulama **yalnızca** localhost'a gönderilen istekleri yanıtlar. `streamable_http_app()`
hangi ana bilgisayar adının arkasında sunulacağını bilemez; bu yüzden DNS rebinding korumasını
olabilecek en güvenli izin listesiyle etkinleştirir. Kendi makinenizde bu tam olarak doğru olandır.
Gerçek bir ana bilgisayar adının arkasına dağıtıldığında ise, `transport_security=` parametresine
gerçekte sunduğunuz adların izin listesini geçirene kadar **her istek `421 Misdirected Request` ile
reddedilir** demektir. Sizin yazdığınız hiçbir şeye önce danışılmaz bile. Bu izin listesi ve çalışan
bir uygulama ile gerçek bir ana bilgisayar adı arasındaki diğer her şey
**[Dağıtım ve ölçekleme](deploy.md)** sayfasında.

## Mount etme {#mounting-it}

MCP sunucusu daha büyük bir uygulamanın *parçası* olduğu anda uygulamayı bir `Mount` içine koyarsınız. Bunu yaptığınız anda da lifespan sizin sorununuz olur:

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` ile varsayılan `/mcp` yolu birlikte endpoint'i `/mcp` yolunda tutar. Starlette rotaları sırayla dener ve `Mount("/")` **her** yolla eşleşir; bu yüzden kendi rotalarınız listede ondan *önce* gelir. Ondan sonraki hiçbir şeye ulaşılamaz.
* `lifespan` fonksiyonu, **ana** uygulamanın ömrü boyunca `mcp.session_manager.run()` içine girer. Herkesin unuttuğu satır budur.
* `mcp.session_manager` ancak `streamable_http_app()` çağrıldıktan *sonra* var olur. Rotaların modül düzeyinde kurulmasının ve yöneticiye yalnızca lifespan içinde dokunulmasının nedeni budur.

Starlette'in `Host` rotası aynı şekilde çalışır: yola göre değil ana bilgisayar adına göre yönlendirmek için `Mount("/", ...)` yerine `Host("mcp.example.com", ...)` koyun. Lifespan kuralı değişmez, aktarım güvenliği kuralı da. `Host("mcp.example.com", ...)` rotası yalnızca o ana bilgisayar adına gönderilen istekleri alır, ancak aktarımın kendi Host izin listesi (**[Dağıtım ve ölçekleme](deploy.md)**) yine de önce çalışır. Listede `"mcp.example.com"` yoksa bu rota o isteklerin her birini `421` ile yanıtlar.

!!! warning "Ana uygulama lifespan'in sahibidir"
    `streamable_http_app()`, `session_manager.run()`'ı döndürdüğü Starlette'in lifespan'ine bağlar;
    ancak **mount edilmiş bir alt uygulamanın lifespan'i hiçbir zaman çalışmaz**. Uygulamayı mount
    edin, o yerleşik lifespan ölü kod olur. ASGI yığınınızın en üstünde hangi uygulama duruyorsa,
    kendi lifespan'inde `mcp.session_manager.run()` içine girmelidir.

!!! check
    `lifespan=lifespan` satırını silin ve sunucuyu başlatın. Başlar. Rota çözülür.
    Sonra `/mcp` yoluna gelen ilk istek şu hatayla başarısız olur:

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    Oturum yöneticisini kendi `run()`'ından başka hiçbir şey başlatmaz.

## İki sunucu, tek uygulama {#two-servers-one-app}

Her `MCPServer`, kendi oturum yöneticisi olan ayrı bir uygulamadır. İstediğiniz kadarını mount edin; her yöneticiye tek ana lifespan'den girin:

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` iki yöneticiye de girer; birlikte başlar, ters sırada kapanırlar.
* Endpoint'ler `/notes/mcp` ve `/tasks/mcp`: mount öneki artı varsayılan yol.

## Yolu değiştirme {#changing-the-path}

Sondaki o `/mcp`, `streamable_http_path` değeridir. Bunu `"/"` yapın, mount öneki genel yolun tamamı olur:

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

Artık istemciler `/notes/mcp` yoluna değil `/notes` yoluna bağlanır.

## Tarayıcı istemcileri için CORS {#cors-for-browser-clients}

Tarayıcı tabanlı bir istemcinin sizden iki izne ihtiyacı vardır: MCP istek başlıklarını **göndermek** ve MCP'nin geri gönderdiği başlığı **okumak**. İkisi de ana uygulamadaki CORS yapılandırmasıdır ve yukarıdaki aktarım güvenliği izin listesinin bununla uyuşması gerekir:

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` herkesin unuttuğu yarıdır. Tarayıcı her MCP isteği için **preflight** yapar; çünkü `Content-Type: application/json` ve `Mcp-*` istek başlıkları CORS güvenli listesinde değildir ve preflight'ın izin vermediği bir başlık, tarayıcının asla göndermediği bir istek demektir. (`allow_headers=["*"]` da çalışır: Starlette bir preflight'ı ne istediyse onunla yanıtlar.)
* `expose_headers=["Mcp-Session-Id"]` okuma yarısıdır. Streamable HTTP oturum kimliğini bu yanıt başlığında döndürür ve tarayıcılar, CORS adlarıyla açığa çıkarmadıkça yanıt başlıklarını JavaScript'ten gizler. Bu olmadan istemci ikinci isteğini asla yapamaz.
* `allow_origins` MCP'nin değil sizin kararınızdır. Kesin olun ve yukarıdaki `allowed_origins=` ile birebir eşleştirin: CORS'u tarayıcı uygular, ama sunucu `Origin`'i kendisi de denetler ve aktarımın güvenmediği bir origin, temiz bir preflight'tan sonra bile `403` alır.
* `allow_methods` Streamable HTTP'nin kullandığı üç yöntemi listeler: ileti göndermek için `POST`, sunucudan istemciye akışı açmak için `GET`, oturumu sonlandırmak için `DELETE`.

## Özel rotalar {#custom-routes}

`@mcp.custom_route()` aynı uygulamada düz bir HTTP endpoint'i kaydeder; dağıtılan her servisin ihtiyaç duyduğu ama MCP ile hiçbir ilgisi olmayan şeyler için: sağlık denetimi, OAuth callback'i.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* İşleyici düz Starlette'tir: `Request`'ten `Response`'a bir `async` fonksiyon.
* `streamable_http_app()` her özel rotayı alır. `app.routes` artık `/mcp` ve `/health`.
* `GET /health`, ortada hiç MCP olmadan `{"status": "ok"}` yanıtını verir.

!!! warning
    Özel rotalar, sunucunun geri kalanı doğrulansa bile **hiçbir zaman kimlik doğrulamasından
    geçmez**. Bu kasıtlıdır: sağlık denetimleri ve OAuth callback'leri herhangi bir token var
    olmadan önce erişilebilir olmak zorundadır. Bunların arkasına özel hiçbir şey koymayın.

## Özet {#recap}

* `mcp.streamable_http_app()` tek rotası `/mcp` olan bir Starlette uygulaması döndürür. Herhangi bir ASGI sunucusu onu çalıştırabilir.
* Varsayılan olarak uygulama yalnızca localhost'a gönderilen istekleri yanıtlar; gerçek bir ana bilgisayar adının arkasında ise `transport_security=` parametresine bir izin listesi geçirene kadar her şeyi `421` ile reddeder. Bu konu ve üretime giden yolun geri kalanı **[Dağıtım ve ölçekleme](deploy.md)** sayfasında.
* `Mount` (veya `Host`) onu daha büyük bir Starlette ya da FastAPI uygulamasının içine koyar.
* **Mount etmek yerleşik lifespan'i devre dışı bırakır.** Ana uygulamanın lifespan'i `mcp.session_manager.run()` içine girmelidir, yoksa ilk istek başarısız olur.
* Tek uygulamada birden fazla sunucu, birden fazla mount ve her oturum yöneticisine giren tek bir lifespan demektir.
* `streamable_http_path="/"` endpoint'i mount önekinin kendisine taşır.
* Tarayıcı istemcilerinin CORS'a ihtiyacı vardır: `Mcp-*` istek başlıkları için `allow_headers`, yanıt için `expose_headers=["Mcp-Session-Id"]`.
* `@mcp.custom_route()`, `/mcp`'nin yanına düz, kimlik doğrulaması olmayan HTTP endpoint'leri ekler.

Sunucu gerçek bir URL'den erişilebilir olduğunda **[İstemci](../client/index.md)** ona bir sunucu nesnesi yerine o URL ile bağlanır.
