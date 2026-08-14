---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# Başlarken {#get-started}

MCP'de ya da bu SDK'da yeni misiniz? Buradan başlayın. Bu sayfalar sizi sıfırdan
çalışan, test edilmiş bir sunucuya götürür: [SDK'yı kurun](installation.md),
[ilk sunucunuzu](first-steps.md) yazın, [onu gerçek bir host'a bağlayın](real-host.md) ve
bellek içi bir istemciyle [test edin](testing.md).

## Kodu çalıştırma {#run-the-code}

Kod bloklarının tamamı doğrudan kopyalanıp kullanılabilir: hepsi eksiksiz, çalışan dosyalardır.

Takip etmek için bir bloğu `server.py` dosyasına yapıştırın ve MCP Inspector'da açın:

```console
uv run mcp dev server.py
```

Kodu yazmanız (ya da kopyalamanız), düzenlemeniz ve yerelde çalıştırmanız **ŞİDDETLE önerilir**. Asıl meseleyi kendi editörünüzde kullanırken görürsünüz: ne kadar az kod yazdığınızı, otomatik tamamlamayı, daha hiçbir şeyi çalıştırmadan hataları yakalayan tür denetimlerini.

## Tahmin yürütmeyeceksiniz {#you-will-not-be-guessing}

Bu belgelerdeki her örnek, SDK'nın kendi deposunda [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) altında duran eksiksiz bir dosyadır ve her biri SDK'nın test paketi tarafından **bellek içi bir istemci** aracılığıyla çalıştırılır:

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

Alt süreç yok, port yok, aktarım yok. `Client(mcp)` sunucu nesnesine doğrudan bağlanır.

SDK'daki bir değişiklik bu sayfalardan birindeki örneği bozarsa, sayfadan önce CI kırmızıya döner. Burada okuduğunuz kod, çalışan kodun ta kendisidir.

Bunu [Test etme](testing.md) sayfasında kendiniz de kullanacaksınız; kendi sunucularınızı da böyle test edersiniz.

## Bundan sonra nereye {#where-to-go-next}

Bir sunucuyu çalıştırdıktan sonra bu belgelerin geri kalanı bir kurs değil, bir başvuru kaynağıdır.
Her sayfa kendi başına ayakta durur; bu yüzden doğrudan ihtiyacınız olana atlayın:

* Bir sunucunun ne sunduğu (araçlar, kaynaklar, prompt'lar) **[Sunucular](../servers/index.md)** bölümünde.
* Kaydettiğiniz fonksiyonların içinde nelerin kullanılabildiği **[İşleyicinin içinde](../handlers/index.md)** bölümünde.
* Sunucuyu istemcilerin önüne çıkarma (stdio, HTTP, mevcut FastAPI uygulamanız) **[Sunucunuzu çalıştırma](../run/index.md)** bölümünde.
* Diğer tarafı, yani MCP sunucularını *kullanan* bir uygulamayı oluşturma **[İstemciler](../client/index.md)** bölümünde.
