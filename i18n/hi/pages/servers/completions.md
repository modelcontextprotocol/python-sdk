---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# Completions {#completions}

आपके server के ऊपर UI बना रहा कोई client चाहता है कि user के टाइप करते ही argument values अपने आप पूरे हों: भाषाओं के नाम, repositories के नाम, file paths।

**Completions** वह तरीका है जिससे server ये सुझाव देता है।

## कुछ ऐसा जो complete करने लायक हो {#something-worth-completing}

Completions ठीक दो चीज़ों पर लागू होते हैं: किसी **prompt** के arguments और किसी **resource template** के parameters। तो ऐसे server से शुरू करें जिसमें दोनों में से एक-एक हो:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

यहाँ अभी तक completions के बारे में कुछ नहीं है।

* `review_code` एक `language` लेता है। user को यह अनुमान नहीं लगाना चाहिए कि आप कौन-सी वर्तनियाँ स्वीकार करते हैं।
* `github_repo` एक `owner` और एक `repo` लेता है। दोनों के लिए free-text boxes रखना खराब form बनाता है।

## Completion handler {#the-completion-handler}

`@mcp.completion()` से सजाया हुआ **एक** function जोड़ें:

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* हर server में एक ही handler होता है। हर completion request यहीं आती है, और जो complete हो रहा है उसके हिसाब से आप branch करते हैं।
* इसे `async def` होना ज़रूरी है: SDK इसे await करता है।
* इसे तीन arguments मिलते हैं:
  * `ref`: **कौन-सा** prompt या resource template, `PromptReference` या `ResourceTemplateReference` के रूप में। दोनों में फ़र्क `isinstance` से पता चलता है।
  * `argument`: `argument.name` वह argument है जो complete हो रहा है, `argument.value` वह है जो user ने अब तक टाइप किया है।
  * `context`: पहले से तय हो चुके arguments। अभी इसे नज़रअंदाज़ करें।
* आप `Completion(values=[...])` लौटाते हैं, या जब देने को कुछ न हो तो `None`।

!!! tip
    `argument.value` वह prefix है जो user ने टाइप किया है। SDK आपके लिए filter **नहीं** करता: जो कुछ
    आप `values` में रखते हैं, UI वही दिखाता है। `startswith` आपको खुद लिखना है।

### इसे आज़माएँ {#try-it}

इसे **[Testing](../get-started/testing.md)** वाले in-memory `Client` से चलाएँ।
`client.complete()` को `ref=PromptReference(name="review_code")` और
`argument={"name": "language", "value": "py"}` के साथ call करें:

```python
result.completion.values  # ['python']
```

* `ref` वही reference type है जो आपके handler को मिलता है।
* `argument` एक सादी dict है जिसमें ठीक दो keys हैं, `name` और `value`।

खाली `value` भेजें और आपको पूरी सूची वापस मिलती है। `lang.startswith("")` हर भाषा के लिए true है:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

`code` के बारे में पूछें (ऐसा argument जिसे handler नहीं पहचानता) और वह `None` लौटाता है, जिसे SDK खाली list में बदल देता है:

```python
result.completion.values  # []
```

`None` का मतलब है **"कोई सुझाव नहीं"**, error कभी नहीं। UI सादे text box पर लौट आता है।

## एक capability जो आपने कभी declare नहीं की {#a-capability-you-never-declared}

handler register करना ही declaration है। कोई client जोड़ें और देखें:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

आपने `completions` कहीं नहीं लिखी। SDK ने handler देखा और आपके लिए capability declare कर दी। हर **optional** capability ऐसे ही काम करती है: handler ही declaration है। (तीनों primitives optional नहीं हैं: `MCPServer` उन्हें हमेशा declare करता है, handlers हों या न हों।)

!!! check
    पहली `server.py` पर वापस जाएँ (जिसमें कोई handler नहीं है) और फिर भी उससे पूछें। call
    JSON-RPC error के साथ fail होती है:

    ```text
    Method not found
    ```

    और `client.server_capabilities.completions` `None` है। capability का यही मतलब है:
    सही ढंग से बना client इसे जाँचता है और वह request कभी नहीं भेजता जिसका जवाब आप नहीं दे सकते।

## एक-दूसरे पर निर्भर arguments {#dependent-arguments}

`github://repos/{owner}/{repo}` में दो parameters हैं, और `repo` के काम के values इस पर निर्भर करते हैं कि पहले कौन-सा `owner` चुना गया।

`context` इसी के लिए है। इसमें वे arguments होते हैं जो user **पहले ही तय कर चुका है**:

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* नई branch template के `repo` parameter के लिए चलती है।
* `context.arguments` अब तक चुने गए values (यहाँ, `owner`) की `dict[str, str] | None` है।
* अभी `owner` नहीं है तो कोई समझदार सुझाव भी नहीं, इसलिए handler `None` लौटाता है।

client ये तय हो चुके values `context_arguments=` से भेजता है। इस बार `ref` है
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`। खाली `value` के साथ
`repo` माँगें और `context_arguments={"owner": "modelcontextprotocol"}` pass करें:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

`context_arguments=` हटा दें और वही call `[]` लौटाती है। जब तक handler को owner पता न हो, वह नहीं जान सकता कि कौन-से repos सुझाए।

!!! info
    `Completion` `total=` और `has_more=` भी लेता है। इन्हें तब set करें जब `values` किसी लंबी सूची का
    एक हिस्सा हो, ताकि UI **"और 200 बाकी"** दिखा सके। ज़्यादातर handlers को इनकी कभी ज़रूरत नहीं पड़ती।

## सारांश {#recap}

* Completions **prompt arguments** और **resource template parameters** के लिए सुझाव हैं। और कुछ नहीं।
* `@mcp.completion()` वह एक handler register करता है। यह `async def (ref, argument, context) -> Completion | None` है।
* `isinstance(ref, ...)` और `argument.name` पर branch करें। `argument.value` से filter खुद करें।
* `None` खाली list बन जाता है। यह कभी error नहीं है।
* `context.arguments` में पहले से तय values होती हैं; client उन्हें `context_arguments=` के रूप में देता है।
* `completions` capability उसी पल आ जाती है जब आप handler register करते हैं। उसके बिना, request का जवाब `Method not found` है।

सुझाव तब काम आते हैं जब user अभी prompt या template **भर ही रहा हो**; किसी tool call के **बीच** में उससे सवाल पूछना हो तो आपको **[Elicitation](../handlers/elicitation.md)** चाहिए। text के अलावा tool जो कुछ लौटा सकता है वह सब **[Images, audio और icons](media.md)** में है।
