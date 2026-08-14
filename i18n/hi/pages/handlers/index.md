---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# आपके handler के अंदर {#inside-your-handler}

handler के arguments client से आते हैं। इसके **अलावा** वह जो कुछ पढ़ सकता है, और चलते समय जो कुछ कर सकता है, वह सब यहाँ है।

वह क्या पढ़ सकता है:

* **[Context](context.md)** वह एक अतिरिक्त parameter है जिसे कोई भी handler माँग सकता है: चल रही request, उसके headers, उसका session, और progress व change-notification के verbs।
* **[Dependencies](dependencies.md)** वे parameters हैं जिन्हें model कभी नहीं देखता; इन्हें `Resolve` के ज़रिए आपके अपने functions भरते हैं।
* **[Lifespan](lifespan.md)** उस state के बारे में है जिसे server startup पर एक बार बनाता है, और handler `Context` के ज़रिए उस तक कैसे पहुँचता है।

चलते समय वह क्या कर सकता है:

* **[Elicitation](elicitation.md)** से user से और input माँगना, और **[Multi-round-trip requests](multi-round-trip.md)**, 2026-07-28 का वह pattern जो इसे ले जाता है।
* **[Sampling और roots](sampling-and-roots.md)** से client से LLM completion या उसके workspace folders माँगना; ये deprecated हैं पर अब भी serve होते हैं।
* किसी धीमे काम पर **[Progress](progress.md)** बताना।
* **[Logging](logging.md)** से logs लिखना (standard error पर, server चलाने वाले के लिए)।
* **[Subscriptions](subscriptions.md)** से subscribe किए हुए clients को बताना कि कुछ बदला है।

अगर आपने अभी तक कोई handler register नहीं किया है, तो **[Tools](../servers/tools.md)** से शुरू करें। यहाँ का हर page मानकर चलता है कि आपके पास एक handler है।
