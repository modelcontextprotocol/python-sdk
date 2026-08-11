---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Installation {#installation}

Python SDK PyPI पर [`mcp`](https://pypi.org/project/mcp/) नाम से उपलब्ध है। इसके लिए **Python 3.10+** ज़रूरी है।

ये docs **v2** का वर्णन करते हैं, जो मौजूदा stable release line है:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "v1 से आ रहे हैं?"
    v2 एक major version है जिसमें breaking changes हैं; **[Migration Guide](../migration.md)**
    में हर एक बदलाव की जानकारी है। अगर आपका **package** `mcp` पर निर्भर है और अभी migrate करने के लिए
    तैयार नहीं है, तो `<2` की upper bound रखें (उदाहरण के लिए `mcp>=1.28,<2`), ताकि बिना pin किया गया resolve 1.x line पर ही रहे।

## क्या-क्या install होता है {#what-gets-installed}

SDK इस्तेमाल करने के लिए यह सब जानना ज़रूरी नहीं है, लेकिन अगर आप सोच रहे हैं कि हर dependency किस काम की है:

* `mcp-types`: हर protocol type (requests, results, content blocks) अपने अलग package के रूप में, जिसका version SDK के साथ कदम मिलाकर चलता है। जो code `mcp` पर निर्भर है, वह इसे `mcp.types` alias के ज़रिए import करता है (इन docs में हर `from mcp.types import ...`); `mcp_types` को सीधे सिर्फ़ उसी project में import करें जो SDK के बिना `mcp-types` install करता है।
* [`anyio`](https://anyio.readthedocs.io/): async runtime। पूरा SDK anyio के आधार पर लिखा गया है, इसलिए यह `asyncio` या `trio` दोनों में से किसी पर भी चलता है।
* [`pydantic`](https://docs.pydantic.dev/): हर `mcp.types` model इसी पर बना है, साथ ही पूरा schema generation और validation भी।
* [`httpx2`](https://pypi.org/project/httpx2/): Streamable HTTP और SSE **client** transports के पीछे का HTTP client, जिसमें server-sent events का support पहले से मौजूद है।
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/), और [`python-multipart`](https://pypi.org/project/python-multipart/): HTTP **server** transports।
* [`jsonschema`](https://pypi.org/project/jsonschema/): tool के structured output को उसके घोषित output schema के अनुसार validate करता है।
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): authorization के लिए OAuth token संभालना।
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): सिर्फ़ हल्का-सा API, ताकि SDK के tracing middleware की कोई लागत न हो, जब तक आप खुद OpenTelemetry SDK और exporter install न करें।
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) और [`typing-inspection`](https://pypi.org/project/typing-inspection/): Python 3.10 पर आधुनिक typing features।
* [`pywin32`](https://pypi.org/project/pywin32/): सिर्फ़ Windows पर, `stdio` subprocess management के लिए इस्तेमाल होता है।

## Optional extras {#optional-extras}

* `mcp[cli]`, `mcp` command-line tool (`mcp dev`, `mcp run`, `mcp install`) के लिए [`typer`](https://typer.tiangolo.com/) और [`python-dotenv`](https://pypi.org/project/python-dotenv/) जोड़ता है। development के दौरान आपको यह चाहिए होगा; deploy किए गए server में शायद इसकी ज़रूरत न पड़े।
* `mcp[rich]` बेहतर server logs के लिए [`rich`](https://rich.readthedocs.io/) जोड़ता है।
