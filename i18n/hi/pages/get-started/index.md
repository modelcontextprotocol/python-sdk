---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# शुरू करें {#get-started}

MCP में नए हैं, या इस SDK में? यहीं से शुरू करें। ये pages आपको शून्य से एक चालू,
test किए हुए server तक ले जाते हैं: [SDK install करें](installation.md), अपना
[पहला server](first-steps.md) बनाएँ, [उसे असली host से जोड़ें](real-host.md), और
in-memory client से [उसे test करें](testing.md)।

## code चलाएँ {#run-the-code}

सभी code blocks सीधे copy करके इस्तेमाल किए जा सकते हैं: ये पूरी, काम करने वाली files हैं।

साथ-साथ चलने के लिए, किसी block को `server.py` में paste करें और उसे MCP Inspector में खोलें:

```console
uv run mcp dev server.py
```

**पुरज़ोर सलाह** है कि code खुद लिखें (या copy करें), उसमें बदलाव करें और उसे locally चलाएँ। अपने editor में इस्तेमाल करने पर ही असली बात समझ आती है: कितना कम लिखना पड़ता है, autocompletion, और कुछ भी चलाने से पहले गलतियाँ पकड़ लेने वाले type checks।

## आपको अंदाज़ा नहीं लगाना पड़ेगा {#you-will-not-be-guessing}

इन docs का हर उदाहरण SDK की अपनी repository में [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) के नीचे एक पूरी file है, और SDK का test suite हर एक को **in-memory client** के ज़रिए चलाकर परखता है:

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

न subprocess, न port, न transport। `Client(mcp)` सीधे server object से जुड़ता है।

अगर SDK में कोई बदलाव इन pages के किसी उदाहरण को तोड़ता है, तो page से पहले CI लाल हो जाता है। जो code आप यहाँ पढ़ते हैं, वही code चलता है।

[Testing](testing.md) में आप इसे खुद इस्तेमाल करेंगे; अपने servers भी इसी तरह test किए जाते हैं।

## आगे कहाँ जाएँ {#where-to-go-next}

एक बार server चल जाए, तो बाकी docs course नहीं, reference हैं।
हर page अपने आप में पूरा है, इसलिए सीधे वहीं जाएँ जिसकी ज़रूरत है:

* server क्या expose करता है (tools, resources, prompts), यह **[Servers](../servers/index.md)** में है।
* आपके register किए functions के अंदर क्या-क्या उपलब्ध है, यह **[आपके handler के अंदर](../handlers/index.md)** में है।
* इसे clients के सामने लाना (stdio, HTTP, आपका मौजूदा FastAPI app) **[अपना server चलाना](../run/index.md)** में है।
* दूसरा पक्ष बनाना, यानी ऐसा application जो MCP servers **इस्तेमाल करता है**, **[Clients](../client/index.md)** में है।
