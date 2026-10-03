---
translation:
  sections: [09defc170a0da89d]
  tool: 1
---
# Servers {#servers}

`MCPServer` जुड़े हुए client को तीन primitives देता है। इनमें फ़र्क इस बात का है कि
इन्हें इस्तेमाल करने का फ़ैसला कौन करता है:

* **[tool](tools.md)** वह action है जिसे **model** चुनता और call करता है। यही
  वह page है जो ज़्यादातर लोग सबसे पहले चाहते हैं, और
  **[Structured Output](structured-output.md)** इसका reference साथी है:
  tool जो लौटाता है उसके आकार से जुड़ी हर बात वहाँ है।
* **[resource](resources.md)** read-only data है जिसे **application**
  पढ़ना चुनता है। **[URI templates](uri-templates.md)** इसका reference
  साथी है: addressing का पूरा syntax और path-safety के नियम।
* **[prompt](prompts.md)** एक message template है जिसे कोई **इंसान** नाम से
  invoke करता है, menu से या slash command से।

इन तीन primitives के इर्द-गिर्द वह सब है जो server और declare करता है:

* **[Completions](completions.md)** prompt और resource-template के arguments
  के लिए server-side autocomplete है।
* **[Images, audio & icons](media.md)** में वह सब है जो tool text के अलावा
  लौटा सकता है, और वे icons जो client आपके server के बगल में दिखाता है।
* **[Handling errors](handling-errors.md)** समझाता है कि जिस error से model
  उबर सकता है और जिसे model को कभी नहीं देखना चाहिए, उन दोनों में क्या फ़र्क है।

यहाँ का हर page अपने आप में पूरा है; सीधे उसी पर जाएँ जिसकी ज़रूरत है। अगर अभी तक
कोई server नहीं बनाया है, तो इसके बजाय **[पहले कदम](../get-started/first-steps.md)** से शुरू करें।

जो functions आप register करते हैं उनके **अंदर** क्या होता है (`Context`, dependency injection,
call के बीच में user से और input माँगना), वह अगला section है,
**[आपके handler के अंदर](../handlers/index.md)**।
