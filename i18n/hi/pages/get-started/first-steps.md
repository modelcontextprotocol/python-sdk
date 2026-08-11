---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# पहले कदम {#first-steps}

**[landing page](../index.md)** तेज़ी से चलता है: server लिखें, उसे चलाएँ, tool call करें।

यह page आराम से चलता है: वे तीनों चीज़ें जो server expose कर सकता है, और रास्ते में हर चीज़ का नाम भी।

## host, client और server {#host-client-and-server}

तीन शब्द जो यहाँ से आगे हर page पर दिखेंगे:

* **host** LLM application है: Claude, कोई IDE, कोई agent runtime। यह वह चीज़ है जिससे user बात करता है।
* **client** host के अंदर रहता है और MCP बोलता है। host जितने servers से जुड़ा है, हर एक के लिए एक client चलाता है।
* **server** वह है जो आप इस SDK से बनाते हैं। यह clients को चीज़ें expose करता है। यह model से सीधे कभी बात नहीं करता।

server आप लिखते हैं। hosts किसी और का product हैं। SDK आपको एक `Client` भी देता है। इससे आप अपने servers test करेंगे, और यह इसी page पर आगे दिखता है।

## तीन primitives {#the-three-primitives}

server ठीक तीन तरह की चीज़ें expose करता है। इन्हें अलग करने वाली बात यह है कि **इन्हें इस्तेमाल करने का फ़ैसला कौन करता है**:

| Primitive     | नियंत्रण किसका   | यह क्या है                                          | उदाहरण                            |
|---------------|-----------------|-----------------------------------------------------|------------------------------------|
| **Tools**     | model           | ऐसा function जिसे model कोई काम करने के लिए call करता है | API call, database write           |
| **Resources** | application     | data जिसे host model के context में load करता है     | किसी file की सामग्री, API response  |
| **Prompts**   | user            | दोबारा इस्तेमाल होने वाला message template जिसे user नाम से चलाता है | slash command, menu entry |

"नियंत्रण किसका" ही इस बँटवारे का पूरा मतलब है। tool इसलिए चलता है क्योंकि **model** ने उसे call करने का फ़ैसला किया। resource इसलिए जुड़ता है क्योंकि **application** ने तय किया कि model को उसकी ज़रूरत है। prompt इसलिए चलता है क्योंकि **user** ने उसे चुना।

!!! info
    अगर आपने web API बनाया है तो ज़्यादातर समझ आपके पास पहले से है: **resource** एक `GET` है
    (data load करता है और कुछ बदलता नहीं) और **tool** एक `POST` है (काम करता है और उसके
    side effects हो सकते हैं)। **prompt** का HTTP में कोई जोड़ीदार नहीं; यह उस saved query के
    ज़्यादा करीब है जिसे user नाम से चलाता है।

## एक server, तीनों चीज़ें {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

तीन सादे functions, तीन decorators। हर decorator ही पूरा registration है:

* `@mcp.tool()` `add` को **tool** बनाता है।
* `@mcp.resource("greeting://{name}")` `greeting` को **resource template** बनाता है: URI में `{name}` function का parameter है।
* `@mcp.prompt()` `summarize` को **prompt** बनाता है। यह जो string लौटाता है, वही user message बन जाती है।

बाकी सब कुछ (नाम, description, argument schema) SDK function से ही पढ़ लेता है: उसका नाम, उसका docstring, उसके type hints। आपने इनमें से कुछ भी अलग से declare नहीं किया।

!!! tip
    SDK के दो हिस्सों के दो import paths हैं: `from mcp import Client` और
    `from mcp.server import MCPServer`। `from mcp import MCPServer` जैसा कुछ नहीं है।

### इसे आज़माएँ {#try-it}

इसे MCP Inspector से चलाएँ:

```console
uv run mcp dev server.py
```

जो URL यह print करता है उसे खोलें। Inspector में हर primitive के लिए एक tab है; उन्हें क्रम से देखें।

**Tools.** एक entry: `add`, जिसका description है *Add two numbers.* form में `a` के लिए एक ज़रूरी integer field है और `b` के लिए एक और। उन्हें भरें, call करें, और result `3` है। Inspector ने वह form `a: int, b: int` से बनाया। बाकी हर client भी यही करता है।

**Resources.** *Resources* सूची खाली है। `greeting` **Resource Templates** के नीचे है, क्योंकि `greeting://{name}` में parameter है: जब तक कोई `name` न दे, सूची में दिखाने के लिए कोई एक resource है ही नहीं। इसे `World` दें और पढ़ें:

```text
Hello, World!
```

**Prompts.** एक entry: `summarize`, एक ही ज़रूरी `text` argument के साथ। कुछ text देकर इसे get करें और आपको एक message मिलता है जिसमें `role: user` है और content के रूप में आपकी render की हुई string। prompt बस इतना ही है: messages बनाने वाला function।

Inspector ने आपका server **stdio** पर चलाया, जो उन transports में से एक है जो MCP server बोल सकता है। अभी आपको कोई चुनना नहीं है; उसके लिए **[अपना server चलाना](../run/index.md)** page है।

## Capabilities {#capabilities}

Inspector में आपने तीन tabs देखे। उसे कैसे पता चला कि तीन हैं?

जब client जुड़ता है, server अपनी **capabilities** declare करता है: requests के कौन-से परिवारों का वह जवाब देगा। client उसी declaration से तय करता है कि माँगे भी तो क्या। आपने यह कभी नहीं लिखा; `MCPServer` आपके लिए इसे declare करता है।

खुद देखें। SDK का `Client` सीधे server object लेता है और उससे **in memory** जुड़ता है (न subprocess, न port):

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

वह dictionary आपके server की declared **capabilities** है। हर जुड़ने वाला client सबसे पहले यही जानता है:

| Capability  | client अब ये call कर सकता है                                |
|-------------|------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                  |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                               |

`MCPServer` तीनों primitives serve करता है, इसलिए तीनों हमेशा declare होती हैं।

ध्यान दें कि क्या नहीं है। `completions` (resource templates और prompts के लिए argument autocomplete) को आपका लिखा handler चाहिए, इस server में वह नहीं है, इसलिए capability मौजूद नहीं है और सलीके वाला client पूछेगा ही नहीं। हर optional चीज़ का यही नियम है: चीज़ register करें और capability आ जाती है; **[Completions](../servers/completions.md)** इसे साबित करता है।

!!! info
    `Client(mcp)` वही in-memory client है जिससे इन docs का हर उदाहरण test होता है, और
    इसी से आप अपने servers test करेंगे। इसे पूरा एक page मिलता है: **[Testing](testing.md)**।

## जो आपने नहीं लिखा {#what-you-did-not-write}

इस page पर पीछे मुड़कर देखें। आपने तीन छोटे Python functions लिखे। आपने ये **नहीं** लिखे:

* JSON Schema। `a: int, b: int` **ही** `add` का schema है।
* request handler। `tools/list`, `resources/read`, `prompts/get`: सब आपके लिए serve होते हैं।
* capability declaration। `MCPServer` ने आपके लिए बना दिया।
* protocol की एक भी line। version negotiation, JSON-RPC framing, capability exchange: यह सब `mcp dev` और `Client(mcp)` के अंदर हुआ, और आपने कभी देखा ही नहीं।

यही अनुपात SDK का पूरा मतलब है।

## सारांश {#recap}

* **host** LLM app है, **client** उसका MCP बोलने वाला हिस्सा है, **server** वह है जो आप बनाते हैं।
* tools पर **model** का नियंत्रण है, resources पर **application** का, prompts पर **user** का।
* हर primitive के लिए एक decorator: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`। नाम, description और schema function से आते हैं।
* `{param}` वाला URI resource **template** बनाता है, जो concrete resources से अलग सूची में दिखता है।
* server की **capabilities** आपके लिए declare हो जाती हैं, और client वही माँगता है जो server declare करता है।
* `Client(mcp)` server object से in memory जुड़ता है: पहले दिन से आपका test harness।

आगे है **[असली host से जुड़ें](real-host.md)**: यही server Claude Desktop या किसी IDE के अंदर, सच में। फिर **[Testing](testing.md)**: एक page, एक in-memory client, और आपको कभी अंदाज़ा नहीं लगाना पड़ेगा कि यह काम करता है या नहीं। उसके बाद हर primitive को अपना page मिलता है, शुरुआत उससे जिसे model चलाता है: **[Tools](../servers/tools.md)**।
