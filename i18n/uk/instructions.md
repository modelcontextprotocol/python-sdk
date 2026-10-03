# Ukrainian (uk) — translation instructions

Target language: Ukrainian (українська мова), directory and URL code `uk`,
page language tag `uk`. This file is sent verbatim with every translation
request for this language, on top of the shared rules in
`../general-prompt.md`. The termbase in `glossary.json` is sent alongside it
and wins any terminology conflict with this file.

## 1. Register

Write modern, natural Ukrainian as today's Ukrainian developer community
writes it: literate and plain, neither officialese nor chat.

- The reader is «ви», always lowercase mid-sentence: ви, вас, вам, ваш.
  Capitalised Ви / Ваш belongs in a personal letter to one person and is wrong
  here. Never ти, never a mix.
- Reach for the pronoun rarely; prefer constructions that need no subject:
  "You can pass a schema" → Можна передати схему; "If you need the raw
  result" → Якщо потрібен сам результат; "You get a `CallToolResult`" →
  Повертається `CallToolResult`. Three ви in one paragraph is a signal to
  rephrase. Never replace "you" with користувач — the user is the person
  talking to the host, not the reader.
- Steps and instructions are plain imperatives in the ви form: "Install the
  SDK, then run the server" → Встановіть SDK і запустіть сервер. A purpose
  clause is the other natural shape: "To run it: …" → Щоб запустити: …. Not
  Вам необхідно встановити, not Слід здійснити встановлення.
- Headings, table headers and content-tab labels are noun phrases in sentence
  case with no final punctuation: "Running your server" → Запуск сервера,
  "Handling errors" → Обробка помилок, "Inside your handler" → Усередині
  обробника. "How to …" becomes Як + infinitive; a heading the English phrases
  as a question may stay a question.
- The authorial "we" is fine where the English has it (Радимо …), but no
  давайте. One page, one register: a page that drifts between imperatives and
  officialese, or between ви and Ви, is wrong even if each sentence is fine.

## 2. Voice

The English is warm, direct and confident: short sentences, second person, the
occasional one-line payoff ("That's the whole API."). Carry that into Ukrainian.

- Use concrete verbs: запустити, передати, повернути, оголосити, заблокувати.
  Prefer the active voice: "The tool is called by the model" → Модель
  викликає інструмент, not Інструмент викликається моделлю. Keep the payoff
  lines short: "That's a complete MCP server." → Це вже готовий MCP-сервер.
- Split long English sentences and follow Ukrainian word order, but never
  merge, drop or reorder the technical claims themselves.
- Avoid канцелярит: даний → цей; здійснювати / виконувати + noun → the verb
  itself (здійснює надсилання → надсилає); з метою → щоб; у випадку якщо →
  якщо; no chains of verbal nouns (для забезпечення можливості запуску → щоб
  запустити). Avoid active participles in -учий / -ючий, which read as
  calques: існуючий → наявний or що існує; працюючий сервер → сервер, що
  працює.
- Avoid russianisms and суржик of every kind — vocabulary, calqued phrases,
  and Russian letters (ы, э, ъ, ё never appear in Ukrainian text; ґ, є, і, ї
  do where the orthography requires). §5 pins the common traps.
- No hedging the English does not have ("don't" is не використовуйте, not
  можливо, варто утриматися) — and no over-correction either: no ти, no slang
  (юзати, тулза, дефолтний, задеплоїти), no smileys.

Example — English: "You don't construct it and you don't configure it. You ask
for it."

- Not this (officialese): Користувачу не потрібно здійснювати його створення
  та конфігурування. Необхідно лише виконати відповідний запит.
- Not this either (familiar): Ти його не створюєш і не налаштовуєш. Просто
  просиш.
- This: Його не потрібно ні створювати, ні налаштовувати. Достатньо попросити.

## 3. Humour and idioms

- Translate the intent of a joke, aside or idiom, never its words: recast it
  as a short, natural Ukrainian sentence in the same register, or keep it
  brief where it carries nothing. Never drop the technical content around it.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → Докладніше — на сторінці
  **[X](…)**.; "That's the whole API." / "That's the whole protocol." → Оце й
  увесь API. / Оце й увесь протокол.; "That's it. It's just Python." → От і
  все. Це звичайний Python.; "You get `3` back. ✨" → У відповідь приходить
  `3`. ✨
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → За замовчуванням
  застосунок відповідає **лише** на запити, адресовані localhost. — not з
  коробки; "under the hood" → усередині, not під капотом; "on the wire" → у
  переданих даних / мережею, never по дроту.
- Keep an exclamation mark only where the English is a genuine exclamation of
  encouragement — never after a warning or a step, never doubled, never in a
  heading. Reproduce an emoji only where the English has one, in the same
  place (two payoff lines end in ✨); never add one.

## 4. Typography

- Quotation marks in Ukrainian prose are «лапки-ялинки»; a quote nested inside
  them takes „…“. Straight quotes inside code spans, code blocks, commands and
  URLs stay untouched. When the English quotes a word the example code prints
  or a UI label, the text inside stays exactly as emitted and only the marks
  change: вкладка «Tools», кнопка «Connect».
- The apostrophe is part of Ukrainian spelling and is never dropped or spaced:
  об'єкт, з'єднання, під'єднати, пам'ять, ім'я, комп'ютер, зв'язок,
  обов'язковий, п'ять — never обєкт. Write it as the plain character `'`
  (U+0027) on every page, rather than ’ (U+2019) or ʼ (U+02BC); this choice
  of character is provisional, apply it uniformly. It never glues an ending
  onto a Latin word (see §5).
- Dashes: the grammatical dash is an em dash with a space on each side (Хост —
  це застосунок, з яким говорить користувач); a hyphen only joins compounds
  (MCP-сервер, HTTP-запит); numeric ranges use an en dash (3.10–3.14) or від
  3.10 до 3.14. An English em-dash aside may also become a comma pair,
  parentheses or its own sentence.
- Sentence case everywhere: headings, admonition titles, tab labels and table
  headers capitalise the first word and proper nouns only. No capital after a
  colon. Language names, weekdays and months are lowercase (у липні).
- Digits stay ASCII. Protocol revision strings such as `2026-07-28` and
  `2025-11-25` are identifiers, copied byte for byte — never 28.07.2026, never
  28 липня 2026 р. Version numbers, ports, HTTP status codes, error codes, RFC
  and SEP numbers are copied exactly.
- Prose quantities take the decimal comma only when nothing but the separator
  changes (2.5 seconds → 2,5 секунди); when in doubt keep the number as
  written. A space separates a number from its unit (100 МБ, 30 секунд, 5 с);
  % attaches with no space (100%). Numerals govern the noun the Ukrainian way:
  1 інструмент, 3 інструменти, 5 інструментів.
- e.g. → наприклад; i.e. → тобто; etc. → тощо; "&" → і / та. Emphasis lands on
  the same words the source emphasises, and a bolded negation ("**not**" →
  **не**) stays bold. Loanwords and Latin-script names are set in plain type —
  no italics, no quotes around them. Keep the source's colons and parentheses;
  a colon before a list or code block is natural Ukrainian too.

## 5. Terminology pointer

The glossary (`glossary.json`) is injected separately and overrides this file
on every term it covers; each entry marks its choice as standard or provisional
and says whether it takes a first-use gloss. Its renderings assume:

- Identifiers stay in Latin script exactly as written: class, function,
  method, parameter, module, environment-variable and header names, protocol
  method strings such as `tools/call`, and everything in code font. So do the
  keep-list terms, acronyms and product and protocol names, always without
  the English plural "s": "the SDKs" → SDK or пакети SDK.
- Never decline a Latin-script word with an apostrophe or a glued ending
  (API'шка, SDK-а). Let a Ukrainian word carry the case instead: a hyphenated
  head noun (MCP-сервер, HTTP-запит, JSON-об'єкт, ASGI-застосунок) or the kind
  of thing in front of code (клас `Context`, параметр `lifespan=`, метод
  `client.call_tool()`). Adjectives and verbs agree with that Ukrainian word.
- Russianism traps, pinned: application / app → застосунок (додаток is an
  add-on or an appendix); "by default" → за замовчуванням (never по
  замовчуванню; "default value" → типове значення); next → наступний (never
  слідуючий); the linking verb "is" → є or a dash (never являється); settings
  → налаштування (never настройки); cancel → скасувати (not відмінити);
  exception → виняток (виключення means exclusion); authentication →
  автентифікація (not аутентифікація); environment → середовище (not
  оточення); get → отримати; delete → видалити.
- Where an established Ukrainian term exists, use it, not the anglicism:
  обробник (not хендлер), сповіщення (not нотифікація), екземпляр (not
  інстанс), розгортання (not деплой), середовище виконання (not рантайм).
  Settled loanwords stay: сервер, клієнт, хост, токен, сесія, схема,
  декоратор, промпт, репозиторій, фреймворк, плагін, лог.
- Text quoted from what the example code prints or displays — an output line,
  a log message, an Inspector tab or button label — stays exactly as the code
  emits it (usually English), in or out of code font; never translate it.
- First-use gloss: a term the glossary marks for it carries the English in
  parentheses on its first appearance in a page — еліцитація (elicitation) —
  and appears alone after that. A glossary word used as a wire identifier or
  a key in code font stays Latin: "the `sampling` capability" → можливість
  `sampling`.
- One rendering per term per page: the glossary target, every time.

## 6. Provisional note

Every decision in this file, and every entry in `glossary.json`, is
provisional pending review by native Ukrainian-speaking developers. To propose
a change, edit this file or `glossary.json` in a pull request, ideally with a
short good/bad example; never edit the generated `pages/` or `notices.md`.
