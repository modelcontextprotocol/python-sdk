# French (fr) — translation instructions

Target language: French as written in France (français, fr-FR conventions),
directory and URL code `fr`, page language tag `fr`. This file is sent verbatim
with every translation request for this language, on top of the shared rules
in `../general-prompt.md`. The termbase in `glossary.json` is sent alongside it
and wins any terminology conflict with this file.

## 1. Register

Address the reader as **vous**, always — verb forms, votre / vos and object
pronouns to match. French developer documentation does not use tu.

- Never tu / toi / ton, never a mix. A page that drifts between vous and tu, or
  between direct instructions and an impersonal administrative voice, is wrong
  even when each sentence is acceptable on its own.
- Steps are imperatives in the second person plural: "Install the SDK, then
  run the server" → Installez le SDK, puis lancez le serveur — not Veuillez
  installer … before every step, not the infinitive Installer le SDK in
  running prose. Obligations take the present: vous devez, not vous devrez,
  unless the English is explicitly about the future.
- Headings, table headers, tab labels and admonition titles are infinitives or
  noun phrases, never conjugated imperatives: "Declare a tool" → Déclarer un
  outil, "Handling errors" → Gérer les erreurs, "Running your server" →
  Exécuter votre serveur, "The Context" → L’objet Context. A question heading
  may stay a question (Où placer ce code ?). No full stop after a heading.
- Requirement strength stays exact: must → devez / il faut, should → devriez /
  il est recommandé de, may / can → pouvez, must not → ne devez pas.
- The authorial "we" is nous (Nous recommandons). The impersonal on is fine
  for a genuinely general statement (on obtient alors un schéma), never as a
  substitute for addressing the reader, never mixed with nous for one referent.
- "The user" — the human in front of the host — is l’utilisateur, the generic
  form French documentation uses; no typographic inclusive forms
  (utilisateur·rice). Where a sentence is really about the reader, say vous.

## 2. Voice

The English source is warm, direct and confident: short sentences, the
occasional one-line payoff. Aim for an experienced French engineer explaining a
library to a colleague — professional, warm, plain-spoken; not stiff, not chatty.

- Keep the payoff sentences short: "That's the whole API." → C’est toute
  l’API. — not a formal summary sentence. Split a long English sentence rather
  than mirroring its clause chain; never merge, drop or reorder the technical
  claims themselves.
- Verbs, not nominal chains: procéder à l’installation de → installer;
  effectuer la configuration → configurer. Active voice: "The tool is called by
  the model" → Le modèle appelle l’outil.
- No administrative French (il convient de, il est à noter que, dans le cadre
  de, afin de pouvoir, ledit, ce dernier as an all-purpose pronoun) and no hype
  (puissant, en toute simplicité, révolutionnaire).
- No English-shaped French: supporter for "support" (→ prendre en charge),
  retourner une valeur (→ renvoyer), consistant for "consistent" (→ cohérent),
  adresser un problème (→ traiter), faire sens (→ avoir du sens), définitivement
  for "definitely", and bare en 2026-07-28 (→ en version 2026-07-28).
- Body prose uses cela rather than the spoken ça; ça is tolerable only in a
  deliberately conversational payoff line, never in reference material.
- Example — "You don't construct it and you don't configure it. You ask for
  it." → Vous ne le construisez pas, vous ne le configurez pas. Vous le
  demandez. Not the administrative Il n’est pas nécessaire de procéder à son
  instanciation ni à sa configuration ; il suffit d’en effectuer la demande. —
  nor the calque Tu ne le construis pas … Tu le demandes, c’est tout !

## 3. Humour and idioms

- The English is friendly and dry rather than jokey; French technical prose
  tolerates warmth but less wit than English. Never translate a pun, idiom or
  aside literally: say what it means as a short, natural French sentence in
  the same register; a French idiom at home in technical prose is welcome
  (sous le capot for "under the hood"). An aside with no information may go —
  a technical caveat phrased lightly never does.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole story"
  / "The whole story is in **[X](…)**" → Tous les détails sont dans
  **[X](…)**; "That's the whole API." / "That's the whole protocol." → C’est
  toute l’API. / C’est tout le protocole.; "That's it. It's just Python." →
  C’est tout. C’est du Python, tout simplement. (not C’est ça. C’est juste du
  Python !); "You get `3` back. ✨" → Vous obtenez `3` en retour. ✨ (not Vous
  récupérez 3 en retour ! ✨ — lost code span, added exclamation mark).
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → Par défaut,
  l’application répond **uniquement** aux requêtes adressées à localhost — not
  a calqued sortie de la boîte. "it stops being required" → il cesse d’être
  obligatoire, not il arrête d’être requis.
- Exclamation marks are rare in French documentation: keep one only where the
  English carries genuine emphasis, with its espace insécable (§4); never add,
  never double, never in a heading. Emoji: keep the source's rare, deliberately
  placed emoji exactly where they are; never add new ones.

## 4. Typography

- Espace insécable: put a no-break space (the character U+00A0 itself, never
  `&nbsp;` and never an ordinary space) before ; : ! ? and %, and inside
  guillemets — after « and before ». So: Où placer ce code ? / le schéma
  suit : / « bonjour » / 100 %. Never inside code spans, code blocks, URLs,
  link targets or `{#id}` attributes; never after the `!!!` / `???` admonition
  markers or inside the `![` of an image; and no space at all before , or .
- Quotation marks are guillemets « … » for quotations, scare quotes and
  example utterances; English "…" and “…” in the source prose become « … »,
  with “…” for a quote inside a quote. Quotes inside code stay exactly as they
  are, and a code span is never wrapped in guillemets.
- Apostrophe: the typographic ’ (U+2019) throughout the prose — l’outil,
  jusqu’à, C’est — and the straight ' only inside code. Do not elide onto a
  code span: la fonction `add`, le paramètre `a`, not l’`add`.
- Accented capitals are mandatory (À partir de, État, Ça, Échantillonnage);
  the ligature is œ (cœur, nœud); ordinals are 1er, 2e, 3e (not 2ème).
- Sentence case everywhere; French has no title case (Gérer les erreurs, not
  Gérer Les Erreurs). Language names, weekdays and months are lower-case (en
  anglais, en juillet); proper nouns keep their capitals (Python, GitHub).
- Digits stay ASCII. Protocol revision strings such as `2026-07-28`, version
  numbers, ports, status and error codes, RFC and SEP numbers are identifiers,
  copied byte for byte — never 28/07/2026, never 28 juillet 2026. Prose
  quantities take the decimal comma only when nothing but the separator changes
  (2,5 secondes), never inside code. Thousands and units take a no-break space
  (10 000, 30 s, 100 Mo — byte units are o, ko, Mo, Go in prose, unchanged
  inside code or quoted output).
- Dashes: keep the source's em-dash incise with a space on each side (texte —
  incise — texte) or recast it with commas or parentheses. Ranges read de 3.10
  à 3.14, never a hyphen. The ellipsis is the single character … in prose.
- Abbreviations: e.g. → par exemple, i.e. → c’est-à-dire, etc. → etc., vs →
  ou / par rapport à; & in prose → et. No comma before et / ou closing a list.
- Bold and italics land on the words that carry the source's emphasis; a bolded
  negation ("**not**" → **pas** / **aucun**) stays bold. English words kept in
  French text are set in normal type — no italics, no guillemets.

## 5. Terminology pointer

The termbase is `glossary.json` next to this file. It is injected into the
prompt separately and its renderings override anything written here. This
section only fixes the conventions the glossary assumes:

- Terms in the glossary's `keep` list are copied exactly — same spelling and
  casing, not translated, italicised or quoted — and invariable in French (les
  SDK, les API, no plural s). They take an article by gender: le SDK, l’API
  (f.), le JSON, l’URL (f.), l’URI (m.), la CLI, le LLM, la SEP, la RFC.
- Everything in code font — class, function, parameter and module names,
  protocol method strings (`tools/call`), header names, error text, config keys
  — stays byte-identical. Name the kind of thing in front where it helps: la
  classe `Context`, le paramètre `lifespan=`. A glossary term used as a
  code-font identifier stays English although its prose noun is translated:
  "the `sampling` capability" → la capacité `sampling`.
- Text quoted from what the example code prints or displays — an output line, a
  log message, an error string, a UI label such as the Inspector's **Tools**
  and **Resources** tabs — stays exactly as the code emits it (usually
  English), in or out of code font. The guillemets around it are French; the
  text inside does not change.
- France, not Québec, and natural French before anglicism: prefer the French
  word wherever developers in France use it — outil, requête, réponse,
  gestionnaire, dépendance, bibliothèque, dépôt, fichier, flux, en-tête,
  jeton, journal, déploiement, e-mail — and keep the English noun where they
  do, masculine, plural in -s: le prompt, le framework, le middleware, le
  build, le commit, le hook. Never the purist or Québec coinages cadriciel,
  intergiciel, courriel, téléverser. Verbs are French: déployer, fusionner
  (not merger), récupérer (not fetcher), analyser (not parser), journaliser
  (not logger), mettre en cache, déboguer; créer un commit, never commiter.
- First-use gloss: a translated MCP concept the reader may need to map back to
  the English specification carries the English in parentheses on its first
  occurrence on a page — l’échantillonnage (sampling) — where the note says so.
- One rendering per term per page: the glossary target, every time. Where an
  entry's note marks the choice as open or provisional, still use the listed
  target consistently — never requête in one paragraph and demande in the next.

## 6. Provisional note

The register, voice and terminology decisions above, and every entry in
`glossary.json`, are provisional pending review by native French-speaking
readers — in particular the translate-versus-keep line for individual nouns
and the typographic apostrophe. To propose a change, edit this file or
`glossary.json` in a pull request, ideally with a short good/bad example;
never edit the generated `pages/` or `notices.md` next to this file. The tool
cannot tell a hand edit from its own output, so one would persist unchecked
and be carried forward into later runs; a correction made here reaches the
pages when they are regenerated with `translate --lang fr --pages …`.
