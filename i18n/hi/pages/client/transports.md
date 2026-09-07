---
translation:
  sections: [9cac816674181eb0, 7c157764133fea1f, 40b4916d82eaf1d4, 10d151f2cc75317f, 3d0832f39b0d7059, 92742ba36533633d, 0aeca6145e7bd302]
  tool: 1
---
# Client transports {#client-transports}

हर `Client` अपने server से एक **transport** के ज़रिए बात करता है: वही चीज़ जो असल में messages ले जाती है।

आप कभी transport को अलग से configure नहीं करते। `Client` सिर्फ़ एक positional argument लेता है और उसके type से transport तय कर लेता है।

हर transport का **server** वाला पक्ष (`mcp.run()` क्या करता है और आप क्या deploy करते हैं) **[अपना server चलाना](../run/index.md)** में है।

## Streamable HTTP {#streamable-http}

URL string पास करें और आपको **Streamable HTTP** मिलता है, वह transport जिसके पीछे आप deploy करते हैं और जिसे सबसे पहले चुनना चाहिए:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

पूरा production client बस इतना ही है। `Client` आपके लिए URL को `streamable_http_client(...)` में लपेट देता है, एक `httpx2.AsyncClient` के ऊपर जो MCP की ज़रूरत के हिसाब से configure किया गया है: connect/write/pool के लिए 30 सेकंड का timeout, और 300 सेकंड का read timeout, क्योंकि server response stream को खुला रख सकता है।

!!! check
    जो `Client` आपने बनाया है वह connected **नहीं** है। बनाने से सिर्फ़ transport चुना जाता है;
    उसे खोलता `async with` है। enter करने से पहले connection तक पहुँचने की कोशिश करें तो SDK साफ़ बता देता है:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    जब आपने `Client("http://...")` लिखा, तब न कुछ resolve हुआ, न fetch, न spawn। वह line मुफ़्त है।

### अपना `httpx2.AsyncClient` लाएँ {#bring-your-own-httpx2asyncclient}

जैसे ही आपको `Authorization` header, cookie, proxy, mTLS या कोई अलग timeout चाहिए, `httpx2.AsyncClient` खुद बनाएँ और उसे `streamable_http_client` को दें:

```python title="client.py" hl_lines="8-13"
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
    हटाता है, सिवाय [redirect handling](#redirects) के। OAuth भी यहीं जुड़ता है:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`। वह पूरा flow **[OAuth clients](oauth-clients.md)** में है।

### Redirects {#redirects}

transport उसी URL से जुड़ता है जो आपने दिया, और सिर्फ़ उसी origin से।

* जो `307`/`308` redirect उसी scheme, host और port पर रहता है, उसे follow किया जाता है, और उसी host पर `http://` → `https://` को भी। आम `/mcp` → `/mcp/` वाला trailing-slash redirect इसी में आ जाता है।
* कहीं और जाने वाला redirect follow **नहीं** किया जाता। call इस error के साथ fail होती है:

    ```text
    MCPError: Redirect to https://other.example.com/mcp not followed; use that URL as the endpoint if it is the intended server
    ```

    अगर वह URL वही server है जो आप चाहते थे, तो उसे अपने config में डालें। अगर नहीं, तो server या उसके आगे लगा कोई proxy गलत configure है।

यह आपके पास किए गए किसी भी `httpx2.AsyncClient` पर लागू होता है: MCP requests के लिए उसकी `follow_redirects` setting नहीं देखी जाती, किसी भी दिशा में। SDK के OAuth providers अपनी requests पर यही नियम लागू करते हैं।

!!! tip
    `Redirect to http://… not followed: it would downgrade this HTTPS endpoint to plain HTTP` का मतलब है कि
    server किसी ऐसे TLS-terminating proxy के पीछे है जिसके बारे में उसे पता नहीं, और वह `http://` redirects जारी कर रहा है।
    इसे server पर ठीक किया जाता है (**[Deploy & scale](../run/deploy.md#behind-a-tls-terminating-proxy)**),
    या ठीक वही `https://…/` URL इस्तेमाल करके जो message सुझाता है।

## stdio {#stdio}

**stdio** server एक subprocess है। client उसे launch करता है, उसके stdin पर JSON-RPC लिखता है और उसके stdout से JSON-RPC पढ़ता है। desktop host आपकी machine पर server इसी तरह चलाता है: host यही code **है**, बस ऊपर एक UI के साथ, और **[असली host से जुड़ें](../get-started/real-host.md)** यही रिश्ता host की तरफ़ से, एक config file के रूप में दिखाता है।

process को `StdioServerParameters` से बताएँ और उसे `Client` को दें:

```python title="client.py" hl_lines="3-7 11"
--8<-- "docs_src/client_transports/tutorial004.py"
```

block में enter करते ही process spawn हो जाता है। बाहर निकलने पर subprocess बंद हो जाता है: stdin बंद, इंतज़ार, और अटका रहे तो kill। आपको उसे खुद कभी साफ़ नहीं करना पड़ता।

child का stderr आपके stderr पर जाता है। उसे कहीं और भेजना हो तो transport खुद `stdio_client` (`mcp` से) के साथ बनाएँ और वही पास करें: `Client(stdio_client(server, errlog=log_file))`।

!!! warning
    child आपका environment inherit **नहीं** करता। उसे एक minimal allow-list मिलती है (POSIX पर `HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` और `USER`) ताकि ऐसे process में कुछ भी संवेदनशील leak न हो जिसे शायद
    आपने लिखा ही न हो।

    जिस server को API key चाहिए, उसे वह वहाँ नहीं मिलेगी। उसे `env=` से explicitly पास करें; वे
    variables allow-list के ऊपर merge हो जाते हैं। ऊपर `BOOKSHOP_API_KEY` यही कर रहा है।

## Memory में {#in-memory}

test में न कुछ deploy करना है, न कुछ launch करना। server object ही पास करें:

```python hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

न कोई subprocess, न कोई port, न wire पर कोई bytes। client और server एक ही process में दो objects हैं, और call फिर भी असली protocol layer से होकर जाती है: `search_books` ठीक वैसे ही list, validate और invoke होता है जैसे HTTP पर होता। **[Testing](../get-started/testing.md)** पूरा pattern इसी के इर्द-गिर्द बनाता है।

यही रूप embedding API का काम भी करता है: जो application खुद server बनाता है, वह बिना network hop के उसके tools call कर सकता है।

## SSE {#sse}

`mcp.client.sse` का `sse_client(url)` वह HTTP transport है जिसकी जगह Streamable HTTP ने ली। जो server अब भी इसे बोलता है, उससे बात करने के लिए इसे उसी तरह wrap करें, `Client(sse_client("http://localhost:8000/sse"))`, और इस पर कुछ नया न बनाएँ।

## `Transport` protocol {#the-transport-protocol}

`Client` के लिए ऊपर की सभी चीज़ें एक ही हैं।

**transport** कोई भी async context manager है जो message streams का `(read, write)` जोड़ा yield करता है: औपचारिक रूप से, `mcp.client` का `Transport` protocol। `Client` अपने argument को type से resolve करता है: `str` `streamable_http_client(url)` बन जाता है, `StdioServerParameters` `stdio_client(params)` बन जाता है, server object in-process जुड़ता है, और बाकी सब कुछ सीधे transport के रूप में enter किया जाता है। यही आख़िरी नियम वजह है कि `stdio_client(...)`, `streamable_http_client(...)` और `sse_client(...)` सब उसी एक slot में बैठते हैं, और यही वजह है कि आप अपना खुद का भी लिख सकते हैं।

## सारांश {#recap}

* `Client("http://.../mcp")` (URL) Streamable HTTP पर जुड़ता है, जो production transport है।
* Headers, auth, proxies और timeouts उस `httpx2.AsyncClient` पर होने चाहिए जो आप `streamable_http_client(url, http_client=...)` को पास करते हैं। कोई `headers=` keyword नहीं है।
* Redirects सिर्फ़ URL के अपने origin के भीतर follow होते हैं (trailing-slash वाला `307`/`308`), और उसी host पर `http`→`https`। बाकी सब `Redirect to … not followed` के साथ fail होता है; final URL configure करें।
* stdio है `Client(StdioServerParameters(...))`। इसे खुद `stdio_client(...)` में सिर्फ़ तब wrap करें जब child का stderr कहीं और भेजना हो।
* subprocess को allow-list वाला environment मिलता है, आपका नहीं; `env=` उसमें जोड़ता है।
* `Client(mcp)` (server object) memory में जुड़ता है। इसे tests में इस्तेमाल करें, या server को उसी application में embed करने के लिए जिसने उसे बनाया।
* transport वह हर चीज़ है जिस पर आप `async with x as (read, write)` कर सकें। जो कुछ server object, URL या `StdioServerParameters` नहीं है, `Client` उसे सीधे उसी protocol को सौंप देता है।
* `Client` बनाने से transport चुना जाता है। `async with` उसे खोलता है।

transport खुल जाने के बाद दोनों पक्षों को protocol version पर सहमत होना होता है। आम तौर पर आपको इस बारे में सोचना ही नहीं पड़ता; जब पड़े, तो **[Protocol versions](../protocol-versions.md)** वह page है।
