---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "यह v2 का documentation है, जो मौजूदा stable release line है"
    v2 पर नए हैं, या v1 से आ रहे हैं? **[v2 में नया क्या है](whats-new.md)** पाँच मिनट में दिखाता है कि क्या बदला, और **[Migration Guide](migration.md)** में हर breaking change शामिल है।
    अभी भी v1.x पर हैं? उसका documentation [v1.x docs](https://py.sdk.modelcontextprotocol.io/v1/) पर है।
    कुछ अटपटा या उलझाने वाला लगा? [हमें बताएँ](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)।

**Model Context Protocol (MCP)** applications को standardized तरीके से LLM को context देने देता है, जिससे context **देने** का काम खुद LLM interaction से अलग रहता है।

यह उसका official Python SDK है। इससे आप:

* **MCP servers बना सकते हैं** जो किसी भी MCP host के लिए tools, resources और prompts expose करते हैं।
* **MCP clients बना सकते हैं** जो किसी भी MCP server से जुड़ते हैं।
* हर standard transport इस्तेमाल कर सकते हैं: stdio, Streamable HTTP और SSE।

## ज़रूरतें {#requirements}

Python 3.10+।

## Installation {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` extra से आपको `mcp` command मिलता है; development के दौरान इसकी ज़रूरत पड़ेगी।
हर dependency किस काम की है, यह [Installation](get-started/installation.md) में देखें।

## उदाहरण {#example}

### इसे बनाएँ {#create-it}

`server.py` नाम की file बनाएँ:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

यह पूरा MCP server है।

यह एक **tool**, `add`, और एक templated **resource**, `greeting://{name}` expose करता है।

### इसे चलाएँ {#run-it}

```console
uv run mcp dev server.py
```

इससे server शुरू होता है और [MCP Inspector](https://github.com/modelcontextprotocol/inspector) खुलता है, जो server को परखने के लिए बना interactive UI है। यह जो URL print करता है, उसे खोलें।

!!! note
    Inspector Node.js app है, इसलिए `mcp dev` को आपके `PATH` पर `npx` चाहिए।

### इसे आज़माएँ {#try-it}

Inspector में **Tools** पर जाएँ और `a=1`, `b=2` के साथ `add` को call करें।

आपको `3` वापस मिलता है। ✨

Inspector ने वह form (`a` के लिए एक ज़रूरी integer field, `b` के लिए एक और) आपके type hints से बनाया। Claude और बाकी हर MCP host भी यही करेगा।

अब **Resources** पर जाएँ और `greeting://World` पढ़ें:

```text
Hello, World!
```

### सारांश {#recap}

एक बार फिर देखें कि आपने क्या **नहीं** लिखा:

* कोई JSON Schema नहीं। `a: int, b: int` ही schema है।
* न request parsing, न serialization, न validation code।
* protocol handling बिल्कुल नहीं।

आपने type hints और docstring वाले दो Python functions लिखे। बाकी सब SDK करता है।

## आगे कहाँ जाएँ {#where-to-go-next}

* **[शुरू करें](get-started/index.md)** आपको install से लेकर चलते हुए, test किए हुए server तक ले जाता है।
* ऐसा application बना रहे हैं जो MCP servers **इस्तेमाल** करता है? **[Clients](client/index.md)** से शुरू करें।
* पहले से FastAPI या Starlette app है? **[मौजूदा app में जोड़ें](run/asgi.md)** उसके अंदर MCP server mount करता है।
* कोई ख़ास error message ढूँढ रहे हैं? **[Troubleshooting](troubleshooting.md)** हूबहू text के हिसाब से व्यवस्थित है।
* सोच रहे हैं कि v2 में क्या बदला? **[v2 में नया क्या है](whats-new.md)** पाँच मिनट में सब दिखा देता है।
* v1 से migrate कर रहे हैं? **[Migration Guide](migration.md)** से शुरू करें।
* कोई ख़ास signature ढूँढ रहे हैं? **[API Reference](api/mcp/index.md)** सीधे source से generate होता है।
* LLM के साथ पढ़ रहे हैं? यह documentation [llms.txt](https://llmstxt.org/) format में भी publish होता है:
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) pages की सूची है, और
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) में हर page एक ही file में है।
