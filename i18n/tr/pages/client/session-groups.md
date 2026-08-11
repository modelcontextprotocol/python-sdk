---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# Oturum grupları {#session-groups}

Bir `Client` tek bir sunucuya bağlanır. Gerçek uygulamalar ise çoğu zaman birden fazlasını ister (bir arama sunucusu, bir veritabanı sunucusu, dahili bir API) ve her biri için ayrı bir bağlantı ile ayrı bir araç listesiyle uğraşmak zorunda kalır.

**`ClientSessionGroup`**, birçok bağlantıyı tutan ve bunların sunduğu her şeyi tek bir görünümde birleştiren tek bir nesnedir.

## İki sunucu {#two-servers}

İki sıradan sunucuyla başlayın. Birbirleriyle hiçbir ilgileri yok, bu yüzden ikisi de doğal olarak aracına `search` adını vermiş:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## Tek grup {#one-group}

Bir `ClientSessionGroup` oluşturun ve her sunucu için bir kez **`connect_to_server`**'ı çağırın:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` bir sunucu nesnesi değil, aktarım parametreleri alır: bir alt süreç başlatmak için `StdioServerParameters` (`mcp`'den) ya da zaten bir URL'de dinleyen bir sunucu için `StreamableHttpParameters` / `SseServerParameters` (`mcp.client.session_group`'tan).
* `group.tools`, bağlı tüm sunucuların araçlarını içeren bir `dict[str, Tool]`'dur. `group.resources` ve `group.prompts` da aynı biçimdedir.
* `group.call_tool(name, arguments)` adı arar, ona sahip olan oturumu bulur ve çağrıyı iletir. Hangi sunucu olduğunu hiçbir zaman söylemezsiniz.

!!! check
    `client.py` dosyasını iki sunucunun yanına koyun ve çalıştırın. İkinci `connect_to_server` reddeder:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    Bu, ikinci sunucudan herhangi bir şey kaydedilmeden önce fırlatılan bir `MCPError`'dır. Bir ad
    grubun **tamamında** benzersiz olmalıdır ve sizin denetiminizde olmayan iki sunucu eninde sonunda çakışır.

## `component_name_hook` {#component_name_hook}

Bunu sunucularda değil, grupta düzeltirsiniz. `(name, server_info)` alan bir fonksiyon geçirin; grup, kaydettiği her ad üzerinde onu çalıştırır:

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

Yeniden çalıştırın. `print(sorted(group.tools))` artık ikisini de gösterir:

```text
['Library.search', 'Web.search']
```

* **Anahtar** sizindir. `by_server` onu `server_info.name`'den, yani her `MCPServer(...)`'ın oluşturulduğu addan üretti.
* İçindeki `Tool`'a dokunulmaz: `group.tools["Web.search"].name` hâlâ `"search"`'tür ve `call_tool`'un ağ üzerinde gönderdiği ad budur. Önek hiçbir zaman sürecinizin dışına çıkmaz.
* Bu yalnızca araçlarla sınırlı değil. Kütüphanenin `hours` kaynağı `Library.hours` olarak kaydedilir.

!!! tip
    Kanca yalnızca çakışmalarda değil, **her** sunucudan gelen **her** ad üzerinde çalışır: yalnızca
    çakışmada önek ekleyen bir kip yoktur. Bir şema seçin ve her yerde uygulanmasına izin verin.

## Sunucu ekleme ve kaldırma {#adding-and-removing-servers}

`connect_to_server`, açtığı `ClientSession`'ı döndürür. O sunucuyu bir gün kaldırmak isterseniz bunu saklayın: `await group.disconnect_from_server(session)` sunucunun araçlarını, kaynaklarını ve prompt'larını gruptan kaldırır.

Elinizde zaten bağlı bir `ClientSession` varsa (`Client.session` bunlardan biridir), yeni bir aktarım açmak yerine onu `await group.connect_with_session(server_info, session)`'a verin. Aynı şekilde birleştirilir. Grup, kendisinin açmadığı bir oturumu hiçbir zaman kapatmaz. `server_info`, bileşen önekleri için sunucuya ad verir; 2026 neslinden bir bağlantıda `client.server_info` `None` olabilir (kimlik isteğe bağlıdır), bu durumda kendi `Implementation(name=..., version=...)`'ınızı geçirin.

## Klasik el sıkışma {#the-classic-handshake}

`ClientSessionGroup`, `Client` üzerine değil `ClientSession` üzerine kuruludur. Her `connect_to_server` klasik `initialize` el sıkışmasını yürütür. **[Protokol sürümleri](../protocol-versions.md)** sayfasında anlatılan `server/discover` yoklamasını hiçbir zaman göndermez. Her MCP sunucusu bu el sıkışmayı anlar; bu yüzden uyumluluk açısından hiçbir şey kaybetmezsiniz. Bunun tek anlamı, grubun daha iyisini yapabilecek bir sunucuya giderken daha eski ve daha yavaş yolu izlemesidir.

## Özet {#recap}

* `ClientSessionGroup` birçok sunucu bağlantısını tutar ve bunların araçlarını, kaynaklarını ve prompt'larını birer `dict`'te birleştirir.
* Her sunucu için `connect_to_server(params)`. Aktarım parametreleri alır; bir `Client`'ın aldığı sunucu nesnesini ya da URL'yi asla almaz.
* `group.call_tool(name, arguments)` çağrıyı sizin yerinize sahibi olan sunucuya yönlendirir.
* Adlar grubun tamamında benzersiz olmalıdır; `search` aracı olan iki sunucu kendi hâllerine bırakılırsa bir arada bulunamaz.
* `component_name_hook=` kaydedilen her adı yeniden yazar. Sözlük anahtarı değişir, ağ üzerindeki ad değişmez.
* `connect_with_session` elinizde zaten olan bir oturumu ekler; `disconnect_from_server` bir oturumu kaldırır.

Bir grubun konuştuğu el sıkışma (ve bir `Client`'ın tercih ettiği daha hızlı olanı), **[Protokol sürümleri](../protocol-versions.md)** sayfasının konusudur.
