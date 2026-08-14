---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# Yetkilendirme {#authorization}

Streamable HTTP üzerinden MCP sunucunuz sıradan bir web hizmetidir ve onu her web hizmetini koruduğunuz gibi korursunuz: OAuth 2.1 bearer token'larıyla.

OAuth terimleriyle sunucunuz bir **kaynak sunucusudur**. Hiç kimsenin oturumunu açmaz ve hiçbir zaman token vermez. Tek bir şey yapar: her istekteki `Authorization` başlığına bakar ve içindeki token'ın geçerli olup olmadığına karar verir.

Bu sayfa sunucu tarafını anlatır. Yetkilendirme sunucunuzu keşfeden ve token'ı alan istemci ise **[OAuth istemcileri](../client/oauth-clients.md)** sayfasında.

## Üç taraf {#the-three-parties}

* **Yetkilendirme sunucusu** kullanıcıların oturumunu açar ve erişim token'ları verir. Bunu siz yazmazsınız. Kimlik sağlayıcınızdır (Auth0, Keycloak, Entra ya da kendinizinki).
* **Kaynak sunucusu** MCP sunucunuzdur. Her istekte token'ı doğrular.
* **İstemci** hangi yetkilendirme sunucusuna güvendiğinizi keşfeder, ondan bir token alır ve size `Authorization: Bearer <token>` olarak geri gönderir.

Üçgenin tamamı bu. Bu sayfadaki her şey ortadaki maddeyle ilgili.

## Token doğrulayıcı {#a-token-verifier}

SDK'nın geçerli bir token'ın neye benzediği konusunda bir fikri yoktur. Bunu **`TokenVerifier`**'ı uygulayarak siz söylersiniz:

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` tek bir asenkron metodu olan bir protokoldür. `verify_token`, `Authorization` başlığındaki ham token'ı alır; geçerliyse bir **`AccessToken`**, değilse `None` döndürür. Uygulanacak başka bir şey yok.
* Buradaki, token'ı bir tabloda arar. Gerçek bir doğrulayıcı JWT imzasını doğrular ya da yetkilendirme sunucusunun token-introspection endpoint'ini çağırır. O kod sizindir; SDK onu yalnızca çağırır.
* `token_verifier=` ve `auth=` her zaman birlikte kullanılır. Birini diğeri olmadan geçirirseniz `MCPServer(...)` daha tek bir istek sunmadan `ValueError` fırlatır.

`AuthSettings`, kaynak sunucunuzun dışa dönük yüzüdür:

* `issuer_url`: token'larınızı veren yetkilendirme sunucusu.
* `resource_server_url`: bu MCP endpoint'inin herkese açık URL'si. Bir token'ın *hangi* kaynak için olduğunu belirtir ve keşif belgesi burada bulunur.
* `required_scopes`: her token bunların hepsini taşımalıdır.

!!! tip
    SDK deposundaki `examples/servers/simple-auth/` dizininde, gerçek bir yetkilendirme sunucusunun
    [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) endpoint'ini çağıran bir `IntrospectionTokenVerifier` var. Üretimdeki çoğu doğrulayıcı bu biçimdedir.

## HTTP üzerinden elinize geçenler {#what-you-get-over-http}

Yetkilendirme HTTP başlıklarında yaşar; bu yüzden yalnızca HTTP aktarımlarında vardır. Dağıttığınız aktarımda çalıştırın: `mcp.run(transport="streamable-http")` onu `http://127.0.0.1:8000/mcp` adresinde sunar; gerisi **[Sunucunuzu çalıştırma](index.md)** sayfasında. Uygulamanın artık iki rotası var:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

Siz tek bir araç kaydettiniz. İkinci rota SDK'nındır.

### Keşif {#discovery}

Bu well-known yoluna `GET` isteği gönderin; doğrudan `AuthSettings` değerlerinizden oluşturulmuş **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata** belgesini alırsınız:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

Sunucunuzu hiç duymamış bir istemci içeri giden yolu bu belgeyle bulur: `authorization_servers` alanını okur ve token almak için oraya gider. Bunun hiçbirini siz yazmadınız.

!!! check
    `/mcp` yolunu token olmadan (ya da doğrulayıcınızın `None` döndürdüğü bir token'la) çağırın; istek
    kapıda durdurulur:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    Hiçbir şey ayrıştırılmadı, hiçbir araç çalışmadı. `WWW-Authenticate` içindeki o `resource_metadata`
    işaretçisi de keşfi otomatik hale getiren şeydir: 401 -> meta veri belgesi -> yetkilendirme sunucusu -> token -> yeniden deneme.

!!! warning
    Bunların hiçbiri `stdio`'yu korumaz. Bir pipe'ın `Authorization` başlığı yoktur; bu yüzden orada
    `token_verifier`'a hiç danışılmaz. Bir `stdio` sunucusunun güvenlik sınırı, onu başlatan süreçtir.
    Aynısı testlerde kullandığınız bellek içi `Client(mcp)` için de geçerlidir: doğrudan sunucu nesnesine
    bağlanır ve yetkilendirme dahil HTTP katmanını atlar.

## Çağıranın kimliği {#the-callers-identity}

Herhangi bir işleyicinin içinde **`get_access_token()`**, doğrulayıcınızın geçerli istek için döndürdüğü `AccessToken`'dır:

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* Araçlarda, kaynaklarda ve prompt'larda çalışır ve elden ele geçirilecek bir şey yoktur: auth middleware'i onu istek başına bir bağlam değişkeninde saklar.
* Geriye **doğrulayıcınızın oluşturduğu nesnenin aynısı** döner: `client_id`, `scopes`, `subject`, `expires_at` ve eklediğiniz ek `claims`. Araç başına kurallar için kanca budur: kapsamları okuyun ve reddedin.
* Kimliği doğrulanmış bir HTTP isteğinin dışında `None` döndürür. Bellek içinde ve `stdio` üzerinden her zaman `None`'dır.

`whoami` aracını `Authorization: Bearer alice-token` ile çağırın; model şunu okur:

```text
alice (scopes: notes:read)
```

## SDK'nın üstlenmediği yarı {#the-half-the-sdk-doesnt-do}

SDK size kaynak sunucusu yarısını verir: doğrula, duyur, reddet. Size bir giriş sayfası, bir onay ekranı ya da bir token vermez.

Üç tarafın birden hareketini izlemek için SDK deposundaki `examples/servers/simple-auth/` örneğini çalıştırın (küçük bir yetkilendirme sunucusu ve tam bu sayfadaki gibi kurulmuş bir kaynak sunucusu), ardından keşif ve token akışının tamamını görmek için `examples/clients/simple-auth-client/` istemcisini ona yönlendirin.

!!! info
    İkinci bir kurucu argümanı daha var: `auth_server_provider=`. MCP sunucunuzun içine eksiksiz bir
    yetkilendirme sunucusu gömer. MCP yetkilendirme spesifikasyonunun üzerine kurulduğu AS/RS ayrımından
    daha eskidir. Yeni sunucular onu kullanmamalıdır.

Bir yetkilendirme sunucusu, kullanıcının onay ekranından tıklayarak geçmesi yerine kurumsal bir kimlik sağlayıcının imzalı beyanını da kabul edebilir; SDK bu alışverişin iki tarafını da destekler. Bu grant ve onu sunan istemci **[Kimlik beyanı](../client/identity-assertion.md)** sayfasında.

## Özet {#recap}

* Streamable HTTP üzerinden sunucunuz bir OAuth 2.1 **kaynak sunucusudur**: token'ları doğrular, asla vermez.
* `TokenVerifier` entegrasyon yüzeyinin tamamıdır: tek bir asenkron metot, token girer, `AccessToken | None` çıkar.
* `token_verifier=` ve `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` her zaman birlikte kullanılır.
* SDK, [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata belgesini `/.well-known/oauth-protected-resource/...` altında yayımlar ve kimliği doğrulanmamış istekleri, `WWW-Authenticate` başlığı ona işaret eden bir 401 ile yanıtlar. Keşif hikâyesinin tamamı bu.
* Herhangi bir işleyicide `get_access_token()`, kimin çağırdığını söyler.
* Yetkilendirme bir HTTP meselesidir. `stdio` ve bellek içi istemci onu hiç görmez.

İstemci yarısı (yetkilendirme sunucunuzu keşfetme ve token'ı sizin yerinize alma) **[OAuth istemcileri](../client/oauth-clients.md)** sayfasında. Kullanıcıdan kimlik istemek yerine bir kimliği *beyan eden* istemci ise **[Kimlik beyanı](../client/identity-assertion.md)** sayfasında.
