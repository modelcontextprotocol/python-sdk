---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# Progress {#progress}

जो tool तीस सेकंड लेता है और तीस सेकंड तक कुछ नहीं बोलता, वह टूटा हुआ लगता है।

**Progress notifications** इसे ठीक करते हैं। Tool बताता है कि काम कितना हो चुका है; client तय करता है कि उससे क्या दिखाए: bar, spinner, या log line।

## Tool से report करें {#report-it-from-the-tool}

एक **`Context`** parameter लें और `report_progress` call करें:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

तीन arguments, और उनका मतलब आप तय करते हैं:

* `progress`: आप कहाँ तक पहुँचे हैं। Spec की माँग है कि यह हर report के साथ **बढ़े**; कोई value न दोहराएँ, न पीछे जाएँ।
* `total`: कुल कितना है, अगर आपको पता हो। Optional।
* `message`: **इसी** चरण के बारे में एक human-readable line। Optional।

`ctx` अपने type hint की वजह से inject होता है और model इसे कभी नहीं देखता: `import_catalog` के input schema में सिर्फ़ एक property है, `urls`। **[Context](context.md)** page पूरी तरह उसी object के बारे में है; progress उन चीज़ों में से एक है जो वह आपको देता है।

## Client से सुनें {#listen-for-it-from-the-client}

Client **हर call पर** अलग से opt in करता है, `call_tool` को `progress_callback=` देकर:

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

Callback एक `async` function है जो ठीक वही लेता है जो server ने report किया: `progress`, `total`, `message`।

!!! info
    `Client(mcp)` सीधे server object से जुड़ता है, memory में, वही client जिस पर **[Testing](../get-started/testing.md)**
    page बना है। `Client` चाहे कोई भी transport इस्तेमाल करे, `progress_callback` parameter वही रहता है;
    जो **timing** आप अभी देखने वाले हैं वह in-memory connection की है। वह आपका callback inline चलाता है,
    इसलिए हर report `call_tool` के लौटने से पहले पहुँच जाती है। असली transport पर notifications और result
    में होड़ लगती है, और एक धीमा callback `call_tool` के लौटने के बाद भी चल रहा हो सकता है।

### इसे आज़माएँ {#try-it}

`client.py` को `server.py` के बगल में रखें और चलाएँ:

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

Server पर हर `await ctx.report_progress(...)` client पर `show` का एक call बना, उसी क्रम में, और दोनों lines `call_tool` के लौटने से **पहले** print हुईं। Progress result में बंडल होकर नहीं आता; tool के काम करते रहने के दौरान ही stream होता है।

!!! warning
    `progress_callback` **call** का है, `Client` का नहीं। इसके लिए कोई constructor argument नहीं है,
    क्योंकि अलग-अलग calls को अलग-अलग callbacks चाहिए: एक download bar चलाता है, अगला
    एक log line।

!!! check
    अब `progress_callback=show` हटा दें और फिर से चलाएँ:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    कोई error नहीं, कोई warning नहीं, वही result। जब caller ने progress नहीं माँगा हो तब
    `report_progress` **no-op** है, इसलिए आप बिना शर्त report करें और कभी यह सोचने की ज़रूरत नहीं
    कि कोई सुन भी रहा है या नहीं।

## जब total पता न हो {#when-you-dont-know-the-total}

`total` तब के लिए है जब आपको denominator पता हो। अक्सर नहीं होता: आप कोई feed खाली कर रहे हैं, cursor पर चल रहे हैं, बिना length header वाली कोई चीज़ download कर रहे हैं।

इसे छोड़ दें:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

Callback को `total=None` मिलता है। Client अब भी **activity** दिखा सकता है ("3 imported so far..."), लेकिन percentage नहीं दिखा सकता। ज़्यादा सुंदर bar पाने के लिए कोई total न गढ़ें।

!!! tip
    ज़रूरी नहीं कि `progress` किसी ख़ास चीज़ को गिने। Bytes, rows, pages: वह unit चुनें जिसे
    user पहचाने, और सिर्फ़ वही `total` वादा करें जिसे आप निभा सकें।

## सारांश {#recap}

* `Context` लेने वाले किसी भी tool से `await ctx.report_progress(progress, total=None, message=None)`।
* Client `call_tool` को `progress_callback=` देता है: हर call पर, कभी `Client` पर नहीं।
* Callback `async (progress, total, message) -> None` है और tool के चलते रहने के दौरान ही fire होता है।
* Call पर callback न हो तो `report_progress` कुछ नहीं करता। बिना शर्त report करें।
* जब `total` पता न हो तो उसे छोड़ दें; callback को `None` मिलता है।

Progress वह है जो चलता हुआ tool **user** को दिखाता है। जो lines वह **आपके** लिए, यानी server चलाने वाले व्यक्ति के लिए log करता है, वे एक अलग channel हैं: **[Logging](logging.md)**।
