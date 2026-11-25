---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# Header parameters {#header-parameters}

ज़्यादातर servers को इसकी कभी ज़रूरत नहीं पड़ती।

server के आगे लगा gateway या load balancer सिर्फ़ उसी के आधार पर route कर सकता है जिसे वह body को parse किए बिना पढ़ सके। tool के किसी argument को `x-mcp-header` से mark करें, और `2026-07-28` **[protocol version](../protocol-versions.md)** वाले clients उसकी value HTTP header के रूप में भी भेजते हैं।

## argument को mark करना {#mark-an-argument}

यह mark argument के JSON Schema में बस एक अतिरिक्त key है। `MCPServer` पर `Field` इसे वहाँ रख देता है:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* `2026-07-28` पर Streamable HTTP के ज़रिए client body के साथ `Mcp-Param-Region` भी भेजता है, और जिस call में दोनों मेल नहीं खाते उसे server reject कर देता है।
* जिस client ने tool को list नहीं किया है, उसने mark कभी देखा ही नहीं: वह कोई header नहीं भेजता, और call reject हो जाता है। तब इस SDK का `Client` tools को list करता है और call एक बार दोबारा भेजता है, इसलिए पहले list करने से सिर्फ़ एक round trip बचता है।
* बाकी हर connection इस annotation को अनदेखा करता है।

function में कोई बदलाव नहीं होता: `region` अब भी argument के रूप में ही आता है।

## क्या mark किया जा सकता है {#what-can-be-marked}

`str`, `int` और `bool` arguments। इनके अलावा कुछ भी हो, तो tool register होते समय `InvalidSignature` के साथ मना कर दिया जाता है।

इसमें `str | None` भी शामिल है, जिसका कोई एक type नहीं होता। optional argument के लिए उसका schema साफ़-साफ़ लिखना पड़ता है, Pydantic के `WithJsonSchema` से:

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## low-level `Server` पर {#on-the-low-level-server}

वहाँ `input_schema` आप खुद हाथ से लिखते हैं, इसलिए key सीधे उसी में जाती है:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* यहाँ annotation की जाँच आपके लिए कोई नहीं करता: invalid annotation भी serve हो जाता है, और `2026-07-28` clients उस tool को अपनी listing से बाहर रखते हैं।

### नाम से schemas {#schemas-by-name}

header की जाँच के लिए SDK को call dispatch करने से पहले tool का input schema चाहिए। `get_tool_input_schema` के बिना SDK यह schema हर उस call पर आपका `on_list_tools` handler चलाकर लेता है जिसमें arguments हों, चाहे कोई tool mark किया गया हो या नहीं।

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* यह function pass करें, ताकि जवाब उसी से दिया जा सके जो आपके पास पहले से है।
* जिस tool में जाँचने को कुछ नहीं है, उसके लिए `None` लौटाएँ।

## सारांश {#recap}

* tool argument पर `x-mcp-header` होने से `2026-07-28` clients उसे `Mcp-Param-*` HTTP header के रूप में भी दोहराते हैं।
* जिस call के header और body मेल नहीं खाते, उसे server reject कर देता है।
* सिर्फ़ `str`, `int` और `bool` arguments mark किए जा सकते हैं। बाकी किसी भी चीज़ के लिए `MCPServer` `InvalidSignature` raise करता है।
* low-level `Server` कुछ भी नहीं जाँचता, और जिस tool का annotation invalid हो उसे clients छोड़ देते हैं।
* `get_tool_input_schema` की वजह से low-level `Server` को हर call पर `on_list_tools` नहीं चलाना पड़ता।

हाथ से लिखी जाने वाली `Server` API का बाकी हिस्सा **[low-level Server](low-level-server.md)** में है।
