---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth istemcileri {#oauth-clients}

Bazı MCP sunucuları korumalıdır. Onlara token'sız bir istek gönderin, `401 Unauthorized` yanıtını verirler.

Token'ı edinmenin yolu **`OAuthClientProvider`**'dır. Bu bir MCP nesnesi bile değildir. Bir `httpx2.Auth`'tur; httpx2'nin "her isteğe bir şey yap" için sunduğu standart kancadır. Onu bir `httpx2.AsyncClient`'a takarsınız, o istemciyi Streamable HTTP aktarımına verirsiniz ve konuyu unutursunuz.

Bu sayfa istemci tarafını anlatır. Kendi sunucunuzun token talep etmesini sağlamak **[Yetkilendirme](../run/authorization.md)** sayfasının konusudur.

## Sağlayıcı {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

Ona dört şey verirsiniz:

* `server_url`: bağlandığınız MCP endpoint'i. Sağlayıcı geri kalan her şeyi buradan keşfeder.
* `client_metadata`: bir yetkilendirme sunucusunun "uygulama kaydet" formuna yazacağınız bilgiler.
* `storage`: token'ların çalıştırmalar arasında saklandığı yer.
* `redirect_handler` ve `callback_handler`: bir insanın devreye girdiği iki an.

Dosyada OAuth'tan söz eden başka hiçbir şey yok. `main()` hiçbir zaman bir token görmez.

### İstemci metadatası {#client-metadata}

`OAuthClientMetadata`, gerçek [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) kayıt belgesinin Pydantic modeli hâlidir.

Üç alan ayarlarsınız. Gerisini varsayılanlar doldurur: `grant_types` zaten `["authorization_code", "refresh_token"]`, `response_types` ise zaten `["code"]`; bu sağlayıcının çalıştırdığı akış da tam olarak budur.

!!! check
    Bir Pydantic modeli olduğu için doğrulamayı **ağa tek bir bayt bile gitmeden** yapar.
    `redirect_uris` alanını atlarsanız oluşturma, alanın adını veren bir `ValidationError` ile
    anında başarısız olur:

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    Ne bir tarayıcı açılır ne de yetkilendirme sunucusunda yarım kalmış bir kayıt bırakılır.

### Token deposu {#token-storage}

**`TokenStorage`**, dört asenkron metodu olan bir `Protocol`'dür. Hiçbir şeyden kalıtım almazsınız; metotları yazın, herhangi bir sınıf bir token deposu olur:

* `get_tokens` / `set_tokens`, `OAuthToken`'ı tutar: erişim token'ı, yenileme token'ı, geçerlilik süresi, kapsam.
* `get_client_info` / `set_client_info`, sağlayıcı sizi kaydettiğinde yetkilendirme sunucusunun verdiği `OAuthClientInformationFull`'u tutar; `client_id`'niz de bunun içindedir.

Yukarıdaki bellek içi sürüm çalışır. Ancak süreç sona erdiğinde her şeyi unutur; bu yüzden bir sonraki çalıştırma bütün süreci baştan yapar. Onu bir dosyada ya da platformunuzun anahtarlığında kalıcı hâle getirin, bir sonraki çalıştırma sessiz geçer.

!!! tip
    Yalnızca token'ları değil, `client_info`'yu da saklayın. Sağlayıcı, depoda `client_info`
    bulamadığı ilk seferde dinamik olarak kayıt yaptırır. Onu atarsanız her çalıştırmada yeni bir
    kayıt üretirsiniz.

### İki işleyici {#the-two-handlers}

Yetkilendirme kodu akışı bir insana tam olarak bir kez ihtiyaç duyar: birinin oturum açıp "allow" düğmesine tıklaması gerekir.

* **`redirect_handler`**, tamamen hazırlanmış yetkilendirme URL'siyle await edilir. `client_id`, `redirect_uri`, `state` ve PKCE challenge'ı zaten içindedir. Tek işiniz bir tarayıcıyı oraya götürmektir. Bir masaüstü uygulaması `webbrowser.open`'ı çağırır; bu dosya URL'yi yazdırır.
* Ardından **`callback_handler`** await edilir. Kullanıcı `redirect_uri`'nize geri dönene kadar bekler ve o yönlendirmenin sorgu parametrelerini bir `AuthorizationCodeResult` olarak döndürür.

Gerçek bir istemci `input()` çağırmak yerine yönlendirme URI'si üzerinde küçük bir yerel HTTP sunucusu çalıştırır. Biçim aynıdır: yönlendirilin, `code`, `state` ve `iss` değerlerini geri verin.

!!! warning
    `state` ve `iss` değerlerini tam geldikleri gibi aktarın. Sağlayıcı `state`'i kendi ürettiğiyle,
    `iss`'i de keşfettiği yayıncıyla karşılaştırır ve uyuşmazlığı reddeder. Bunlar CSRF ve
    sunucu karışıklığı (mix-up) savunmalarıdır.

### `Client`'a bağlama {#into-the-client}

`main()`'e bakın. Sağlayıcı **httpx2 istemcisine** takılır, httpx2 istemcisi `streamable_http_client(url, http_client=...)`'a verilir, bu aktarım da `Client`'a gider.

`streamable_http_client`'ın `auth=` diye bir anahtar sözcük argümanı yoktur. HTTP düzeyindeki her şey (kimlik doğrulama, başlıklar, zaman aşımları, vekil sunucular) sizin getirdiğiniz `httpx2.AsyncClient`'a aittir. Bu katmanlama **[İstemci aktarımları](transports.md)** sayfasında anlatılır.

## Sağlayıcının sizin için yaptıkları {#what-the-provider-does-for-you}

`Client` ilk kez bir istek gönderdiğinde sunucu `401` yanıtını verir. Sağlayıcı devralır:

1. **Keşif.** `WWW-Authenticate` başlığını okur, sunucunun Protected Resource Metadata belgesini `/.well-known/oauth-protected-resource` adresinden alır, bu kaynağı hangi yetkilendirme sunucusunun koruduğunu öğrenir ve *o* sunucunun metadatasını alır.
2. **Kayıt.** Depoda bir şey yok mu? `OAuthClientMetadata`'nızla sizi dinamik olarak kaydeder ve sonucu saklar.
3. **Yetkilendirme.** PKCE çiftini ve bir `state` üretir, yetkilendirme URL'sini oluşturur, `redirect_handler`'ınızı await eder, ardından kod için `callback_handler`'ınızı await eder.
4. **Değişim.** Kodu bir `OAuthToken` ile takas eder, onu saklar ve özgün isteğinizi `Authorization: Bearer ...` ile yeniden gönderir.

Bundan sonra sessizdir. Token'lar depodan gelir, süresi dolmuş bir erişim token'ı yenileme token'ıyla yenilenir ve ancak bunların hiçbiri işe yaramadığında akışı yeniden çalıştırır.

Bunların hiçbirini siz yazmadınız. Geriye iki anahtar sözcük argümanı kalır (`client_metadata_url` ve `validate_resource_url`) ve bu dosyanın ikisine de ihtiyacı yoktur. Bilmeye değer olanı `client_metadata_url`'dir; aşağıda kendi bölümü var.

### Deneyin {#try-it}

Bu belgelerdeki örneklerin çoğunu bellek içi bir `Client(server)` ile sınayabilirsiniz. Bunu değil: akışın bütün amacı bir HTTP `401`'idir ve bellek içi bir istemci ile sunucusu arasında HTTP yoktur.

Depo canlı sürümü içerir. `examples/servers/simple-auth/` bağımsız bir yetkilendirme sunucusu ile korumalı bir MCP sunucusu çalıştırır; `examples/clients/simple-auth-client/` ise bu sayfadaki istemcinin küçük bir CLI'a dönüşmüş hâlidir. README'sinde iki komut var: sunucuları başlatın, istemciyi onlara karşı çalıştırın ve dört adımın geçişini izleyin.

## Client ID Metadata Documents {#client-id-metadata-documents}

Belirtimin 2026-07-28 sürümü, dinamik istemci kaydını **Client ID Metadata Documents** (CIMD) lehine kullanım dışı bırakır. İstemciniz karşılaştığı her yetkilendirme sunucusuna yeni bir kayıt POST etmek yerine, kendisi hakkında tek bir JSON belgesini kararlı bir HTTPS URL'sinde yayımlar ve `client_id`'si bu URL'nin *ta kendisidir*. Belgeyi yetkilendirme sunucusu alır; sağlayıcı ona hiç dokunmaz.

SDK bunu zaten destekler: sağlayıcıyı oluştururken URL'yi `client_metadata_url=` olarak geçirin. Yetkilendirme sunucusunun metadatası `client_id_metadata_document_supported: true` bildiriyorsa sağlayıcı `/register` isteğini tamamen atlar: URL akışa `client_id` olarak girer ve `client_secret` yoktur. Sunucu bunu bildirmiyorsa (çoğu henüz bildirmiyor) ya da hiç URL geçirmediyseniz sağlayıcı **sessizce** dinamik kayda geri döner ve yukarıdaki her şey tam anlatıldığı gibi çalışır. Saklanmış `client_info` yine de ikisinin de önüne geçer.

URL, kök olmayan bir yola sahip HTTPS olmalıdır; başka her şey, herhangi bir ağ trafiği olmadan oluşturma sırasında bir `ValueError`'dır. Depodaki `examples/clients/simple-auth-client/` bunu `MCP_CLIENT_METADATA_URL` ortam değişkeni olarak alır.

## Makineden makineye {#machine-to-machine}

Bir gece görevi, bir CI adımı, başka bir servis. Tarayıcı yok, "allow" düğmesine tıklayacak kimse de yok. Bu **client credentials** yetkilendirme türüdür: elinizde zaten bir `client_id` ve bir `client_secret` vardır, akışın tamamı da token endpoint'idir.

`ClientCredentialsOAuthProvider` aynı `httpx2.Auth`'tur, insan hariç:

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

Neler değişti:

* `OAuthClientMetadata` yok, işleyiciler yok. `client_id` ve `client_secret` geçirirsiniz; sağlayıcı bunların etrafında asgari bir `client_credentials` kaydı oluşturur ve dinamik kaydı tamamen atlar.
* `scope`, boşlukla ayrılmış bir dizedir; OAuth'un iletilen verideki biçimi budur.
* Bundan sonraki her şey aynıdır: aynı `TokenStorage`, aynı `httpx2.AsyncClient(auth=...)`, aynı `streamable_http_client`.

Varsayılan olarak sır, token isteğinde HTTP Basic kimlik doğrulaması olarak gider (`client_secret_basic`). Onu bunun yerine form gövdesine koymak için `token_endpoint_auth_method="client_secret_post"` geçirin. Bazı yetkilendirme sunucuları ikisinden yalnızca birini kabul eder.

!!! tip
    `client_secret`'ı ortamdan ya da bir sır yöneticisinden okuyun, asla kaynak kontrolünden değil.

!!! info
    `mcp.client.auth.extensions.client_credentials` içinde bir sağlayıcı daha var:
    paylaşılan bir sır yerine JWT ile kimlik doğrulayan istemciler için **`PrivateKeyJWTOAuthProvider`**
    (`private_key_jwt`; anahtar çifti ve iş yükü kimliği türü). Aynı kalıbı izler:
    bir tane oluşturun, `auth=`'a koyun. Aynı modül, onun assertion'ını oluşturan iki yardımcıyı da
    sunar: `SignedJWTParameters` ve `static_assertion_provider`.

İnsansız bir durum daha var: istemci, hangi MCP sunucularına erişebileceğine kullanıcının değil kimlik sağlayıcısının karar verdiği bir kuruluşa aittir. Bu, kendi güven modeli ve kendi sayfası olan farklı bir yetkilendirme türüdür: **[Kimlik beyanı](identity-assertion.md)**.

## Başarısız olduğunda {#when-it-fails}

OAuth akışı ters gittiğinde sağlayıcı, `mcp.client.auth` içinden bir `OAuthFlowError` fırlatır. İki alt sınıfı vardır. `OAuthRegistrationError`, kaydın kullanabileceğiniz bir istemci üretmediği anlamına gelir: yetkilendirme sunucusu sizi kaydetmeyi reddetti ya da kaydetti ama bu akışın kullanamayacağı kimlik bilgileriyle (örneğin uygulamadığı bir kimlik doğrulama yöntemiyle). `OAuthTokenError` ise bir token alınamadığı anlamına gelir: token endpoint'i hayır dedi ya da saklanan bir istemci kaydı bu istemcinin uygulayamayacağı bir kimlik doğrulama yöntemi taşıyor; bu durum gönderilmek yerine token isteği oluşturulurken bildirilir. Tek bir `except OAuthFlowError:` keşfi, kaydı, yetkilendirmeyi ve değişimi kapsar.

Her şey bir akış hatası değildir. Ağ yine de başarısız olabilir; bunlar sıradan `httpx2` istisnalarıdır ve dokunulmadan geçer.

## Özet {#recap}

* `OAuthClientProvider` bir `httpx2.Auth`'tur. Onu bir `httpx2.AsyncClient`'a koyun, bunu `streamable_http_client(url, http_client=...)`'a geçirin; `Client` OAuth'un gerçekleştiğini hiç bilmez.
* Dört şey sağlarsınız: sunucu URL'si, bir `OAuthClientMetadata`, bir `TokenStorage` ve redirect/callback işleyici çifti.
* `TokenStorage` bir `Protocol`'dür: dört asenkron metot, taban sınıf yok. Token'ların yanı sıra `client_info`'yu da kalıcı hâle getirin.
* Keşif, kayıt (dinamik ya da bir **Client ID Metadata Document** aracılığıyla), PKCE, `state` ve `iss` denetimleri ile token yenileme sağlayıcının işidir, sizin değil.
* `ClientCredentialsOAuthProvider` insansız sürümdür: `client_id` + `client_secret`, işleyici yok, tarayıcı yok.
* Her OAuth hatası bir `OAuthFlowError`'dır; `OAuthRegistrationError` ve `OAuthTokenError` onun alt sınıflarıdır.

Bu el sıkışmanın diğer yarısı, yani *sunucunuzun* token talep etmesini sağlamak **[Yetkilendirme](../run/authorization.md)** sayfasındadır.
