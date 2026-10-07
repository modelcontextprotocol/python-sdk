---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# İptal {#cancellation}

İstemci bir çağrıdan vazgeçebilir: kullanıcı durdur düğmesine basmıştır ya da zaman aşımı süresi dolmuştur.

Bu olduğunda SDK **işleyicinizi iptal eder**. İşleyicinin beklediği `await` istisna fırlatır, fonksiyon geri sarılır ve döndürdüğü hiçbir şey gönderilmez. Çoğu işleyicinin bu konuda bir şey yapması gerekmez.

İki tür işleyicinin ise gerekir: temizlemesi gereken bir şey olan işleyici ve düz bir `def` olan işleyici.

## `async def` araçta temizlik yapma {#clean-up-in-an-async-def-tool}

Temizliği bir `finally` bloğuna koyun:

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* `finally`, araç nasıl biterse bitsin çalışır: değer döndürmüş, istisna fırlatmış ya da iptal edilmiş olabilir.
* `await` kullanmak zorunda olan temizlik için `shield=True` gerekir. İptal edilmiş bir işleyicide sonraki her `await` de istisna fırlatır; bu yüzden koruma olmadan `release_hold` ilk satırında dururdu.
* Korumalı bir bloğu hiçbir şey iptal edemez, bu yüzden ona bir süre sınırı verin. Burada bu sınır `5` saniye.

!!! tip
    `except` değil, `finally` kullanın. Temizliğiniz bittikten sonra iptalin yukarı doğru ilerlemeye
    devam etmesi gerekir; `finally` buna izin verir.

## Düz `def` araçta erken durma {#stop-early-in-a-plain-def-tool}

Düz bir `def` araç bir iş parçacığında çalışır ve bir iş parçacığını dışarıdan hiçbir şey kesemez. Aracın kendisinin sorması gerekir:

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()`, çağrı sürerken hiçbir şey yapmaz; çağrı iptal edildikten sonra ise istisna fırlatır. Onu iş birimleri arasında çağırın.
* Temizlik burada da bir `finally` bloğuna girer. İş parçacığında hiçbir şey await kullanmaz, bu yüzden korumaya gerek yok.
* Hiç sormayan bir `def` araç sonuna kadar çalışır ve sonucu atılır.

## Geçerli olduğu yerler {#where-it-applies}

Prompt ve kaynak fonksiyonları tam olarak araçlar gibi iptal edilir.

İptal, stdio ve Streamable HTTP üzerinde aynı şekilde çalışır. Bu SDK'nın `Client`'ında vazgeçmek, `call_tool`'u bekleyen görevi iptal etmek ya da `read_timeout_seconds` süresinin dolmasına izin vermek demektir.

!!! warning
    İki Streamable HTTP seçeneği bu haberi işleyicinize ulaştırmaz: `2026-07-28` bağlantısında
    `json_response=True` ve eski nesil bağlantıda `stateless_http=True`. Bu durumlarda işleyici,
    istemci ne yapmış olursa olsun sonuna kadar çalışır.

## Özet {#recap}

* İstemci bir çağrıdan vazgeçtiğinde SDK işleyiciyi iptal eder: araç, prompt ya da kaynak.
* `async def`: temizliği bir `finally` bloğunda yapın, await kullanan temizliği de `anyio.move_on_after(seconds, shield=True)` içine koyun.
* Düz `def`: iş birimleri arasında `anyio.from_thread.check_cancelled()` fonksiyonunu çağırın, yoksa araç sonuna kadar çalışır. Temizlik için düz bir `finally` yeter.
* `json_response=True` (modern bağlantılar) ve `stateless_http=True` (eski nesil bağlantılar) iptali devre dışı bırakır.

İlerleme ve iptal, çalışan bir araç ile onu *çağıran* arasındadır. Aracın *sizin* için, yani sunucuyu işleten kişi için log'a yazdığı satırlar ise ayrı bir kanaldır: **[Log kaydı](logging.md)**.
