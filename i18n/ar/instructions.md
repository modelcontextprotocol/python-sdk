# Arabic (ar) — translation instructions

Target language: Modern Standard Arabic (العربية الفصحى), directory and URL
code `ar`, page language tag `ar`. These instructions accompany the shared
rules in `../general-prompt.md`; `glossary.json` wins terminology conflicts.

## 1. Register

Write clear Modern Standard Arabic for software developers across the Arabic-speaking
world. Use neither regional dialect nor ornate literary or bureaucratic language.
Address the reader with direct singular imperatives: "ثبّت", "أنشئ", "شغّل", "مرّر".
Prefer verbs to nominal constructions: "شغّل الخادم", not "قم بعملية تشغيل الخادم".
Use "يمكنك" for can, "يجب" for must, "ينبغي" for should, and "قد" for may
when it expresses possibility; never weaken a requirement or turn an option into one.
Do not add "يرجى" to instructions that are direct in English.

## 2. Voice

Sound like an experienced Arabic-speaking developer explaining the SDK to a colleague:
direct, practical, and approachable. Prefer short sentences and familiar connectors
such as "ثم", "لذلك", and "أي". Preserve every technical claim, caveat, condition,
negation, example, and step, including those in a friendly aside. Recast clause order
when Arabic needs it without rearranging blocks or changing emphasis.

Avoid inflated introductions such as "تجدر الإشارة إلى" and "من الجدير بالذكر",
mechanical English word order, excessive passive voice, and transliterated verbs.
"Returns" is "يعيد" in a function description, not "يرجع إلى". "Expose" means
"يتيح" in MCP prose, not "يفضح". "Argument" means a passed value, never a dispute.
Distinguish the MCP host application from the client inside it and the server it
connects to. Distinguish authentication (المصادقة) from authorization (التفويض).

## 3. Humour and idioms

Translate the meaning of an idiom rather than its literal image. "Out of the box"
is "افتراضيًا"; "under the hood" is "داخليًا"; "the whole story" is "التفاصيل كاملة".
"That's it. It's just Python." is "هذا كل شيء. إنها Python فحسب.".
Keep short payoff sentences short. Preserve the source's emojis and punctuation
emphasis without adding new ones. Do not omit an aside or invent explanatory notes.

## 4. Typography

Arabic prose reads right to left; Latin identifiers and code retain their original
left-to-right spelling. Do not reverse text, insert invisible bidi control characters,
or wrap identifiers in added HTML or Markdown. Direction is the site's responsibility.
Use the Arabic comma "،", semicolon "؛", and question mark "؟" in prose; retain
ordinary colons, parentheses, straight quotes, and the source's Markdown syntax.
Do not translate punctuation inside code, URLs, or pinned heading anchors.

Use ASCII digits throughout, including quantities, ports, versions, dates, HTTP
status codes, percentages, RFCs, and SEPs. Preserve decimal separators and protocol
revision identifiers exactly. Avoid decorative elongation (tatweel) and full vowel
marks; use an occasional mark only to resolve ambiguity. Spell hamza and final
letters correctly (إعداد، إنشاء، استدعاء، واجهة، مكتبة).

Translate headings, table cells, admonition titles, tab labels, link text, and image
alt text. Product/package names used as labels (uv, pip, Claude Desktop) stay as named.
When referring to an actual English UI tab, keep its displayed label (Tools,
Resources, Resource Templates, Prompts) so the reader can find it. Preserve bold and
italic emphasis on the corresponding meaning and never add code spans.

## 5. Terminology pointer

Follow `glossary.json` consistently, allowing normal Arabic inflection, definiteness,
agreement, and plural forms (أداة / الأدوات، مورد / الموارد، عميل / العملاء).
The listed targets name concepts; do not force the singular into a plural sentence.
Everything in a code span or fenced block stays byte-identical, including comments,
docstrings, strings, snippet includes, annotation markers, and error messages.
API identifiers, classes, functions, parameters, modules, headers, environment
variables, commands, and protocol methods stay unchanged even outside code font.

On a page's first prose use of an unfamiliar MCP concept, include its English term
in parentheses where the glossary asks for it. Subsequent uses use Arabic alone.
Do not add a gloss to a code identifier or to a heading when the concept is explained
in the body. Acronyms and proper names in `keep` remain exactly as in the source.
Translate all other reader-visible English; do not leave whole sentences in English.

## 6. Provisional note

These choices require review by native Arabic-speaking developers. Propose durable
corrections here or in `glossary.json`, then regenerate the affected pages; do not
patch generated `pages/` or `notices.md`. The normal command is
`translate --lang ar --pages …`; the English documentation remains authoritative.
