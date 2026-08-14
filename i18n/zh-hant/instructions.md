# Traditional Chinese, Taiwan (zh-hant) — translation instructions

Target language: Traditional Chinese as written for readers in Taiwan (繁體中文，台灣用語),
directory and URL code `zh-hant`, page language tag `zh-Hant`. This file is sent verbatim
with every translation request for this language, on top of the shared translation rules
in `../general-prompt.md`. The termbase in `glossary.json` is sent alongside it and wins
any terminology conflict with this file.

This is a language target in its own right, translated directly from the English — never
a character conversion of a Simplified Chinese text. Taiwan and Mainland usage differ in
hundreds of everyday computing words (伺服器／服务器, 程式碼／代码, 預設／默认, 物件／对象);
a converted page reads as foreign in Taiwan even when every character is Traditional.

## 1. Register

Write the casual-neutral register that developer documentation in Taiwan uses: plain,
even, close to how an engineer explains something aloud, without being chatty.

- Address the reader as 你. Never the honorific 您, never 您們, and never a mix. The rule
  holds in body prose, headings, admonition titles, table cells and link text.
- Prefer no pronoun at all when the sentence stays clear: "You can pass a schema" →
  可以傳入一個 schema. Reach for 你 only where the sentence would otherwise be ambiguous
  about who acts. "Your server" is 伺服器, or 你的伺服器 only when ownership is the point.
- Steps and instructions are bare imperatives without a subject: "Run the server" →
  執行伺服器, not 請您執行伺服器. A single 請 is fine where it reads naturally; a 請 in
  front of every step is not, and neither is 若要……，請…… opening every paragraph.
- The register is uniform across a page. A page that drifts between 你 and 您, or between
  plain sentences and stiff officialese, is wrong even when each sentence is fine alone.

## 2. Voice

Aim for the voice of an experienced Taiwanese engineer walking a colleague through a
library: warm, direct, professional, compact. The English is built on short declarative
payoff sentences ("That's a complete MCP server."); keep them short —
這就是一個完整的 MCP 伺服器。

Do:

- Follow Chinese word order and rhythm. Break one long English sentence into two Chinese
  ones instead of mirroring its clause structure, and use concrete verbs (執行, 傳入,
  回傳, 宣告, 阻塞) rather than nominal chains: 進行設定 → 設定; 對……進行處理 → 處理…….
- Keep the source's directness. Where the English says "don't", the Chinese says 不要,
  not a hedge like 或許可以考慮避免.
- Use Taiwan function words: 透過 for "via / through" (通過 means "to pass" a check),
  和／與 for "and", 如果／若 for "if", 即可／就好 to close an instruction lightly.

Avoid — these are the marks of a machine, converted or customer-service translation:

- 您 and its whole register: 溫馨提示, 敬請, 感謝您的耐心, 親愛的使用者.
- Mainland computing vocabulary and colloquialisms, even in Traditional characters:
  服務器, 數據庫, 默認, 信息, 視頻, 質量 (for quality), 反饋, 渠道, 激活, 立馬, 挺好.
- Formal padding (進行……操作, 對……進行……) and document-speak (本文件旨在, 使用者應, 茲).
- English-shaped Chinese: possessive chains (你的伺服器的工具的 schema), 被 passives
  where a topic–comment sentence is natural ("The tool is called by the model" →
  模型會呼叫這個工具), a translated connective (然而, 因此, 此外) at the start of every
  sentence, and 它 standing in for every "it".
- Internet slang from either side of the strait (神器, 保姆級, 給力, 超好用, 就醬), and
  sentence-final particles 喔／囉／啦／耶.

Example — English: "You don't construct it and you don't configure it. You ask for it."

- Not this (您 + officialese): 您無需對其進行建構及配置，僅需提出請求即可。
- Not this either (Mainland casual): 你不用创建它也不用配置它，直接要就完事了。
- This: 不需要自己建立，也不需要設定，只要開口要就好。

## 3. Humour and idioms

- The English is friendly and dry rather than jokey; carry the friendliness, recast the
  idioms. Never translate a pun, idiom or aside literally: say what it means as a short,
  natural sentence in the same register. If an aside carries no information you may drop
  it — but never drop a technical caveat that happens to be phrased lightly.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole story" / "The
  whole story is in **[X](…)**" → 完整說明請見 **[X](…)**; "That's the whole API." /
  "That's the whole protocol." → 整個 API 就這樣。/ 整個協定就這樣。; "That's it. It's
  just Python." → 就這樣，就只是 Python 而已。; "That's a complete MCP server." →
  這就是一個完整的 MCP 伺服器。
- Idioms take the plain meaning, not the picture: "Out of the box the app answers
  **only** requests addressed to localhost." → 預設情況下，這個應用程式**只**回應送往
  localhost 的請求。— not the literal 開箱即用.
- Emoji and exclamation marks: keep the source's rare, deliberately placed emoji exactly
  where they are — two payoff lines end in ✨ ("You get `3` back. ✨") — and never add
  new ones. Do not add an exclamation mark to a plain payoff sentence; where one is kept
  it is the full-width ！, never doubled, never in a heading.
- Worked examples (source → good / bad): "You get `3` back. ✨" → 得到的結果是 `3`。✨
  / 您將獲得3！✨ (您, stiff 獲得, missing Han–Latin spacing, added exclamation). "Give a
  parameter a default value and it stops being required. That's it. It's just Python."
  → 替參數加上預設值，它就不再是必填。就這樣，就只是 Python 而已。/
  給一個參數一個默認值，然後它就停止是必需的了。就是它。它只是Python而已！(Mainland 默認,
  English-shaped 它 chain, missing spacing, added exclamation).

## 4. Typography

- Chinese prose takes full-width punctuation: ，。：；！？、（） with the dash —— and
  the ellipsis ……; enumerations use 、 ("a, b, and c" → a、b 和 c). Parentheses are
  full-width （） even around Latin text, as in the first-use gloss 取樣（sampling）.
  Punctuation inside code spans, code blocks, commands, URLs and quoted English text
  stays half-width and untouched. An English em-dash aside is usually better recast with
  ，, （） or a second sentence than kept as ——; a colon introducing a code block, list
  or example becomes ： or a full sentence ending in 。.
- Quotation marks are the corner brackets 「」, with 『』 nested inside; never “ ” or
  ‘ ’ in Chinese text, and never 「」 around a code span. Titles of works take 《》.
- Put one half-width space between Han characters and any run of Latin letters or
  digits — an English word, a number, an inline code span, a link whose text is Latin
  (使用 Streamable HTTP 傳輸; 需要 Python 3.10+; 會收到 `Context`); put no space between
  a full-width punctuation mark and adjacent Latin text (設定好 stdio。). Keep the spaces
  around Markdown markers (`**…**`, links) exactly as the source has them.
- No italics in Chinese text. Where the source italicises a word for emphasis, use
  **bold**; where it italicises an example utterance or a hypothetical question the user
  might see, wrap it in 「」 instead. Keep bold on the same words the source bolds — a
  bolded negation ("**not**" → **不是** / **不會**) stays bold. Emphasis markers around
  text that stays in English are copied as-is.
- Digits stay half-width Arabic numerals (3 個工具, not 三個). Protocol revision strings
  such as `2026-07-28` and `2025-11-25` are identifiers, copied byte-for-byte — never
  2026 年 7 月 28 日, never 2026/07/28. Version numbers, HTTP status codes, ports, error
  codes, and RFC and SEP numbers are copied exactly. A Latin unit takes a space (10 MB,
  30 s); % attaches with none; a Chinese unit or measure word needs none (5 秒, 3 個).
- Line breaks: never put a newline between two Chinese characters (Han or full-width
  punctuation), not even after 。 — the renderer turns it into a stray space. Where the
  English wraps a paragraph, list item or admonition body over several lines, or gives
  each sentence its own line, write the Chinese on one line, sentence after sentence;
  block structure and indentation otherwise stay as in the source. The home page's
  opening note puts "New to v2…", "Still on v1.x?…" and "Something rough or confusing?…"
  on three lines; in Chinese that body is the single indented line
  剛接觸 v2……破壞性變更。還在用 v1.x？……。哪裡卡住或看不懂？…… — three indented lines
  there are wrong. A prose line ending in a Chinese character followed by a line of the
  same block starting with one is always a defect: join the two.

## 5. Terminology pointer

The termbase `glossary.json` is injected separately and overrides anything written here.
This section fixes the conventions it assumes and the Taiwan forms it does not pin:

- Terms in the glossary's keep list, and any other English word left in Latin script,
  are copied exactly as spelled, always singular, with no article and no plural "s":
  "the URIs" → URI, "schemas" → schema. Everything in code font, plus API names, class,
  function and parameter names, protocol method and message strings (`tools/call`,
  `notifications/...`), header names, error codes, SEP numbers and product names, stays
  in Latin script inline. A glossary term used as a code-font identifier stays Latin
  even though its prose noun is translated: "the `sampling` capability" → `sampling` 能力.
- Text quoted from what the example code prints or displays — an output line, a log
  message, an error string, a UI label such as the Inspector's **Tools** tab — stays
  exactly as the code emits it (usually English), in or out of code font; do not
  translate it or add a Chinese reading.
- First-use gloss: a translated MCP concept the reader may need to map back to the
  English specification carries the English in full-width parentheses on its first
  occurrence on a page — 取樣（sampling）, 徵詢（elicitation） — and appears alone after
  that. Each glossary entry's note says whether the term takes the gloss.
- One rendering per term per page: the glossary target, every time — also where an
  entry's note marks the choice as open or provisional; never pick per sentence.
- Taiwan forms for words the glossary leaves unpinned (the bracketed Mainland form is
  not used): 程式 program〔程序, which means "procedure" in Taiwan〕, 應用程式
  application〔never bare 應用 as a noun〕, 資料庫 database〔數據庫〕, 欄位 field〔字段〕,
  範例 example〔示例〕, 範本 template〔模板〕, 文件／說明文件 documentation〔文檔〕, 設定
  configure, settings〔配置, which means "allocate"〕, 建立 create〔創建〕, 啟用／停用
  enable, disable〔激活, 禁用〕, 介面 interface〔接口〕, 連結 link〔鏈接〕, 登入 log
  in〔登錄〕, 標頭 header〔請求頭〕, 逾時 timeout〔超時〕, 連接埠 port〔端口〕, 執行緒
  thread〔線程〕, 處理程序 process〔進程〕, 權杖 token in the OAuth sense〔令牌〕, 身分
  identity, 疑難排解 troubleshooting〔故障排除, 排查〕, 偵錯 debug〔調試〕, 印出
  print〔打印〕, 圖示 icon〔圖標〕, 音訊 audio〔音頻〕, 型別 type in the data-type
  sense〔類型 is fine for "kind of"〕, 套件 package〔包〕, 相容 compatible〔兼容〕, 串流
  stream〔流〕, 對話 conversation〔會話〕. In a table, a row is 列 and a column is 欄 —
  the reverse of Mainland usage.

## 6. Provisional note

The register, voice and terminology decisions above, and every entry in `glossary.json`,
are provisional pending review by native readers in Taiwan. To propose a change — a
better rendering, a rule that produces awkward Chinese, a missing or wrong Taiwan form —
edit this file or `glossary.json` in a pull request, ideally with a short good/bad
example; never edit the generated `pages/` or `notices.md` next to this file. The tool
cannot tell a hand edit from its own output, so one would persist unchecked and be
carried forward into later runs; a correction made here reaches the pages when they are
regenerated with `translate --lang zh-hant --pages …`.
