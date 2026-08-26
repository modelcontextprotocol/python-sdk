# Simplified Chinese (zh) — translation instructions

Target language: Simplified Chinese (简体中文), directory and URL code
`zh`, page language tag `zh-Hans`. This file is sent verbatim with every
translation request for this language, on top of the shared translation rules
in `../general-prompt.md`. The termbase in `glossary.json` is sent alongside
it and wins any terminology conflict with this file.

## 1. Register

Write the casual-neutral written register that Chinese developer
documentation uses: plain, matter-of-fact, and even.

- Address the reader as 你. Never use the honorific 您, and never mix the
  two. The rule holds in body prose, headings, admonition titles, table
  cells and link text.
- Prefer no pronoun at all when the sentence stays clear — Chinese
  instructions read naturally without a subject: "You can pass a schema" →
  可以传入一个模式. Reach for 你 only where the sentence would otherwise be
  ambiguous about who acts.
- Steps and instructions are bare imperatives without a subject:
  "Run the server" → 运行服务器, not 请您运行服务器. A single 请 is fine where
  it reads natural; a 请 in front of every step is not.
- The register is uniform across a page. A page that drifts between 你 and
  您, or between plain and formal sentence endings, is wrong even when each
  sentence is acceptable on its own.

## 2. Voice

Aim for the voice of an experienced Chinese-speaking engineer explaining a
library to a colleague: warm, direct, professional, compact. The English is
built on short declarative payoff sentences ("That's a complete MCP
server."); keep them short — 这就是一个完整的 MCP 服务器。

Do:

- Follow Chinese word order and rhythm. Break one long English sentence
  into two Chinese ones instead of mirroring its clause structure.
- Use concrete verbs (运行, 传入, 返回, 声明, 阻塞) rather than nominal chains.
- Keep the source's directness. Where the English says "don't", the
  Chinese says 不要, not a hedge like 也许可以考虑避免.

Avoid — these are the marks of a machine or customer-service translation:

- 您, and its whole register: 温馨提示, 亲, 敬请, 感谢您的耐心等待.
- Formal padding: 进行……操作, 对……进行处理, and 可能像下面这样, where a plain
  是这样的 does the job.
- English-shaped Chinese: possessive chains (你的服务器的工具的模式), 被 passives
  where a topic-comment sentence is natural, and a translated connective
  (然而, 因此, 此外) at the start of every sentence.
- Marketing hype and internet slang: 神器, 保姆级, 给力, 强大到没朋友.

## 3. Humour and idioms

The English is friendly and dry rather than jokey: short payoff sentences,
a few stock phrases, the rare emoji. Carry the friendliness; recast the
idioms.

- Never translate a pun, idiom or aside literally. Say what it means as a
  short, natural Chinese sentence in the same register. If an aside carries
  no information you may drop it — but never drop a technical caveat that
  happens to be phrased lightly.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → 详见 **[X](…)**;
  "That's the whole API." / "That's the whole protocol." → 整个 API 就这些。
  / 整个协议就是这样。; "That's it. It's just Python." → 就这样，只是普通的
  Python。
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → 默认情况下，这个应用
  **只**响应发往 localhost 的请求。— not the literal 开箱即用地.
- Emoji: keep the source's rare, deliberately placed emoji exactly where
  they are — two payoff lines end in ✨ ("You get `3` back. ✨"). Never
  add new ones.
- Exclamation marks are rare in Chinese technical prose and the English
  hardly uses them; do not add one to a plain payoff sentence.

Worked examples (source → good / bad):

- "You get `3` back. ✨" → good: 返回值是 `3`。✨ / bad: 你会得到3！✨
  (missing Han–Latin spacing, added exclamation).
- "Give a parameter a default value and it stops being required. That's
  it. It's just Python." → good: 给参数设一个默认值，它就不再是必填参数。
  就这样，只是普通的 Python。/ bad: 给一个参数一个默认值，然后它就停止是必需的了。
  就是它。它只是Python而已！(English-shaped 它 chain, missing Han–Latin
  spacing, added exclamation).

## 4. Typography

- Chinese prose takes full-width punctuation: ，。：；！？、（）“” with ‘’
  nested inside “”, the dash —— and the ellipsis ……. Punctuation inside
  code spans, code blocks, commands, URLs and quoted English text stays
  half-width and untouched.
- Enumerations in prose use the enumeration comma 、: "a, b, and c" →
  a、b 和 c, not a，b，和 c.
- Put one half-width space between Han characters and any run of Latin
  letters or digits (使用 Streamable HTTP 传输; 需要 Python 3.10+); put no
  space between a full-width punctuation mark and adjacent Latin text
  (配置好 stdio。). Keep the spaces around Markdown markers (`**…**`,
  links) exactly as the source has them.
- No italics in Chinese text. Where the source italicises a word for
  emphasis, use **bold**; where the source italicises an example utterance
  or a hypothetical question the user might see, wrap it in “” instead.
  Keep bold on the same words the source bolds — a bolded negation
  ("**not**" → "**不是**" / "**不会**") stays bold.
- Digits stay half-width Arabic numerals. Protocol revision strings such
  as `2026-07-28` and `2025-11-25` are identifiers, copied byte-for-byte —
  never 2026年7月28日, never 2026/07/28. Other dates keep the source's format.
- Numbers and units: half-width digits with a space before a Latin unit
  (10 MB); % and ° attach with no space; a Chinese unit needs no space
  (5 秒).
- Line breaks: never put a newline between two Chinese characters (Han or
  full-width punctuation), not even after 。 — the renderer turns it into a
  stray space. Where the English wraps a paragraph, list item or admonition
  body over several lines, or gives each sentence its own line, write the
  Chinese on one line, sentence after sentence; block structure and
  indentation otherwise stay as in the source. The home page's opening
  note puts "New to v2…", "Still on v1.x?…" and "Something rough or
  confusing?…" on three lines; in Chinese that body is the single indented
  line 刚接触 v2……破坏性变更。还在用 v1.x？……。哪里不顺手或看不明白？…… and
  three indented lines there are wrong. A prose line that ends in a Chinese
  character followed by a line of the same block that starts with one is
  always a defect to fix — join the two.

## 5. Terminology pointer

The termbase is `glossary.json` next to this file. It is injected into the
prompt separately and its renderings override anything written here. This
section only fixes the conventions the glossary assumes:

- Terms in the glossary's keep list, and any other English word left in
  Latin script, are copied exactly as spelled and always in the singular,
  with no article and no English plural "s": "the URIs" → URI, "children" →
  child. They are never transliterated or re-cased; the spacing rule in §4
  sets them off from the surrounding Han text.
- Everything in code font, plus API names, class, function and parameter
  names, protocol method and message strings (`tools/call`,
  `notifications/...`), header names, error codes, SEP numbers and product
  names, stays in Latin script inline. A glossary term used as a code-font
  identifier stays Latin even though its prose noun is translated:
  "the `sampling` capability" → `sampling` 能力.
- Text quoted from what the example code prints or displays — an output
  line, a log message, a UI label — stays exactly as the code emits it
  (usually English), in or out of code font.
- First-use gloss: a translated MCP concept the reader may need to map back
  to the English specification carries the English in full-width parentheses
  on its first occurrence on a page — 采样（sampling） — and appears alone
  after that. Each glossary entry's note says whether the term takes the
  gloss.
- One rendering per term per page: the glossary target, every time. Where an
  entry's note marks the choice as open or provisional, still use the listed
  target consistently rather than picking per sentence.

## 6. Provisional note

The register, voice and terminology decisions above are provisional,
pending review by native Chinese-speaking readers. To propose a change, edit
this file or `glossary.json` in a pull request; never edit the generated
pages under `pages/` or `notices.md` next to this file. The tool cannot tell
a hand edit from its own output, so one would persist unchecked and be
carried forward into later runs; a correction made here reaches the pages
when they are regenerated with `translate --lang zh --pages …`.
