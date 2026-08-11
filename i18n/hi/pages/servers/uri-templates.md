---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# URI templates और path safety {#uri-templates-and-path-safety}

यह उस URI-template syntax का reference है जिसे
[`@mcp.resource`](resources.md) स्वीकार करता है, और उस path-safety policy का भी जो SDK निकाली गई values पर लागू करता है। resources क्या हैं और उन्हें कब इस्तेमाल करना है, इसके परिचय के लिए **[Resources](resources.md)** से शुरू करें; यह page मानकर चलता है कि आप resource declare करने में पहले से सहज हैं और अब पूरा operator set, security से जुड़े विकल्प, या low-level wiring जानना चाहते हैं।

template syntax [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) है।
SDK इसका एक subset support करता है जो आने वाले `resources/read` URIs को match करने के लिए चुना गया है, साथ ही एक security layer भी है जो ऐसी values को reject करती है जो उस directory के बाहर resolve होतीं जिसे आप serve करना चाहते हैं। protocol-स्तर के विवरण (message formats, lifecycle, pagination) के लिए
[MCP resources specification](https://modelcontextprotocol.io/specification/latest/server/resources) देखें।

## पूरा operator set {#the-full-operator-set}

सादा placeholder, `{user_id}`, वही है जिसका परिचय **[Resources](resources.md)** देता है। operator के चार और रूप हैं; यहाँ वे एक ही server पर हैं ताकि आप उन्हें साथ-साथ देख सकें:

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

हर highlighted decorator URI को बाँटने का अलग तरीका है।
नीचे के sections इन्हें ऊपर से नीचे तक एक-एक करके समझाते हैं।

### Simple expansion: `{name}` {#simple-expansion-name}

`books://{isbn}` सादा, रोज़मर्रा का रूप है। placeholder `isbn` parameter से जुड़ता है, इसलिए `books://978-0441172719` पढ़ने वाला client
`get_book("978-0441172719")` call करता है।

सादा `{name}` पहले `/` पर रुक जाता है। `books://978/extra` match नहीं करता क्योंकि `978` के बाद का slash capture को खत्म कर देता है और `/extra` बचा रह जाता है।

### Type conversion {#type-conversion}

निकाली गई values strings के रूप में आती हैं, लेकिन आप ज़्यादा सटीक type declare कर सकते हैं और SDK convert कर देगा। `orders://{order_id}` ऐसे function में पहुँचता है जिसका parameter `order_id: int` है, इसलिए `orders://12345` पढ़ने पर
`get_order(12345)` call होता है, `get_order("12345")` नहीं। handler बिना cast के उस पर arithmetic करता है (`order_id + 1`)।

### Multi-segment paths: `{+name}` {#multi-segment-paths-name}

ऐसी value capture करने के लिए जिसमें slashes हों, `{+name}` इस्तेमाल करें।
`manuals://{+path}` के साथ:

* `manuals://returns.md` से `path = "returns.md"` मिलता है
* `manuals://printing/setup.md` से `path = "printing/setup.md"` मिलता है

जब भी value hierarchical हो, `{+name}` चुनें: filesystem paths, nested object keys, वे URL paths जिन्हें आप proxy कर रहे हैं।

### Query parameters: `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` `limit` और `sort` को `?` के बाद रखता है।
path बताता है **कौन-सी** किताब; query तय करती है उसे **कैसे** पढ़ना है।

query params उदारता से match होते हैं: क्रम मायने नहीं रखता, अतिरिक्त params नज़रअंदाज़ होते हैं, और छोड़े गए params आपके function defaults पर आ जाते हैं। इसलिए
`reviews://978-0441172719` `limit=10, sort="newest"` इस्तेमाल करता है, और
`reviews://978-0441172719?sort=top` सिर्फ़ `sort` को override करता है।

### List के रूप में path segments: `{/name*}` {#path-segments-as-a-list-name}

अगर आप हर path segment को slashes वाली एक string की जगह list के अलग-अलग item के रूप में चाहते हैं, तो `{/name*}` इस्तेमाल करें। `shelves://browse{/path*}` के साथ, `shelves://browse/fiction/sci-fi` पढ़ने वाला client
`browse_shelf(["fiction", "sci-fi"])` call करता है।

### Template reference {#template-reference}

सबसे आम patterns:

| Pattern      | उदाहरण input           | आपको मिलता है            |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | **कोई match नहीं** (`/` पर रुकता है) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### Parser क्या reject करता है {#what-the-parser-rejects}

template के कुछ आकार पहली request पर fail होने की बजाय शुरू में ही पकड़ लिए जाते हैं। `@mcp.resource` decorator चलते समय template को parse करता है, इसलिए इनमें से कोई भी चलते हुए server तक कभी नहीं पहुँचता।

`UriTemplate.parse()` इनके लिए `InvalidUriTemplate` raise करता है:

* **दो variables जिनके बीच कुछ न हो।** `manuals://{+path}{ext}`
  reject होता है: matching यह नहीं बता सकती कि `path` कहाँ खत्म होता है और `ext` कहाँ शुरू होता है।
  उनके बीच कोई literal रखें (`manuals://{+path}/{ext}`), या ऐसा operator इस्तेमाल करें जो अपना delimiter खुद देता हो। `manuals://{+path}{.ext}`
  स्वीकार होता है क्योंकि `{.ext}` खुद `.` जोड़ता है।
* **एक से ज़्यादा multi-segment variable।** हर template में `{+var}`,
  `{#var}`, या exploded variable (`{/var*}`, `{.var*}`, `{;var*}`) में से ज़्यादा से ज़्यादा एक। दो होना स्वभाव से ही अस्पष्ट है: यह तय करने का कोई सिद्धांत-सम्मत तरीका नहीं है कि अतिरिक्त segment किसमें समाए।
* **आम syntax errors**: बिना बंद किया brace, दो बार इस्तेमाल हुआ variable नाम, या RFC 6570 का कोई ऐसा feature जिसे SDK support नहीं करता, जैसे `{var:3}` prefix modifier या `{?vars*}` query explode।

इसके अलावा, `@mcp.resource` `ValueError` raise करता है जब handler का कोई parameter template के आखिरी `{?...}`/`{&...}` हिस्से के किसी query variable से बँधा हो लेकिन उसका कोई Python default न हो। वे variables उदारता से match होते हैं (client उनमें से कोई भी छोड़ सकता है), इसलिए बिना default वाला parameter सिर्फ़ उसे छोड़ने वाली पहली request पर एक अस्पष्ट internal error के रूप में सामने आता। ऊपर के server में `reviews://{isbn}{?limit,sort}` सही बना हुआ रूप है: `limit` और `sort` दोनों के defaults हैं।

## Security {#security}

template parameters client से आते हैं। अगर वे बिना जाँच के filesystem या database operations में चले जाएँ, तो `../../etc/passwd` जैसी values उस directory के बाहर resolve हो सकती हैं जिसे आप serve करना चाहते थे।

### SDK default रूप से क्या जाँचता है {#what-the-sdk-checks-by-default}

आपका handler चलने से पहले, SDK हर उस parameter को reject करता है जो:

* `..` components के ज़रिए अपनी शुरुआती directory से बाहर निकलता हो
* absolute path जैसा दिखता हो (`/etc/passwd`, `C:\Windows`) या
  Windows का drive-relative path हो (`C:foo`)। drive-relative value और `x:y` जैसा namespaced identifier strings के रूप में एक-दूसरे से अलग नहीं किए जा सकते, इसलिए एक-अक्षर-और-colon वाली कोई भी value default रूप से reject होती है; अगर parameter को वाजिब तौर पर ऐसी values मिलती हैं तो उसे exempt करें
* null byte (`\x00`) रखता हो

`..` की जाँच component-आधारित है, substring scan नहीं। `v1.0..v2.0` या `HEAD~3..HEAD` जैसी values pass होती हैं क्योंकि वहाँ `..` कोई अलग path segment नहीं है।

ये जाँचें decoded value पर लागू होती हैं, इसलिए traversal URI में चाहे जैसे भी encode किया गया हो, पकड़ा जाता है (`../etc`, `..%2Fetc`,
`%2E%2E/etc`, `..%5Cetc`, `%00` सब पकड़े जाते हैं)।

!!! check
    ऊपर के server से `manuals://../etc/passwd` पढ़ें और request सीधे reject हो जाती है: template matching पहली विफलता पर ही रुक जाती है, इसलिए बाद का कोई (संभवतः ज़्यादा उदार) template fallback के रूप में आज़माया नहीं जाता। client को वही `-32602` "Unknown resource" error दिखता है जो किसी भी template से match न करने वाले URI के लिए दिखता, और `read_manual` कभी नहीं चलता।

### Filesystem handlers: safe_join इस्तेमाल करें {#filesystem-handlers-use-safe_join}

built-in जाँचें आम मामलों को रोकती हैं लेकिन आपकी sandbox सीमा नहीं जान सकतीं। filesystem access के लिए, path resolve करने और यह पक्का करने के लिए कि वह आपकी base directory के अंदर ही रहे, `safe_join` इस्तेमाल करें:

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` symlink escapes, `..` sequences, और absolute-path की वे चालें पकड़ता है जो सादी string जाँच से छूट जातीं। अगर resolved path `DOCS_ROOT` से बाहर निकलता है, तो यह `PathEscapeError` raise करता है, जो client तक `ResourceError` के रूप में पहुँचता है।

### जब defaults आड़े आएँ {#when-the-defaults-get-in-the-way}

कभी-कभी ये जाँचें वाजिब values को रोक देती हैं। catalog-import tool जानबूझकर absolute path ले सकता है, या कोई parameter `../sibling` जैसा relative reference हो सकता है जिसे आपका handler filesystem छुए बिना सुरक्षित रूप से समझता है। उस parameter को exempt करें, या पूरे server के लिए policy ढीली करें:

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* decorator पर `security=ResourceSecurity(exempt_params={"source"})`
  उस एक resource के उस एक parameter के लिए जाँचें छोड़ देता है। बाकी server default policy रखता है।
* `MCPServer` constructor पर `resource_security=` हर resource के लिए default तय करता है। यहाँ `relaxed` `..` की जाँच पूरी तरह बंद कर देता है।

configure की जा सकने वाली जाँचें:

| Setting                 | Default | यह क्या करता है                      |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | शुरुआती directory से बाहर निकलने वाले `..` sequences reject करता है |
| `reject_absolute_paths` | `True`  | `/foo`, `C:\foo`, UNC paths, और drive-relative `C:foo` reject करता है (`x:y` भी पकड़ता है) |
| `reject_null_bytes`     | `True`  | `\x00` वाली values reject करता है    |
| `exempt_params`         | खाली     | वे parameter नाम जिनके लिए जाँचें छोड़नी हैं  |

ये जाँचें एक heuristic pre-filter हैं; filesystem access के लिए,
`safe_join` ही containment boundary बना रहता है।

!!! tip
    अगर आपका handler request पूरी नहीं कर सकता (file मौजूद नहीं है, id अनजान है), तो exception raise करें। SDK उसे error response में बदल देता है। protocol error और tool error के बीच के फ़र्क़ के लिए **[errors संभालना](handling-errors.md)** देखें।

## Low-level Server पर resources {#resources-on-the-low-level-server}

अगर आप low-level `Server` पर बना रहे हैं (देखें **[Low-level
Server](../advanced/low-level-server.md)**), तो आप `resources/list` और `resources/read` protocol methods के लिए handlers सीधे register करते हैं। कोई decorator नहीं है; protocol types आप खुद लौटाते हैं।

### Static resources {#static-resources}

तय URIs के लिए, एक registry रखें और exact match पर dispatch करें:

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

list handler clients को बताता है कि क्या उपलब्ध है; read handler content serve करता है। पहले अपनी registry जाँचें, अगर आपके पास templates (नीचे) हैं तो उन पर जाएँ, फिर बाकी सब के लिए raise करें।

### Templates {#templates}

`MCPServer` जो template engine इस्तेमाल करता है वह `mcp.shared.uri_template` में रहता है और अपने आप में काम करता है। आपको वही parsing और matching मिलती है; routing और security policy आप खुद जोड़ते हैं।

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

highlighted lines में तीन चीज़ें हो रही हैं:

* **एक बार parse करें, हर request पर match करें।** `UriTemplate.parse()` template बनाता है; `template.match(uri)` निकाले गए variables को `dict` के रूप में लौटाता है, या URI फ़िट न हो तो `None`। URL decoding `match()` के अंदर होती है; decoded values बिना path-safety validation के जस की तस लौटाई जाती हैं। values strings के रूप में निकलती हैं: उन्हें खुद convert करें (`int(matched["id"])`, `Path(matched["path"])`)।
* **safety जाँचें खुद लागू करें।** `..` और absolute-path की जो जाँचें `MCPServer` default रूप से चलाता है वे `mcp.shared.path_security` में रहती हैं।
  `read_manual_safely` `MANUALS` को छूने से पहले उन्हें call करता है। अगर कोई parameter filesystem path नहीं है (ISBN, search query), तो उस value के लिए जाँचें छोड़ दें: policy आप config object के ज़रिए नहीं बल्कि हर handler के स्तर पर नियंत्रित करते हैं।
* **templates को उसी source से list करें।** clients
  `resources/templates/list` के ज़रिए templates खोजते हैं। `str(template)` मूल template string वापस देता है, इसलिए listing और matcher का source of truth एक ही रहता है।

## सारांश {#recap}

* `{name}` एक segment match करता है; `{+name}` slashes रखता है; `{?a,b}`
  query string से लेता है; `{/name*}` segments को list में बाँटता है।
* दो variables जिनके बीच कुछ न हो, या दूसरा multi-segment variable, parse के समय reject होते हैं। आखिरी `{?...}`/`{&...}` query variable से बँधे parameter को Python default declare करना ज़रूरी है।
* parameter को annotate करें (`order_id: int`) और SDK convert कर देता है।
* default security policy आपका handler चलने से पहले `..`, absolute paths, और null bytes reject करती है; हर resource के लिए `security=ResourceSecurity(...)` से या पूरे server के लिए `resource_security=` से override करें।
* filesystem access के लिए, `safe_join` ही containment boundary है।
* low-level `Server` पर, `UriTemplate.parse()` से parse करें, `.match()` से match करें, और `mcp.shared.path_security` खुद लागू करें।
