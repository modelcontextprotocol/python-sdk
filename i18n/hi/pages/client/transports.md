---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# Client transports {#client-transports}

हर `Client` अपने server से एक **transport** के ज़रिए बात करता है: वही चीज़ जो असल में messages ले जाती है।

आप कभी transport को अलग से configure नहीं करते। `Client` सिर्फ़ एक positional argument लेता है और उसके type से transport तय कर लेता है।

हर transport का **server** वाला पक्ष (`mcp.run()` क्या करता है और आप क्या deploy करते हैं) **[अपना server चलाना](../run/index.md)** में है।

## Memory में {#in-memory}

server object ही पास करें:

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

न कोई subprocess, न कोई port, न wire पर कोई bytes। client और server एक ही process में दो objects हैं, और call फिर भी असली protocol layer से होकर जाती है: `search_books` ठीक वैसे ही list, validate और invoke होता है जैसे HTTP पर होता।

इससे यह एक साथ दो काम करता है:

* **Test harness।** इस documentation का हर उदाहरण इसी तरीके से चलाया जाता है, और **[Testing](../get-started/testing.md)** page पूरा pattern इसी के इर्द-गिर्द बनाता है।
* **Embedding API।** जो application खुद server बनाता है, उसे उसके tools call करने के लिए network hop की ज़रूरत नहीं।

## Streamable HTTP {#streamable-http}

URL string पास करें और आपको **Streamable HTTP** मिलता है, वह transport जिसके पीछे आप deploy करते हैं:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

पूरा production client बस इतना ही है। `Client` आपके लिए URL को `streamable_http_client(...)` में लपेट देता है, एक `httpx2.AsyncClient` के ऊपर जो MCP की ज़रूरत के हिसाब से configure किया गया है: `follow_redirects=True`, connect/write/pool के लिए 30 सेकंड का timeout, और 300 सेकंड का read timeout, क्योंकि server response stream को खुला रख सकता है।

!!! check
    जो `Client` आपने बनाया है वह connected **नहीं** है। बनाने से सिर्फ़ transport चुना जाता है;
    उसे खोलता `async with` है। enter करने से पहले connection तक पहुँचने की कोशिश करें तो SDK साफ़ बता देता है:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    जब आपने `Client("http://...")` लिखा, तब न कुछ resolve हुआ, न fetch, न spawn। वह line मुफ़्त है।

### अपना `httpx2.AsyncClient` लाएँ {#bring-your-own-httpx2asyncclient}

जैसे ही आपको `Authorization` header, cookie, proxy, mTLS या कोई अलग timeout चाहिए, `httpx2.AsyncClient` खुद बनाएँ और उसे `streamable_http_client` को दें:

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

दो बातें ध्यान देने लायक हैं:

* `httpx2.AsyncClient` आपका है, इसलिए उसे enter और exit भी **आप** ही करते हैं। SDK कभी ऐसे client को बंद नहीं करता जो उसने नहीं बनाया।
* `streamable_http_client(url, http_client=...)` एक transport लौटाता है, और `Client(transport)` उसे किसी भी दूसरी चीज़ की तरह स्वीकार करता है।

TLS पर एक बात: `httpx2` certificates को operating system के trust store (
[`truststore`](https://pypi.org/project/truststore/) के ज़रिए) से verify करता है, किसी bundled CA list से नहीं। ऐसे environment में जहाँ
काम का system CA store न हो (कुछ minimal containers), standard `SSL_CERT_FILE`/`SSL_CERT_DIR`
environment variables set करें या अपने `httpx2.AsyncClient` को explicit `verify=ssl_context` पास करें
(पृष्ठभूमि
[`httpx` and `httpx-sse` replaced by `httpx2`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2) में है)।

!!! warning
    `streamable_http_client` पहले `headers=` और `timeout=` सीधे लेता था। अब नहीं लेता:
    इसके parameters सिर्फ़ `url`, `http_client` और `terminate_on_close` हैं। आदत से `headers=`
    लिख दें तो यह मिलता है:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    HTTP से जुड़ी हर चीज़ अब उसी एक `httpx2.AsyncClient` पर रहती है जो आप पास करते हैं।

!!! info
    `httpx2` जाना-पहचाना `httpx` API ही रखता है, इसलिए अगर आप `httpx` जानते हैं तो यहाँ auth,
    proxies, event hooks, retries और connection limits कैसे करने हैं, यह आप पहले से जानते हैं। SDK न ऊपर से कुछ जोड़ता है, न कुछ
    हटाता है। OAuth भी यहीं जुड़ता है:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`। वह पूरा flow **[OAuth clients](oauth-clients.md)** में है।

## stdio {#stdio}

**stdio** server एक subprocess है। client उसे launch करता है, उसके stdin पर JSON-RPC लिखता है और उसके stdout से JSON-RPC पढ़ता है। desktop host आपकी machine पर server इसी तरह चलाता है: host यही code **है**, बस ऊपर एक UI के साथ, और **[असली host से जुड़ें](../get-started/real-host.md)** यही रिश्ता host की तरफ़ से, एक config file के रूप में दिखाता है।

process को `StdioServerParameters` से बताएँ, `stdio_client` से उसे transport में बदलें, और **वही** `Client` को दें:

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` अकेले parameters object को स्वीकार नहीं करता। `StdioServerParameters` configuration है; `stdio_client(server)` वह transport है जो उससे process spawn करना जानता है। हमेशा wrap करें।

`async with` block से बाहर निकलने पर subprocess भी बंद हो जाता है: stdin बंद, इंतज़ार, और अटका रहे तो kill। आपको उसे खुद कभी साफ़ नहीं करना पड़ता।

!!! warning
    child आपका environment inherit **नहीं** करता। उसे एक minimal allow-list मिलती है (POSIX पर `HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` और `USER`) ताकि ऐसे process में कुछ भी संवेदनशील leak न हो जिसे शायद
    आपने लिखा ही न हो।

    जिस server को API key चाहिए, उसे वह वहाँ नहीं मिलेगी। उसे `env=` से explicitly पास करें; वे
    variables allow-list के ऊपर merge हो जाते हैं। ऊपर `BOOKSHOP_API_KEY` यही कर रहा है।

## SSE {#sse}

`mcp.client.sse` का `sse_client(url)` वह HTTP transport है जिसकी जगह Streamable HTTP ने ली। जो server अब भी इसे बोलता है, उससे बात करने के लिए इसे उसी तरह wrap करें, `Client(sse_client("http://localhost:8000/sse"))`, और इस पर कुछ नया न बनाएँ।

## `Transport` protocol {#the-transport-protocol}

`Client` के लिए ऊपर की सभी चीज़ें एक ही हैं।

**transport** कोई भी async context manager है जो message streams का `(read, write)` जोड़ा yield करता है: औपचारिक रूप से, `mcp.client` का `Transport` protocol। `Client` अपने argument को type से resolve करता है: server object in-process जुड़ता है, `str` `streamable_http_client(url)` बन जाता है, और बाकी सब कुछ सीधे transport के रूप में enter किया जाता है। यही आख़िरी नियम वजह है कि `stdio_client(...)`, `streamable_http_client(...)` और `sse_client(...)` सब उसी एक slot में बैठते हैं, और यही वजह है कि आप अपना खुद का भी लिख सकते हैं।

## सारांश {#recap}

* `Client(mcp)` (server object) memory में जुड़ता है। इसे tests और embedding के लिए इस्तेमाल करें।
* `Client("http://.../mcp")` (URL) Streamable HTTP पर जुड़ता है, जो production transport है।
* Headers, auth, proxies और timeouts उस `httpx2.AsyncClient` पर होने चाहिए जो आप `streamable_http_client(url, http_client=...)` को पास करते हैं। कोई `headers=` keyword नहीं है।
* stdio है `Client(stdio_client(StdioServerParameters(...)))`, अकेला parameters object कभी नहीं।
* subprocess को allow-list वाला environment मिलता है, आपका नहीं; `env=` उसमें जोड़ता है।
* transport वह हर चीज़ है जिस पर आप `async with x as (read, write)` कर सकें। जो कुछ server object या URL नहीं है, `Client` उसे सीधे उसी protocol को सौंप देता है।
* `Client` बनाने से transport चुना जाता है। `async with` उसे खोलता है।

transport खुल जाने के बाद दोनों पक्षों को protocol version पर सहमत होना होता है। आम तौर पर आपको इस बारे में सोचना ही नहीं पड़ता; जब पड़े, तो **[Protocol versions](../protocol-versions.md)** वह page है।
