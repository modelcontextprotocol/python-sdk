---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# Deprecated features {#deprecated-features}

2026-07-28 spec पाँच चीज़ों को retire करता है। SDK अब भी इनमें से हर एक को implement करता है, और अब हर एक पर **deprecation warning** लगी है। एक SDK helper अपनी अलग वजह से deprecated है और [आख़िर में](#deprecated-sdk-helpers) दिया गया है।

नीचे दी गई table हर deprecated feature का नाम, उसके हटने की वजह, और उसकी जगह किस replacement पर build करना है, यह बताती है।

## क्या deprecated है {#what-is-deprecated}

| Deprecated | क्यों | इसके बजाय क्या करें |
|---|---|---|
| **Roots**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, `Client(...)` को दिया जाने वाला `list_roots_callback=` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) इस capability को retire करता है। | paths को साधारण tool arguments या resource URIs के रूप में लें, या `InputRequiredResult` में `ListRootsRequest` embed करें (**[Multi-round-trip requests](handlers/multi-round-trip.md)** देखें)। |
| **Server-initiated sampling**: `ctx.session.create_message()`, `Client(...)` को दिया जाने वाला `sampling_callback=` | SEP-2577 इस capability को retire करता है। | `InputRequiredResult` लौटाएँ और client को call retry करने दें (**[Multi-round-trip requests](handlers/multi-round-trip.md)** देखें)। |
| **Protocol logging**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 इस capability को retire करता है। protocol के अंदर इसकी जगह कुछ नहीं लेता। | stderr पर साधारण `import logging` (**[Logging](handlers/logging.md)** देखें)। |
| **`ping`**: `client.send_ping()` | protocol से **हटा दिया गया**, सिर्फ़ deprecated नहीं। 2026-07-28 में कोई `ping` method नहीं है। | कुछ नहीं। यह सिर्फ़ `mode="legacy"` connection पर काम करता है। |
| **Client->server progress**: `client.send_progress_notification()` | 2026-07-28 progress को सिर्फ़ server->client बनाता है। | भेजने को कुछ नहीं। आपका *server* `ctx.report_progress()` से progress report करता है (**[Progress](handlers/progress.md)** देखें)। |

इस table से तीन बातें निकलती हैं:

* roots, sampling और logging साथ-साथ जाते हैं। एक ही proposal, **SEP-2577**, तीनों capabilities को एक साथ deprecate करता है।
* sampling और roots की एक गहरी साझा समस्या है: ये वे जगहें हैं जहाँ **server** **client** को **request** भेजता है। यही वह पूरी दिशा है जिसे 2026-07-28 **[Multi-round-trip requests](handlers/multi-round-trip.md)** से बदलता है। जो गए हैं वे standalone RPC methods हैं (`sampling/createMessage`, `roots/list`, और push-style `elicitation/create`); `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` payload types बचे रहते हैं, `InputRequiredResult.input_requests` में embed होकर, और client पर वे उन्हीं callbacks तक पहुँचते हैं।
* `ping` बाकियों से अलग है। protocol इसे deprecate नहीं करता, हटा देता है। SDK method अब भी warn करता है (उसका message *removed* कहता है, *deprecated* नहीं) और modern connection पर इसे call करने पर जवाब *"Method not found"* आता है।

## Deprecated होना बस सलाह भर है {#deprecated-is-advisory}

आज कुछ नहीं टूटता।

ऊपर का हर method ऐसे किसी भी session पर काम करता रहता है जिसने **2025-11-25 या उससे पहले** का version negotiate किया हो। client पर `mode="legacy"` pin करें और आपको ठीक 2026 से पहले वाला व्यवहार मिलता है। wire में कोई बदलाव नहीं है और capability negotiation जस का तस है।

बदलता यह है कि हर एक के पहली बार चलने पर आपको साफ़ दिखने वाली warning मिलती है:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` `UserWarning` का subclass है, `DeprecationWarning` का **नहीं**। यह जानबूझकर है: Python का default filter `DeprecationWarning` को सिर्फ़ उसी code में दिखाता है जो सीधे `__main__` के रूप में चलता है, और इसी तरह libraries चीज़ें deprecate करती हैं और दो साल तक किसी को पता नहीं चलता। यह वाली हर जगह दिखती है, बिना किसी `-W` flag के।

!!! warning
    "बस सलाह" वाली बात wire पर आकर खत्म हो जाती है। sampling और roots server-से-client
    *requests* हैं, और 2026-07-28 session के पास इन्हें ले जाने का कोई channel नहीं है। modern
    connection पर tool के अंदर `ctx.session.create_message()` call करें तो warning फिर भी
    fire होती है, और फिर send एक error के साथ fail हो जाता है:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    दो संकेत, इसी क्रम में। `MCPDeprecationWarning` उसी पल fire होती है जब आप method call
    करते हैं, किसी भी connection पर। error वह है जो तब वापस आता है जब SDK उसे भेजने की
    कोशिश करता है। ये दोनों end-to-end सिर्फ़ ऐसे `mode="legacy"` connection पर काम करते हैं
    जिसके client ने matching callback register किया हो।

## legacy session पर `ping` {#ping-on-a-legacy-session}

**ping** एक खाली request है जिसे कोई भी पक्ष यह जाँचने के लिए भेज सकता है कि दूसरा अब भी जवाब दे रहा है। 2026-07-28 spec इसे हटा देता है ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): modern client की भेजी हर request पहले ही साबित कर देती है कि server मौजूद है, और modern server के पास इसे भेजने का कोई channel नहीं है। दोनों SDK methods handshake वाली पीढ़ी के session पर अब भी काम करते हैं। client से:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

और server से, किसी भी handler के अंदर:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` हर call पर `MCPDeprecationWarning` के साथ warn करता है। default (`2026-07-28`) connection पर server इसके बजाय `MCPError: Method not found` जवाब देता है।
* `ctx.session.send_ping()` पर कोई warning नहीं है। modern connection पर यह वही no-back-channel error raise करता है जो कोई भी दूसरी server-initiated request करती है।
* ping का जवाब देने के लिए कोई भी पक्ष कुछ register नहीं करता।

## roots में बदलाव के notifications {#roots-change-notifications}

roots capability declare करने वाला 2025 पीढ़ी का client `notifications/roots/list_changed` भेजकर server को बता सकता है कि उसके workspace folders बदल गए हैं; जवाब में server दोबारा `roots/list` की request करता है। 2026-07-28 spec बाकी push-style roots flow के साथ इस notification को भी हटा देता है। client पर `list_roots_callback=` देना (**[Client callbacks](client/callbacks.md)**) ही `"roots": {"listChanged": true}` declare करता है, और एक call वह वादा निभाता है:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

server पर, इसे पाने वाला handler low-level `Server` लेता है:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` वह list है जो आपका `list_roots_callback` लौटाता है। `client.send_roots_list_changed()` warn करता है, और इसे `mode="legacy"` client चाहिए: modern connection पर notification चुपचाप drop हो जाता है। इसके बाद session खुला रखें, क्योंकि server की follow-up `roots/list` उसी पर आती है।
* `MCPServer` के पास इस notification के लिए कोई hook नहीं है। low-level `Server` पर `on_roots_list_changed=` handler register करता है (यह भी deprecated है, और construction के समय warn करता है)। notification में कोई payload नहीं होता, इसलिए handler नई list के लिए `ctx.session.list_roots()` call करता है।

## warning को चुप कराना {#silencing-the-warning}

नए code में ऐसा न करें।

लेकिन जिस server की आप देखरेख करते हैं और जो सच में 2026 से पहले के clients को serve करता है, उसे शांत log का पूरा हक है। पहला deprecated call चलने से पहले इस category को filter करें:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

पूरा API बस इतना ही है। हर method के लिए अलग switch नहीं है, और आपको चाहिए भी नहीं: एक category का मतलब ही यह है कि एक line उसे चुप कराती है और एक line उसे वापस ले आती है।

!!! check
    filter को उल्टा चलाएँ और आपको मुफ़्त में regression test मिलता है। अपनी pytest
    configuration की `filterwarnings` setting में `"error::mcp.MCPDeprecationWarning"`
    जोड़ें और deprecated call warn करने के बजाय **raise** करता है। `old_log` नाम का tool
    जो अब भी `ctx.info()` call करता है, pass होना बंद कर देता है: call `is_error=True` और
    `Error executing tool old_log` के साथ वापस आता है, और capture किया गया server log
    असली दोषी का नाम बताता है:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    pytest configuration की एक line, और कोई deprecated call बिना test fail किए आपके
    codebase में चुपके से वापस नहीं आ सकता।

## Deprecated SDK helpers {#deprecated-sdk-helpers}

ये spec के बदलाव नहीं हैं, सिर्फ़ SDK के अंदरूनी हिस्से हैं जिनका बेहतर replacement मौजूद है। ये उसी `MCPDeprecationWarning` के साथ warn करते हैं और 3.0 में हटा दिए जाएँगे।

| Deprecated | इसके बजाय क्या करें |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` और फिर `FuncMetadata.call_fn()`। इसे सिर्फ़ वही code call करता था जो `FuncMetadata` को सीधे चलाता है (जैसे कोई custom `Tool` subclass)। |

## सारांश {#recap}

* 2026-07-28 spec **roots**, server-initiated **sampling**, और protocol **logging** को deprecate करता है (तीनों [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), **progress** को server-से-client तक सीमित करता है, और **`ping`** को हटा देता है।
* replacement वाला column आपको आगे का रास्ता दिखाता है: sampling और roots के लिए **[Multi-round-trip requests](handlers/multi-round-trip.md)**, logging के लिए **[Logging](handlers/logging.md)**, progress के लिए **[Progress](handlers/progress.md)**। `ping` को कुछ भी नहीं चाहिए।
* Deprecated होना बस सलाह भर है: wire में कोई बदलाव नहीं, 2026 से पहले के sessions पर सब कुछ काम करता रहता है, और आपको साफ़ दिखने वाली `MCPDeprecationWarning` मिलती है (यह `UserWarning` है, इसलिए default रूप से चालू है)।
* sampling और roots को इसके अलावा back-channel चाहिए जो 2026-07-28 session के पास नहीं है। modern connection पर ये warn करते हैं और फिर raise करते हैं।
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` पूरी category को चुप कराता है; pytest में `"error::mcp.MCPDeprecationWarning"` इसे test failure में बदल देता है।
* एक SDK helper, `FuncMetadata.call_fn_with_arg_validation()`, अलग से deprecated है और 3.0 में हटाया जाएगा।
* नया code इनमें से किसी पर भी नहीं बनना चाहिए।

इन docs का बाकी हर page मौजूदा API सिखाता है।
