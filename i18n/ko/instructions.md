# Korean (ko) — translation instructions

Target language: Korean (한국어), directory and URL code `ko`, page language
tag `ko`. This file is sent verbatim with every translation request for this
language, on top of the shared rules in `../general-prompt.md`. The termbase
in `glossary.json` is sent alongside it and wins any terminology conflict with
this file.

## 1. Register

Write 합쇼체 (formal-polite, sentence endings in -습니다 / -ㅂ니다) as the one
register for the whole page.

- Body prose, list items, table cells and admonition bodies end in -습니다 /
  -ㅂ니다: "The SDK does the rest." → SDK가 나머지를 처리합니다.
- Short imperatives (steps, instructions, calls to action) use -세요:
  "Create a file `server.py`" → `server.py` 파일을 만드세요. Never -십시오, never
  the bare 해요체 (-어요 / -예요 / -해요), and never plain-style -다 endings.
- Headings are noun phrases where the English heading is a noun phrase
  ("Installation" → 설치). An English heading phrased as a sentence or a
  question becomes a noun phrase too: "What's new in v2" → v2에서 달라진 점.
  Do not write -나요? or -습니까? headings.
- Never address the reader with 당신, 여러분 or 우리. Korean drops the
  subject: "you can pass a URL" → URL을 전달할 수 있습니다. Where a subject is
  unavoidable, name the role — 클라이언트, 서버, 사용자 — never a pronoun.
  "Your server" is 서버 or, when the contrast matters, 작성한 서버.
- One page, one register. Mixing -습니다 with -어요, or -세요 with -십시오, is
  wrong even when each sentence is correct on its own.

## 2. Voice

Warm, direct and considerate: the reader is a capable developer being
guided by a colleague, not lectured by a manual.

- Keep the source's directness and its short payoff sentences. "That's a
  complete MCP server." → 이것으로 완전한 MCP 서버가 완성됩니다. Do not pad the
  translation with hedges the English does not have.
- A brief friendly aside is welcome in Korean too — 참고로, 다행히, a plain
  환영합니다 — as long as it stays in 합쇼체.
- Prefer verbs over noun stacks. "Configuration of the transport" is 트랜스포트를
  설정하는 방법, not 트랜스포트의 설정.
- Avoid translationese (번역체):
  - no double passives: -되어지다 → -되다; no -할 것입니다 chains where -합니다
    says the same thing;
  - no pronoun crutches: drop 그것, 그들, 이것들 — repeat the noun or restructure;
  - do not stack a conditional marker on top of -면: drop 만약 when -(으)면
    already carries the condition;
  - mark plurals sparingly: Korean rarely needs -들 ("the tools" → 도구);
  - no honorific inflation: 살펴보시면 ✗ → 살펴보면 ✓ (-세요 endings are the
    only place -시- appears);
  - do not overuse -에 대해 / -에 대하여 where a plain object particle works.

Example — English: "A **host** is the LLM application: Claude, an IDE, an
agent runtime. It's the thing the user is talking to."

- Wrong (translationese): **호스트**는 LLM 애플리케이션입니다: Claude, IDE,
  에이전트 런타임. 그것은 사용자가 그것에게 이야기하는 것입니다.
- Right: **호스트**는 LLM 애플리케이션입니다. Claude, IDE, 에이전트 런타임이 여기에
  해당하며, 사용자가 대화하는 상대가 바로 호스트입니다.

## 3. Humour and idioms

Translate the information, not the joke.

- Idioms, puns and light asides are recast into a plain friendly 합쇼체
  sentence that carries the same fact, never translated word for word: "Out
  of the box the app answers **only** requests addressed to localhost." →
  기본적으로 이 앱은 localhost로 오는 요청**만** 받습니다. — not 상자에서 꺼내자마자.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → 자세한 내용은 **[X](…)**에서
  확인하세요.; "That's the whole API." / "That's the whole protocol." → 이것이
  API의 전부입니다. / 프로토콜은 이것이 전부입니다.; "That's it. It's just Python."
  → 이게 전부입니다. 평범한 Python일 뿐입니다.
- Exclamation marks: keep one only where the English is genuinely
  emphatic; a routine sentence ends with 온점 even if the source ends in "!".
- Emoji: the source's only emoji are two ✨ closing payoff lines, and they
  are dropped in Korean; the friendliness moves into the wording. "You get
  `3` back. ✨" → `3`이 돌아옵니다. Emoji shortcodes (`:smile:`) are syntax and
  stay untouched.
- If a light aside has no natural Korean equivalent, replace it with a
  neutral sentence stating the underlying point — never leave a gap and
  never add a translator's note explaining the joke.

## 4. Typography

- Punctuation is ASCII: `. , ? ! ( )`. Never 。 、 「」 or full-width forms.
  Every sentence, including -세요 imperatives, ends with 온점 `.`.
- No sentence-final colon or dash before a code block or list: "Try this:"
  → 다음을 시도해 보세요. An English em-dash aside becomes a comma, a
  parenthesis, or its own sentence — no ` — ` in Korean prose.
- Straight quotes only. No italics on Hangul: where the source italicises a
  word that becomes Korean, use `**굵게**` or nothing; italics may stay
  around Latin-script words.
- Spacing follows 한글 맞춤법: words are separated by spaces, but a
  particle (조사) attaches to the word before it — also after Latin words and
  code spans, with no space in between: Python은, MCP를, `add`를 호출합니다,
  `Client`가 연결을 맺습니다. Latin words otherwise sit in the sentence like
  Korean words, with normal spacing on each side.
- Choose the particle after a Latin word or code span by how the term is
  read aloud: Python은 (파이썬), stdio는, MCP는 (엠씨피), `list_tools`를,
  Streamable HTTP를. When the reading is unclear (symbols, mixed digits),
  restructure so a Korean noun carries the particle — `x` 값을, `--port`
  옵션은. Never write the double form 은(는) / 을(를) / 이(가).
- Digits are ASCII; a unit or counter follows a numeral without a space:
  3개, 30초, 8000번 포트, 5MB. Version numbers and the protocol's date-shaped
  revision strings are identifiers and are copied byte-for-byte (they are in
  the glossary's keep list). A calendar date written out in prose, if any,
  becomes 2026년 7월 28일.
- Parenthetical originals use ASCII parentheses with no space before them:
  엘리시테이션(elicitation).

## 5. Terminology pointer

The glossary (`glossary.json`) is injected separately and overrides this
file on every term it covers. These conventions apply to everything the
glossary does not pin:

- Loanword spellings follow the standard 외래어 표기법: 서버, 클라이언트,
  콜백 (not 콜빽), 프롬프트, 세션, 토큰, 스키마, 데코레이터, 미들웨어. Where an
  ICT term is not in the glossary, prefer the rendering that mainstream
  Korean developer documentation uses; treat 국립국어원 and TTA usage as the
  tie-breaker.
- Three strategies coexist and the glossary decides which applies per term:
  transliterate established loanwords (스트림, 서버), translate into the common
  Sino-Korean word where that is the mainstream (요청, 응답, 알림, 도구, 인가,
  의존성), and keep in Latin script anything that is an identifier or a
  proper name — class and function names, wire method names such as
  `tools/call`, package names, protocol and product names.
- Text quoted from what the example code prints or displays (an output
  line, a log message, a UI label) stays exactly as the code emits it,
  usually English.
- 한글(English) 병기: the glossary marks a few MCP-specific nouns for a
  parenthetical original on first mention only — 엘리시테이션(elicitation) once,
  then 엘리시테이션. Class names never get a Hangul gloss.
- One term, one rendering, throughout the page. Do not alternate between
  객체 and 오브젝트, or between 컨텍스트 and 맥락, for the same source term.
- Abbreviations stay Latin and lose the English plural "s": "the APIs" → API.

## 6. Provisional note

Every decision in this file is provisional pending review by native Korean
speakers. To propose a change, edit this file (or `glossary.json`) in a pull
request — never edit the generated pages under `pages/`.
