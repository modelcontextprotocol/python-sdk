---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# Subscriptions {#subscriptions}

server का catalog स्थिर नहीं होता। tools runtime पर आते हैं, और किसी resource URI के पीछे का content बदलता रहता है। client को इसकी ख़बर `client.listen(...)` से मिलती है: एक `subscriptions/listen` request, जिसका response ही stream **है**। यह खुला रहता है और वे change notifications लाता है जो client ने माँगे थे।

यह page client वाला सिरा है: stream खोलना, उस पर अपने main flow के साथ-साथ नज़र रखना, और उसके ख़त्म होने को संभालना। बदलाव publish करना, filter करना और method को serve करना server की तरफ़ की कहानी है, जो **आपके handler के अंदर** section के **[Subscriptions](../handlers/subscriptions.md)** page में बताई गई है। यहाँ के उदाहरण वहीं बनाए गए sprint-board server से बात करते हैं।

## stream पर नज़र रखना {#watching-the-stream}

subscription बस एक context manager है। इसमें enter करते ही request भेजी जाती है, जिसमें आपके keyword arguments subscription filter बनते हैं, और server के acknowledgment का इंतज़ार होता है, इसलिए block शुरू होने तक stream live हो चुका होता है।

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

iterate करने पर चार typed events मिलते हैं: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged`, और `ResourceUpdated(uri=...)`।

event यह बताता है कि **क्या** बदला, कभी यह नहीं कि **कैसे**। इसीलिए `follow_board` `read_resource` और `list_tools` को call करता है: event दोबारा fetch करने का इशारा है। कौन-सा resource बदला, यह मान लेने के बजाय `event.uri` पढ़ें: filter में कई URI हो सकते हैं, और server उनमें से किसी एक के sub-resource पर बदलाव की ख़बर दे सकता है।

consume होने का इंतज़ार कर रहे duplicate events मिलकर एक हो जाते हैं, और दोबारा fetch करने पर आपको फिर भी मौजूदा state ही मिलता है। सिर्फ़ एक जैसे events ही मिलते हैं: अलग-अलग URI के दो `ResourceUpdated` दो events हैं।

handle की दो और properties:

* `sub.honored` वह filter है जिसे server ने acknowledge किया: एक `SubscriptionFilter` जिसमें आपके दिए fields हैं, जिन्हें attributes की तरह पढ़ा जाता है (`sub.honored.prompts_list_changed`)। `MCPServer` आपके माँगे हर kind को honor करता है, इसलिए वह आपकी request ज्यों की त्यों वापस लौटा देता है। कम kinds support करने वाला server कम acknowledge करता है, और honor किया गया kind फिर भी शायद कभी fire न हो। server पूरी request को acknowledge करने के बजाय उसे ठुकरा भी सकता है (server page पर [कौन देख सकता है, यह तय करना](../handlers/subscriptions.md#deciding-who-may-watch) देखें), जो request के error के रूप में सामने आता है।
* `sub.subscription_id` listen request की id है, वही जो इस stream के हर frame पर लगी होती है। एक साथ कई subscriptions खुले हो सकते हैं, और हर एक अपनी id से demultiplex होता है।

## बिना block किए नज़र रखना {#watching-without-blocking}

`follow_board` तब तक चलता है जब तक server stream बंद न कर दे, जो शायद कभी न हो, इसलिए अकेले चलाने पर यह आपके पूरे program पर क़ब्ज़ा कर लेता है। असली clients को watcher main flow के **साथ-साथ** चाहिए: agent tools call करता रहे और watcher cache या UI को ताज़ा रखे।

पहले subscription खोलें, फिर watcher शुरू करें और अपने काम में लग जाएँ।

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` पहले उदाहरण से `BOARD` और `read_board` import करता है, जिसे यह repo
    `tutorial003.py` नाम से रखता है। अगर आप rendered files को साथ-साथ `client.py` और `app.py` नाम से save करते हैं,
    तो इसके बजाय `from client import BOARD, read_board` लिखें। नीचे दिया `watch.py` उदाहरण
    भी `read_board` को इसी तरह import करता है।

असली बात क्रम की है। कुछ भी replay नहीं होता, इसलिए stream बनने से पहले publish हुआ event छूट जाता है। `client.listen(...)` में enter करना acknowledgment का इंतज़ार करता है, इसलिए उस पल के बाद का हर बदलाव आपके watcher तक पहुँचता है, और block के अंदर लिया गया snapshot एक भी बदलाव नहीं चूक सकता।

खुले stream के साथ-साथ उसी client पर requests बेरोक चलती हैं, चाहे watcher task से हों या किसी और से। चूँकि consume न हुए **duplicate** events मिलकर एक हो जाते हैं, इसलिए व्यस्त main flow में तीन के बजाय शायद एक ही refetch हो। अलग-अलग events नहीं मिलते: कई URI वाला filter हर URI के लिए एक pending event queue में रखता है।

नज़र रखना बंद करने के लिए block से बाहर निकलें: कोई `unsubscribe` call नहीं है। block वाले task को cancel करने से यह अपने आप हो जाता है, और SDK listen request को उसी तरह cancel करता है जैसा transport चाहता है: Streamable HTTP पर, उस request का stream बंद करके। app के पूरे जीवनकाल तक चलने वाला watcher कभी अपने आप नहीं लौटता, इसलिए shutdown पर उसे, या उसके task group के scope को, cancel करें।

## streams का ख़त्म होना {#streams-end}

stream दो में से किसी एक तरह से ख़त्म होता है, और दोनों साधारण control flow हैं। server का graceful close `async for` को ख़त्म कर देता है; अचानक टूटने पर `SubscriptionLost` raise होता है।

यह फ़र्क़ सिर्फ़ diagnosis के काम का है, आगे क्या करना है उसमें कोई फ़र्क़ नहीं: stream जा चुका है, कुछ replay नहीं हुआ, और जिस watcher को अब भी परवाह है वह दोबारा listen करता है और दोबारा fetch करता है।

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

servers अपने कारणों से streams को gracefully बंद करते हैं, जिनमें ऐसे subscriber को हटाना भी शामिल है जिसका backlog बहुत बड़ा हो गया हो, इसलिए साफ़ अंत नज़र रखना बंद करने का इशारा नहीं है। दोबारा listen करने से पहले back off करें।

`SubscriptionLost` का एक local कारण भी है। client ज़्यादा से ज़्यादा 1024 बिना consume हुए events रखता है, और जो consumer इतना पीछे रह जाए वह बिना सीमा के बढ़ते जाने के बजाय subscription खो देता है। `async for` की body छोटी रखें और धीमा काम कहीं और करें।

`keep_following` सिर्फ़ `SubscriptionLost` को catch करता है। `listen()` में enter करने पर `MCPError` (connection fail हुआ, या server यह method serve नहीं करता), `TimeoutError` (कोई acknowledgment नहीं आया), और `ListenNotSupportedError` (2026 से पहले का connection) भी raise हो सकते हैं। तय करें कि इनमें से किन पर आपका watcher retry करे: आख़िरी वाला कभी ठीक नहीं होता।

## सारांश {#recap}

* `async with client.listen(...)` में enter करें; enter करना acknowledgment का इंतज़ार करता है, इसलिए उसके बाद publish हुआ कुछ भी नहीं छूटता।
* `async for event in sub` से iterate करें। events दोबारा fetch करने के इशारे हैं, payload कभी नहीं।
* subscription खोलें, फिर watcher को task के रूप में चलाएँ, और tool calls उसके साथ-साथ चलते रहते हैं।
* साफ़ अंत loop को रोक देता है; टूटने पर `SubscriptionLost` raise होता है। दोनों ही हालात में: दोबारा listen करें, दोबारा fetch करें, पहले back off करें।
* block से बाहर निकलना ही unsubscribe है।

इन events को publish करना, filter को सीमित करना, और एक process से आगे scale करना server की कहानी है: **[Subscriptions](../handlers/subscriptions.md)**। यही events client-side cache को भी सही बनाए रखते हैं, और अगला page **[Caching](caching.md)** है।
