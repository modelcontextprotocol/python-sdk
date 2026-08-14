---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Kurulum {#installation}

Python SDK, PyPI'da [`mcp`](https://pypi.org/project/mcp/) adıyla yayımlanır. **Python 3.10+** gerektirir.

Bu belgeler, güncel kararlı sürüm hattı olan **v2**'yi anlatır:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "v1'den mi geliyorsunuz?"
    v2, geriye dönük uyumsuz değişiklikler içeren bir ana sürümdür; **[Geçiş kılavuzu](../migration.md)**
    bunların her birini ele alır. *Paketiniz* `mcp`'ye bağımlıysa ve henüz geçişe hazır değilse,
    sabitlenmemiş bir çözümlemenin 1.x hattında kalması için `<2` üst sınırını koruyun (örneğin `mcp>=1.28,<2`).

## Neler kurulur {#what-gets-installed}

SDK'yı kullanmak için bunların hiçbirini bilmeniz gerekmez. Yine de her bağımlılığın ne işe yaradığını merak ediyorsanız:

* `mcp-types`: tüm protokol türleri (istekler, sonuçlar, içerik blokları), SDK ile birebir aynı sürüm numarasıyla yayımlanan ayrı bir paket olarak gelir. `mcp`'ye bağımlı kod bunu `mcp.types` takma adı üzerinden içe aktarır (bu belgelerdeki her `from mcp.types import ...` satırı böyledir); `mcp_types`'ı doğrudan yalnızca `mcp-types`'ı SDK olmadan kuran bir projede içe aktarın.
* [`anyio`](https://anyio.readthedocs.io/): asenkron çalışma zamanı. SDK'nın tamamı anyio üzerine yazıldığı için hem `asyncio` hem de `trio` üzerinde çalışır.
* [`pydantic`](https://docs.pydantic.dev/): her `mcp.types` modelinin temeli; ayrıca tüm şema üretimi ve doğrulaması.
* [`httpx2`](https://pypi.org/project/httpx2/): Streamable HTTP ve SSE *istemci* aktarımlarının arkasındaki HTTP istemcisi; server-sent events desteği yerleşik olarak gelir.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) ve [`python-multipart`](https://pypi.org/project/python-multipart/): HTTP *sunucu* aktarımları.
* [`jsonschema`](https://pypi.org/project/jsonschema/): bir aracın yapılandırılmış çıktısını, bildirdiği çıktı şemasına göre doğrular.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): yetkilendirme için OAuth token işleme.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): yalnızca hafif API; bu sayede siz bir OpenTelemetry SDK'sı ve dışa aktarıcı kurmadıkça SDK'nın izleme middleware'inin hiçbir maliyeti olmaz.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) ve [`typing-inspection`](https://pypi.org/project/typing-inspection/): Python 3.10'da modern tür özellikleri.
* [`pywin32`](https://pypi.org/project/pywin32/): yalnızca Windows'ta, `stdio` alt süreç yönetimi için kullanılır.

## İsteğe bağlı ekler {#optional-extras}

* `mcp[cli]`, `mcp` komut satırı aracı (`mcp dev`, `mcp run`, `mcp install`) için [`typer`](https://typer.tiangolo.com/) ve [`python-dotenv`](https://pypi.org/project/python-dotenv/) paketlerini ekler. Geliştirme sırasında bunu istersiniz; dağıtılmış bir sunucuda gerekmeyebilir.
* `mcp[rich]`, daha okunaklı sunucu log'ları için [`rich`](https://rich.readthedocs.io/) paketini ekler.
