---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
  tool: 1
---
# Prompts {#prompts}

**Prompt** एक message template है जिसे user चुनता है।

Tools model के लिए होते हैं। Prompt इसका उल्टा है: user अपने client के menu (slash command, button) से कोई prompt चुनता है, उसके arguments भरता है, और render हुए messages बातचीत में ऐसे जुड़ जाते हैं मानो user ने खुद type किए हों।

Prompt declare करने के लिए text लौटाने वाले function पर `@mcp.prompt()` लगाएँ।

## आपका पहला prompt {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK वही तीन चीज़ें पढ़ता है जो वह tool से पढ़ता है:

* **Name** function का नाम है: `review_code`।
* Client जो **description** दिखाता है, वह docstring है: `Review a piece of code.`
* **Arguments** parameters से आते हैं। `code` का कोई default नहीं है, इसलिए वह required है।

`prompts/list` से client को यही वापस मिलता है:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

यहाँ कोई JSON Schema नहीं है। Prompt arguments **named string values** की एक flat list हैं: ऐसा form जिसे इंसान भरता है, ऐसा payload नहीं जिसे model बनाता है।

### इसे render करना {#rendering-it}

Client arguments pass करते हुए `prompts/get` से template render करता है। आपका function चलता है और जो `str` आप लौटाते हैं, वह **एक user message** बन जाता है:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

Prompt का पूरा जीवन बस इतना ही है: नाम से list होना, माँगे जाने पर render होना, chat में डाल दिया जाना।

!!! check
    `required` आपके function के चलने से पहले ही enforce होता है। `review_code` को `code` के बिना render करें और
    request खुद JSON-RPC error (code `-32603`) के साथ fail हो जाती है:

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Model को लौटाने के लिए tool जैसा कोई error result नहीं है, क्योंकि यहाँ कोई model शामिल ही नहीं है:
    call raise करता है। वजह (`Missing required arguments: {'code'}`) आपके server के log में जाती है।

### इसे आज़माएँ {#try-it}

Server को MCP Inspector के साथ चलाएँ:

```console
uv run mcp dev server.py
```

**Prompts** tab खोलें और `review_code` चुनें। Inspector एक required `code` field वाला form बनाता है। इसे भरें, render करें, और आपको ठीक ऊपर वाला user message वापस मिलता है।

## एक से ज़्यादा messages {#more-than-one-message}

Code review एक message है। Debugging session एक बातचीत है, और prompt पूरी बातचीत की शुरुआत कर सकता है।

`str` की जगह messages की list लौटाएँ:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` और `AssistantMessage`, `mcp.server.mcpserver.prompts.base` से आते हैं। इन्हें `str` दें और ये उसे आपके लिए `TextContent` में wrap कर देते हैं। Role class का नाम है।
* `Message` इनका साझा base है। इसे return annotation के रूप में इस्तेमाल करें।

`debug_error` को render करने पर अब तीन messages इसी क्रम में बनते हैं:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

आख़िरी message पर ध्यान दें। `assistant` turn पहले से भरना ही वह तरीका है जिससे आप model के **अगले** जवाब की दिशा तय करते हैं, बिना user से वह निर्देश खुद type करवाए।

## Titles और argument descriptions {#titles-and-argument-descriptions}

`review_code` function का नाम है, label नहीं। Client को button पर लगाने के लिए कुछ बेहतर दें, और हर argument का description लिखें ताकि form खुद ही समझ में आ जाए:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` इंसानों के पढ़ने लायक नाम है, ठीक tool के `title` की तरह।
* `Annotated[str, Field(description=...)]` वही pattern है जो **[Tools](tools.md)** tool के parameters describe करने के लिए इस्तेमाल करता है। यहाँ description schema में जाने के बजाय argument पर लगता है।
* `language` का default है, इसलिए वह अब required नहीं रहता।

`prompts/list` entry में अब वह सब है जो client को अच्छा form बनाने के लिए चाहिए:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    अगर आपने **[Tools](tools.md)** पढ़ लिया है, तो इस page की हर बात आप पहले से जानते हैं। वही decorator, वही
    docstring-as-description, वही `Annotated`/`Field`। बदलता सिर्फ़ इतना है कि इसे
    trigger कौन करता है (user) और result कहाँ जाता है (बातचीत में)।

## सारांश {#recap}

* Function पर `@mcp.prompt()` लगाने से वह prompt बन जाता है। नाम function से, description docstring से।
* Prompts **user-controlled** हैं: client इन्हें list करता है, user कोई एक चुनता है और arguments भरता है।
* Arguments named strings की flat list हैं (कोई schema नहीं)। Default वाला parameter optional है।
* `str` लौटाएँ और वह एक user message बन जाता है। Multi-turn बातचीत की शुरुआत करने के लिए `UserMessage` / `AssistantMessage` की list लौटाएँ।
* `title=` और `Field(description=...)` वही हैं जो client अपने UI में दिखाता है।
* कोई required argument छूट जाए तो पूरी request fail होती है। हर prompt का अलग error result नहीं होता।

Prompt के (या resource template के) arguments के लिए server-side autocomplete **[Completions](completions.md)** में है।
