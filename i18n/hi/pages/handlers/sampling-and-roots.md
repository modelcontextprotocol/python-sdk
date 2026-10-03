---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# Sampling और roots {#sampling-and-roots}

handler जुड़े हुए client से दो और चीज़ें माँग सकता है: client के अपने model से एक completion (**sampling**), और client के workspace folders (**roots**)।

दोनों अब भी काम करते हैं, उस हर protocol version पर जो SDK बोलता है। लेकिन इनके इर्द-गिर्द design बनाने से पहले यह warning पढ़ लें:

!!! warning "2026-07-28 specification में deprecated"
    Sampling और roots `2026-07-28` से deprecated हैं ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577))। ये पूरी तरह काम करते रहेंगे और हटाए जाने योग्य होने से पहले कम से कम बारह महीने specification में बने रहेंगे, लेकिन नए implementations को इन पर नहीं बनना चाहिए। सुझाए गए migrations: sampling की जगह सीधे अपने LLM provider की API से integrate करें, और roots की जगह directories को tool parameters, resource URIs या server configuration से दें। SDK भर की सूची **[Deprecated features](../deprecated.md)** में है।

## Sampling: client का model उधार लेना {#sampling-borrow-the-clients-model}

resolver `Sample(...)` लौटाता है और tool को completion मिलता है, उसी dependency तंत्र के ज़रिए जो **[Dependencies](dependencies.md)** में `Elicit` चलाता है:

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` `sampling/createMessage` के parameters को दोहराता है। inject की गई value client का `CreateMessageResult` है; `tools` या `tool_choice` दें तो यह `CreateMessageResultWithTools` बन जाता है।
* client ने `sampling` capability declare की होनी चाहिए (अगर आप `tools` या `tool_choice` देते हैं तो `sampling.tools`)। अगर नहीं की, तो ऐसी request भेजने के बजाय जिसे client संभाल नहीं सकता, call `-32021` protocol error के साथ fail हो जाता है। बिना back-channel वाला 2026 से पहले का session अपने सामान्य no-back-channel error के साथ fail होता है, क्योंकि भेजने के लिए कोई रास्ता ही नहीं है।
* `2026-07-28` पर request multi-round-trip flow के अंदर पहुँचाई जाती है (**[Multi-round-trip requests](multi-round-trip.md)**); `2025-11-25` पर यह client को भेजी गई एक अलग request होती है। code दोनों तरह से वही रहता है, लेकिन multi-round-trip का नियम ध्यान में रखें: request हर retry round में एक जैसी बननी चाहिए, इसलिए इसे सिर्फ़ tool के arguments और दूसरे स्थिर data से ही बनाएँ।
* `include_context` को न छेड़ें: `"none"` के अलावा बाकी values खुद deprecated हैं (SEP-2596) और उन्हें ऐसी capability चाहिए जो लगभग कोई client declare नहीं करता।

## Roots: यह कहाँ जाए? {#roots-where-should-this-go}

Roots वे folders हैं जिन पर, client के अनुसार, server काम कर सकता है। ये जानकारी के लिए दिए गए मार्गदर्शन हैं, access-control का तंत्र नहीं। resolver `ListRoots()` लौटाता है:

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* inject किया गया `ListRootsResult` `Root`s की एक सूची रखता है: एक `file://` URI और एक वैकल्पिक display name।
* शर्त वही है जो sampling के लिए है: declare की गई `roots` capability के बिना, request भेजने के बजाय call `-32021` के साथ fail हो जाता है।

wire के दूसरी तरफ़, client दोनों requests का जवाब उन्हीं callbacks से देता है जो उसके पास पहले से हैं: `sampling_callback` और `list_roots_callback`, जिनकी जानकारी **[Client callbacks](../client/callbacks.md)** में है।

## 2025 पीढ़ी के connections पर {#on-2025-era-connections}

`ctx.session.create_message(...)` और `ctx.session.list_roots()` उस code के लिए अब भी मौजूद हैं जो session को सीधे चलाता है। ये सिर्फ़ वहीं काम करते हैं जहाँ back-channel मौजूद है (2025 पीढ़ी के, non-stateless connections), और इन्हें call करने पर deprecation warning आती है। ऊपर दिए गए resolver markers ही समर्थित तरीका हैं: वे negotiate हुए version के हिसाब से delivery चुनते हैं और कोई warning नहीं देते।

## सारांश {#recap}

* resolver से `Sample(...)` या `ListRoots()` लौटाएँ; tool को `CreateMessageResult` या `ListRootsResult` किसी भी दूसरी dependency की तरह मिलता है।
* client को मेल खाती capability declare करनी होगी, वरना request भेजे जाने के बजाय call `-32021` के साथ fail हो जाता है।
* दोनों features `2026-07-28` पर deprecated हैं: फ़िलहाल पूरी तरह काम करते हैं, पर नए designs के लिए गलत चुनाव हैं। sampling की जगह provider APIs और roots की जगह स्पष्ट parameters को तरजीह दें।

धीमा tool कितना आगे बढ़ा, यह बताना: **[Progress](progress.md)**।
