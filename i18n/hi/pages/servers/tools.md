---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# Tools {#tools}

**tool** ऐसा function है जिसे model call कर सकता है।

किसी सादे Python function पर `@mcp.tool()` लगाकर आप tool declare करते हैं। पूरा API बस इतना ही है।

## आपका पहला tool {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

देखें आपने क्या लिखा। न कोई schema, न JSON, न protocol, बस एक function। SDK इससे तीन चीज़ें पढ़ता है:

* tool का **नाम** function का नाम है: `search_books`।
* model को जो **description** दिखता है वह docstring है: `Search the catalog by title or author.`
* model जो **arguments** pass कर सकता है वे type hints से आते हैं: `query: str` और `limit: int`।

### Input schema {#the-input-schema}

इन्हीं type hints से SDK एक JSON Schema बनाता है और `tools/list` के दौरान client को भेजता है:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

दोनों arguments `required` में हैं क्योंकि किसी का भी default नहीं है। इसे आप थोड़ी ही देर में ठीक करेंगे। (`title` keys Pydantic की देन हैं; properties, उनके types और `required` ही असली contract हैं।)

!!! tip
    यहाँ type hints documentation नहीं हैं। वे ही **contract** हैं। अगर कोई client `"limit": "ten"` भेजता है,
    तो SDK उसे आपके function के चलने से पहले ही reject कर देता है।

### model को क्या वापस मिलता है {#what-the-model-gets-back}

tool को `{"query": "dune", "limit": 5}` के साथ call करें और result के दो हिस्से होते हैं:

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` वह text है जो **model** पढ़ता है। `structured_content` **client application** के लिए typed data है। यह इसलिए मौजूद है क्योंकि आपने return type `-> str` declare किया।

`structured_content` की अभी चिंता न करें। अपने tools से असली Python objects लौटाएँ और सही चीज़ अपने-आप होती है; **[Structured Output](structured-output.md)** page पूरा इसी बारे में है।

### इसे आज़माएँ {#try-it}

server को MCP Inspector के साथ चलाएँ:

```console
uv run mcp dev server.py
```

यह जो URL print करे उसे खोलें, **Tools** tab पर जाएँ, और `search_books` call करें।

Inspector एक form दिखाता है जिसमें एक required `query` text field और एक required `limit` number field है। यह form उसने आपके type hints से बनाया। बाकी हर MCP client भी यही करेगा।

## Optional arguments {#optional-arguments}

किसी parameter को default value दें और वह required नहीं रहता। बस इतना ही। यह सिर्फ़ Python है।

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

schema भी साथ बदलता है:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

`limit` `required` से बाहर हो गया और उसे `"default": 10` मिल गया। जो client इसे छोड़ देता है उसे `10` मिलता है, ठीक वैसे ही जैसे Python में होता।

## `Field` के साथ ज़्यादा विस्तृत schemas {#richer-schemas-with-field}

type hints से काफ़ी काम चल जाता है, लेकिन कभी-कभी आप किसी argument की **description देना** चाहते हैं, या उस पर constraints लगाना।

type को `Annotated` में लपेटें और एक Pydantic `Field` जोड़ें:

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

तीन नई चीज़ें, सब parameters पर:

* `Field(description=...)`: हर argument की अपनी description, जिसे model docstring के साथ पढ़ता है।
* `Field(ge=1, le=50)`: संख्या की सीमाएँ। ये schema में `"minimum": 1, "maximum": 50` बनकर पहुँचती हैं।
* `Literal["fiction", "non-fiction", "poetry"]`: एक enum। model इन्हीं में से कोई एक चुन सकता है।

!!! check
    constraints सजावट नहीं हैं। tool को `limit=999` के साथ call करें और SDK
    **आपके function के चलने से पहले ही** tool error के साथ जवाब देता है:

    ```text
    Input should be less than or equal to 50
    ```

    यह error tool result के रूप में model के पास वापस जाता है, model इसे पढ़ता है और सही value के साथ
    दोबारा कोशिश करता है। आपने एक बार `le=50` लिखा और खुद को सुधारने वाले agents मुफ़्त में मिल गए।

!!! info
    अगर आपने FastAPI या Pydantic इस्तेमाल किया है, तो यह सब आप पहले से जानते हैं। वही `Field`,
    वही `Annotated`, वही validation। यहाँ MCP से जुड़ा कुछ नया सीखने को नहीं है।

## parameter के रूप में model {#a-model-as-a-parameter}

जब कोई tool दो-तीन से ज़्यादा arguments लेता है, तो उन्हें एक Pydantic model में समेट लें:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

`Book` schema tool के input schema के अंदर nested होता है (एक `$defs` reference के रूप में), model इसे JSON object के रूप में भरता है, और आपके function को एक **असली `Book` instance** मिलता है, पहले से validated, जिसमें `.title`, `.author` और `.year` attributes हैं।

आप इन्हें मिला-जुला सकते हैं: model parameters के साथ सादे parameters, nested models, models की lists। नीचे तक सब Pydantic ही है।

## `async def` {#async-def}

अगर कोई tool I/O करता है (कोई API call करता है, file पढ़ता है, database से query करता है), तो उसे `async def` declare करें और उसके अंदर `await` करें। SDK उसे await करता है।

सादा `def` tool भी चलता है: SDK उसे एक thread में चलाता है ताकि वह server को कभी block न करे।

और कुछ configure करने को नहीं है।

## नाम, titles और annotations {#names-titles-and-annotations}

SDK जो कुछ भी अनुमान लगाता है, उसे आप decorator में override कर सकते हैं:

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` UIs के लिए इंसानों के पढ़ने लायक नाम है। clients `search_books` की जगह *"Search the catalog"* दिखाते हैं।
* `annotations` client के लिए व्यवहार से जुड़े **hints** हैं:
  * `read_only_hint=True`: यह tool कुछ नहीं बदलता।
  * `open_world_hint=False`: यह चीज़ों के एक बंद set (इस catalog) पर काम करता है, खुले web पर नहीं।
  * बाकी दो, `destructive_hint` और `idempotent_hint`, ऐसे tool के बारे में बताते हैं जो **लिखता** है: क्या वह
    कुछ delete कर सकता है, और क्या उसे दो बार call करना एक बार call करने जैसा ही है? spec दोनों को
    सिर्फ़ non-read-only tools के लिए define करता है, इसलिए `search_books` पर ये कुछ नहीं कहते।

सलीकेदार client "क्या इसे चलाने से पहले मुझे user से पूछना होगा?" जैसी बातें इन्हीं से तय करता है। ये hints हैं, security नहीं। कभी इस भरोसे न रहें कि client इनका पालन करेगा।

!!! tip
    अगर आप इन्हें function के नाम और docstring से नहीं निकालना चाहते, तो `@mcp.tool()` `name=` और `description=` भी
    स्वीकार करता है। ज़्यादातर वक्त आप उन्हीं से निकालना चाहेंगे।

## सारांश {#recap}

* function पर `@mcp.tool()` उसे tool बना देता है। नाम function से, description docstring से।
* type hints **ही** input schema हैं। defaults arguments को optional बनाते हैं।
* `Annotated[..., Field(...)]` descriptions और constraints जोड़ता है; `Literal` enums जोड़ता है।
* structured "body" लेने का तरीका Pydantic model parameter है।
* गलत arguments आपके लिए reject कर दिए जाते हैं, ऐसे error के साथ जिसे model पढ़ सके और संभल सके।
* I/O के लिए `async def`, बाकी सब के लिए सादा `def`।

जो value आप `return` करते हैं उसका क्या होता है, यह **[Structured Output](structured-output.md)** में है।
