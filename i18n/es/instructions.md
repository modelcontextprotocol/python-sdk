# Spanish (es) — translation instructions

Target language: Spanish (español), one global variant for Latin America
and Spain alike, directory and URL code `es`, page language tag `es`. This
file is sent verbatim with every translation request for this language, on
top of the shared rules in `../general-prompt.md`. The termbase in
`glossary.json` is sent alongside it and wins any terminology conflict.

## 1. Register

Write the relaxed, direct register of modern open-source documentation in
Spanish: professional, plain-spoken, addressed to a colleague.

- Address the reader as **tú**, always, with matching verb forms and
  pronouns (puedes, tu servidor, te devuelve). Never usted (ejecute, su, le),
  never vosotros or its forms (ejecutáis, vuestro, os), never voseo (podés,
  tenés). Where the English "you" is plainly plural ("you and your team"),
  the plural is **ustedes**, never vosotros.
- Steps are bare tú imperatives: "Install the SDK, then run the server" →
  Instala el SDK y luego ejecuta el servidor — not Instale (usted), not Debes
  instalar, no por favor before every step; prohibitions are no + subjunctive
  (no llames, no uses). The authorial "we" is nosotros.
- Spanish drops the subject pronoun. Let the verb carry the person; write tú
  only for contrast — two or three explicit tú on a page is a lot. "Your
  server" is usually el servidor; tu servidor when ownership is the point.
  Impersonal se constructions (se instala con uv) are welcome for describing
  behaviour and keep a page from becoming a wall of imperatives, but a
  third-person verb aimed at the reader is an usted form and is wrong.
- One page, one register: a page that drifts between tú and usted, or slips
  in one vosotros or vos form, is wrong even when each sentence is fine.
- One global Spanish. Where regions differ, use the form understood
  everywhere and pinned in the glossary (archivo, not fichero; computadora,
  not ordenador); avoid words that are everyday in one region and odd in
  another (vale, coger; accesar, checar). ejecutar, not correr, a program;
  "enter a value" → escribe or indica (ingresar and introducir each read as
  regional); "click **Tools**" → haz clic en **Tools**.

## 2. Voice

The English is warm, direct and confident: short sentences, second person,
the occasional one-line payoff ("That's the whole API."). Developer Spanish
carries that voice naturally; keep it, and keep the payoff lines short — Esa
es toda la API.

- Follow Spanish rhythm: split a long English sentence in two rather than
  chaining clauses with commas; use plain connectives (así que, es decir,
  por eso) where they help. Prefer concrete verbs to noun stacks (realizar la
  ejecución de → ejecutar) and the active voice or pasiva refleja to a
  calqued passive: "The tool is called by the model" → el modelo llama a la
  herramienta, not la herramienta es llamada por el modelo.
- Keep the directness ("don't" is no uses, not quizá convenga evitar), skip
  the hype, and avoid officialese: el presente documento, dicho / dicha
  everywhere, el mismo as a pronoun, a nivel de, en base a, cabe destacar.
- Verbs are Spanish even when the noun is borrowed: never deployar, setear,
  loguear, debuggear, testear, parsear, pushear — write desplegar, configurar,
  registrar, depurar, probar, analizar, enviar; hacer un commit, hacer push.
- False friends and calques: librería for a code library (→ biblioteca),
  eventualmente for "eventually" (→ con el tiempo), actual for "actual"
  (→ real), soportar for "support" (→ admite / es compatible con), remover
  (→ quitar / eliminar), asumir (→ suponer), the gerundio de posterioridad
  ("…, generando un error"), and "under the hood" → internamente, not bajo
  el capó. retornar is understood everywhere, but this corpus pins devolver.

Example — English: "You don't construct it and you don't configure it. You
ask for it."

- Not this (usted, pronoun in every clause): Usted no lo construye y usted
  no lo configura. Usted lo solicita.
- Not this either (voseo, slang, added emphasis): No lo construís ni lo
  configurás. Lo pedís y listo, ¡facilísimo!
- This: No lo construyes ni lo configuras. Lo pides.

## 3. Humour and idioms

- The English is friendly and dry rather than jokey, and conversational
  Spanish absorbs that easily; what needs work is idiom. Never translate a
  pun, idiom or aside word for word: say what it means in a short natural
  sentence in the same register. A widely understood turn of phrase (y
  listo, sin más) is fine, a regional one is not; culture-bound references
  take the plain meaning. An aside that carries no information may go —
  never a technical caveat that happens to be phrased lightly.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" → **[X](…)** tiene todos los detalles; "The whole story is in
  **[X](…)**" → Todos los detalles están en **[X](…)**; "That's the whole
  API." / "That is the whole API." → Esa es toda la API.; "That's the whole
  protocol." → Ese es todo el protocolo.; "That's it. It's just Python." →
  Eso es todo. Es simplemente Python.; "You get `3` back. ✨" → Te devuelve
  `3`. ✨; "Out of the box the app answers **only** requests addressed to
  localhost." → Por defecto, la app responde **solo** a las solicitudes
  dirigidas a localhost. — never recién sacada de la caja.
- Exclamation marks: English exports far more than Spanish prose wants. Keep
  one only where the source is genuinely emphatic, always paired ¡…!, never
  doubled, never in a heading, never after a warning or error description.
- Emoji: keep the source's rare, deliberately placed emoji exactly where they
  are (two payoff lines end in ✨); never add one, never in a heading. "Give
  a parameter a default value and it stops being required. That's it. It's
  just Python." → Dale un valor por defecto a un parámetro y deja de ser
  obligatorio. Eso es todo. Es simplemente Python. — not ¡Eso es todo, es
  solo Python! ✨ (merged sentences, added exclamation and emoji).

## 4. Typography

- Questions and exclamations always open with the inverted mark — ¿Dónde va
  esto?, ¡Listo! — placed where the question starts: Si falla, ¿qué ves?
- Sentence case for headings, admonition titles, tab labels and table
  headers: first word and proper nouns only (Configurar el transporte). An
  English -ing heading becomes an infinitive or a noun phrase, never a
  gerund: "Handling errors" → Manejo de errores, not Manejando errores.
  Language names and months are lower-case (en inglés, en julio); capitals
  keep their accents; solo and este / ese / aquel never take one.
- Punctuation characters stay as the source has them: straight double quotes
  "…" (not «…», not curly), ASCII apostrophes, parentheses and colons. No
  space before : ; ! ? and lower case after a colon unless a proper noun or
  code follows. An English em-dash aside becomes commas, parentheses, a
  colon or a second sentence; if a dash pair truly reads best, use the raya
  pegada —así—, never an English " — " floating between spaces.
- Digits stay ASCII and identifiers are copied byte for byte: protocol
  revisions such as `2026-07-28`, versions, ports, status and error codes,
  RFC and SEP numbers — never 28/07/2026 or 28 de julio de 2026. Ordinary
  quantities keep the source's form, decimal point included (2.5 segundos),
  since decimal conventions differ across the Spanish-speaking world. A
  space between number and unit (100 MB, 30 s); % as in the source (100%).
- e.g. → por ejemplo, i.e. → es decir, vs → frente a, etc. stays; & → y,
  and y → e / o → u also before English words (clientes e IDE).
- Loanwords kept in English are plain type — no italics, no quotes — with a
  Spanish article: el token, la API. Emphasis lands where the source puts
  it; a bolded negation stays bold ("does **not** raise" → **no** lanza).

## 5. Terminology pointer

The termbase `glossary.json` is injected separately and overrides anything
written here. This section fixes the conventions its renderings assume:

- Terms in the glossary's `keep` list and every identifier — class, function,
  method, parameter, module and package names, protocol method strings
  (`tools/call`, `notifications/...`), header names, environment variables,
  anything in code font — are copied byte for byte. Acronyms and product
  names take no plural s in Spanish: "the SDKs" → los SDK, "both APIs" →
  ambas API; the article carries the number. You may name the kind of thing
  in front: la clase `Context`, el parámetro `lifespan=`. A glossary term
  used as a code-font identifier stays English although its prose noun is
  translated: "the `sampling` capability" → la capacidad `sampling`.
- Text quoted from what the example code prints or displays — an output
  line, a log message, an error string, a UI label such as the Inspector's
  **Tools** and **Resources** tabs — stays exactly as the code emits it
  (usually English), with no Spanish reading added in brackets.
- English nouns kept in English keep their spelling, take a fixed gender and
  pluralise with -s (los tokens, los callbacks). Masculine by default — el
  token, el handler, el callback, el host, el prompt, el endpoint, el log,
  el middleware, el payload, el timeout; feminine where settled — la API, la
  URL, la URI, la CLI, la web, la caché, la terminal (el terminal is Spain
  usage). A gender given in a glossary note wins.
- First-use gloss: a translated MCP concept the reader may need to map back
  to the English specification carries the English in parentheses on its
  first occurrence in the page body — muestreo (sampling) — and appears alone
  after that, never glossed in a heading. Each glossary note says which
  terms take the gloss.
- Python vocabulary follows the established Spanish of the Python
  documentation: devolver un valor, lanzar una excepción, argumento
  nombrado, decorador, cadena, entorno virtual, tiempo de ejecución, hilo,
  de terceros, asíncrono. One rendering per term per page: the glossary
  target, every time — also where a note marks the choice as provisional.

## 6. Provisional note

Every decision above, and every entry in `glossary.json`, is provisional
pending review by native Spanish-speaking readers from more than one region.
To propose a change — a rendering that reads as regional, a rule that yields
stiff Spanish, a term to pin — edit this file or `glossary.json` in a pull
request; the generated pages under `pages/` are never edited by hand.
