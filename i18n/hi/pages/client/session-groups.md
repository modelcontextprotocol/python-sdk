---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# Session groups {#session-groups}

`Client` सिर्फ़ एक server से जुड़ता है। असली applications को अक्सर कई servers चाहिए होते हैं (search server, database server, कोई internal API) और फिर हर एक के लिए अलग connection और अलग tools की सूची संभालनी पड़ती है।

**`ClientSessionGroup`** एक अकेला object है जिसमें कई connections रहते हैं और जो उन सबकी expose की गई हर चीज़ को एक ही view में मिला देता है।

## दो servers {#two-servers}

दो साधारण servers से शुरू करें। इनका आपस में कोई लेना-देना नहीं है, इसलिए स्वाभाविक रूप से दोनों ने अपने tool का नाम `search` रखा:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## एक group {#one-group}

`ClientSessionGroup` बनाएँ और हर server के लिए एक बार **`connect_to_server`** call करें:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` transport parameters लेता है, server object नहीं: subprocess शुरू करने के लिए `StdioServerParameters` (`mcp` से), या पहले से किसी URL पर सुन रहे server के लिए `StreamableHttpParameters` / `SseServerParameters` (`mcp.client.session_group` से)।
* `group.tools` हर जुड़े हुए server के tools का `dict[str, Tool]` है। `group.resources` और `group.prompts` का आकार भी यही है।
* `group.call_tool(name, arguments)` नाम खोजता है, वह session ढूँढता है जिसका यह tool है, और call आगे भेज देता है। आपको कभी बताना नहीं पड़ता कि कौन सा server।

!!! check
    `client.py` को दोनों servers के साथ रखें और चलाएँ। दूसरा `connect_to_server` मना कर देता है:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    यह `MCPError` है, जो दूसरे server से कुछ भी register होने से पहले raise होता है। नाम **पूरे**
    group में unique होना ज़रूरी है, और जिन दो servers पर आपका नियंत्रण नहीं है वे कभी न कभी टकराएँगे ही।

## `component_name_hook` {#component_name_hook}

इसे servers पर नहीं, group पर ठीक किया जाता है। `(name, server_info)` लेने वाला function pass करें, और group उसे हर उस नाम पर चलाता है जिसे वह register करता है:

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

इसे फिर चलाएँ। `print(sorted(group.tools))` अब दोनों दिखाता है:

```text
['Library.search', 'Web.search']
```

* **key** आपकी है। `by_server` ने इसे `server_info.name` से बनाया, यानी वह नाम जिससे हर `MCPServer(...)` बनाया गया था।
* अंदर का `Tool` जस का तस है: `group.tools["Web.search"].name` अब भी `"search"` है, और `call_tool` wire पर यही नाम भेजता है। prefix आपके process से बाहर कभी नहीं जाता।
* बात सिर्फ़ tools की नहीं है। library का `hours` resource `Library.hours` नाम से register होता है।

!!! tip
    hook **हर** server के **हर** नाम पर चलता है, सिर्फ़ टकराव पर नहीं: सिर्फ़-टकराव-पर-prefix
    जैसा कोई mode नहीं है। एक scheme चुनें और उसे हर जगह लागू होने दें।

## servers जोड़ना और हटाना {#adding-and-removing-servers}

`connect_to_server` वह `ClientSession` लौटाता है जो उसने खोला। अगर कभी उस server को हटाना हो तो इसे संभालकर रखें: `await group.disconnect_from_server(session)` उसके tools, resources और prompts group से हटा देता है।

अगर आपके पास पहले से जुड़ा हुआ `ClientSession` है (`Client.session` ऐसा ही एक है), तो नया transport खोलने के बजाय उसे `await group.connect_with_session(server_info, session)` को सौंप दें। यह उसी तरह aggregate करता है। group कभी ऐसा session बंद नहीं करता जो उसने खुद नहीं खोला। `server_info` component prefixes के लिए server का नाम देता है; 2026 पीढ़ी के connection पर `client.server_info` `None` हो सकता है (identity वैकल्पिक है), इसलिए उस स्थिति में अपना `Implementation(name=..., version=...)` pass करें।

## Classic handshake {#the-classic-handshake}

`ClientSessionGroup` `Client` पर नहीं, `ClientSession` पर बना है। हर `connect_to_server` classic `initialize` handshake चलाता है। यह **[Protocol versions](../protocol-versions.md)** में बताया गया `server/discover` probe कभी नहीं भेजता। हर MCP server वह handshake समझता है, इसलिए इससे किसी के साथ भी compatibility नहीं खोती; इसका मतलब बस इतना है कि group ऐसे server तक भी पुराने, धीमे रास्ते से पहुँचता है जो बेहतर कर सकता था।

## सारांश {#recap}

* `ClientSessionGroup` कई server connections रखता है और उनके tools, resources और prompts को एक-एक `dict` में मिला देता है।
* हर server के लिए `connect_to_server(params)`। यह transport parameters लेता है, कभी वह server object या URL नहीं जो `Client` लेता है।
* `group.call_tool(name, arguments)` आपके लिए call को उस server तक पहुँचाता है जिसका वह tool है।
* नाम पूरे group में unique होने ज़रूरी हैं; `search` tool वाले दो servers अपने आप साथ नहीं रह सकते।
* `component_name_hook=` हर register किए गए नाम को फिर से लिखता है। dict key बदलती है, wire पर जाने वाला नाम नहीं।
* `connect_with_session` पहले से आपके पास मौजूद session जोड़ता है; `disconnect_from_server` एक session हटाता है।

group कौन सा handshake बोलता है (और `Client` किस तेज़ handshake को तरजीह देता है), यही **[Protocol versions](../protocol-versions.md)** का विषय है।
