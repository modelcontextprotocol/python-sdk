---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# Cancellation {#cancellation}

client किसी call को बीच में छोड़ सकता है: user ने stop दबा दिया, या timeout पूरा हो गया।

ऐसा होने पर SDK **आपके handler को cancel कर देता है**। handler जिस `await` पर रुका है वह raise करता है, function unwind हो जाता है, और वह जो कुछ भी लौटाता है उसमें से कुछ नहीं भेजा जाता। ज़्यादातर handlers को इस बारे में कुछ करने की ज़रूरत नहीं होती।

दो तरह के handlers को ज़रूरत होती है: वह handler जिसे कुछ cleanup करना हो, और वह handler जो सादा `def` हो।

## `async def` tool में cleanup करना {#clean-up-in-an-async-def-tool}

cleanup को `finally` में रखें:

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* tool चाहे जैसे खत्म हो, `finally` चलता है: tool ने कुछ लौटाया हो, raise किया हो, या cancel हुआ हो।
* जिस cleanup को `await` करना पड़े, उसे `shield=True` चाहिए। cancel हो चुके handler में आगे का हर `await` भी raise करता है, इसलिए shield के बिना `release_hold` अपनी पहली line पर ही रुक जाता।
* shielded block को कोई cancel नहीं कर सकता, इसलिए उसे समय सीमा दें। यहाँ वह `5` सेकंड है।

!!! tip
    `except` नहीं, `finally` इस्तेमाल करें। cleanup पूरा होने के बाद cancellation को ऊपर की ओर
    बढ़ते रहना होता है, और `finally` उसे बढ़ने देता है।

## सादे `def` tool में जल्दी रुकना {#stop-early-in-a-plain-def-tool}

सादा `def` tool thread में चलता है, और thread को बाहर से कोई interrupt नहीं कर सकता। tool को खुद पूछना पड़ता है:

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* जब तक call चालू है, `anyio.from_thread.check_cancelled()` कुछ नहीं करता, और call cancel हो जाने के बाद raise करता है। इसे काम की इकाइयों के बीच call करें।
* यहाँ भी cleanup `finally` में जाता है। thread में कुछ भी await नहीं करता, इसलिए इसे shield की ज़रूरत नहीं होती।
* जो `def` tool कभी नहीं पूछता, वह अंत तक चलता है, और उसका नतीजा फेंक दिया जाता है।

## यह कहाँ लागू होता है {#where-it-applies}

prompt और resource functions ठीक tools की तरह cancel होते हैं।

stdio और Streamable HTTP दोनों पर यह एक जैसा काम करता है। इस SDK के `Client` में call छोड़ने का मतलब है उस task को cancel करना जो `call_tool` को await कर रहा है, या उसका `read_timeout_seconds` पूरा हो जाने देना।

!!! warning
    Streamable HTTP के दो options यह खबर handler तक नहीं पहुँचने देते: `2026-07-28` connection पर
    `json_response=True`, और legacy connection पर `stateless_http=True`। वहाँ client ने चाहे जो
    किया हो, handler अंत तक चलता है।

## सारांश {#recap}

* जब client किसी call को छोड़ देता है, तो SDK handler को cancel कर देता है: tool, prompt या resource।
* `async def`: cleanup `finally` में करें, और जो cleanup await करता है उसे `anyio.move_on_after(seconds, shield=True)` के अंदर रखें।
* सादा `def`: काम की इकाइयों के बीच `anyio.from_thread.check_cancelled()` call करें, नहीं तो tool अंत तक चलता है। सादा `finally` cleanup कर देता है।
* `json_response=True` (modern connections) और `stateless_http=True` (legacy connections) cancellation को बंद कर देते हैं।

progress और cancellation चलते हुए tool और उसके *caller* के बीच की बात हैं। tool जो lines **आपके** लिए, यानी server चलाने वाले व्यक्ति के लिए, log करता है, वे एक अलग channel हैं: **[Logging](logging.md)**।
