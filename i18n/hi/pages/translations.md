---
translation:
  sections: [f671b445b16e4f99, 3983a560eb2cece7, b5c8bd4f2b3903e5, c6e2debf1da06eb7, 81d412ed5f399f94]
  tool: 1
---
# अनुवाद {#translations}

यह documentation अंग्रेज़ी में लिखी गई है। इसे ज़्यादा लोगों के लिए उपयोगी बनाने के लिए हम इसके machine-translated संस्करण भी प्रकाशित करते हैं। यह page बताता है कि इसका आपके लिए क्या मतलब है और इन्हें बेहतर बनाने में आप कैसे मदद कर सकते हैं।

## क्या उपलब्ध है {#whats-available}

अनुवादित documentation फ़िलहाल बारह भाषाओं में **preview** के रूप में उपलब्ध है: Deutsch, español, français, हिन्दी, 日本語, 한국어, português (Brasil), русский язык, Türkçe, українська мова, 简体中文 और 繁體中文। किसी भी page के ऊपर बने language switcher से भाषा चुनें। जब ये भाषाएँ अपनी उपयोगिता साबित कर देंगी, तो और भाषाएँ भी जोड़ी जा सकती हैं।

API reference का अनुवाद नहीं किया गया है: अनुवादित site उसी एक अंग्रेज़ी reference से link करती है।

## अंग्रेज़ी ही सही मानी जाएगी {#english-is-the-source-of-truth}

अगर किसी अनुवादित page और उसके अंग्रेज़ी मूल में फ़र्क हो, तो अंग्रेज़ी page सही है। अनुवादित site का हर page इन तीन notes में से किसी एक से शुरू होता है, जो बताता है कि वह page किस स्थिति में है:

- **Machine translation** — page का अनुवाद अपने आप किया गया है और उसमें उसके अंग्रेज़ी मूल का link है।
- **Translation behind the English page** — page का अनुवाद होने के बाद अंग्रेज़ी मूल बदल गया है। आप अब भी वही अनुवाद पढ़ रहे हैं, इसलिए जब तक वह अंग्रेज़ी के बराबर नहीं आ जाता, इसके कुछ हिस्से पुराने हो सकते हैं; note में मौजूदा अंग्रेज़ी page का link है।
- **Shown in English** — इस page का अनुवाद अभी तक नहीं हुआ है, इसलिए आप अंग्रेज़ी text पढ़ रहे हैं।

## अनुवाद कैसे बनते हैं {#how-the-translations-are-made}

अनुवादित pages इसी repository के एक tool से `docs/` के अंग्रेज़ी pages से machine-generated होते हैं। हर भाषा के लिए इंसानों के लिखे दो inputs इसका मार्गदर्शन करते हैं: एक style guide (register, tone, typography, मज़ाक और मुहावरों को कैसे संभालना है) और एक glossary (कौन से terms अंग्रेज़ी में रहेंगे, और बाकी के लिए ज़रूरी और मना किए गए renderings)। Generate हुए text को कभी हाथ से edit नहीं किया जाता। हर सुधार इन्हीं inputs में जाता है, ताकि अगली बार pages फिर से generate होने पर भी वह बना रहे।

## अनुवाद की समस्या की सूचना देना {#reporting-a-translation-problem}

कोई गलत term, अटपटा वाक्य, या ऐसा अनुवाद मिला जो अंग्रेज़ी में कही ही नहीं गई बात कहता हो? भाषा, page और उस अंश के साथ [issue खोलें](https://github.com/modelcontextprotocol/python-sdk/issues); मूल भाषा बोलने वालों की reports खास तौर पर कीमती हैं। अगर आपको सुधार पता है, तो उसे सीधे [`i18n/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/i18n) के अंदर उस भाषा की style guide (`instructions.md`) या glossary (`glossary.json`) पर pull request के रूप में प्रस्तावित करें — फिर अगली बार अनुवाद generate होने पर वह सुधार हर प्रभावित page तक पहुँच जाता है। अंग्रेज़ी text की समस्याएँ, documentation के किसी भी दूसरे बदलाव की तरह, `docs/` के pages में ठीक की जाती हैं।
