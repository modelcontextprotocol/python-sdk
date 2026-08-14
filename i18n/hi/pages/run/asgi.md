---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# मौजूदा app में जोड़ना {#add-to-an-existing-app}

`mcp.run("streamable-http")` आपके लिए web server शुरू कर देता है। कभी-कभी आप यह नहीं चाहते: आपका MCP server किसी बड़ी web application का एक हिस्सा है, या आपके पास पहले से ASGI deployment है।

इसके लिए `mcp.streamable_http_app()` एक **Starlette application** लौटाता है।

Starlette app एक ASGI app है, इसलिए जो कुछ भी ASGI host कर सकता है (uvicorn, Hypercorn, कोई दूसरा Starlette, FastAPI), वह आपका MCP server host कर सकता है।

## app {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` एक साधारण ASGI application है। इसे किसी भी ASGI server को सौंप दें:

```console
uvicorn server:app
```

MCP endpoint `/mcp` पर है, इसलिए client `http://127.0.0.1:8000/mcp` से जुड़ता है।

app में दो चीज़ें पहले से मौजूद हैं:

* एक route, `/mcp`: Streamable HTTP endpoint।
* एक **lifespan**, जो `mcp.session_manager` को शुरू करता है, यानी वह object जो हर live session के background काम का मालिक है।

app को अकेले चलाएँ (`uvicorn server:app`) तो आपको दोनों में से किसी के बारे में सोचना नहीं पड़ता।

!!! tip
    `streamable_http_app()` वही keyword arguments लेता है जो `mcp.run("streamable-http", ...)`
    लेता है, बस `port` को छोड़कर: port उसका है जो app को serve करता है। `host` अभी भी स्वीकार
    होता है लेकिन यहाँ कुछ bind नहीं करता; **[Deploy & scale](deploy.md)** बताता है कि वह असल
    में क्या नियंत्रित करता है। खुद options की जानकारी **[अपना server चलाना](index.md)** में है।

`mcp.sse_app()` पुराने पड़ चुके SSE transport के लिए यही करता है।

## सिर्फ़ localhost, जब तक आप कुछ और न कहें {#localhost-only-until-you-say-otherwise}

बिना कुछ configure किए app **सिर्फ़** उन्हीं requests का जवाब देता है जो localhost को भेजी गई हों।
`streamable_http_app()` यह नहीं जान सकता कि उसे किस hostname के पीछे serve किया जाएगा, इसलिए वह
सबसे सुरक्षित allowlist के साथ DNS-rebinding protection चालू कर देता है; आपकी मशीन पर यह बिल्कुल
सही है। असली hostname के पीछे deploy होने पर इसका मतलब है कि **हर request `421 Misdirected Request`
के साथ reject होती है**, जब तक आप `transport_security=` में वह allowlist नहीं देते जो आप असल में
serve करते हैं। आपने जो कुछ बनाया है, उससे पहले पूछा तक नहीं जाता। वह allowlist, और काम करते app
से असली hostname तक के बीच की बाकी हर चीज़, **[Deploy & scale](deploy.md)** में है।

## इसे mount करना {#mounting-it}

जैसे ही MCP server किसी बड़ी application का **हिस्सा** बनता है, आप app को `Mount` के अंदर रखते हैं। और जैसे ही आप ऐसा करते हैं, lifespan आपकी ज़िम्मेदारी बन जाता है:

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` और default `/mcp` path मिलकर endpoint को `/mcp` पर ही रखते हैं। Starlette routes को क्रम से आज़माता है और `Mount("/")` **हर** path से match करता है, इसलिए आपके अपने routes सूची में इससे **पहले** जाते हैं। इसके बाद जो कुछ भी है, वहाँ तक पहुँचा नहीं जा सकता।
* `lifespan` function **host** app के पूरे जीवनकाल के लिए `mcp.session_manager.run()` में प्रवेश करता है। यही वह line है जिसे सब भूल जाते हैं।
* `mcp.session_manager` तभी मौजूद होता है जब `streamable_http_app()` call हो चुका हो। इसीलिए routes module level पर बनते हैं और manager को सिर्फ़ lifespan के अंदर छुआ जाता है।

Starlette का `Host` route इसी तरह काम करता है: path के बजाय hostname से route करने के लिए `Mount("/", ...)` की जगह `Host("mcp.example.com", ...)` रखें। lifespan का नियम नहीं बदलता, और transport-security का भी नहीं। `Host("mcp.example.com", ...)` route को सिर्फ़ वही requests मिलती हैं जो उस hostname को भेजी गई हों, लेकिन transport की अपनी Host allowlist (**[Deploy & scale](deploy.md)**) फिर भी पहले चलती है। उसमें `"mcp.example.com"` न हो तो वह route उनमें से हर एक का जवाब `421` से देता है।

!!! warning "lifespan का मालिक host app है"
    `streamable_http_app()` जो Starlette लौटाता है, उसके lifespan में `session_manager.run()`
    जोड़ देता है, लेकिन **mount की गई sub-application का lifespan कभी नहीं चलता**। app को mount
    करें और वह built-in lifespan dead code बन जाता है। आपके ASGI stack में सबसे ऊपर जो भी app
    है, उसे अपने lifespan में `mcp.session_manager.run()` में प्रवेश करना होगा।

!!! check
    `lifespan=lifespan` वाली line हटाएँ और server शुरू करें। वह शुरू होता है। route resolve
    होता है। फिर `/mcp` पर पहली request इस error के साथ fail होती है:

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    session manager को उसके `run()` के अलावा कुछ शुरू नहीं करता।

## दो servers, एक app {#two-servers-one-app}

हर `MCPServer` अपने session manager के साथ अपना अलग app है। जितने चाहें mount करें; हर manager में उसी एक host lifespan से प्रवेश करें:

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` दोनों managers में प्रवेश करता है; वे साथ शुरू होते हैं और उल्टे क्रम में बंद होते हैं।
* endpoints `/notes/mcp` और `/tasks/mcp` हैं: mount prefix और default path मिलाकर।

## path बदलना {#changing-the-path}

अंत वाला वह `/mcp` ही `streamable_http_path` है। इसे `"/"` पर set करें और mount prefix ही पूरा public path बन जाता है:

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

अब clients `/notes` से जुड़ते हैं, `/notes/mcp` से नहीं।

## browser clients के लिए CORS {#cors-for-browser-clients}

browser-based client को आपसे दो अनुमतियाँ चाहिए: अपने MCP request headers **भेजने** की, और MCP जो header वापस भेजता है उसे **पढ़ने** की। दोनों host app पर CORS configuration हैं, और ऊपर वाली transport-security allowlist का इससे मेल खाना ज़रूरी है:

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` वह आधा हिस्सा है जिसे सब भूल जाते हैं। browser हर MCP request से पहले **preflight** करता है, क्योंकि `Content-Type: application/json` और `Mcp-*` request headers CORS safelist में नहीं हैं, और जिस header की अनुमति preflight नहीं देता, वह ऐसी request है जिसे browser कभी भेजता ही नहीं। (`allow_headers=["*"]` भी काम करता है: Starlette preflight का जवाब उसी से देता है जो उसने माँगा था।)
* `expose_headers=["Mcp-Session-Id"]` पढ़ने वाला आधा हिस्सा है। Streamable HTTP session ID उसी response header में लौटाता है, और जब तक CORS उन्हें नाम से expose न करे, browsers response headers को JavaScript से छिपाते हैं। इसके बिना client अपनी दूसरी request कभी नहीं कर सकता।
* `allow_origins` आपका फ़ैसला है, MCP का नहीं। सटीक रहें, और इसे ऊपर `allowed_origins=` में भी दोहराएँ: CORS browser लागू करता है, लेकिन server `Origin` खुद जाँचता है, और जिस origin पर transport भरोसा नहीं करता उसे साफ़ preflight के बाद भी `403` मिलता है।
* `allow_methods` उन तीन methods की सूची है जो Streamable HTTP इस्तेमाल करता है: messages भेजने के लिए `POST`, server-to-client stream खोलने के लिए `GET`, session खत्म करने के लिए `DELETE`।

## custom routes {#custom-routes}

`@mcp.custom_route()` उसी app पर एक सादा HTTP endpoint register करता है, उन चीज़ों के लिए जो हर deployed service को चाहिए पर जिनका MCP से कोई लेना-देना नहीं: health check, OAuth callback।

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* handler सादा Starlette है: `Request` से `Response` तक का एक `async` function।
* `streamable_http_app()` हर custom route को उठा लेता है। `app.routes` अब `/mcp` और `/health` है।
* `GET /health` का जवाब `{"status": "ok"}` है, जिसमें MCP कहीं नहीं।

!!! warning
    custom routes **कभी authenticate नहीं होते**, तब भी जब बाकी server होता है। यह जानबूझकर
    है: health checks और OAuth callbacks तक किसी token के मौजूद होने से पहले पहुँचा जा सकना
    ज़रूरी है। इनके पीछे कुछ भी निजी न रखें।

## सारांश {#recap}

* `mcp.streamable_http_app()` एक route, `/mcp`, वाला Starlette app लौटाता है। कोई भी ASGI server इसे चला सकता है।
* बिना कुछ configure किए app सिर्फ़ localhost को भेजी गई requests का जवाब देता है, और असली hostname के पीछे वह हर चीज़ को `421` से reject करता है, जब तक आप `transport_security=` में allowlist नहीं देते। यह, और production तक का बाकी रास्ता, **[Deploy & scale](deploy.md)** का विषय है।
* `Mount` (या `Host`) इसे किसी बड़े Starlette या FastAPI app के अंदर रखता है।
* **mount करने से built-in lifespan बंद हो जाता है।** host app के lifespan को `mcp.session_manager.run()` में प्रवेश करना होगा, वरना पहली request fail होती है।
* एक app में कई servers का मतलब है कई mounts और एक lifespan जो हर session manager में प्रवेश करता है।
* `streamable_http_path="/"` endpoint को खुद mount prefix पर ले जाता है।
* browser clients को CORS चाहिए: `Mcp-*` request headers के लिए `allow_headers`, response के लिए `expose_headers=["Mcp-Session-Id"]`।
* `@mcp.custom_route()` `/mcp` के बगल में सादे, बिना authentication वाले HTTP endpoints जोड़ता है।

जब server असली URL पर पहुँच में आ जाए, तो **[Client](../client/index.md)** server object के बजाय उसी URL से उससे जुड़ता है।
