---
translation:
  sections: [e33d441f12d50535, 7099694c603e0f5f, c1df4cf9673433e6, c9cd294541422e6e, 6cec073617bfd037, efa92b8f99e908c8, 6a22a29e27fb4601]
  tool: 1
---
# errors संभालना {#handling-errors}

tool दो तरीकों से fail हो सकता है, और SDK दोनों के साथ बहुत अलग बर्ताव करता है।

साधारण exception raise करें तो उसे **model** देखता है। `MCPError` raise करें तो उसे **protocol** देखता है।

यह page इन दोनों में से चुनने के बारे में है।

## ऐसा error जिसे model ठीक कर सकता है {#an-error-the-model-can-fix}

ऐसा tool लें जो कुछ खोजता है, और खोज को नाकाम होने दें:

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

उन दो lines में MCP जैसा कुछ नहीं है। `get_author` सादा `ValueError` raise करता है, जैसे कोई भी Python function करता।

इसे ऐसे title से call करें जो catalog में नहीं है और result देखें:

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* request **सफल रही**। result मौजूद है; caller की तरफ़ कुछ raise नहीं हुआ।
* `is_error` `True` है, और आपके exception का message (आगे tool का नाम लगा हुआ) `content` में है, ठीक वहीं जहाँ model पढ़ता है।
* `structured_content` `None` है। fail हुए call के पास structure करने को कोई return value नहीं होती।

यह **tool error** है, और आपका tool **कोई भी** exception raise करे, default यही है। और लगभग हमेशा आप यही चाहते भी हैं।

आपके tool को call करने वाला model ही है। arguments उसी ने चुने। इसलिए tool error बातचीत का एक turn है: model *"No book titled 'Nothing' in the catalog."* पढ़ता है, समझ जाता है कि उसने title का गलत अंदाज़ा लगाया, और बेहतर title के साथ फिर call करता है। आपने एक `raise` लिखा और बदले में खुद को सुधारने वाला agent मिल गया।

!!! tip
    tool से कभी error message `return` न करें। लौटाई गई string का `is_error=False` होता है, इसलिए
    model को (और हर client UI को) लगता है कि tool ठीक चला और वही string जवाब थी।
    `raise` करें। flag ही संकेत है।

## ऐसा error जिसे model ठीक नहीं कर सकता {#an-error-the-model-cannot-fix}

अब `ValueError` की जगह `MCPError` रखें।

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` SDK का **protocol error** है। यही वह एक exception है जिसे tool wrapper catch **नहीं** करता: यह ऊपर propagate होता है, और पूरी `tools/call` request result के बजाय JSON-RPC error के साथ fail हो जाती है।

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* कोई **result नहीं** है। न `content`, न `is_error`: model के पढ़ने के लिए कुछ भी नहीं।
* इसके बजाय error **host** application को मिलता है, ठीक वैसे ही जैसे tool के बिल्कुल मौजूद न होने पर मिलता।
* `code`, `message`, और `data` जस के तस पहुँचते हैं। `INVALID_PARAMS` `-32602` है; `mcp.types` इसे और बाकी JSON-RPC error codes (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...) को constants के रूप में export करता है, ताकि आपको कभी magic number न लिखना पड़े।

!!! check
    वही lookup, वही चूक, लेकिन अब call client की तरफ़ लौटने के बजाय **raise** होता है:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    पहले version ने model को एक वाक्य थमाया जिस पर वह कुछ कर सकता था। यह version उसे कुछ नहीं देता।
    `get_author` के लिए यह साफ़ तौर पर बदतर है, और यही अगले section का मुद्दा है।

## कौन सा raise करें {#which-one-to-raise}

दोनों रास्ते दो अलग-अलग सवालों का जवाब देते हैं।

* **कोई भी exception raise करें** जब नाकामी **execution** की हो: आपके tool ने जो करने की कोशिश की, वह नहीं हुआ। call model ने चुना था, इसलिए नतीजा भी model को दिखना चाहिए और उसे संभलने का मौका मिलना चाहिए। गलत वर्तनी वाला title, timeout हो गया upstream API, ऐसी row जो मौजूद नहीं: सब tool errors।
* **`MCPError` raise करें** जब **request खुद** ठुकराई जानी चाहिए: client के पास वह capability नहीं जिस पर आपका tool निर्भर है, server किसी को भी serve करने की हालत में नहीं है, caller ने कोई ज़रूरी चरण छोड़ दिया। model का कोई retry इनमें से किसी को ठीक नहीं करता, इसलिए उसे message थमाने से कुछ हासिल नहीं।

एक सवाल से फ़ैसला हो जाता है: **क्या ज़्यादा समझदार model इससे बच सकता था?** हाँ -> साधारण exception। नहीं -> `MCPError`।

इस कसौटी पर `get_author` के दूसरे version ने गलत चुनाव किया: बेहतर title से बात बन जाती है, इसलिए model message देखने का हक़दार था। वह version आपको mechanism दिखाने के लिए है, उसकी सिफ़ारिश करने के लिए नहीं।

!!! info
    `MCPError` `from mcp import MCPError` पर मिलता है और `code`, `message`, और एक optional
    `data` payload लेता है। इनमें आप जो भी रखें, client को वही मिलता है: SDK raise किए गए
    `MCPError` को sanitise करने के बजाय जस का तस आगे भेज देता है।

## ऐसा resource जो मौजूद नहीं है {#a-resource-that-doesnt-exist}

resources भी यही रेखा खींचते हैं, और आम मामले के लिए एक नाम वाला exception साथ देते हैं।

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` एक **template** है। यह **किसी भी** title से match करता है, इसलिए "URI सही बना है" और "किताब मौजूद है" दो अलग सवाल हैं, और दूसरे का जवाब सिर्फ़ आपका function दे सकता है।

जब वह न दे सके, `ResourceNotFoundError` raise करें। SDK इसे उस protocol error में बदल देता है जो spec ने गायब resource के लिए तय किया है: `-32602`, और `data` में माँगा गया URI, ताकि client को पता रहे कि **कौन सा** read fail हुआ।

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

ध्यान दें, यहाँ कोई `is_error=True` वाला आधा-अधूरा result नहीं है। resource read या तो contents लौटाता है या fail होता है: resources के पास सिर्फ़ protocol वाला रास्ता है। templates और resources के बारे में बाकी सब कुछ **[Resources](resources.md)** में है।

## ऐसे errors जो आप कभी raise नहीं करते {#errors-you-never-raise}

गलत argument आपके function तक कभी पहुँचता ही नहीं।

`get_author` को ऐसा `title` भेजें जो string नहीं है, और SDK आपको call करने से **पहले** ही उसे input schema के आधार पर ठुकरा देता है, उसी तरह के `is_error=True` tool error के रूप में जिसे model पढ़ और सुधार सकता है। **[Tools](tools.md)** यही अस्वीकृति `Field(le=50)` constraint के साथ दिखाता है।

इसका मतलब है `raise` statements की एक पूरी श्रेणी जो आपको लिखनी नहीं पड़ती: अपने ही type hints को दोबारा validate न करें।

!!! info
    इस page पर सब कुछ वही है जो **client** को दिखता है, और जिस in-memory `Client` से आप
    tests लिखेंगे, उसे भी ठीक यही दिखता है। `raise_exceptions=True` भी tool error को वापस
    traceback में नहीं बदलता: जब तक वह flag कुछ कर पाता, आपका exception पहले ही
    `is_error=True` result बन चुका होता है। result पर assert करें। **[Testing](../get-started/testing.md)** में यह pattern बताया गया है।

## सारांश {#recap}

* tool में **कोई भी exception** raise करें -> call `is_error=True` लौटाता है, `content` में आपके message के साथ। model उसे पढ़ता है और retry कर सकता है। यही default है।
* **`MCPError`** raise करें -> call खुद JSON-RPC error के साथ fail हो जाता है। model को कुछ नहीं दिखता; host इससे निपटता है। `code`, `message`, और `data` जस के तस बचे रहते हैं।
* फ़ैसला करने वाला सवाल: **क्या ज़्यादा समझदार model इससे बच सकता था?** हाँ -> exception। नहीं -> `MCPError`।
* resource handler से `ResourceNotFoundError` -> protocol का `-32602`, `data` में URI के साथ।
* गलत arguments आपका function चलने से पहले ही schema के आधार पर ठुकरा दिए जाते हैं; उनके लिए आप `raise` नहीं करते।
* `from mcp import MCPError`; error-code constants `mcp.types` से आते हैं।

errors संभल गए। server जो कुछ **expose** करता है, वह सब यही है। हर handler क्या पढ़ सकता है, और चलते-चलते client के साथ वापस क्या कर सकता है, यह अगला section है: **[आपके handler के अंदर](../handlers/index.md)**।

जिन SDK errors से आपका सामना होने की सबसे ज़्यादा संभावना है, उनका हूबहू text, हर एक का मतलब, और हर एक का एक-कदम वाला हल **[Troubleshooting](../troubleshooting.md)** में है।
