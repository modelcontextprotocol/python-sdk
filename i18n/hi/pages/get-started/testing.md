---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Testing {#testing}

Python SDK में `Client` class आती है जिसके साथ **in-memory transport** मिलता है: इसे अपना server object दें और यह उससे सीधे जुड़ जाता है।

कोई subprocess नहीं। कोई port नहीं। कोई transport ही नहीं। यह वही विचार है जो FastAPI के `TestClient` का है।

## Basic usage {#basic-usage}

मान लेते हैं कि आपके पास एक ही tool वाला सीधा-सादा server है:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

नीचे दिया गया test चलाने के लिए दो अतिरिक्त (development) dependencies चाहिए:

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    ये docs मानकर चलते हैं कि आप [`pytest`](https://docs.pytest.org/en/stable/) पहले से जानते हैं।

    नीचे दिया गया test पूरे result object पर एक ही line में assert करने के लिए
    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) का इस्तेमाल करता है। यह test के
    output को उसी `snapshot(...)` literal के रूप में record करता है जो आपको दिख रहा है। अगर आप इसे इस्तेमाल
    नहीं करना चाहते, तो import हटा दें और किसी भी दूसरे test की तरह उन्हीं fields पर assert करें जो आपके
    लिए मायने रखती हैं (`result.content[0].text == "3"`)।

अब test:

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

1. अगर आप `trio` इस्तेमाल कर रहे हैं, तो इसकी जगह `"trio"` लौटाएँ। विस्तार से जानने के लिए [anyio documentation](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) देखें।
2. यह fixture एक जुड़ा हुआ client yield करता है। हर test जो `client` लेता है, उसे उसी server से नया in-memory connection मिलता है।

हो गया! अब आप और scenarios को cover करने के लिए अपने tests बढ़ा सकते हैं।

## `raise_exceptions=True` क्यों? {#why-raise_exceptionstrue}

दो अलग-अलग चीज़ें गड़बड़ हो सकती हैं, और यह flag उनमें से सिर्फ़ एक को छूता है।

**आपके tools** में से किसी के अंदर हुआ exception protocol failure नहीं है। वह `is_error=True` वाला सामान्य result बन जाता है, और model उसका message पढ़ता है। `raise_exceptions` इसमें कुछ नहीं बदलता: इसके साथ या इसके बिना, `call_tool` वही `is_error=True` वाला result लौटाता है। इस पर एक पूरा page है:
**[Errors संभालना](../servers/handling-errors.md)**।

Tool body के **बाहर** की failure अलग है। `Client(mcp)` जो connection देता है, उस पर server इसे client तक पहुँचने से पहले एक सामान्य `"Internal server error"` में sanitise कर देता है। किसी अनपेक्षित crash की बारीकियाँ remote caller तक कभी leak नहीं होनी चाहिए। Test में आप ठीक यही **नहीं** चाहते, और `raise_exceptions=True` यही बदलता है: आपके test को sanitise किया हुआ message नहीं, बल्कि असली message दिखता है।

Tests में इसे चालू रहने दें। Production code में इसका कोई मतलब नहीं है।

## Default रूप से in-process {#in-process-by-default}

!!! note
    `Client(mcp)` in-process जुड़ता है और default रूप से **पीढ़ी-निरपेक्ष** है: यह server को probe करता है और
    सही protocol path चुनता है। अगर आपका test legacy-विशेष semantics (sampling या elicitation push,
    `message_handler`) को परखता है, तो `mode="legacy"` pin करें, और वहाँ `raise_exceptions=True` हटा दें:
    legacy connection पहले से ही कभी sanitise नहीं करता, और यह flag failure को आपके test में नहीं, बल्कि
    server task के अंदर दोबारा raise करता है।

यही एक line वह वजह भी है कि ये docs आपसे वादा कर सकते हैं कि इनके उदाहरण काम करते हैं: हर example file को SDK का अपना test suite चलाकर परखता है, और उनमें से लगभग सभी को ठीक इसी client के ज़रिए। आप वही tool इस्तेमाल कर रहे हैं जो SDK खुद पर इस्तेमाल करता है।

आपके पास एक चलता हुआ, tested server है। इसे किसी असली application (Claude Desktop, कोई IDE) के अंदर रखना **[असली host से जुड़ें](real-host.md)** में है; इसे serve करने का हर दूसरा तरीका **[अपना server चलाना](../run/index.md)** में है।
