---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# Subscriptions {#subscriptions}

किसी server का catalog तय नहीं होता। tools runtime पर आ जाते हैं, और resource URI के पीछे का content बदलता रहता है।

client को इसकी खबर **subscriptions** से मिलती है। client एक `subscriptions/listen` request भेजता है, और उस request का response ही stream है: वह खुला रहता है और वही change notifications लाता है जो client ने माँगे थे।

## tool से publish करना {#publish-it-from-the-tool}

आपके हिस्से का काम बस एक line है: बदलाव publish करें।

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` हर उस खुले stream तक पहुँचता है जिसने उस URI को subscribe किया था। और किसी तक नहीं।
* `await ctx.notify_tools_changed()` हर उस stream तक पहुँचता है जिसने tool-list के बदलाव माँगे थे। जिस client को यह मिलता है वह `tools/list` दोबारा call करता है, और अब उसे `sprint_report` दिखता है।
* इसके साथी `notify_prompts_changed()` और `notify_resources_changed()` हैं।
* कोई subscriber नहीं, तो कोई काम नहीं। खाली बैठे server पर publish करना no-op है, इसलिए आपको कभी जाँचना नहीं पड़ता कि कोई सुन रहा है या नहीं। आप बस बताते हैं कि क्या बदला।

`MCPServer` आपके लिए `subscriptions/listen` serve करता है। wire की ज़िम्मेदारियाँ (पहले frame के रूप में acknowledgment, हर stream के हिसाब से filtering, हर frame पर subscription id) SDK संभालता है।

!!! check
    wire पर, जिस stream के filter में `board://sprint` का नाम था वह `complete_task` चलने के बाद ऐसा दिखता है:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    ध्यान दें कि update में क्या **नहीं** है: board। हर frame में `_meta` के नीचे listen request की JSON-RPC id होती है, और वही id subscription id है। इसे client गढ़ता है: Python का `Client` `"listen-1"` जैसी strings इस्तेमाल करता है; दूसरे clients integers इस्तेमाल कर सकते हैं।

## सिर्फ़ वही जो माँगा गया {#only-what-was-asked-for}

filter एक contract है। जिस stream ने tool-list के बदलाव और एक resource URI माँगे थे, उसे यही दो तरह की चीज़ें मिलती हैं और कुछ नहीं। कोई prompt change publish करें, तो वह stream चुप रहता है।

`MCPServer` resource URIs को हूबहू strings के रूप में मिलाता है, इसलिए जिस stream ने `board://sprint` का नाम दिया उसे `board://sprint/tasks/1` के बारे में कुछ सुनाई नहीं देता। spec server को subscribe किए गए URI के किसी sub-resource पर बदलाव बताने देता है; `MCPServer` ऐसा कभी नहीं करता, पर clients इसकी उम्मीद रखने के लिए बने होते हैं।

दो चीज़ें जो stream **नहीं** है:

* **यह replay log नहीं है।** टूटा हुआ stream चला गया, और जब कोई जुड़ा नहीं था तब publish हुए events queue में नहीं रखे जाते। clients दोबारा listen करते हैं और दोबारा fetch करते हैं।
* **यह 2025 वाला रास्ता नहीं है।** जिन clients ने `resources/subscribe` call किया था उन्हें `ctx.session.send_resource_updated(uri)` serve करता है। `notify_*` methods सिर्फ़ `subscriptions/listen` streams तक पहुँचते हैं।

## कौन देख सकता है, यह तय करना {#deciding-who-may-watch}

default रूप से हर माँगा गया kind और URI मान लिया जाता है: कोई भी caller आपके publish किए किसी भी URI को देख सकता है। कोई भी आपके read handler से नहीं पूछता, क्योंकि कोई पढ़ ही नहीं रहा — जिस caller को आपका `files://{name}` handler लौटा देता, वह भी `files://payroll.csv` पर stream खोल सकता है और जान सकता है कि वह बदली, और कब। उसे content कभी नहीं मिलता, और वह यह टटोल नहीं सकता कि क्या मौजूद है, क्योंकि अनजान URI भी मान लिया जाता है और बस कभी fire नहीं होता। खतरा छोटा है पर असली है, इसलिए multi-tenant server से हर user के अलग URIs publish करने से पहले इस पर gate लगाएँ।

यह gate एक middleware है। वह `subscriptions/listen` request को SDK के acknowledge करने से पहले देखता है, और जब caller कुछ ऐसा माँगता है जिसे पढ़ने की उसे इजाज़त नहीं, तो मना कर देता है:

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` कच्ची request है, इसलिए middleware खुद उसे `SubscriptionsListenRequestParams` में validate करता है और वह filter पढ़ता है जो client ने माँगा था।
* मना करने का मतलब `call_next(ctx)` से पहले `MCPError` raise करना है: client को वह error मिलता है और कोई stream नहीं, और connection चलता रहता है। message एक जैसा रखें, किसी URI का नाम न लें, ताकि मना करने से कभी यह पक्का न हो कि कौन से URIs सुरक्षित हैं।
* एक ही `can_access(user, uri)` दोनों सवालों का जवाब देता है। resource handler उससे `resources/read` पर पूछता है; middleware उससे `subscriptions/listen` पर पूछता है। table की जगह database या अपना RBAC system रख दें, और दोनों कदम मिलाकर चलते रहते हैं।
* फ़ैसला stream के पूरे जीवनकाल तक लागू रहता है। हर event पर दोबारा जाँच नहीं होती, इसलिए अगर किसी caller की पहुँच stream के बीच में खत्म हो सकती है (expire होता token), तो जब ऐसा हो तब उस caller का connection बंद कर दें।

middleware का पूरा contract, यह और क्या-क्या wrap करता है और इसे provisional क्यों कहा गया है, यह सब **[Middleware](../advanced/middleware.md)** पर है।

## client वाला सिरा {#the-client-end}

यह रहा उस stream के दूसरी तरफ़ का client, जो board पर नज़र रख रहा है:

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

`client.listen(...)` में दाख़िल होते ही request भेजी जाती है और आपके acknowledgment का इंतज़ार होता है, इसलिए block शुरू होते समय stream चालू होता है, और हर typed event दोबारा fetch करने का इशारा है, payload कभी नहीं। पूरा contract एक ही screen में बस इतना है। client वाले सिरे की बाकी हर बात अपने अलग page पर है: main flow के साथ-साथ नज़र रखना, stream का खत्म होना, और दोबारा listen करना। *Clients* के नीचे **[Subscriptions](../client/subscriptions.md)** देखें।

## एक process से आगे scale करना {#scaling-past-one-process}

publishes आपके handler से खुले streams तक `SubscriptionBus` के ज़रिए पहुँचते हैं। default in-memory है: एक process, उसके अंदर का हर stream। यही सही जवाब है जब तक आप load balancer के पीछे replicas नहीं चलाते, क्योंकि तब client का stream एक replica से बँध जाता है, और किसी दूसरे replica पर हुए publish को उस तक पहुँचना होता है।

यह जोड़ आपको implement करना है: आपके pub/sub backend के ऊपर दो methods।

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` आपका है, और हर replica पर वह reader task भी आपका है जो आने वाले messages को decode करता है और हर registered listener को call करता है। listeners synchronous होते हैं, उन्हें raise करना मना है, और वे server के event loop पर चलते हैं।

bus typed `ServerEvent` values ले जाता है, चार छोटी dataclasses, JSON-RPC कभी नहीं। stamping, filtering, और stream lifecycles SDK में ही रहते हैं, इसलिए bus का कोई implementation protocol नहीं तोड़ सकता। वह सिर्फ़ events को processes के बीच पहुँचा सकता है।

request के बाहर से publish करने के लिए bus खुद बनाएँ ताकि reference आपके पास रहे। जब आप कुछ pass नहीं करते तो `MCPServer` अंदर ही अंदर एक बना लेता है, और उसे बाहर नहीं दिखाता।

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## Low-level composition {#the-low-level-composition}

low-level `Server` पर पहले से कुछ भी जुड़ा हुआ नहीं है, और वही हिस्से तीन lines में जुड़ जाते हैं:

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* bus आपका है, इसलिए आप सीधे उस पर publish करते हैं: `await bus.publish(ResourceUpdated(uri=...))`। उसे वहाँ रखें जहाँ आपके handlers उस तक पहुँच सकें: यहाँ module scope में, बड़े app में lifespan में।
* `ListenHandler(bus)` वही handler है जो `MCPServer` register करता है, और `on_subscriptions_listen=` एक साधारण handler slot है। अलग semantics के लिए उस slot में अपना callable रखें, और spec की ज़िम्मेदारियाँ आप पर आ जाती हैं: पहले acknowledge करें, हर frame पर subscription id की मुहर लगाएँ, filter के बाहर कुछ भी न भेजें।
* `ListenHandler.close()` हर खुले stream को सलीके से खत्म करता है। हर एक को अपने आख़िरी frame के रूप में listen request का result मिलता है, जो spec का यह कहने का तरीका है कि server ने subscription जान-बूझकर खत्म किया। यह उन streams के flush पूरा करने से पहले लौट आता है, इसलिए transport गिराने से पहले उन्हें एक पल दें। इसके बिना, streams तब खत्म होते हैं जब client disconnect करता है।

## सारांश {#recap}

* client एक `subscriptions/listen` request से शामिल होता है, और response ही stream है। इसे serve करना पहले से बना हुआ है।
* आप `ctx.notify_*` से publish करते हैं, और stamping, filtering, और lifecycle का काम SDK करता है।
* events इशारे हैं, payloads नहीं। दोनों सिरे दोबारा fetch करते हैं।
* client वाला सिरा `async with client.listen(...)` है: उसकी कहानी *Clients* के नीचे **[Subscriptions](../client/subscriptions.md)** में है।
* low-level `Server` पर आप वही हिस्से खुद जोड़ते हैं: एक bus, `ListenHandler(bus)`, `on_subscriptions_listen` slot।
* scale out करने का मतलब है `SubscriptionBus` implement करना, बस दो methods, और उसे `MCPServer(subscriptions=...)` के रूप में pass करना।

यह सब serve करने वाले server को चलाना, एक replica के पीछे हो या बीस के, **[Deploy और scale](../run/deploy.md)** में है।
