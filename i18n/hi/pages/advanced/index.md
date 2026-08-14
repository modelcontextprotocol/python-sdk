---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# Advanced {#advanced}

एक साधारण server या client को जो कुछ चाहिए, उस सबकी विषय के हिसाब से जगह ऊपर के sections में है।
यह section उन रास्तों के लिए है जिनकी ज़रूरत तब पड़ती है जब `MCPServer` की convenience
layer आड़े आने लगे:

* **[Low-level Server](low-level-server.md)**: वह class जिस पर `MCPServer` बना है।
  हाथ से लिखे schemas, `on_*` handlers, आपके लिए कुछ भी check नहीं होता, और आपके अपने custom JSON-RPC
  methods।
* **[Pagination](pagination.md)** और **[Middleware](middleware.md)**: दो चीज़ें जो आप
  **सिर्फ़** low-level `Server` पर ही कर सकते हैं।
* **[Extensions](extensions.md)** और **[MCP Apps](apps.md)**: protocol की
  extension surface। extension packages को server में जोड़ें, या अपना खुद का लिखें।

कुछ चीज़ें जिन्हें आप शायद यहाँ ढूँढें, असल में वहीं रखी गई हैं जहाँ उनका इस्तेमाल
होता है:

* **Authorization**, **[अपना server चलाना](../run/index.md)** के अंतर्गत है, क्योंकि server
  को वहीं सुरक्षित किया जाता है जहाँ उसे deploy किया जाता है।
* **OAuth**, **identity assertion**, **एक से ज़्यादा servers** से जुड़ना, और
  response **cache**, ये सब **[Clients](../client/index.md)** के अंतर्गत हैं।
* **Multi-round-trip requests** और **Subscriptions**,
  **[आपके handler के अंदर](../handlers/index.md)** के अंतर्गत हैं, क्योंकि दोनों ही ऐसे काम हैं जो
  handler **करता** है।
* **URI templates**, **[Servers](../servers/index.md)** के अंतर्गत है, Resources के बगल में।
* **[Protocol versions](../protocol-versions.md)** और
  **[Deprecated features](../deprecated.md)**, दोनों का अपना-अपना top-level page है।

अगर आपको पक्का नहीं पता कि इस section की ज़रूरत है या नहीं, तो नहीं है।
