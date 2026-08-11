---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Test etme {#testing}

Python SDK, **bellek içi aktarıma** sahip bir `Client` sınıfıyla gelir: ona sunucu nesnenizi geçirirsiniz, o da doğrudan bağlanır.

Alt süreç yok. Port yok. Hiç aktarım yok. FastAPI'nin `TestClient`'ıyla aynı fikir.

## Temel kullanım {#basic-usage}

Tek bir aracı olan basit bir sunucunuz olduğunu varsayalım:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Aşağıdaki testi çalıştırmak için iki ek (geliştirme) bağımlılığına ihtiyacınız var:

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Bu belgeler [`pytest`](https://docs.pytest.org/en/stable/)'i zaten bildiğinizi varsayar.

    Aşağıdaki test, sonuç nesnesinin tamamını tek satırda doğrulamak için
    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) kullanır. Bir testin
    çıktısını, gördüğünüz `snapshot(...)` değişmezi olarak kaydeder. Kullanmak istemezseniz
    import satırını silin ve herhangi bir testte olduğu gibi ilgilendiğiniz alanları doğrulayın
    (`result.content[0].text == "3"`).

Şimdi test:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. `trio` kullanıyorsanız bunun yerine `"trio"` döndürün. Ayrıntılar için [anyio belgelerine](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) bakın.
2. Fixture, bağlı bir istemci üretir. `client` alan her test, aynı sunucuya yeni bir bellek içi bağlantı alır.

İşte bu kadar! Artık testlerinizi daha fazla senaryoyu kapsayacak şekilde genişletebilirsiniz.

## Neden `raise_exceptions=True`? {#why-raise_exceptionstrue}

İki farklı şey ters gidebilir ve bu bayrak yalnızca birine dokunur.

**Araçlarınızdan** birinin içindeki bir istisna, protokol hatası değildir. `is_error=True` taşıyan
normal bir sonuca dönüşür ve model mesajı okur. `raise_exceptions` bunu değiştirmez: onunla da
onsuz da `call_tool` aynı `is_error=True` sonucunu döndürür. Bu konuda ayrı bir sayfa var:
**[Hataları ele alma](../servers/handling-errors.md)**.

Araç gövdesinin **dışındaki** bir hata ise farklıdır. `Client(mcp)`'nin size verdiği bağlantıda
sunucu, istemci görmeden önce onu genel bir `"Internal server error"` mesajına dönüştürerek
temizler. Beklenmedik bir çökmenin ayrıntılarını uzak bir çağırana asla sızdırmamalısınız. Bir
testte ise tam olarak *istemediğiniz* şey budur ve `raise_exceptions=True`'nun değiştirdiği de
budur: testiniz temizlenmiş mesaj yerine gerçek mesajı görür.

Testlerde açık bırakın. Üretim kodunda bir anlamı yoktur.

## Varsayılan olarak süreç içi {#in-process-by-default}

!!! note
    `Client(mcp)` süreç içinde bağlanır ve varsayılan olarak **nesilden bağımsızdır**: sunucuyu
    yoklar ve uygun protokol yolunu seçer. Testiniz eski nesle özgü anlamları (örnekleme (sampling)
    veya elicitation (kullanıcıdan bilgi isteme) itmesi, `message_handler`) sınıyorsa `mode="legacy"`
    olarak sabitleyin ve orada `raise_exceptions=True`'yu kaldırın: eski nesil bir bağlantı zaten
    hiçbir zaman temizleme yapmaz ve bayrak, hatayı testinizde değil sunucu görevinin içinde
    yeniden fırlatır.

Bu belgelerin, örneklerinin çalıştığı sözünü verebilmesinin nedeni de o tek satırdır: her örnek
dosya SDK'nın kendi test paketinde çalıştırılır, neredeyse hepsi tam olarak bu istemci
üzerinden. SDK'nın kendi üzerinde kullandığı aracın aynısını kullanıyorsunuz.

Çalışan, test edilmiş bir sunucunuz var. Onu gerçek bir uygulamanın (Claude Desktop, bir IDE)
içine koymak **[Gerçek bir host'a bağlanma](real-host.md)** sayfasında; sunmanın diğer tüm
yolları ise **[Sunucunuzu çalıştırma](../run/index.md)** sayfasında.
