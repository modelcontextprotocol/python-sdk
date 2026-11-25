# Hindi (hi) — translation instructions

Target language: Hindi (हिन्दी) in Devanagari script, directory and URL code
`hi`, page language tag `hi`. This file is sent verbatim with every
translation request for this language, on top of the shared rules in
`../general-prompt.md`. The termbase in `glossary.json` is sent alongside it
and wins any terminology conflict with this file.

## 1. Register

Write modern technical Hindi the way Indian developers write it for each
other: polite-neutral, plain, at ease with English words in Hindi sentences.

- Address the reader as **आप**, always, with the matching plural-honorific
  agreement: आप देख सकते हैं, आप चाहें तो, आपका server. Never तुम or तू forms
  (बनाओ, चलाओ, तुम्हारा), never the colloquial आप + -ो (आप देखो), never a
  mix. Agreement with आप is the generic masculine plural (कर सकते हैं), with
  no सकते/सकती doublets.
- Steps and instructions are the polite -ें / -एँ imperative: बनाएँ, चलाएँ,
  जोड़ें, खोलें, install करें — करें / दें / लें, not कीजिए / दीजिए / लीजिए, so a
  page has one imperative shape; prohibitions are न + the same form (stdout
  पर कुछ न लिखें). No कृपया before every step, and no bare -ना infinitive as
  a command in body text (folder बनाना ✗ as a step).
- Headings, tab labels and table headers are noun phrases or -ना verbal
  nouns: "Handling errors" → errors संभालना, "Running your server" → अपना
  server चलाना. A short imperative heading may stay one ("Run it" → इसे
  चलाएँ), and a question may stay a question (यह कहाँ जाए?).
- Hindi does not need a pronoun in every clause. Translate "you" / "your"
  with आप / आपका only where the sentence needs a subject or the ownership
  matters; "your server" is usually just server, and three or four आप in one
  paragraph is a signal to restructure. Name the role (server, client, user)
  rather than leaning on यह / वह / इसे chains. The authorial "we" is हम.
- One page, one register: a page that drifts from आप to तुम, or from करें to
  कीजिए to करो, is wrong even when each sentence is acceptable on its own.

## 2. Voice

The English is warm, direct and confident: short sentences, second person,
the occasional one-line payoff ("That's the whole API."). Educated everyday
Hindi carries that tone naturally; keep the payoff lines short — पूरा API बस
इतना ही है। Guide rather than lecture: split long English sentences and follow
Hindi word order (verb last) rather than the English clause chain, but
never merge, drop or reorder the technical claims themselves.

- Technical actions use the natural light-verb pattern — install करें,
  import करें, call करें, register करें, deploy करें, parse करता है — and
  everyday actions use plain Hindi verbs: चलाएँ (run), भेजें, लिखें, पढ़ें,
  खोलें, जोड़ें, हटाएँ, बदलें, चुनें, बनाएँ, पूछें, लौटाता है (returns), मिलता है.
- Avoid शुद्ध-हिन्दी officialese, the default failure of formal Hindi
  translation: no उपर्युक्त / निम्नलिखित (→ ऊपर बताया गया / नीचे दिया गया), no
  प्रदान करना where देना is meant, no करने में सक्षम हैं for "can" (→ कर
  सकते हैं), no के द्वारा passives where an active sentence is natural ("The
  tool is called by the model" → model tool को call करता है), and none of the
  coinages the glossary rules out (संचिका, प्रलेखन, कार्यान्वयन, पदावनत).
- Avoid English-shaped Hindi too — एक as an article in every noun phrase
  ("That's a complete MCP server" → यह पूरा MCP server है, not यह एक पूर्ण
  MCP server है), जो कि chains, word-for-word idioms — and the opposite
  over-correction: no street Hinglish (यार, मस्त, झट से), no तुम.

Example — English: "You don't construct it and you don't configure it. You
ask for it."

- Not this (officialese, pronoun in every clause): आप इसका निर्माण नहीं करते
  हैं और आप इसे कॉन्फ़िगर नहीं करते हैं। आप इसके लिए अनुरोध करते हैं।
- Not this either (तुम register, slang): इसे बनाना-वनाना नहीं है, configure
  भी नहीं। बस माँग लो यार।
- This: न आपको इसे बनाना है, न configure करना है। बस माँगना है।

## 3. Humour and idioms

- Translate the intent of a joke, aside or idiom, never its words. Recast it
  as a friendly plain sentence carrying the same information; if a light
  phrase carries no information, keep the sentence brief rather than
  inventing a Hindi joke or reaching for a मुहावरा. Never drop the technical
  content around it; culture-bound references take the plain meaning.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → पूरी जानकारी **[X](…)** में
  है।; "That's the whole API." / "That is the whole API." → पूरा API बस इतना
  ही है।; "That's the whole protocol." → पूरा protocol बस इतना ही है।;
  "That's it. It's just Python." → बस इतना ही। यह सिर्फ़ Python है।; "You get
  `3` back. ✨" → आपको `3` वापस मिलता है। ✨
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → बिना कुछ configure किए
  app **सिर्फ़** उन्हीं requests का जवाब देता है जो localhost को भेजी गई हों। —
  not डिब्बे से निकालते ही. "Under the hood" → अंदर ही अंदर / असल में.
- Exclamation marks: one only where the English is genuinely emphatic; never
  doubled, never in a heading, never after a warning. Emoji: only where the
  English page has one, in the same place (✨ closes two payoff lines); never
  add one, never in a heading.

## 4. Typography

- The sentence terminator is the danda । (U+0964): every declarative and
  imperative sentence of Hindi prose ends in ।, no space before it, one
  space after. Never a Latin full stop after Devanagari text, never the pipe
  character | in place of the danda, never the double danda ॥. Question and
  exclamation marks, commas, colons and parentheses are ASCII, used as in
  the source; a fragment in a list or table takes no terminator.
- Digits are Latin (0–9) everywhere — counts, versions, ports, status codes
  — never Devanagari numerals (०–९). Identifiers are copied byte for byte
  (`2026-07-28`, RFC and SEP numbers, error codes); a calendar date written
  out in prose, if any, becomes 28 जुलाई 2026. A space between a number and
  a Latin unit (100 MB, 30 s); % attaches (100%); number words stay words.
- Straight double quotes "…" and ASCII apostrophes as in the source; no
  curly or single quotes. No italics on Devanagari (a slanted शिरोरेखा reads
  as broken): where the English italicises a word that becomes Hindi, use
  **bold** or nothing; keep `**bold**` where the source has it, negations
  included ("does **not** raise" → raise **नहीं** करता). An English em-dash
  aside is recast with commas, parentheses or a second sentence, or keeps
  the source's " — "; hyphens stay in pairs (अलग-अलग), never on postpositions.
- Spelling follows current standard Hindi: chandrabindu on nasalised vowel
  endings (बनाएँ, जाएँ, भाषाएँ; में, हैं, नहीं keep the bindu), nuqta where
  standard Hindi has it (ज़रूरत, सिर्फ़, फ़ायदा; ड़ / ढ़ always), गई / गए / नई /
  लिए rather than गयी / गये / नयी / लिये, and one spelling per word per page
  (हिन्दी or हिंदी, not both).
- Spacing around Latin script and code: a postposition or particle after an
  English word, an acronym or a code span is a separate word with one
  ordinary space before it — Python में, MCP का, `ctx` को, `add` से, server
  पर, tools की सूची — never glued (Pythonमें ✗), never hyphenated (Python-में
  ✗), and never a Devanagari ending grafted onto a Latin word (serverों ✗).
  Compound labels keep their space too: MCP server, tool call. Line breaks
  inside a paragraph are harmless in Hindi; keep the source's block
  structure and indentation exactly.

## 5. Terminology pointer

The termbase `glossary.json` is injected separately and overrides anything
written here. This section fixes the conventions its renderings assume:

- Script rule. English technical and computing terms stay in Latin script,
  lower-case as in running English, and are not transliterated: server,
  client, host, tool, resource, prompt, request, response, file, code, app,
  schema, token — not सर्वर, क्लाइंट, टूल, रिक्वेस्ट, फ़ाइल. Hindi words are for
  everything that is ordinary language (उदाहरण, तरीका, सवाल, जवाब, सूची, चरण,
  बदलाव, ज़रूरत, सुरक्षा, अनुमति), and Sanskritised coinages for technical
  concepts (संचिका for file, सत्र for session, अनुरोध for the protocol
  request) are not used. The only Devanagari loanwords are the few that are
  everyday Hindi beyond computing (कंप्यूटर, इंटरनेट, ईमेल); when unsure, Latin.
- Latin-script terms stay lower-case even first in a Hindi sentence or
  heading (server चलाएँ); a heading made only of English words takes English
  sentence case (Structured output). They may take the English plural -s
  where Hindi grammar calls for a plural and no Hindi word carries the
  number (सभी tools, इन clients को), never a possessive 's (→ server का);
  `keep`-list terms are copied exactly as listed, no s added (दोनों SDK).
- Grammatical gender of Latin-script nouns, for verb and का / की / के
  agreement, is masculine by default (server, tool, token, response, error,
  code, app, object, message, schema …) and feminine for file, directory,
  library, repository, registry, key, query, entry, property, body,
  capability, dependency, request, list, line, class, API, ID, image and
  the -ing nouns (sampling, logging, caching). One gender per term per page.
- Identifiers — class, function, parameter, module and package names,
  protocol method strings (`tools/call`), header names, environment
  variables, anything in code font — are copied byte for byte and take
  postpositions like any Latin word (`Context` को, `lifespan=` में).
- Text quoted from what the example code prints or displays — an output
  line, a log message, an error string, a UI label such as the Inspector's
  **Tools** and **Resources** tabs — stays exactly as the code emits it
  (usually English); do not translate it or add a Hindi reading in brackets.
- Between an everyday word and its formal twin (ज़रूरी / आवश्यक, शुरू / आरंभ,
  इस्तेमाल / प्रयोग) prefer the everyday one and keep to it. One rendering per
  term per page: the glossary target, every time — also where a note marks
  it provisional.

## 6. Provisional note

Every decision in this file — the आप register, the Latin-script rule for
technical terms, the genders, the fixed renderings — and every entry in
`glossary.json` is provisional pending review by native Hindi-speaking
developers. To propose a change, edit this file or `glossary.json` in a pull
request; the generated pages under `pages/` are never edited by hand.
