---
translation:
  sections: [20541a40dbdd5980, 01262a123ad9501d, 429db5b574a2ac08, 56b2d49da412cb28, 6a1717123fe4513c]
  tool: 1
---
# Kullanım dışı özellikler {#deprecated-features}

2026-07-28 spesifikasyonu beş şeyi emekliye ayırıyor. SDK hâlâ hepsini uygular ve artık her biri bir **kullanım dışı bırakma uyarısı** taşır.

Aşağıdaki tablo kullanım dışı bırakılan her özelliği, neden gittiğini ve yerine neyin üzerine inşa etmeniz gerektiğini gösterir.

## Neler kullanım dışı {#what-is-deprecated}

| Kullanım dışı | Neden | Bunun yerine ne yaparsınız |
|---|---|---|
| **Kök dizinler (roots)**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, `Client(...)`'a geçirdiğiniz `list_roots_callback=` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) bu yeteneği emekliye ayırıyor. | Yolları sıradan araç argümanları veya kaynak URI'leri olarak alın ya da bir `InputRequiredResult` içine bir `ListRootsRequest` gömün (bkz. **[Çok turlu istekler (multi-round-trip)](handlers/multi-round-trip.md)**). |
| **Sunucunun başlattığı örnekleme (sampling)**: `ctx.session.create_message()`, `Client(...)`'a geçirdiğiniz `sampling_callback=` | SEP-2577 bu yeteneği emekliye ayırıyor. | `InputRequiredResult` döndürün ve çağrıyı istemcinin yeniden denemesine bırakın (bkz. **[Çok turlu istekler](handlers/multi-round-trip.md)**). |
| **Protokol üzerinden log tutma**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 bu yeteneği emekliye ayırıyor. Protokol içinde yerine geçen bir şey yok. | stderr'e yazan sıradan `import logging` (bkz. **[Log tutma](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | Yalnızca kullanım dışı bırakılmadı, protokolden **kaldırıldı**. 2026-07-28 sürümünde `ping` yöntemi yok. | Hiçbir şey. Yalnızca `mode="legacy"` bağlantısında çalışır. |
| **İstemciden sunucuya ilerleme**: `client.send_progress_notification()` | 2026-07-28 ilerlemeyi yalnızca sunucudan istemciye yönlü yapar. | Gönderecek bir şey yok. İlerlemeyi *sunucunuz* `ctx.report_progress()` ile bildirir (bkz. **[İlerleme](handlers/progress.md)**). |

Bu tablodan üç şey çıkar:

* Kök dizinler, örnekleme ve log tutma bir arada gider. Tek bir öneri, **SEP-2577**, üç yeteneği birden kullanım dışı bırakır.
* Örnekleme ve kök dizinler daha derin bir sorunu paylaşır: bunlar bir **sunucunun** **istemciye** **istek** gönderdiği yerlerdir. 2026-07-28 sürümünün **[Çok turlu istekler](handlers/multi-round-trip.md)** ile değiştirdiği şey tam da bu yöndür. Giden, bağımsız RPC yöntemleridir (`sampling/createMessage`, `roots/list` ve push tarzı `elicitation/create`); `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` yük türleri `InputRequiredResult.input_requests` içine gömülü olarak yaşamaya devam eder ve istemcide aynı callback'lere ulaşır.
* `ping` diğerlerinden ayrılır. Protokol onu kullanım dışı bırakmaz, kaldırır. SDK yöntemi yine de uyarır (mesajı *deprecated* değil *removed* der) ve modern bir bağlantıda çağrıldığında *"Method not found"* yanıtı gelir.

## Kullanım dışı bırakma tavsiye niteliğindedir {#deprecated-is-advisory}

Bugün hiçbir şey bozulmaz.

Yukarıdaki her yöntem, **2025-11-25 veya daha eski** bir sürümle anlaşmış her oturumda çalışmaya devam eder. İstemcide `mode="legacy"` sabitleyin, 2026 öncesi davranışın aynısını elde edersiniz. İletilen veride hiçbir değişiklik yoktur ve yetenek anlaşması aynıdır.

Değişen şey, her biri ilk kez çalıştığında görünür bir uyarı almanızdır:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning`, `DeprecationWarning`'in **değil**, `UserWarning`'in alt sınıfıdır. Bu kasıtlıdır: Python'ın varsayılan filtresi `DeprecationWarning`'i yalnızca doğrudan `__main__` olarak çalıştırılan kodda gösterir; kütüphaneler bir şeyleri böyle kullanım dışı bırakır ve iki yıl boyunca kimse fark etmez. Bu uyarı ise her yerde, `-W` bayrağı olmadan görünür.

!!! warning
    "Tavsiye niteliği" iletilen veriye gelince biter. Örnekleme ve kök dizinler sunucudan
    istemciye giden *isteklerdir* ve 2026-07-28 oturumunda bunları taşıyacak bir kanal yoktur.
    Modern bir bağlantıda bir aracın içinde `ctx.session.create_message()`'ı çağırın: uyarı
    yine tetiklenir, ardından gönderim bir hatayla başarısız olur:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Bu sırayla iki sinyal. `MCPDeprecationWarning`, yöntemi çağırdığınız anda, her
    bağlantıda tetiklenir. Hata ise SDK ardından göndermeyi denediğinde geri dönen şeydir.
    Bu ikisi yalnızca, istemcisi eşleşen callback'i kaydetmiş bir `mode="legacy"`
    bağlantısında uçtan uca çalışır.

## Uyarıyı susturma {#silencing-the-warning}

Yeni kodda susturmayın.

Ancak bakımını yaptığınız ve gerçekten 2026 öncesi istemcilere hizmet veren bir sunucunun sessiz bir log'a sonuna kadar hakkı vardır. Kategoriyi, ilk kullanım dışı çağrı çalışmadan önce filtreleyin:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

API'nin tamamı bu. Yöntem başına bir anahtar yok, zaten istemezsiniz de: tek kategori olmasının anlamı, tek satırın onu susturması ve tek satırın geri getirmesidir.

!!! check
    Filtreyi ters yönde çalıştırın, bedava bir regresyon testi elde edersiniz. pytest
    yapılandırmanızdaki `filterwarnings` ayarına `"error::mcp.MCPDeprecationWarning"`
    ekleyin; kullanım dışı çağrı uyarmak yerine **istisna fırlatır**. Hâlâ `ctx.info()`'yu
    çağıran `old_log` adlı bir araç artık geçmez ve şunu bildirmeye başlar:

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Tek satır pytest yapılandırmasıyla, kullanım dışı bir çağrı bir testi başarısız kılmadan
    kod tabanınıza bir daha asla sızamaz.

## Özet {#recap}

* 2026-07-28 spesifikasyonu **kök dizinleri**, sunucunun başlattığı **örneklemeyi** ve protokol üzerinden **log tutmayı** kullanım dışı bırakır (hepsi [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), **ilerlemeyi** sunucudan istemciye yönle sınırlar ve **`ping`**'i kaldırır.
* Yerine geçenler sütunu sizi ileriye yönlendirir: örnekleme ve kök dizinler için **[Çok turlu istekler](handlers/multi-round-trip.md)**, log tutma için **[Log tutma](handlers/logging.md)**, ilerleme için **[İlerleme](handlers/progress.md)**. `ping` için hiçbir şey gerekmez.
* Kullanım dışı bırakma tavsiye niteliğindedir: iletilen veride değişiklik yok, her şey 2026 öncesi oturumlarda çalışmaya devam eder ve görünür bir `MCPDeprecationWarning` alırsınız (bir `UserWarning`, dolayısıyla varsayılan olarak açık).
* Örnekleme ve kök dizinler ayrıca, 2026-07-28 oturumunda bulunmayan bir geri kanala (back-channel) ihtiyaç duyar. Modern bir bağlantıda önce uyarır, sonra istisna fırlatırlar.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` tüm kategoriyi susturur; pytest'te `"error::mcp.MCPDeprecationWarning"` bunu bir test hatasına dönüştürür.
* Yeni kod bunların hiçbiri üzerine kurulmamalıdır.

Bu belgelerdeki diğer tüm sayfalar güncel API'yi anlatır.
