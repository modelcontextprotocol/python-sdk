---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# Caching hints {#caching-hints}

2026-07-28 protocol पर server `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` और `server/discover` के लिए जो भी result लौटाता है, उसमें दो fields होते हैं: `ttlMs`, यानी client कितने milliseconds तक उस result को fresh मान सकता है, और `cacheScope`, यानी cache किया गया result users के बीच share किया जा सकता है (`"public"`) या किसी एक authorization context का है (`"private"`)।

server खुद कुछ भी cache नहीं करता। ये fields एक **घोषणा** हैं: "यह tool list सबके लिए एक जैसी है और अगले एक मिनट तक नहीं बदलेगी।" इसके बाद client (या आपके आगे लगा कोई gateway) round trip छोड़ सकता है। hints मानना या न मानना client की मर्ज़ी है; उन्हें भेजना server का काम है, और SDK यह आपके लिए कर देता है।

बिना कुछ configure किए हर result `ttlMs: 0, cacheScope: "private"` कहता है: तुरंत stale, कभी share नहीं। यह हमेशा सुरक्षित है और हमेशा spec के अनुरूप। अगर आपकी lists सच में स्थिर हैं और सभी callers के लिए एक जैसी हैं, तो construction के समय ही यह बता दें:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* map की keys **method name** हैं, और सिर्फ़ वही छह cacheable methods वैध keys हैं। parameter का type `Mapping[CacheableMethod, CacheHint]` है, इसलिए editor keys को autocomplete करता है और चलाने से पहले ही typo पकड़ लेता है; जो कुछ type checker से बच निकलता है, वह construction के समय raise होता है।
* जिस method का आप ज़िक्र नहीं करते, उसके defaults बने रहते हैं। map overrides का समूह है, manifest नहीं।
* `CacheHint(ttl_ms=5_000)` ने `scope` को unset छोड़ा, इसलिए वह `"private"` ही रहता है: हर caller के लिए पाँच second की freshness। scope और TTL अलग-अलग फ़ैसले हैं।
* `"server/discover"` भी वैध key है, क्योंकि discovery result किसी भी list की तरह cacheable है।

!!! warning
    `cacheScope: "public"` का मतलब है कि आपका cache किया गया response **किसी को भी** दिया जा
    सकता है। shared gateway बेझिझक एक user का result दूसरे को थमा देगा, भले ही request
    authenticated रही हो। किसी result को `"public"` तभी mark करें जब वह हर caller के लिए एक जैसा
    हो, और `cacheScope` को कभी access control की तरह इस्तेमाल न करें: यह label है, ताला नहीं।

## Per-handler override {#per-handler-override}

low-level `Server` पर handlers अपने results खुद बनाते हैं, और `ttl_ms` / `cache_scope` result models पर बस fields हैं। जो handler इन्हें explicitly set करता है, वह constructor map पर हमेशा भारी पड़ता है, field दर field:

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

handler ने `ttl_ms=1_000` कहा और scope के बारे में कुछ नहीं। wire पर: `ttlMs: 1000` (handler वाला, map का `60_000` नहीं) और `cacheScope: "public"` (map वाला, क्योंकि handler ने इसे unset छोड़ा)। explicit, configured पर भारी पड़ता है, और configured, default पर। यह हर field पर अलग से लागू होता है, इसलिए handler एक field को पक्का कर सकता है और दूसरे को server-wide policy पर छोड़ सकता है।

यही उन dynamic मामलों का रास्ता भी है जिन्हें constructor जान नहीं सकता: जो handler `resources/read` को हर user के हिसाब से filter करता है, वह बाकी तरह से public server में किसी एक URI के लिए `cache_scope="private"` लौटा सकता है।

paginated lists पर एक सावधानी: protocol की माँग है कि एक list के **हर page पर वही `cacheScope`** हो। constructor map यह अपने आप पूरा करता है, क्योंकि उसकी keys method हैं, page नहीं। लेकिन जो handler scope को खुद override करता है, उस consistency की ज़िम्मेदारी उसी की है: इसे **हर** page पर override करें, सिर्फ़ cursor मौजूद होने पर नहीं, वरना पहले page और दूसरे page में मेल नहीं रहेगा।

## client को क्या दिखता है {#what-the-client-sees}

2026-07-28 session पर `Client` आपके लिए hints का पालन करता है: इसमें built-in response cache है, जो default रूप से चालू रहता है। जो result `ttlMs` के साथ आता है, वह store हो जाता है, और उस TTL के भीतर वैसा ही call cache से serve होता है, बिना round trip के। जिस result में **कोई** hint नहीं होता, वह cache नहीं होता: बिना hint वाले results को `CacheConfig.default_ttl_ms` मिलता है, जिसका default `0` है (तुरंत stale), इसलिए जो server कुछ भी declare नहीं करता, उसे ठीक वैसा ही call-दर-call traffic दिखता है जैसा हमेशा दिखता था।

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

चार calls, तीन fetches। दूसरे call को fresh entry मिली और वह server तक पहुँचा ही नहीं; (inject की गई) clock को TTL से आगे बढ़ाने पर तीसरे ने फिर से fetch किया; चौथे ने `cache_mode="refresh"` कहा। यह kwarg पाँचों caching verbs पर मौजूद है (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`):

* `"use"` (default) fresh entry हो तो उसे serve करता है, और न हो तो fetch करके store करता है।
* `"refresh"` कभी serve नहीं करता: यह fetch करता है और result store करता है, जो कुछ cache में था उसे बदलते हुए।
* `"bypass"` cache को छुए बिना round trip करता है: न read, न write।

एक नियम `"use"` से ऊपर है: **`meta` वाले calls हमेशा server तक पहुँचते हैं।** जिस request में `meta` set हो (progress token, tracing fields), उसे wire request की उम्मीद होती है, इसलिए `cache_mode="use"` में उसे `"refresh"` माना जाता है: cache read छोड़ दिया जाता है, और fetch किया गया result फिर भी cache की entry की जगह ले लेता है। `"bypass"` और explicit `"refresh"` हमेशा की तरह ही बर्ताव करते हैं।

caching पूरी तरह बंद करने के लिए `Client(server, cache=None)` से construct करें: हर call फिर से round trip है, और `cache_mode`, भले ही अब भी स्वीकार होता है, कुछ नहीं करता।

scope का पालन भी अपने आप होता है: `"private"` entries cache के *partition* (नीचे देखें) से बँधी होती हैं, जबकि `"public"` वाली चाहें तो ज़्यादा व्यापक sharing चुन सकती हैं। और जिन entries का नाम notifications लेते हैं, ठीक उनके लिए **notifications TTL पर भारी पड़ते हैं**: `list_changed` notification मेल खाती cached listing को evict कर देता है, और `resources/updated` ठीक उसी URI के तहत store किए गए cached read को evict करता है, चाहे वे कितने भी fresh रहे हों। 2026-07-28 connection पर ये notifications `subscriptions/listen` stream पर आते हैं जिसे आप `client.listen(...)` से खोलते हैं, और eviction आपके watcher को event दिखने से पहले पूरा हो जाता है; **[Subscriptions](subscriptions.md)** वही page है।

`resources/updated` पर एक सावधानी: eviction सिर्फ़ exact URI पर होता है। store contract में कोई enumerate या scan operation नहीं है (reference TypeScript implementation की तरह ही), इसलिए *sub*-resource URI वाला notification उसके parent के cached read को evict नहीं करता। अगर आपका server sub-resources का संकेत इसी तरह देता है, तो parent को `cache_mode="refresh"` से फिर fetch करें।

### इसे configure करना: `CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`: entries कहाँ रहती हैं। default हर client के लिए नया in-memory store है; clients या processes के बीच cache share करना हो तो अपना `ResponseCacheStore` implementation (जैसे Redis-backed) pass करें। contract types (`ResponseCacheStore`, `CacheKey`, `CacheEntry`, और default `InMemoryResponseCacheStore`) `mcp.client` से import किए जा सकते हैं। एक lookup एक के बाद एक ज़्यादा से ज़्यादा दो store `get` जारी कर सकता है (पहले private arm, फिर public), इसलिए remote store की latency की उम्मीदें उसी हिसाब से तय करें। custom store के लिए explicit `partition` **ज़रूरी** है।
* `partition`: authorization-context label, जो shared store के भीतर एक principal की `"private"` entries को किसी दूसरे को serve होने से रोकता है।
* `target_id`: explicit server identity, custom transports और in-process servers के लिए (नीचे देखें)।
* `default_ttl_ms`: उन results पर लागू TTL जिनमें `ttlMs` hint नहीं है। default `0` बिना hint वाले results को uncached छोड़ देता है।
* `share_public`: server ने जिन entries को `"public"` बताया, उन्हें partitions के पार serve करना (नीचे देखें)। default रूप से बंद।
* `clock`: wall-clock source, epoch seconds में। ऊपर के उदाहरण की तरह एक inject करें, और expiry tests में sleep की ज़रूरत नहीं रहती।

!!! warning "Partition = verified principal"
    `partition` किसी **verified credential** से निकालें, जैसे validate किए गए token का subject। इसे request में आए data से कभी न निकालें, और server URL से भी कभी नहीं (server identity key की एक अलग axis है)। SDK एक library है जिसका अपना कोई authentication नहीं: trust anchor वही है जो `CacheConfig` construct करता है, यानी deployment, tenant नहीं। multi-tenant gateway हर authenticated principal के लिए एक अलग `CacheConfig` बनाता है।

    partition `Client` के पूरे जीवनकाल के लिए स्थिर भी रहता है। अगर connection का authorization context session के बीच बदलता है (जैसे किसी दूसरे principal के रूप में re-authentication), तो cache उसके साथ नहीं बदलता; नए principal के लिए नया `Client` construct करें।

cache keys में **server की identity** भी होती है: वह URL string जिसे आपने dial किया, जिसमें से `user:pass@` userinfo हटा दी जाती है और बाकी byte-दर-byte वैसी ही रहती है। न case folding, न query reordering, न trailing slash की सफ़ाई। कम normalize करने से सिर्फ़ sharing घटती है, जबकि ज़्यादा normalize करने से दो tenants (`?tenant=a` बनाम `?tenant=b`) आपस में मिल सकते हैं, इसलिए ऊपरी तौर पर अलग URL बस entries share नहीं करते। जब कोई URL नहीं होता (in-process server, या `Transport` instance), तो client को उसकी जगह हर instance के लिए एक random identity मिलती है; server को नाम देने के लिए `CacheConfig.target_id` set करें (custom store के साथ यह ज़रूरी है, और construction यह बता देता है)। identity key material में जाने से पहले sha256-hash की जाती है, इसलिए जिस URL की query string में secrets हों, वह store keys में कभी नहीं दिखता। pre-hash रूप को खुद भी log न करें।

!!! warning "`share_public` server पर भरोसा करता है, पूरे fleet में"
    default रूप से `"public"` entries भी अपने partition के भीतर ही रहती हैं। `share_public=True` उन entries को, जिन्हें server ने `cacheScope: "public"` mark किया, store इस्तेमाल करने वाले **हर** partition को serve करता है, और उन सबकी ओर से server के वर्गीकरण पर भरोसा करता है। जो server per-tenant data पर `"public"` की मुहर लगा देता है (bug से या बदनीयती से), वह फिर एक tenant का response बाकियों को leak कर देता है। यह flag जान-बूझकर सिर्फ़ constructor स्तर पर है: per-call `cache_mode` caching को सीमित कर सकता है, लेकिन per-call कोई भी चीज़ sharing को बढ़ा नहीं सकती।

### cache क्या कभी नहीं करता {#what-the-cache-never-does}

* **Session-tier calls इसे bypass करते हैं।** `client.session.list_tools()` और उसके साथी हमेशा round trip करते हैं; cache `Client` verbs पर रहता है।
* **`server/discover` इससे बाहर रहता है।** discover result एक बार, connect के समय, दिया जाता है और response cache में कभी नहीं जाता, भले ही उसमें `ttlMs` हो। अगर reconnect probe से बचने के लिए आप उसे खुद persist करते हैं ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), तो उसकी freshness का हिसाब आपका है: `DiscoverResult` में ठीक इसी काम के लिए `ttl_ms` और `cache_scope` पहले से parse किए हुए मौजूद हैं।
* **Continuation pages कभी cache नहीं होते।** सिर्फ़ बिना cursor वाले calls हिस्सा लेते हैं। expired cursor के कारण reject हुआ continuation page cached listing को *evict* ज़रूर करता है, क्योंकि listing उसके नीचे बदल गई।
* **Multi-round-trip reads कभी cache नहीं होते।** `input_responses`/`request_state` से seed किया गया `read_resource`, या ऐसा जो input rounds से होकर resolve होता है, कभी cache में नहीं जाता (spec का MUST)।
* **Notification eviction को notifications चाहिए।** eviction उतना ही अच्छा है जितनी transport की delivery, और आधुनिक in-process path (default `mode="auto"` के साथ `Client(server)`) आज standalone notifications deliver नहीं करता।
* **Eviction eventual है, तात्कालिक नहीं।** wire-path notifications spawn किए गए tasks से dispatch होते हैं, इसलिए किसी notification के आने से race कर रहे call को pre-eviction entry एक बार और serve हो सकती है; यह window dispatch latency से सीमित है, और eviction फिर भी हो ही जाता है।
* **कोई stale-if-error नहीं।** expired entry कभी इसलिए serve नहीं होती कि refetch fail हो गया; error आगे propagate होता है।
* **कोई early re-fetch नहीं।** store की गई entry तब तक serve होती है जब तक उसका TTL expire न हो जाए, और उसके बाद का अगला call round trip की कीमत चुकाता है; background में कुछ refresh नहीं होता।
* **कोई coalescing नहीं।** दो concurrent एक जैसे calls दो fetches हैं।
* **24 घंटे से ज़्यादा का TTL नहीं।** इससे बड़ा `ttlMs`, चाहे server ने भेजा हो या configure किया गया हो, store करते समय घटा दिया जाता है (`mcp.client.caching.MAX_TTL_MS`), जिससे यह सीमित रहता है कि कोई भी entry, hint चाहे कितना भी उदार हो, कितनी देर serve हो सकती है।
* **shared store** पर clients आपस में race करते हैं। जब किसी eviction ने चल रहे fetch को पीछे छोड़ दिया हो तो हर client अपना write छोड़ देता है, लेकिन कोई *co-tenant* client अब भी ऐसी entry वापस लिख सकता है जिसे किसी ऐसे eviction ने हटा दिया था जो उसने कभी देखा ही नहीं; और race का यह हिसाब-किताब भी खुद सीमित है: 4096 tracked keys के बाद सबसे पुरानी key का guard सबसे पहले हटता है। दोनों windows स्वीकार्य हैं, और ऊपर बताई गई TTL cap उन्हें बंद कर देती है।
* **protocol की अलग-अलग पीढ़ियों के बीच serve नहीं किया जाता।** entries negotiated protocol version तक सीमित हैं: shared persistent store पर कोई session कभी ऐसी entry serve नहीं करता जो किसी दूसरे negotiated version के तहत लिखी गई हो (वही listing पीढ़ी के हिसाब से सच में अलग होती है, क्योंकि SDK पुराने sessions के लिए 2026 वाले fields हटा देता है)। eviction भी इसी तरह सिर्फ़ मौजूदा पीढ़ी की entries को छूता है; दूसरी पीढ़ी की entries बस TTL से अपने आप पुरानी होकर हट जाती हैं।

### hints खुद पढ़ना {#reading-the-hints-yourself}

hints हर cacheable result पर सादे fields के रूप में भी मौजूद हैं (`result.ttl_ms` और `result.cache_scope`, पहले से parse किए हुए), अगर आप built-in cache के ऊपर (या उसकी जगह) अपना हिसाब-किताब रखना चाहें।

किसी **पुराने server** (pre-2026 protocol) के सामने ये fields wire पर होते ही नहीं, और models अपने conservative defaults दिखाते हैं: `ttl_ms == 0` और `cache_scope == "private"`, stale और unshared, जो कुछ भी declare न करने वाले server के लिए सही मान्यता है। cache legacy session के साथ भी यही करता है: वहाँ hints कभी देखे ही नहीं जाते (wire पर चाहे जो keys आएँ), सिर्फ़ `default_ttl_ms` लागू होता है, और उसका default `0` कुछ भी cache नहीं करता, इसलिए pre-2026 connection ठीक वैसे ही बर्ताव करता है जैसे cache के आने से पहले करता था। अगर आपको "server ने 0 कहा" और "server ने कुछ नहीं कहा" में फ़र्क करना हो, तो `"ttl_ms" in result.model_fields_set` जाँचें: यह तभी set होता है जब field सच में आया हो।

## पुराने clients {#older-clients}

pre-2026 protocol versions वाले clients को इनमें से कोई भी field कभी नहीं दिखता; SDK उन connections के लिए serialization के समय इन्हें हटा देता है। hints एक बार configure करें; version के हिसाब से अलग कुछ लिखने को नहीं है।

## सारांश {#recap}

* छह methods में `ttlMs`/`cacheScope` होते हैं; SDK इनका default `0`/`"private"` रखता है, stale और unshared, हमेशा सुरक्षित।
* construction के समय `cache_hints={method: CacheHint(...)}` (`MCPServer` और `Server` दोनों में) हर method के लिए server-wide values set करता है।
* जो handler अपने result पर ये fields set करता है, वह map को override करता है, field दर field।
* `"public"` एक वादा है कि result हर caller के लिए एक जैसा है। यह access control नहीं है।
* `Client` hints का पालन अपने आप करता है: उसका response cache default रूप से चालू है, दोबारा fetch करने की बजाय fresh entries serve करता है, और जो servers (या sessions) कोई hint नहीं देते उनके लिए कुछ भी cache नहीं करता।
* हर call पर, `cache_mode="refresh"` दोबारा fetch करता है और `"bypass"` cache को छोड़ देता है; construction के समय `cache=None` इसे पूरी तरह बंद कर देता है।
