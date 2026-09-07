---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 52d6009a07e770ea, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# İlerleme {#progress}

Otuz saniye süren ve otuz saniye boyunca hiçbir şey söylemeyen bir araç bozuk görünür.

**İlerleme bildirimleri** bunu çözer. Araç ne kadar ilerlediğini bildirir; bununla ne çizeceğine istemci karar verir: bir çubuk, dönen bir simge, bir log satırı.

## Araçtan bildirme {#report-it-from-the-tool}

Bir **`Context`** parametresi alın ve `report_progress`'i çağırın:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

Üç argüman var ve ne anlama geldiklerine siz karar verirsiniz:

* `progress`: ne kadar ilerlediğiniz. Spesifikasyon bunun her bildirimde **artmasını** şart koşar; asla bir değeri tekrarlamayın veya geriye gitmeyin.
* `total`: biliyorsanız, toplamda ne kadar iş olduğu. İsteğe bağlı.
* `message`: *bu* adım hakkında insanların okuyabileceği tek bir satır. İsteğe bağlı.

`ctx` tür ipucu sayesinde enjekte edilir ve model onu asla görmez: `import_catalog`'un girdi şemasında tek bir özellik var, `urls`. **[Context nesnesi](context.md)** sayfası baştan sona bu nesneyi anlatır; ilerleme, onun size sunduklarından biridir.

## İstemciden dinleme {#listen-for-it-from-the-client}

İstemci, `call_tool`'a `progress_callback=` geçirerek **çağrı başına** dahil olur:

```python title="client.py" hl_lines="5 14"
import anyio
from mcp import Client


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

Callback, sunucunun bildirdiklerini olduğu gibi alan `async` bir fonksiyondur: `progress`, `total`, `message`.

!!! info
    `Client`'a ne verirseniz verin `progress_callback` aynı parametredir: buradaki gibi bir URL, bir
    `StdioServerParameters` ya da testteki sunucu nesnesi. Yine de gerçek bir aktarım üzerinde
    zamanlamaya dikkat edin. Her bildirim yanıtın yanında, kendi başına iletilir; bu yüzden yavaş bir
    callback, `call_tool` döndükten sonra hâlâ çalışıyor olabilir. Yalnızca süreç içi test bağlantısı
    callback'i satır içinde çalıştırır ve her bildirimin önce ulaşmasını garanti eder.

### Deneyin {#try-it}

`server.py` dosyasını HTTP üzerinden sunun, ardından istemciyi ikinci bir terminalden çalıştırın:

```console
uv run mcp run server.py --transport streamable-http
```

```console
python client.py
```

```text
Imported https://example.com/a.json (1.0/2.0)
Imported https://example.com/b.json (2.0/2.0)
{'result': 'Imported 2 records.'}
```

Sunucudaki her `await ctx.report_progress(...)`, istemcide sırasıyla bir `show` çağrısına dönüştü. İlerleme sonucun içine paketlenmez. Araç hâlâ çalışırken akar.

!!! warning
    `progress_callback` `Client`'a değil, **çağrıya** aittir. Bunun için bir kurucu argümanı yoktur,
    çünkü farklı çağrılar farklı callback'ler ister: biri bir indirme çubuğunu sürer, sonraki bir
    log satırını.

!!! check
    Şimdi `progress_callback=show` kısmını silin ve yeniden çalıştırın:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    Hata yok, uyarı yok, sonuç aynı. `report_progress`, **çağıran taraf ilerleme istemediğinde hiçbir
    şey yapmaz**; bu yüzden koşulsuz bildirirsiniz ve birinin dinleyip dinlemediğini asla merak etmeniz
    gerekmez.

## Toplamı bilmediğinizde {#when-you-dont-know-the-total}

`total`, paydayı bildiğiniz durumlar içindir. Çoğu zaman bilmezsiniz: bir akışı boşaltıyor, bir imleç üzerinde ilerliyor ya da uzunluk başlığı olmayan bir şey indiriyorsunuzdur.

Belirtmeyin:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

Callback `total=None` alır. İstemci yine de *etkinlik* gösterebilir ("şimdiye kadar 3 tane içe aktarıldı...") ama yüzde gösteremez. Daha güzel bir çubuk için toplam uydurmayın.

!!! tip
    `progress`'in belirli bir şeyi sayması gerekmez. Bayt, satır, sayfa: kullanıcının tanıyacağı
    birimi seçin ve yalnızca tutabileceğiniz bir `total` sözü verin.

## Özet {#recap}

* `Context` alan herhangi bir araçtan `await ctx.report_progress(progress, total=None, message=None)`.
* İstemci `call_tool`'a `progress_callback=` geçirir: çağrı başına, asla `Client` üzerinde değil.
* Callback `async (progress, total, message) -> None` biçimindedir ve araç hâlâ çalışırken tetiklenir.
* Çağrıda callback yoksa `report_progress` hiçbir şey yapmaz. Koşulsuz bildirin.
* Bilmediğinizde `total`'ı vermeyin; callback `None` alır.

İlerleme, çalışan bir aracın *kullanıcıya* gösterdiği şeydir. *Sizin* için, yani sunucuyu işleten kişi için yazdığı log satırları ise ayrı bir kanaldır: **[Log tutma](logging.md)**.
