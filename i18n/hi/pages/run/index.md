---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# अपना server चलाना {#running-your-server}

`mcp.run()` server को शुरू करता है।

आपको सिर्फ़ एक फ़ैसला करना है: **transport** कौन सा हो, यानी server और उसके client के बीच bytes असल में कैसे आएँ-जाएँ।

## Transport चुनना {#pick-a-transport}

| Transport | यह क्या है | कब |
|---|---|---|
| `stdio` | Host आपकी file को subprocess के रूप में launch करता है और उसके stdin और stdout पर बात करता है। | Local servers के लिए। यही default है। |
| `streamable-http` | Port पर सुनने वाला असली HTTP server। | जो कुछ भी आप deploy करें। |
| `sse` | पुराना HTTP transport। | कभी नहीं। |

!!! warning
    2025-03-26 protocol revision में SSE की जगह Streamable HTTP ने ले ली।
    `mcp.run(transport="sse")` अब भी काम करता है, अपने `sse_path=` और `message_path=`
    options के साथ, लेकिन यह सिर्फ़ उन clients के लिए है जो अभी तक नहीं बदले। इस पर कुछ नया न बनाएँ।

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` synchronous है। यह server के पूरे जीवनकाल तक block करता है।
* बिना argument के transport `stdio` होता है।
* यह `if __name__ == "__main__":` के नीचे इसलिए है क्योंकि server को load करने वाली हर चीज़ (`mcp dev`, `mcp run`, `mcp install`, आपके tests) इस file को **import** करती है। यह guard import को चलते हुए server में बदलने से रोकता है।

### stdio {#stdio}

Configure करने को कुछ नहीं है। Host आपकी file को child process के रूप में शुरू करता है, उसके stdin पर requests लिखता है, और उसके stdout से responses पढ़ता है।

इसे खुद चलाएँ और नतीजा दिखेगा:

```console
python server.py
```

कुछ print नहीं होता, और यह लौटता भी नहीं। यह stdin पर इंतज़ार कर रहा है कि कोई host पहले बोले।

इसका मतलब यह भी है कि stdout **ही wire है**। Serve करते समय SDK wire को एक private descriptor पर ले जाता है और जो output stdout पर **flush** होता है (कोई subprocess जो अपने inherited stdout पर लिखता है, flush किया गया `print()`), उसे stderr पर मोड़ देता है, जहाँ वह stream को बिगाड़ नहीं सकता। Serving शुरू होने से **पहले** stdout पर flush हुआ output (कोई wrapper script जो echo करे, import के समय का unbuffered print) अब भी wire पर पहुँचता है, और वैसा `print()` भी जो तब तक buffered रहता है जब तक interpreter exit पर उसे drain नहीं कर देता। जो output आप सच में चाहते हैं, उसके लिए `logging` module सही तरीका है: उसका handler हर record को उसी समय stderr पर flush करता है। वह पूरी जानकारी **[Logging](../handlers/logging.md)** में है।

### इसे आज़माएँ {#try-it}

```console
uv run mcp dev server.py
```

Inspector ठीक वही करता है जो असली host करता है: यह `server.py` को subprocess के रूप में launch करता है और stdio पर उससे जुड़ता है।

आपने इसे कभी port नहीं दिया। कोई port है ही नहीं।

## Streamable HTTP {#streamable-http}

इसी server को port पर रखने के लिए `run()` में transport (और उसके options) का नाम दें:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

वह एक line Starlette app बनाती है और उसे uvicorn से serve करती है। Clients `http://127.0.0.1:3001/mcp` से जुड़ते हैं।

हर transport के अपने keyword arguments हैं, सब `run()` पर:

* `host` / `port`: कहाँ सुनना है। Default `127.0.0.1` और `8000`।
* `streamable_http_path`: MCP endpoint कहाँ रहता है। Default `/mcp`।
* `json_response=True`: हर POST का जवाब SSE stream के बजाय एक अकेली JSON body से देना। उस body में सिर्फ़ response की जगह है, और कुछ नहीं, इसलिए जो tool request के बीच में client को वापस call करता है (`ctx.elicit()`, sampling), वह इस leg पर `NoBackChannelError` raise करता है, और चल रही call से जुड़े notifications (`ctx.report_progress()` का progress, per-call log messages) छोड़ दिए जाते हैं; standalone `GET` stream असंबंधित notifications अब भी ले जाती है।
* `stateless_http=True`: हर request के लिए नया transport, कोई session tracking नहीं।
* `max_request_body_size`: स्वीकार की जाने वाली सबसे बड़ी POST body, bytes में। Default 4 MiB है; इससे बड़ी requests
  को parsing या session बनने से पहले ही HTTP 413 मिलता है। इसे तभी बढ़ाएँ जब जायज़ MCP messages
  उस आकार से बड़े हों।
* `event_store`, `retry_interval`, `transport_security`: resumability और DNS-rebinding से सुरक्षा। ये इंतज़ार कर सकते हैं, जब तक आप localhost के अलावा कहीं deploy न करें; `transport_security` की जानकारी **[Deploy & scale](deploy.md)** में है।

!!! warning
    Transport options `run()` को जाते हैं, `MCPServer(...)` को **नहीं**। Constructor बताता है कि
    आपका server **क्या है**: name, version, instructions. `run()` बताता है कि वह कैसे serve होता है। इसे
    उल्टा करेंगे तो MCP के शामिल होने से पहले ही Python जवाब दे देता है:

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` छोटा रास्ता है। जैसे ही आपको इससे ज़्यादा चाहिए (server किसी मौजूदा app के अंदर mount हो, एक process में दो servers, browser clients के लिए CORS), आप ASGI app खुद बनाते हैं और उसे किसी भी ASGI host को सौंप देते हैं। वह **[मौजूदा app में जोड़ना](asgi.md)** है।

## Server settings {#server-settings}

चलाने से जुड़ी कुछ चीज़ें transport के बारे में नहीं हैं। वे constructor arguments हैं:

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: `MCPServer(...)` बनते ही `logging.basicConfig()` को दे दिया जाता है। यह **root** logger को configure करता है, इसलिए यह सिर्फ़ SDK के नहीं, आपके अपने loggers का level भी तय करता है। Default `"INFO"`।
* `debug`: उस Starlette app को आगे भेजा जाता है जिसे HTTP transports बनाते हैं। Default `False`।

दोनों `mcp.settings` पर पहुँचते हैं, जिसे आप runtime पर पढ़ सकते हैं।

## `mcp` command {#the-mcp-command}

`[cli]` extra इन सबके इर्द-गिर्द एक छोटा command-line tool install करता है।

`mcp dev` आपके server को **MCP Inspector** के नीचे चलाता है:

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` जो environment यह बनाता है उसमें packages जोड़ता है; `--with-editable` उसमें आपका अपना package install करता है। इसे आपके `PATH` पर `npx` चाहिए: Inspector Node.js app है।

`mcp run` file को import करता है, server object ढूँढता है (module-level `mcp`, `server`, या `app`), और उस पर `run()` call करता है:

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

जब object का नाम `mcp`, `server`, या `app` नहीं है, तब `:` suffix उसका नाम बताता है।

आपका `if __name__ == "__main__":` block यहाँ कभी नहीं चलता: `mcp run` खुद `run()` call करता है, और जो अकेला option वह आगे भेजता है वह `--transport` है।

`mcp install` server को **Claude Desktop** में register करता है, ताकि app उसे आपके लिए launch करे:

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` और `-f .env` उस entry में environment variables दर्ज करते हैं। Claude Desktop आपके server को अपने process में शुरू करता है। आपके shell का environment वहाँ नहीं होता।

`mcp install` सिर्फ़ Claude Desktop को host के रूप में जानता है। बाकी हर host (Claude Code, Cursor, VS Code) वही launch command अपनी config file में लेता है, और हर एक की जानकारी **[असली host से जुड़ना](../get-started/real-host.md)** में है।

`mcp version` install किया गया SDK version print करता है।

!!! tip
    `mcp dev` और `mcp run` सिर्फ़ `MCPServer` समझते हैं। अगर आप low-level `Server` से बनाते हैं,
    तो उसे खुद चलाते हैं। देखें **[Low-level Server](../advanced/low-level-server.md)**।

## सारांश {#recap}

* **Transport** वह तरीका है जिससे bytes आपके server तक पहुँचते हैं: local subprocess के लिए `stdio`, port के लिए `streamable-http`। SSE की जगह ले ली गई है।
* `mcp.run()` transport चुनता है। बिना argument के यह `stdio` है, और यह block करता है।
* हर transport option (`host`, `port`, `streamable_http_path`, ...) `run()` का argument है, `MCPServer(...)` का कभी नहीं।
* `run()` को `if __name__ == "__main__":` के नीचे रखें। Server को load करने वाली हर चीज़ पहले file import करती है।
* `log_level=` और `debug=` constructor arguments हैं; वे `mcp.settings` पर पहुँचते हैं।
* Inspector के लिए `mcp dev`, file चलाने के लिए `mcp run`, Claude Desktop के लिए `mcp install`, version के लिए `mcp version`।
* Transport कभी नहीं बदलता कि आपका server **क्या है**: इस page की तीनों files बिल्कुल वही tool expose करती हैं।

जब `run()` खुद सीमा बन जाए (आपका server किसी पहले से मौजूद app के अंदर), तो वह **[मौजूदा app में जोड़ना](asgi.md)** है। असली hostname और एक से ज़्यादा worker **[Deploy & scale](deploy.md)** है। और अगर आपके कुछ clients अब भी spec version 2025-11-25 या उससे पहले पर हैं, तो अच्छी ख़बर **[Legacy clients को serve करना](legacy-clients.md)** में है।
