# German (de) — translation instructions

Target language: German in Germany's standard orthography (Deutsch, de-DE),
directory and URL code `de`, page language tag `de`. This file is sent verbatim
with every translation request for this language, on top of the shared rules
in `../general-prompt.md`. The termbase in `glossary.json` is sent alongside it
and wins any terminology conflict with this file.

## 1. Register

Address the reader as **du**, consistently — the register of modern open-source
and developer-tool documentation; Sie would read like vendor docs.

- du, dich, dir, dein are lower-case mid-sentence. Never address the reader as
  Sie / Ihnen / Ihr, never capitalised Du / Dein, never a mix — a page that
  drifts between du and Sie, or between direct imperatives and impersonal
  officialese, is wrong even when each sentence is acceptable on its own.
  (Third-person sie and a sentence-initial Sie are ordinary German and fine.)
- Steps are bare du imperatives: "Install the SDK, then run the server" →
  Installiere das SDK und starte dann den Server — not Installieren Sie …, not
  the infinitive SDK installieren in running prose, not Du solltest … (needless
  modal), no bitte per step. Impersonal man only for truly general statements.
  Where English says "your", German often uses the article: öffne das Terminal.
- Headings, table headers, tab labels and admonition titles are noun phrases or
  infinitive constructions, never imperatives: "Declare a tool" → Ein Tool
  deklarieren, "Handling errors" → Fehler behandeln, "Running your server" →
  Den Server betreiben, "The Context" → Der Context. A question heading may
  stay a question (Wohin damit?). No full stop after a heading.
- Requirement strength stays exact: must → muss, should → sollte, may / can →
  kann or darf, must not → darf nicht (muss nicht means "need not").
- Gender-neutral wording by phrasing, never by typography. Sentences about the
  reader (du) or about software (der Client, der Server) need nothing. For
  people use plurals and neutral nouns — alle, die den Host bedienen; wer das
  SDK einsetzt; das Team — and for the single human in front of the host ("the
  user") die Person, or die Person am Host where the role needs naming, then
  sie. Never Nutzer*innen, Nutzer:innen, NutzerInnen or Nutzer/-innen, and no
  bare generic masculine (der Nutzer, der Entwickler) either. Provisional;
  apply it uniformly.

## 2. Voice

The English source is warm, direct and confident: short sentences, the
occasional one-line payoff. Carry that — sachlich, direkt, freundlich.

- Keep the payoff sentences short: "That's the whole API." → Das ist die ganze
  API. — not a formal summary sentence. Split long English sentences: two main
  clauses read better than one nested period with the verb parked at the end.
  Never merge, drop or reorder the technical claims themselves.
- Verbs, not Nominalstil: die Durchführung der Installation erfolgt →
  installiere; eine Überprüfung vornehmen → prüfen. Active where German allows
  it: "The tool is called by the model" → Das Modell ruft das Tool auf.
- No officialese (seitens, mittels, im Rahmen von, es ist darauf zu achten,
  dass, erfolgt as an all-purpose verb), no hype or softeners (leistungsstark,
  nahtlos, im Handumdrehen; du könntest eventuell → du kannst), no
  English-shaped German (Sinn machen → sinnvoll sein, Python's → Pythons, ist
  am Laufen → läuft). Nor the over-correction: no buddy tone (mega, easy).
- Example — "You don't construct it and you don't configure it. You ask for
  it." → Du erzeugst ihn nicht selbst und konfigurierst ihn auch nicht. Du
  forderst ihn einfach an. (ihn: der Context.) Not the Nominalstil Eine
  Instanziierung sowie Konfiguration ist nicht erforderlich; es genügt eine
  Anforderung. — nor the slangy calque Du baust es nicht … fragst danach, easy!

## 3. Humour and idioms

- The English is friendly and dry rather than jokey; the warmth carries over
  into the du register unchanged, the idioms do not. Never translate a pun,
  idiom or aside literally: say what it means as a short, natural German
  sentence in the same register; a German idiom at home in technical prose is
  welcome (unter der Haube for "under the hood"). An aside with no information
  may go — a technical caveat phrased lightly never does.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole story"
  / "The whole story is in **[X](…)**" → Alles Weitere steht in **[X](…)**;
  "That's the whole API." / "That's the whole protocol." → Das ist die ganze
  API. / Das ist das ganze Protokoll.; "That's it. It's just Python." → Das ist
  alles. Ganz normales Python. (not Das ist es. Es ist nur Python!); "You get
  `3` back. ✨" → Du bekommst `3` zurück. ✨ (not Du erhältst 3 zurück! ✨ —
  lost code span, added exclamation mark).
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → Ohne weitere
  Konfiguration beantwortet die App **nur** Requests an localhost — not aus der
  Box heraus. "it stops being required" → er ist nicht mehr erforderlich, not
  er stoppt, required zu sein.
- Exclamation marks: keep one only where the English carries genuine emphasis;
  never add, never double, never in a heading. Emoji: keep the source's rare,
  deliberately placed emoji exactly where they are; never add new ones.

## 4. Typography

- Quotation marks in prose are German „…“ (U+201E, U+201C), with ‚…‘ for a
  quote inside a quote. Straight "…" and English “…” in the source prose become
  „…“, scare quotes and example utterances included. Quotes inside code spans
  and code blocks stay exactly as they are, and a code span is never wrapped in
  quotation marks.
- Dashes: an English em-dash aside becomes a Gedankenstrich — an en dash with a
  space on each side (Text – Einschub – Text) — or commas, parentheses or a
  second sentence; never an em dash (—) in German text. Ranges: 3.10 bis 3.14,
  or 3.10–3.14 with an en dash and no spaces.
- Compounds are closed or hyphenated, never spaced. A compound with an English,
  abbreviated or code-font part is hyphenated through every joint: der
  MCP-Server, das JSON-RPC-Format, der Streamable-HTTP-Transport, das
  `Context`-Objekt, die `PATH`-Umgebungsvariable. Never MCP Server with a space
  (and `MCPServer` is a class, not ein MCP-Server). A multi-word English term
  standing alone stays open: Streamable HTTP, Dependency Injection.
- Every noun is capitalised, borrowed ones included (der Request, das Tool);
  borrowed adjectives and verbs are not (optional, gecacht). Orthography is
  de-DE: dass, muss, schließen, außerdem — never Swiss ss.
- Digits stay ASCII. Protocol revision strings such as `2026-07-28`, version
  numbers, ports, status and error codes, RFC and SEP numbers are identifiers,
  copied byte for byte — never 28.07.2026, never 28. Juli 2026. Prose
  quantities take the decimal comma only when nothing but the separator changes
  (2,5 Sekunden), never inside code; a space before units and % (30 s, 100 %).
- Abbreviations: e.g. → z. B., i.e. → d. h., etc. → usw. (inner space kept);
  vs → oder / gegenüber; & in prose → und. Commas follow German grammar, not
  the source (before dass, weil, wenn, ob and relative clauses).
- Bold and italics land on the words that carry the source's emphasis; a bolded
  negation ("**not**" → **nicht** / **kein**) stays bold. English words kept in
  German text are set in normal type.

## 5. Terminology pointer

The termbase is `glossary.json` next to this file. It is injected into the
prompt separately and its renderings override anything written here. This
section only fixes the conventions the glossary assumes:

- Terms in the glossary's `keep` list are copied exactly — same spelling and
  casing, not translated, italicised or quoted. They take an article by gender
  (das SDK, die API, das JSON, die URL, der URI, das CLI, das LLM, der SEP, der
  RFC) and the English plural where the source is plural (die SDKs).
- Everything in code font — class, function, parameter and module names,
  protocol method strings (`tools/call`), header names, error text, config keys
  — stays byte-identical. Name the kind of thing in front where it helps (die
  Klasse `Context`, der Parameter `lifespan=`); compounds take a hyphen outside
  the backticks (der `Resolve`-Marker). A glossary term used as a code-font
  identifier stays English: "the `sampling` capability" → die Capability
  `sampling`.
- Text quoted from what the example code prints or displays — an output line, a
  log message, an error string, a UI label such as the Inspector's **Tools**
  and **Resources** tabs — stays exactly as the code emits it (usually
  English), in or out of code font. The quotation marks around it may become
  „…“; the text inside does not change.
- Nouns are borrowed, verbs are not. German developers keep many English nouns
  — capitalised, with a fixed gender, declined: der Request, die Response, der
  Client, der Server, der Host, der Handler, der Callback, das Tool, der
  Prompt, das Token, der String, der Header, die Payload, der Stream, das
  Schema, die Middleware, die Session, der Commit, der Build, das Deployment.
  Plurals take -s (die Requests, die Tools) except nouns in -er, which stay
  unchanged (die Server, die Handler, die Parameter). Verbs are German wherever
  a plain German verb exists: bereitstellen (not deployen), einen Commit
  anlegen (not committen), zusammenführen (not mergen), aktualisieren (not
  updaten). Fully naturalised verbs are fine: debuggen, parsen, loggen, cachen.
- Translate where German developers use the German word themselves — a forced
  purism is as wrong as needless English: Ressource, Abhängigkeit, Fehler,
  Rückgabewert, Standardwert, Umgebungsvariable, Bibliothek, Verzeichnis,
  Verbindung, Benachrichtigung; but never Zeichenkette for String.
- First-use gloss: a rendering the reader may need to map back to the English
  specification carries the English in parentheses on its first occurrence on
  a page — der Rückkanal (back-channel) — where the glossary note says so.
- One rendering per term per page: the glossary target, every time. Where an
  entry's note marks the choice as open or provisional, still use the listed
  target consistently — never Request in one paragraph and Anfrage in the next.

## 6. Provisional note

The register, voice and terminology decisions above, and every entry in
`glossary.json`, are provisional pending review by native German-speaking
readers — in particular the du address, the gender-neutral phrasing convention
and the keep-versus-translate line for individual nouns. To propose a change,
edit this file or `glossary.json` in a pull request, ideally with a short
good/bad example; never edit the generated `pages/` or `notices.md` next to
this file. The tool cannot tell a hand edit from its own output, so one would
persist unchecked and be carried forward into later runs; a correction made
here reaches the pages when they are regenerated with
`translate --lang de --pages …`.
