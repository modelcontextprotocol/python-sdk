---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# Kimlik beyanı {#identity-assertion}

Sıradan bir OAuth sağlayıcısı (**[OAuth istemcileri](oauth-clients.md)**) işe MCP sunucusuna bir soru sorarak başlar: *hangi yetkilendirme sunucusuna güveniyorsun?* Yanıt nereyi gösteriyorsa oraya gider; ardından ya bir kişi oturum açar ya da önceden paylaşılmış bir gizli anahtar onun yerini tutar.

Bir kurum ise bunların hiçbirinin sunucu başına kararlaştırılmasını istemez. Zaten bir kimlik sağlayıcısı işletir (Okta, Microsoft Entra ID, kendi yazdığınız); kullanıcı ona bu sabah zaten oturum açmıştır ve güvenlik ekibinin kimin neye erişebileceğine karar vermek istediği tek yer orasıdır. **Enterprise-Managed Authorization** uzantısı olan [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), kararı oraya taşır. IdP kısa ömürlü bir JWT imzalar: bir **Identity Assertion JWT Authorization Grant**, kısaca **ID-JAG**. Bu, *şu kullanıcının*, *şu istemci* aracılığıyla *şu MCP sunucusuna* erişebileceğini söyleyen bir beyandır. İstemci onu sıradan bir erişim token'ıyla takas eder. Tarayıcı yok, onay ekranı yok, dinamik kayıt yok.

Bu sayfa o takasın iki ucunu da anlatır. MCP sunucusunun kendisi hiç değişmez: hâlâ **[Yetkilendirme](../run/authorization.md)** sayfasındaki kaynak sunucusudur ve önüne hangi token gelirse onu denetler.

## İki token isteği {#two-token-requests}

İşin içinde iki farklı otorite var ve bu sayfayı anlamanın büyük kısmı ikisini ayrı adlarla anmaktan geçer. **Kurumsal IdP**, kuruluşunuzun kimlik sağlayıcısıdır: çalışanın kim olduğunu bilir, politikanın bulunduğu yerdir ve ID-JAG'i o düzenler. SDK onunla hiç konuşmaz. **MCP yetkilendirme sunucusu** ise **[Yetkilendirme](../run/authorization.md)** sayfasındaki aynı taraftır: MCP sunucusunun meta verisinde adı geçen issuer, o MCP sunucusunun kabul ettiği token'ları basan şey. Sıradan bir OAuth akışında bu iki rol genellikle tek bir kutudur. Burada iki ayrı kutudur ve grant'in tamamı, ikincisinin birincisine güvenmeyi kabul etmesinden ibarettir.

İstemci her birine birer token isteği gönderir.

1. **Kurumsal IdP'ye.** İstemci, kullanıcının oturum açma bilgisini (OpenID Connect ID token'ını) ID-JAG ile takas eder. Bu bir [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token takasıdır, tamamen IdP'nizin API'sidir ve **bu isteği SDK yapmaz**. Siz yaparsınız, tek bir asenkron callback'in içinde. Politika kararı da burada verilir: hayır diyen bir IdP ID-JAG'i hiç düzenlemez ve ortada sunulacak bir şey kalmaz.
2. **MCP yetkilendirme sunucusuna.** İstemci ID-JAG'i [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) `jwt-bearer` grant'i kapsamında sunar (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, ID-JAG de `assertion` olarak) ve erişim token'ını alır. **SDK'nın yaptığı istek budur** ve bu sayfanın bir yetkilendirme sunucusuna eklediği tek şey de onu kabul etmektir.

Aşağıdaki her şey ikinci istekle ilgilidir: onu gönderen istemci ve yanıtlayan yetkilendirme sunucusu.

## İstemci {#the-client}

**`IdentityAssertionOAuthProvider`**, `mcp.client.auth.extensions.identity_assertion` modülünde bulunur. **[OAuth istemcileri](oauth-clients.md)** sayfasındaki her sağlayıcı gibi o da bir `httpx2.Auth` nesnesidir: bir tane oluşturun, `auth=` parametresine verin, `httpx2.AsyncClient`'ı aktarıma teslim edin.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

Aşağıdan yukarıya okuyun.

* `main()`, standart OAuth istemcisi `main()`'idir (**[OAuth istemcileri](oauth-clients.md)**), satırı satırına aynı. Mesele de bu: sağlayıcı bir kez var olduktan sonra, akışın devamındaki hiçbir şey token'ı hangi grant'in ürettiğini bilmez.
* Sağlayıcı, diğer sağlayıcıların keşfedemeyeceği şeyleri alır: birinin yetkilendirme sunucusuna **önceden kaydettirdiği** bir `client_id` ve `client_secret`, o yetkilendirme sunucusunun `issuer`'ı ve `assertion_provider`, yani istendiğinde taze bir ID-JAG döndüren asenkron bir callback.
* `storage` aynı `TokenStorage` protokolüdür. Yalnızca iki token metodu çağrılır; burada dinamik kayıt olmadığından hatırlanacak bir `client_info` da yoktur.

### Beyan sağlayıcı {#the-assertion-provider}

Yazdığınız tek kod `fetch_id_jag(audience, resource)` fonksiyonudur. Her token takasında bir kez await edilir; oluşturma sırasında asla, ve ancak yetkilendirme sunucusunun meta verisi alınıp doğrulandıktan *sonra*. Böylece yanlış yapılandırılmış bir issuer hiçbir zaman bir beyan sızdırmaz. İki argümanı, ID-JAG'in basılırken taşıması gereken claim'lerden ikisidir: `audience` yetkilendirme sunucusunun issuer'ıdır (ID-JAG'deki `aud`), `resource` ise MCP sunucusunun kanonik tanımlayıcısıdır (ID-JAG'deki `resource`). Üçüncüsü zaten elinizde: ID-JAG'in `client_id` claim'i, sağlayıcıya verdiğiniz `client_id`'yi göstermelidir; yoksa yetkilendirme sunucusu takası reddeder.

Onun üstündeki `idp_issue_id_jag` **sizin kodunuz değildir**. Kimlik sağlayıcısının yerini tutar; dosya eksiksiz olsun ve bir ID-JAG'in taşıdığı her claim'i okuyabilesiniz diye beyanı süreç içinde imzalar. Gerçek bir `fetch_id_jag` ise bunun yerine önceki bölümdeki ilk token isteğini yapar: IdP'nize karşı bir [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token takası. Bu takası, [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) belgesinin profil olarak daralttığı Identity Assertion JWT Authorization Grant taslağı tanımlar. Oturum açmış kullanıcının ID token'ı `subject_token` olarak girer, `requested_token_type` ID-JAG'in kendi URN'idir (`urn:ietf:params:oauth:token-type:id-jag`), `audience` ve `resource` olduğu gibi aktarılır ve yanıt ID-JAG'i taşır. IdP'nizin belgelerinde aramanız gereken şey, bu adlarla anılan bu takastır.

!!! tip
    Her takas için taze bir ID-JAG istenir ve amaç da budur: tek kullanımlık, ömrü dakikalarla
    ölçülen bir grant'tir ve bu sayfadaki yetkilendirme sunucusu aynısını ikinci kez kabul etmez.
    Onu önbelleğe almayın. Yeniden kullanılan şey, size kazandırdığı erişim token'ıdır.

### Yapılandırma olarak issuer {#the-issuer-is-configuration}

Tersine çevirme işte burada. `OAuthClientProvider`, kaynak sunucusuna hangi yetkilendirme sunucusunu kullanacağını sorar ve yanıt nereyi gösteriyorsa oraya gider. Bu sağlayıcı bunu reddeder: `issuer` zorunludur, [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) meta verisi o issuer'ın kendi well-known yolundan alınır, token endpoint'i o issuer'ın origin'inde olmalıdır ve kaynak sunucusuna hiçbir şey sorulmaz.

Uzantı bunu şart koşmaz; bu, bilerek yapılmış daha katı bir tercihtir. Bu istemci çalınmaya değer iki şey taşır: önceden kaydedilmiş bir gizli anahtar ve audience'a bağlı bir beyan. Ele geçirilmiş bir MCP sunucusunun kendisini saldırganın yetkilendirme sunucusuna yönlendirmesine izin veren bir istemci, ikisini de oraya gönderirdi. Oluşturma sırasında issuer'ı sabitlemek bu konuşmayı ortadan kaldırır.

!!! warning
    Yapılandırılan `issuer`, meta veri belgesinin `issuer` alanıyla RFC 8414 §3.3'teki basit dize
    karşılaştırmasıyla karşılaştırılır: karakter karakter, sondaki eğik çizgi dahil, normalleştirme
    olmadan. Tahmin etmeyin. Yetkilendirme sunucunuzdan `/.well-known/oauth-authorization-server`
    belgesini alın ve döndürdüğü `issuer` değerini kopyalayın. Bu sayfadaki yetkilendirme sunucusu
    için bu değer, eğik çizgisiyle birlikte `https://auth.example.com/` adresidir; çünkü issuer'ı
    bir pydantic URL nesnesinden oluşturulmuştur. Bir uyuşmazlık, tek bir kimlik bilgisi ya da
    beyan gönderilmeden akışı `OAuthFlowError: Authorization server metadata issuer
    mismatch` hatasında durdurur.

### Gizli istemci {#a-confidential-client}

`client_secret` zorunludur; yapıcı onsuz `ValueError` fırlatır. [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) belgesinin dayandığı IETF profili bu grant'i gizli istemcilere ayırır, SEP-990 istemcinin kimliğini doğrulamasını şart koşar ve bu SDK, paylaşılan bir gizli anahtarda ısrar ederek ikisini de uygular. `token_endpoint_auth_method`, anahtarın nereden gideceğini seçer: `client_secret_post` (varsayılan, form gövdesinde) veya `client_secret_basic` (bir HTTP Basic başlığı). Profil `private_key_jwt` yöntemine de izin verir; bu sağlayıcı onu desteklemez.

!!! tip
    `client_secret`'ı ortam değişkenlerinden veya bir gizli anahtar yöneticisinden okuyun, asla
    kaynak kod deposundan değil.

### Sağlayıcının sizin için yaptıkları {#what-the-provider-does-for-you}

İlk istek kimlik doğrulaması olmadan gider ve sunucunun `401` yanıtı akışı başlatır.

1. **Keşif.** Yetkilendirme sunucusu meta verisini yapılandırılan issuer'ın [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known yolundan alır, belgenin `issuer` alanının eşleştiğini denetler ve token endpoint'inin issuer'ın origin'inde olduğunu denetler.
2. **Beyan.** `assertion_provider`'ınızı await eder.
3. **Takas.** `jwt-bearer` grant'ini token endpoint'ine POST eder, `OAuthToken`'ı saklar ve özgün isteğinizi `Authorization: Bearer ...` ile yeniden gönderir.

`WWW-Authenticate` başlığında `insufficient_scope` geçen bir `403`, 2. ve 3. adımları sizin `scope`'unuz ile yanıtın istediği kapsamın birleşimiyle yeniden çalıştırır. (`scope` yalnızca bir istektir; bu sayfadaki yetkilendirme sunucusu ID-JAG ne diyorsa onu verir, başka bir şey değil.) Bunun hiçbir yerinde yenileme token'ı yoktur: erişim token'ının süresi dolduğunda bir sonraki `401` taze bir ID-JAG bastırır ve takas yeniden yapılır; IdP'nin elinde tuttuğu kaldıraç işte *budur*. Hatalar, **[OAuth istemcileri](oauth-clients.md)** sayfasının geri kalanındaki aynı iki istisnadır: keşif ve doğrulama için `OAuthFlowError`, token endpoint'i hayır dediğinde onun alt sınıfı `OAuthTokenError`.

## Yetkilendirme sunucusu {#the-authorization-server}

Çoğu zaman burada durursunuz. MCP yetkilendirme sunucusu başkasının ürünüdür, ID-JAG kabul etmek o ürünün açılacak bir yapılandırmasıdır ve SDK'nın [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) içindeki payı yukarıdaki istemcidir.

SDK yetkilendirme sunucusunun kendisi de *olabilir*: `create_auth_routes`, yetkilendirme sunucusunun route'larını herhangi bir Starlette uygulamasının bağlayabileceği bir liste olarak döndürür; depodaki `examples/servers/simple-auth/` da bir tanesini böyle çalıştırır. SEP-990 bu yüzeye bir bayrak ve bir metot ekler:

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` her şeyin kapısıdır. Kapalıyken (varsayılan budur) `/token`, hook'u uygulamış olsanız bile bu grant'e `unsupported_grant_type` ile yanıt verir ve meta veri ondan söz etmez. Açıkken meta veri `jwt-bearer` grant türünü kazanır ve uzantının desteği duyurmak için kullandığı alan olan `authorization_grant_profiles_supported` içinde `urn:ietf:params:oauth:grant-profile:id-jag` değerini listeler. (Bu SDK'nın istemcisi onu hiç okumaz: tek bir issuer için hazırlanmıştır ve doğrudan sorar.)
* **`exchange_identity_assertion`** hook'un kendisidir. O çalışmadan önce SDK istemcinin kimliğini doğrulamış, açık (public) istemcileri reddetmiş ve kaydında bu grant'in listelenmediği istemcileri reddetmiştir. Size bir `IdentityAssertionParams` gelir (ham `assertion`, istenen `scopes` ve `resource`) ve düz bir `OAuthToken` döndürürsünüz.
* Dinamik istemci kaydı bu grant'i koşulsuz reddeder; bu yüzden buradaki `get_client` elle hazırlanmış bir istemci sunar. Bir ID-JAG istemcisi kendi kendini kaydederek var olamaz.
* Sınıfın yarısı retlerden oluşur. `OAuthAuthorizationServerProvider` yetkilendirme sunucusunun *tamamıdır*, bu yüzden yetkilendirme kodu akışını da ister; kullanıcılara oturum da açtıran bir sunucu onları gerçekten uygular, bunun ise tam olarak tek bir kapısı var.

!!! warning
    SDK beyanın kodunu hiçbir zaman çözmez: hangi IdP'ye güvendiğini ve o IdP'nin hangi
    anahtarları yayımladığını yalnızca sizin dağıtımınız bilir; bu yüzden
    `exchange_identity_assertion` içindeki her şey yük taşır. İmzayı IdP'nin yayımladığı
    anahtarlara karşı (JWKS'i; buradaki paylaşılan gizli anahtar demoya aittir), `iss` ve `exp`
    değerlerini de [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3 uyarınca doğrulayın. JWT başlığındaki `typ` değerinin
    `oauth-id-jag+jwt` olmasını şart koşun; bu, profilin başka bir JWT'nin grant olarak yeniden
    oynatılmasına karşı koyduğu korumadır. `aud` değerinin kendi issuer'ınız olmasını şart koşun.
    ID-JAG'in `client_id` claim'inin işleyicinin kimliğini doğruladığı istemciye eşit olmasını,
    `resource` claim'inin de gerçekten sunduğunuz bir kaynağı göstermesini şart koşun. Beyan
    yalnızca bir kez kabul edilsin diye `jti` değerini beyanın `exp` süresine kadar takip edin.
    Verilen kapsamları ve her şeyden önce düzenlenen token'ın `resource` değerini istekten değil,
    doğrulanmış ID-JAG'den alın: `params.resource` istemci ne yazdıysa odur. İşleme kurallarının
    tamamı [Enterprise-Managed Authorization spesifikasyonunda](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization) yer alır.

Kötü bir beyanı `TokenError("invalid_grant", ...)` ile reddedin. Bu akıştaki diğer hata kodu `invalid_target`'tır: sunmadığınız bir kaynağı gösteren bir ID-JAG onunla reddedilir; bu sunucunun başkasının kaynağı için token basmasını engelleyen de budur. Verilen kapsamlar ise ID-JAG'in `scope` claim'inden gelir (bu claim'i olmayan bir beyan da reddedilir); sizinki bunun yerine kullanıcının gruplarını eşleyebilir.

Döndürülen `OAuthToken`'ın ne taşımadığına da dikkat edin: bir yenileme token'ı. IdP, bir sonraki ID-JAG'i düzenleyip düzenlemeyeceğine karar vererek bu kullanıcının erişimi ne kadar süre koruyacağına karar verir. Burada basılacak bir yenileme token'ı o kararı sessizce geri teslim ederdi.

!!! info
    Yetkilendirme sunucusunu hâlâ `auth_server_provider=` ile içine gömen bir sunucu, aynı koda
    `AuthSettings(identity_assertion_enabled=True)` üzerinden ulaşır. Yeni sunucuların neden oradan
    başlamaması gerektiğini **[Yetkilendirme](../run/authorization.md)** sayfası açıklar.

!!! check
    Bu sayfadaki iki dosyayı birbirine bağlayın; grant'in tamamı tek bir `POST /token` olur:

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    `/authorize` yok, `/register` yok, korumalı kaynak meta verisi isteği yok. Ağ üzerindeki tek
    istekler `401`'i çeken istek, well-known isteği, bu takas ve ardından bearer eklenmiş sıradan
    MCP trafiğidir. Doğrulayıcınızın ID-JAG'den okuduğu `sub` da bir aracın içinde
    `get_access_token().subject`'in bildirdiği değerin ta kendisidir.

### Deneyin {#try-it}

SDK deposundaki `examples/stories/identity_assertion/`, bu sayfanın gerçekten çalışan hâlidir: aynı `exchange_identity_assertion` doğrulayıcısı, onun token'larıyla korunan bir MCP sunucusu, yerine geçen bir IdP ve istemci; hepsi kendi kendini denetleyen tek bir programda. `uv run python -m stories.identity_assertion.client --http` takasın tamamını çalıştırır ve IdP'nin adını verdiği kullanıcının, aracın gördüğü kullanıcı olduğunu doğrular.

## Özet {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), bir istemcinin hangi MCP sunucularına erişebileceğine son kullanıcının değil, kurumsal kimlik sağlayıcısının karar vermesini sağlar. IdP o kararı imzalayıp bir **ID-JAG** içine koyar.
* ID-JAG'i elde etmek *IdP'nize* karşı yapılan bir [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token takasıdır ve SDK bunu yapmaz. Onu MCP yetkilendirme sunucusuna sunmak [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) `jwt-bearer` grant'idir ve SDK bunun iki tarafını da üstlenir.
* `IdentityAssertionOAuthProvider` bir başka `httpx2.Auth` nesnesidir: önceden kaydedilmiş gizli bir istemci, sabitlenmiş bir `issuer` ve tek bir `assertion_provider(audience, resource)` callback'i. Tarayıcı yok, kayıt yok, yenileme token'ı yok.
* Yetkilendirme sunucusu hiçbir zaman kaynak sunucusundan keşfedilmez. `issuer`'ı, meta veri belgesinin sunduğu dizenin tıpatıp aynısı olarak yapılandırın; karşılaştırma karakter karakter yapılır.
* Sunucu tarafında `identity_assertion_enabled=True` artı `exchange_identity_assertion`. SDK istemcinin kimliğini doğrular ve grant'in kapısını tutar; ID-JAG'i doğrulamak tamamen size aittir ve düzenlenen token isteğin değil, ID-JAG'in `resource` değerine bağlanır.

Bu sayfanın hiç dokunmadığı tek taraf MCP sunucusudur. Az önce bastığınız token'la ne yapıyorsa, onu **[Yetkilendirme](../run/authorization.md)** sayfasında zaten yapıyordu.
