# Russian (ru) — translation instructions

Target language: Russian (русский язык), directory and URL code `ru`, page
language tag `ru`. This file is sent verbatim with every translation request
for this language, on top of the shared rules in `../general-prompt.md`. The
termbase in `glossary.json` is sent alongside it and wins any terminology
conflict with this file.

## 1. Register

Write the neutral, literate register of good Russian developer documentation:
closer to a well-edited technical book than to an official notice or a chat.

- The reader is «вы», always lowercase mid-sentence: вы, вас, вам, ваш.
  Capitalised Вы / Ваш is for a personal letter to one person and is wrong
  here. Never ты, never a mix.
- Reach for the pronoun rarely. Russian technical prose prefers constructions
  that need no subject: "You can pass a schema" → Можно передать схему; "If
  you need the raw result" → Если нужен сам результат; "You get a
  `CallToolResult`" → Возвращается `CallToolResult`. Three вы in one paragraph
  is a signal to rephrase. Never replace "you" with пользователь — the user is
  the person talking to the host, not the reader.
- Steps and instructions are plain imperatives in the вы form: "Install the
  SDK, then run the server" → Установите SDK и запустите сервер. A purpose
  clause is the other natural shape: "To run it: …" → Чтобы запустить: …. Not
  Вам необходимо установить, not Следует произвести установку.
- Headings, table headers and content-tab labels are noun phrases in sentence
  case with no final punctuation: "Running your server" → Запуск сервера,
  "Handling errors" → Обработка ошибок, "Inside your handler" → Внутри
  обработчика. "How to …" becomes Как + infinitive; a heading the English
  phrases as a question may stay a question.
- The authorial "we" is fine where the English has it (Рекомендуем …), but no
  мы с вами or давайте. One page, one register: a page that drifts between
  imperatives and officialese, or between вы and Вы, is wrong even when each
  sentence is acceptable on its own.

## 2. Voice

The English is warm, direct and confident: short sentences, second person, the
occasional one-line payoff ("That's the whole API."). Carry that into living
Russian — neither wooden nor familiar.

- Use concrete verbs and let them carry the sentence: запустить, передать,
  вернуть, объявить, заблокировать. Prefer the active voice: "The tool is
  called by the model" → Модель вызывает инструмент, not Инструмент вызывается
  моделью. Keep the payoff lines short: "That's a complete MCP server." → Это
  уже готовый MCP-сервер.
- Split long English sentences and follow Russian word order; never merge,
  drop or reorder the technical claims themselves.
- Avoid канцелярит, the bureaucratic register technical translation slides
  into by default: данный → этот; является → есть, a dash, or nothing (Хост —
  это приложение); осуществлять / производить / выполнять + noun → the verb
  itself (осуществляет отправку → отправляет); в целях → чтобы; посредством →
  с помощью, через; в случае если → если; функционал → возможности; and no
  chains of verbal nouns (для обеспечения возможности выполнения запуска →
  чтобы запустить).
- No hedging the English does not have ("don't" is не используйте, not
  возможно, стоит воздержаться) — and no over-correction either: no ты, no
  slang (юзать, тулза, дефолтный, задеплоить), no smileys.

Example — English: "You don't construct it and you don't configure it. You ask
for it."

- Not this (канцелярит): Пользователю не требуется осуществлять его создание и
  конфигурирование. Необходимо лишь выполнить соответствующий запрос.
- Not this either (familiar): Ты его не создаёшь и не настраиваешь. Просто
  просишь.
- This: Его не нужно ни создавать, ни настраивать. Достаточно попросить.

## 3. Humour and idioms

- Translate the intent of a joke, aside or idiom, never its words. Recast it
  as a short, natural Russian sentence in the same register; if a light phrase
  carries no information at all, keep the sentence brief rather than inventing
  a Russian joke. Never drop the technical content around it.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → Подробнее — на странице
  **[X](…)**.; "That's the whole API." / "That's the whole protocol." → Вот и
  весь API. / Вот и весь протокол.; "That's it. It's just Python." → Вот и
  всё. Это обычный Python.; "You get `3` back. ✨" → В ответ приходит `3`. ✨
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → По умолчанию приложение
  отвечает **только** на запросы, адресованные localhost. — not из коробки;
  "under the hood" → внутри, not под капотом; "on the wire" → в передаваемых
  данных / по сети, never по проводу. Culture-bound references (sports, TV,
  holidays) → the plain meaning.
- Keep an exclamation mark only where the English is a genuine exclamation of
  encouragement — never after a warning or a step, never doubled, never in a
  heading. Reproduce an emoji only where the English has one, in the same
  place (two payoff lines end in ✨); never add one.

## 4. Typography

- Quotation marks in Russian prose are «ёлочки»; a quote nested inside them
  takes „лапки“. Straight quotes inside code spans, code blocks, commands and
  URLs stay untouched. When the English quotes a word the example code prints
  or a UI label, the text inside stays exactly as emitted and only the marks
  change: вкладка «Tools», кнопка «Connect».
- Use ё wherever it belongs, consistently: ещё, её, всё, объём, передаёт,
  вернётся, трёх. A page that writes все for всё is wrong.
- Dashes: the grammatical dash is an em dash with a space on each side (Хост —
  это приложение, с которым говорит пользователь); a hyphen only joins
  compounds (MCP-сервер, HTTP-запрос); numeric ranges use an en dash without
  spaces (3.10–3.14) or от 3.10 до 3.14. Never a hyphen where a dash is meant.
  An English em-dash aside may also become a comma pair, parentheses or its
  own sentence.
- Sentence case everywhere: headings, admonition titles, tab labels and table
  headers capitalise the first word and proper nouns only. No capital after a
  colon. Language names, weekdays and months are lowercase (на английском, в
  июле).
- Digits stay ASCII. Protocol revision strings such as `2026-07-28` and
  `2025-11-25` are identifiers, copied byte for byte — never 28.07.2026, never
  28 июля 2026 г. Version numbers, ports, HTTP status codes, error codes, RFC
  and SEP numbers are copied exactly.
- Prose quantities take the decimal comma only when nothing but the separator
  changes (2.5 seconds → 2,5 секунды); when in doubt keep the number as
  written. A space separates a number from its unit (100 МБ, 30 секунд, 5 с);
  % attaches with no space (100%). Numerals govern the noun the Russian way:
  1 инструмент, 3 инструмента, 5 инструментов.
- e.g. → например; i.e. → то есть; etc. → и т. д.; "&" → и. Emphasis lands
  on the same words the source emphasises, and a bolded negation ("**not**" →
  **не**) stays bold. Loanwords and Latin-script names are set in plain type —
  no italics, no quotes around them. Keep the source's colons and parentheses;
  a colon before a list or code block is natural Russian too.

## 5. Terminology pointer

The glossary (`glossary.json`) is injected separately and overrides this file
on every term it covers; each entry says whether its choice is standard or
provisional and whether it takes a first-use gloss. These conventions are what
its renderings assume:

- Identifiers stay in Latin script exactly as written: class, function,
  method, parameter, module, environment-variable and header names, protocol
  method strings such as `tools/call`, and everything in code font. So do the
  keep-list terms, acronyms and product and protocol names, always without
  the English plural "s": "the SDKs" → SDK or пакеты SDK.
- Never decline a Latin-script word with an apostrophe or a glued ending
  (API'шка, SDK-а, в `Client`'е). Let a Russian word carry the case instead: a
  hyphenated head noun (MCP-сервер, MCP-клиент, HTTP-запрос, JSON-объект,
  ASGI-приложение, OAuth-токен) or the kind of thing in front of code (класс
  `Context`, параметр `lifespan=`, метод `client.call_tool()`, команда
  `uv run`, заголовок `Mcp-Method`). Adjectives and verbs agree with that
  Russian word.
- Programs and components are grammatically inanimate: запустить клиент,
  подключить хост (not клиента in the accusative). Provisional; apply uniformly.
- Where an established Russian term exists, use it, not the anglicism:
  обработчик (not хендлер), запрос / ответ (not реквест / респонс),
  уведомление (not нотификация), исключение (not эксепшен), экземпляр (not
  инстанс), по умолчанию (not дефолтный), развёртывание (not деплой), среда
  выполнения (not рантайм). Settled loanwords stay: сервер, клиент, хост,
  токен, сессия, схема, декоратор, промпт, репозиторий, фреймворк, плагин, лог.
- Text quoted from what the example code prints or displays — an output line,
  a log message, an Inspector tab or button label — stays exactly as the code
  emits it (usually English), in or out of code font; never translate it.
- First-use gloss: a term the glossary marks for it carries the English in
  parentheses on its first appearance in a page — элицитация (elicitation),
  корневые каталоги (roots) — and appears alone after that. A glossary word
  used as a wire identifier or a key in code font is code and stays Latin:
  "the `sampling` capability" → возможность `sampling`.
- One rendering per term per page: the glossary target, every time, even
  where its note marks the choice as provisional.

## 6. Provisional note

Every decision in this file, and every entry in `glossary.json`, is
provisional pending review by native Russian-speaking developers. To propose a
change, edit this file or `glossary.json` in a pull request, ideally with a
short good/bad example; never edit the generated pages under `pages/` or
`notices.md` next to this file. The tool cannot tell a hand edit from its own
output, so one would persist unchecked and be carried forward into later
runs; a correction made here reaches the pages when they are regenerated with
`translate --lang ru --pages …`.
