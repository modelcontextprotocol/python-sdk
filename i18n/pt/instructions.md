# Brazilian Portuguese (pt) — translation instructions

Target language: Brazilian Portuguese (Português do Brasil), directory and
URL code `pt`, page language tag `pt`. This file is sent verbatim with
every translation request for this language, on top of the shared translation
rules in `../general-prompt.md`. The termbase in `glossary.json` is sent
alongside it and wins any terminology conflict with this file.

## 1. Register

Write the casual-neutral register Brazilian developer documentation uses:
professional, relaxed, and direct.

- Address the reader as **você**, with third-person-singular verb forms to
  match. Never o senhor / a senhora, never tu, never vós, and never a mix.
  The rule holds in body prose, headings, admonition titles, table cells and
  link text.
- Instructions and steps are direct imperatives in the você form: "Install
  the SDK, then run the server" → Instale o SDK e depois execute o servidor —
  not Instala o SDK (tu form), and not Você deve instalar o SDK (needless
  modal). A bare imperative per step is fine; a por favor in front of every
  step is not.
- Portuguese drops the subject pronoun freely. Write você where a sentence
  needs an explicit subject or a contrast, and let the verb carry the person
  otherwise; three or four você in one paragraph is a signal to rephrase.
  Object pronouns follow the same person: para você / a você, never the
  tu-form te / ti.
- The authorial "we" is nós (Recomendamos, chamamos), never the spoken
  a gente.
- The register is uniform across a page. A page that drifts between você and
  o senhor, or between direct imperatives and an impersonal officialese voice,
  is wrong even when each sentence is acceptable on its own.
- This is Brazilian Portuguese only. Every European Portuguese form is an
  error here:
  - vocabulary: arquivo (never ficheiro), tela (never ecrã), usuário (never
    utilizador), salvar (never guardar), excluir / apagar (never eliminar for
    "delete"), baixar (never transferir / descarregar for "download"), mouse
    (never rato), site (never sítio);
  - grammar: the progressive is estar + gerund — o servidor está rodando —
    never estar a + infinitive (está a rodar, está a correr);
  - spelling: the post-1990 orthography — ação, ótimo, ideia — never acção,
    óptimo, idéia.

## 2. Voice

Aim for the voice of an experienced Brazilian engineer explaining a library
to a colleague: warm, direct, plain-spoken. The English is built on short
declarative payoff sentences ("That's the whole API."); keep them short — Essa
é a API inteira.

Do:

- Follow Portuguese rhythm. Split a long English sentence into two Portuguese
  ones instead of mirroring its clause chain, and use everyday connectives
  (então, ou seja, por isso) where they help the reader along.
- Use concrete verbs (executar, passar, retornar, declarar, bloquear) rather
  than nominal chains: fazer a execução de → executar.
- Keep the source's directness. Where the English says "don't", the
  Portuguese says não faça isso / não use, not a hedge like talvez seja
  interessante evitar.

Avoid — these are the marks of a machine or bureaucratic translation:

- Officialese and legalistic filler: o presente documento, supracitado,
  outrossim, faz-se necessário, deve-se ressaltar que, and o mesmo used as a
  pronoun.
- Gerundismo: vamos estar mostrando → vamos mostrar; irá estar retornando →
  vai retornar.
- Verbified anglicisms from spoken developer slang: deployar, commitar,
  buildar, startar, mergear. Write fazer o deploy, fazer commit, gerar o build,
  iniciar, fazer o merge.
- English-shaped Portuguese: calqued idioms (sob o capô for "under the hood" —
  the Brazilian phrase is por baixo dos panos; no fim do dia for "at the end
  of the day" — say no fim das contas), possessive chains, and passives where
  an active sentence is natural ("The tool is called by the model" → o modelo
  chama a ferramenta, not a ferramenta é chamada pelo modelo).
- Marketing hype and stacked exclamation marks. Keep an exclamation mark only
  where the English one carries genuine emphasis.

## 3. Humour and idioms

The English is friendly and dry rather than jokey — short payoff sentences, a
few stock phrases, the rare emoji — and Brazilian technical writing is warm by
default, so most of that carries over unchanged. The idioms still need
recasting.

- Never translate a pun, idiom or aside literally. Say what it means as a
  short, natural Brazilian sentence in the same register. Where a common
  Brazilian idiom happens to carry the same meaning, use it; where nothing
  fits, use the plain statement. If an aside carries no information you may
  drop it — but never drop a technical caveat that happens to be phrased
  lightly.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → **[X](…)** tem a história
  completa; "That's the whole API." / "That's the whole protocol." → A API
  inteira é essa. / O protocolo inteiro é esse.; "That's it. It's just
  Python." → É só isso. É apenas Python.
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → Por padrão, o app
  responde **apenas** a requisições endereçadas ao localhost — not a calqued
  fora da caixa.
- Culture-bound references (US sports, TV shows, holidays) → the plain
  meaning.
- Emoji: keep the source's rare, deliberately placed emoji exactly where they
  are — two payoff lines end in ✨ ("You get `3` back. ✨"). Never add new
  ones.

Worked examples (source → good / bad):

- "You get `3` back. ✨" → good: Você recebe `3` de volta. ✨ / bad: Você
  recebe `3` de volta! ✨ (added exclamation mark).
- "Give a parameter a default value and it stops being required. That's it.
  It's just Python." → good: Dê um valor padrão a um parâmetro e ele deixa de
  ser obrigatório. É só isso. É apenas Python. / bad: Dê um valor default
  para um parâmetro e ele para de ser requerido. É isso aí, é só Python! ✨
  (untranslated default and requerido, slangy tag, added exclamation and
  emoji).

## 4. Typography

- Prose punctuation is standard Brazilian usage written with the same
  characters the source uses: keep straight double quotes ("…") and
  apostrophes as they are; do not switch to «guillemets» or “curly quotes”; no
  inverted ¿ ¡; no space before ! ? : ; (that is a French convention).
- Sentence case for headings, admonition titles and content-tab labels:
  capitalise the first word and proper nouns only (Configurando o transporte,
  not Configurando O Transporte). Language names, months and weekdays are
  lower-case in Portuguese (a versão em inglês, em julho); proper nouns stay
  capitalised (Python, GitHub, Claude Desktop).
- Digits stay ASCII. Protocol revision strings such as `2026-07-28` and
  `2025-11-25` are identifiers, copied byte-for-byte — never 28/07/2026,
  never 28 de julho de 2026. Version numbers, HTTP status codes, ports, error
  codes, and RFC and SEP numbers are copied exactly.
- Ordinary prose quantities take the decimal comma only when nothing but the
  separator changes (a timeout of 2.5 seconds → um timeout de 2,5 segundos);
  when in doubt, keep the number as the source writes it. A space separates a
  number from a Latin unit (100 MB, 30 s); % attaches with no space (100%).
- Latin abbreviations: e.g. → por exemplo, i.e. → ou seja / isto é; etc.
  stays etc.; vs → versus, or ou / contra when a plain word reads better.
  Where the English uses & in prose, write e.
- Loanwords kept in English are set in normal type — no italics, no scare
  quotes — and take a Portuguese article: o handler, os tokens, a string.
  Bold and italics land on the same words the source emphasises; a bolded
  negation ("**not**" → **não**) stays bold.
- Ordinals use the indicators º / ª (1º, 2ª). Keep the source's dashes,
  colons and parentheses as they are; do not turn a colon into a travessão
  or the reverse.

## 5. Terminology pointer

The termbase is `glossary.json` next to this file. It is injected into the
prompt separately and its renderings override anything written here. This
section only fixes the conventions the glossary assumes:

- Terms in the glossary's `keep` list are copied exactly as they appear in
  the English source — same spelling, casing and plural "s" (SDKs stays
  SDKs). They are not translated, italicised, re-cased or wrapped in quotes.
- Everything in code font — class, function, method, parameter and module
  names, protocol method strings (`tools/call`, `notifications/...`), header
  names, error text, config keys — stays byte-identical. You may put a
  Portuguese article or the word for the kind of thing in front of it: a
  classe `Context`, o parâmetro `lifespan=`, o método `client.list_tools()`.
  A glossary term used as a code-font identifier stays in English even though
  its prose noun is translated: "the `sampling` capability" → a capacidade
  `sampling`.
- English technical nouns that stay in English keep their English spelling,
  take a fixed grammatical gender, and pluralise the Brazilian way (add "s").
  Masculine by default — o token / os tokens, o handler, o callback, o host,
  o schema, o payload, o endpoint, o log, o loop, o build, o commit, o deploy,
  o prompt, o middleware — feminine where usage is settled: a string, a
  thread, a query, a flag, a tag, a URL, a API, a issue. Where a glossary
  entry's note gives a gender, it wins.
- Nouns are borrowed, verbs are not: fazer o deploy, fazer commit, fazer o
  merge — never deployar, commitar, mergear (see §2).
- First-use gloss: a translated MCP concept the reader may need to map back to
  the English specification carries the English in parentheses on its first
  occurrence on a page — elicitação (elicitation) — and appears alone after
  that. Each glossary entry's note says whether the term takes the gloss.
- One rendering per term per page: the glossary target, every time. Where an
  entry's note marks the choice as open or provisional, still use the listed
  target consistently rather than picking per sentence.

## 6. Provisional note

The register, voice and terminology decisions above, and every entry in
`glossary.json`, are provisional pending review by native Brazilian
Portuguese-speaking readers. To propose a change, edit this file or
`glossary.json` in a pull request — ideally with a short good/bad example when
the change is about phrasing; never edit the generated `pages/` or
`notices.md` next to this file. The tool cannot tell a hand edit from its own
output, so one would persist unchecked and be carried forward into later
runs; a correction made here reaches the pages when they are regenerated with
`translate --lang pt --pages …`.
