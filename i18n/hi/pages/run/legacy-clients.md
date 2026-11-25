---
translation:
  sections: [3d1663c18edc824c, 90956965ae6a1ca1, af9f398a5a8b679a, 5ce83b1f9d88da62, 0d9b5d13fffc94e5, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# legacy clients को serve करना {#serving-legacy-clients}

MCP में protocol की दो पीढ़ियाँ हैं: `initialize`-handshake वाली पीढ़ी, जो spec version `2025-11-25` तक चलती है, और modern पीढ़ी, `2026-07-28`। इस बँटवारे पर अलग से पूरा page **[Protocol versions](../protocol-versions.md)** है।

यह page उस बँटवारे के server वाले पहलू के बारे में है, और जवाब एक वाक्य में आ जाता है: **जो `streamable_http_app()` आप पहले से deploy करते हैं, वही दोनों को serve करता है।**

SDK हर request को उसके `MCP-Protocol-Version` header के हिसाब से route करता है। जिस request में `2026-07-28` लिखा हो, वह modern handler के पास जाती है। जिस request में handshake पीढ़ी का कोई version हो, या कोई header ही न हो (2026 से पहले के client की `initialize` इसी तरह आती है), वह उसी transport के पास जाती है जिसकी उन clients को उम्मीद होती है: `initialize` handshake, sessions, सब कुछ। यह हर request पर होता है, आपके code से पहले, उसी एक app पर।

इसलिए legacy client कोई ऐसी चीज़ नहीं जिसके **लिए** आप कुछ बनाएँ। वह बस उस server **से जुड़ता** है जो आप पहले ही लिख चुके हैं। configure कुछ नहीं करना।

!!! note
    सचमुच कुछ नहीं। न कोई `legacy=` option है, न version allowlist, न किसी पीढ़ी को reject या
    disable करने का कोई तरीका: न `streamable_http_app()` पर, न `run()` पर, न session manager पर।
    दोनों पीढ़ियाँ हमेशा चालू रहती हैं। उस signature में पीढ़ी के हिसाब से switch जैसी सबसे नज़दीकी चीज़
    `stateless_http` है, और इस page का ज़्यादातर हिस्सा उसी के बारे में है।

## एक handler, दोनों पीढ़ियाँ {#one-handler-both-eras}

यह रहा एक tool जिसे user से कुछ पूछना है:

```python title="server.py" hl_lines="21"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` को एक चीज़ चाहिए जो model ने नहीं दी: कितनी copies। tool यह बात `Annotated[..., Resolve(ask_quantity)]` से declare करता है (पूरी जानकारी **[Dependencies](../handlers/dependencies.md)** में है)। `reserve` में कहीं भी न किसी version का नाम है, न capability की जाँच, न कोई branch।

इसे HTTP पर serve करें, और ये रहे दोनों पीढ़ियों के client जो इसे call कर रहे हैं:

```console
uv run mcp run server.py --transport streamable-http
```

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/legacy_clients/tutorial001_client.py"
```

दोनों clients **एक ही समय पर** खुले हैं, उसी चल रहे server पर। `mode="legacy"` `initialize` handshake चलाता है: ठीक वही connection जो 2026 से पहले का client खोलता है। दूसरा client default लेता है और `2026-07-28` पर पहुँचता है। दूसरे terminal से `python client.py` चलाएँ:

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

वही server, वही handler, वही जवाब। पूरा feature बस इतना ही है।

यह **कैसे** हुआ, इस पर थोड़ा रुकना ठीक रहेगा, क्योंकि दोनों clients से वही सवाल दो बिल्कुल अलग wires पर पूछा गया। `2026-07-28` connection में ऐसा कोई channel नहीं जिस पर server request भेज सके, इसलिए `Resolve` ने सवाल tool result के अंदर लौटाया और client ने जवाब के साथ call दोबारा किया (**[Multi-round-trip requests](../handlers/multi-round-trip.md)**)। `2025-11-25` connection में ऐसा कुछ नहीं है; वहाँ `Resolve` ने call के बीच में ही live `elicitation/create` request भेजी और इंतज़ार किया। आपने दोनों में से कुछ नहीं लिखा। `Resolve` connection का negotiated version पढ़ता है और चुनता है; आपकी tool body को दोनों सूरतों में `AcceptedElicitation` ही दिखता है।

!!! tip
    पीढ़ियों के बीच यही portability वह **वजह** है कि `Resolve` ही वह API है जिस पर बनाना चाहिए। इसका पुराना
    भाई `ctx.elicit()` (**[Elicitation](../handlers/elicitation.md)**) हमेशा सिर्फ़ `elicitation/create` भेजता है,
    इसलिए यह सिर्फ़ legacy connection पर ही काम करता है। `2026-07-28` connection पर call fail हो जाता है।
    अगर कोई tool अब भी इसे इस्तेमाल करता है, तो उसका हल वही है जो ऊपर दिखा, version check नहीं।

## legacy session की कीमत क्या है {#what-a-legacy-session-costs-you}

routing मुफ़्त है। session नहीं।

`2026-07-28` connection **sessionless** होता है: हर request अपने आप में पूरी होती है, और modern handler कभी `Mcp-Session-Id` जारी नहीं करता। legacy connection इसका उल्टा है। जैसे ही 2026 से पहले का client `initialize` भेजता है, SDK एक `Mcp-Session-Id` बनाता है, उसे response header में लौटाता है, और उसके पीछे एक live record रखता है ताकि client की बाद की requests उसे ढूँढ सकें: negotiated version, खुले streams, session को चलाने वाला background task।

वह record बस **सादा in-process `dict`** है। कोई distributed session store नहीं है, और न कोई जोड़ने का तरीका।

एक worker पर यह दिखता ही नहीं। दो पर, पूरी समस्या यही है: जो request `Mcp-Session-Id` लेकर आए और ऐसे worker पर पहुँचे जिसने वह ID नहीं बनाई थी, उसे उस dict में कुछ नहीं मिलता, और जवाब `404` (`Session not found`) होता है, tool result नहीं। इसलिए जैसे ही आप एक से ज़्यादा worker चलाते हैं, **legacy clients को sticky routing चाहिए**: session की हर request को उसी process तक पहुँचना होगा जिसने उसे शुरू किया था। modern clients को कभी नहीं; उनके पास कोई session ही नहीं जिससे चिपका जाए। stickiness और एक से ज़्यादा worker चलाने से जुड़ी बाकी सारी बातें **[Deploy और scale](deploy.md)** में हैं।

!!! warning
    `event_store=` हल जैसा दिखता है पर है नहीं। यह **resumability** है (**उसी** session से दोबारा जुड़ रहे
    client को छूटे हुए SSE events फिर से भेजना), session store नहीं। यह कभी किसी session को
    दूसरे process से पहुँच लायक नहीं बनाता।

## session की उम्र और सीमाएँ {#session-lifetime-and-limits}

legacy session हमेशा के लिए नहीं जीता, और एक process अनगिनत sessions नहीं रखता।
इसे दो settings नियंत्रित करती हैं। दोनों `run()`, `streamable_http_app()`
और `Server.streamable_http_app()` पर keyword arguments हैं। modern (`2026-07-28`) connections और `stateless_http=True`
में sessions होते ही नहीं, इसलिए दोनों में से कोई setting उन पर लागू नहीं होती।

| Setting | Default | यह क्या करती है | client को क्या दिखता है | बंद करने के लिए |
|---|---|---|---|---|
| `session_idle_timeout` | `1800` (30 मिनट) | ऐसे session को बंद कर देती है जिसमें इतनी देर से कुछ in flight न रहा हो। | `404 Session not found`। उसे फिर से `initialize` करना पड़ता है। | `None` |
| `max_sessions` | `10_000` | इतने से ज़्यादा होने पर नया session खोलने से मना कर देती है। मौजूदा sessions अछूते रहते हैं और कुछ भी evict नहीं होता। | `503 Too many open sessions`, JSON-RPC code `-32603` के साथ। | `None` |

"in flight" किसे माना जाता है:

* खुला `GET` stream। SDK के clients एक खुला रखते हैं, इसलिए जुड़े हुए client का session कभी
  expire नहीं होता।
* ऐसी request जिसका जवाब अभी दिया जा रहा है। timeout से ज़्यादा देर चलने वाला tool call बीच में
  नहीं रोका जाता, और उलटी गिनती उसके खत्म होने पर ही शुरू होती है।
* और कुछ नहीं। requests के बीच घड़ी चलती रहती है। session पर आई कोई भी request उसे फिर से शुरू कर देती है,
  `ping` भी। एक बार session expire हो जाए, तो उसे कुछ भी वापस नहीं लाता।

जो client अपना session `DELETE` से खत्म करता है, वह उसे तुरंत खाली कर देता है। जिस client की
पहली request मना कर दी गई हो, उसके साथ भी यही होता है।

```python
mcp.run(transport="streamable-http", session_idle_timeout=None, max_sessions=50_000)
```

दोनों घटनाएँ server log में दिखती हैं। expiry `INFO` पर `Session <id> idle timeout` के रूप में दिखती है।
मना किया गया open `WARNING` पर `Refusing to open a new session: <n> sessions are already open` के रूप में।

सीमाएँ हर process की अपनी हैं। चार workers के साथ ऊपरी सीमा `max_sessions` की चार गुना है, और हर
worker अपने sessions खुद expire करता है।

## इकलौता switch: `stateless_http` {#the-one-knob-stateless_http}

अगर stickiness ऐसी कीमत है जो आप चुकाना नहीं चाहते, तो ठीक एक चीज़ है जो आप बदल सकते हैं।

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

यह page के ऊपर वाला server ही है, बस एक keyword ज़्यादा। `stateless_http=True` से legacy हिस्सा इसके बजाय हर request के लिए अलग, अस्थायी session बनाता है: कोई `Mcp-Session-Id` जारी नहीं होती, requests के बीच कुछ याद नहीं रखा जाता, इसलिए कोई भी worker कोई भी request serve कर सकता है और load balancer जो चाहे कर सकता है।

इसके बारे में दो बातें इससे ज़्यादा मायने रखती हैं कि यह करता क्या है।

**यह सिर्फ़ legacy हिस्से को छूता है।** requests version header के हिसाब से `stateless_http` पढ़े जाने से **पहले** route हो जाती हैं, इसलिए modern path इसे कभी देखता ही नहीं। `2026-07-28` connection पहले से sessionless है और दोनों values पर बिल्कुल एक जैसा रहता है।

**उस हिस्से पर इसकी कीमत server से client जाने वाले दोनों channels हैं।** जो session सिर्फ़ एक `POST` तक जीता है, उसके पास न ऐसा stream है जिस पर server request भेज सके, न ऐसा standalone stream जिस पर वह notifications भेज सके। server की तरफ़ से शुरू हुई हर request `NoBackChannelError` raise करती है: `ctx.elicit()`, retire हो चुके sampling और roots calls (**[Deprecated features](../deprecated.md)**), और, हाँ, `Resolve` का किसी **legacy** client से अपना सवाल पूछना भी। notifications को तो error भी नहीं मिलता; वे चुपचाप गिरा दिए जाते हैं।

!!! note
    `json_response=True` वह switch नहीं है, पर **हर** legacy session पर वही कीमत आधी वसूलता है:
    जिस `POST` का जवाब एक JSON body से दिया जाए, उसके पास request-scoped channel के लिए कोई stream
    नहीं होता, इसलिए request के बीच में किया गया `ctx.elicit()` वही `NoBackChannelError` raise करता है और
    request से जुड़े notifications गिरा दिए जाते हैं। session का standalone stream अछूता रहता है: असंबंधित
    notifications अब भी पहुँचते हैं।

!!! check
    जानबूझकर गलत काम करें। `reserve` ठीक वही tool है जिसने अभी दोनों clients को serve किया। इसे
    `stateless_http=True` के साथ deploy करें, वही दो clients जोड़ें, और हर एक से इसे call करें।

    modern client को अब भी `Reserved 2 of 'Dune'.` मिलता है। modern हिस्सा नहीं बदला।

    legacy client का call ऐसे `is_error` result के रूप में वापस नहीं आता जिसे model पढ़ सके।
    पूरी request fail होती है, top-level protocol error के रूप में:

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` ने आपको नहीं बचाया। `2025-11-25` connection पर इसे `elicitation/create` भेजना ही **पड़ता** है,
    और जो channel इसे चाहिए वह ठीक वही चीज़ है जो `stateless_http=True` ने गँवा दी। पीढ़ियों के बीच
    portable code का मतलब back-channel से मुक्त code नहीं है।

तो यह सचमुच का सौदा है, और यह सिर्फ़ legacy हिस्से पर मौजूद है: **session वाला और sticky, या stateless और एकतरफ़ा।** अगर आपके tools कभी client में वापस call नहीं करते, तो `stateless_http=True` मुफ़्त है और आपको इसे ले लेना चाहिए। अगर करते हैं, तो sessions रखें और routing sticky रखें।

## आपका code असल में कहाँ बँटता है {#where-your-code-actually-forks}

लगभग कहीं नहीं।

tools, resources, prompts, structured output, progress, errors: इनमें से किसी को फ़र्क नहीं पड़ता कि किस पीढ़ी ने call किया। `initialize` handshake, `Mcp-Session-Id`, standalone stream, session खत्म करने वाला `DELETE`: यह सब SDK के ज़िम्मे है, और handler को इनमें से कुछ कभी नहीं दिखता। interactive input **वही एक** जगह है जहाँ wire पर पीढ़ियाँ सच में अलग हैं, और `Resolve` इसीलिए है कि यह आपकी समस्या न बने: आपने अभी एक ही tool को दोनों को serve करते देखा।

ठीक एक चीज़ बचती है, और वह है **change notifications**, क्योंकि दोनों पीढ़ियाँ अलग-अलग pipes पर सुनती हैं:

* `2026-07-28` client `subscriptions/listen` stream खोलता है और subscriptions bus पढ़ता है। `ctx.notify_resource_updated()` (और `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`) वहीं publish करते हैं, और **सिर्फ़** वहीं। वह page **[Subscriptions](../handlers/subscriptions.md)** है।
* legacy client वह standalone stream पढ़ता है जो उसका session खुला रखता है। `ctx.session.send_resource_updated()` (और `send_tool_list_changed()` व उसके साथी) उस **connection** पर लिखते हैं जिस पर request आई थी: legacy session के लिए वह उसका standalone stream है। modern connection में इसके लिए कोई जगह नहीं: HTTP पर ऐसा कोई channel है ही नहीं, और stdio पर चारों तरह के change notifications सिर्फ़ `subscriptions/listen` streams पर चलते हैं, इसलिए modern connection पर notification चुपचाप गिरा दिया जाता है।

HTTP पर, दोनों में से कोई call दूसरी पीढ़ी के clients तक नहीं पहुँचता। सबको बताने के लिए, दोनों call करें:

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

दो lines, कोई `if` नहीं, कोई version check नहीं, और काम पूरा। legacy client के होने की वजह से handler जो कुछ अलग करता है, उसकी पूरी सूची बस इतनी ही है।

## सारांश {#recap}

* एक ही `streamable_http_app()` protocol की दोनों पीढ़ियों को serve करता है। SDK हर request को उसके `MCP-Protocol-Version` header के हिसाब से route करता है; configure करने को कुछ नहीं है और पीढ़ी का कोई switch ढूँढने को नहीं है।
* legacy client की कीमत एक session है: in-process `Mcp-Session-Id` record जिसके पीछे कोई distributed store नहीं। एक से ज़्यादा worker का मतलब **sticky routing** है, वरना गलत worker `404 Session not found` जवाब देता है। कई workers वाली पूरी जानकारी **[Deploy और scale](deploy.md)** में है।
* `stateless_http=True` इकलौता switch है, और यह **सिर्फ़ legacy हिस्से पर** असर करता है। यह legacy clients के लिए बेरोक load balancing दिलाता है, पर बदले में उस हिस्से के server से client जाने वाले दोनों channels जाते हैं: server की तरफ़ से शुरू हुई requests `NoBackChannelError` raise करती हैं (client पर top-level error, `is_error` result नहीं), और notifications गिरा दिए जाते हैं।
* `2026-07-28` connection हर हाल में sessionless है। `stateless_http` इसे कभी नहीं छूता।
* आपका handler code पीढ़ी के हिसाब से ठीक एक जगह बँटता है: change notifications। `ctx.notify_*` `subscriptions/listen` clients तक पहुँचता है; `ctx.session.send_*` legacy sessions तक। दोनों call करें।
* बाकी सब कुछ (`Resolve` के ज़रिए user से input माँगना भी) बनावट से ही पीढ़ियों के बीच portable है। modern तरीका एक बार लिखें।
