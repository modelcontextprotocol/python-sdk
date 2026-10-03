# Japanese (ja) — translation instructions

Target language: Japanese (日本語), directory and URL code `ja`, page language
tag `ja`. This file is sent verbatim with every translation request for this
language, on top of the shared rules in `../general-prompt.md`. The termbase
in `glossary.json` is sent alongside it and wins any terminology conflict with
this file.

## 1. Register

Write body prose in the polite です・ます form (敬体), consistently, on every
page — tutorials, reference tables, admonitions and troubleshooting entries
alike.

- Never mix in だ・である (常体) sentence endings within body text, and do
  not escalate into honorifics (尊敬語・謙譲語): 使うときは, not
  お使いいただく際には.
- Headings, table headers, content-tab labels and other UI-like fragments
  are noun phrases (体言止め) or the plain dictionary form of a verb, never
  です・ます: "Run it" → 実行する or 実行方法, "The Context" → Context,
  "Handling errors" → エラーの処理. A heading phrased as a question in
  English may stay a question in the plain form: "Where does this go?" →
  これはどこに置くべきか.
- Instructions to the reader: 〜してください for a step to perform,
  〜します / 〜できます for describing what code does, 〜しないでください
  for prohibitions. Prefer 〜です over 〜になります / 〜となります when both
  are grammatical.
- The reader is never named. Do not translate "you" / "your" as あなた,
  あなたの, 君, ユーザー様: drop the subject, which Japanese does
  naturally, or restructure the sentence. "You can pass a schema" →
  スキーマを渡せます. Where a subject is unavoidable, name the role —
  サーバー, クライアント, ツール, 呼び出し側 — never a pronoun. "Your server"
  is サーバー, or 自分のサーバー / 作成中のサーバー only when the ownership
  is the point.
- One page, one register: a page that drifts between です・ます and である,
  or that reintroduces あなた, is wrong even when each sentence is
  acceptable on its own.

## 2. Voice

The English source is warm, direct and confident: short sentences, second
person, and the occasional one-line payoff ("That's the whole API."). Carry
that voice into natural Japanese; do not flatten it into formality, and do not
mirror the English word for word.

- Guide, don't lecture. The reader should feel accompanied by a knowledgeable
  colleague, not addressed by a notice. Directness comes from concrete verbs
  and plain word order; warmth comes from the polite register itself,
  considerate connectives (まず, ここでは, なお) and the occasional
  〜してみましょう / 〜してみてください for an encouraging aside.
- Keep the short payoff sentences short: "That's the whole API." →
  API はこれだけです。 — not a formal summary sentence.
- Split long English sentences; follow Japanese rhythm rather than the
  source's clause structure, but never merge, drop or reorder the technical
  claims themselves.
- Anti-patterns — the stiff, legalistic translationese that Japanese
  technical translations drift into by default: no 〜なのである /
  〜のである; no nominalisation chains (〜の実施を行うことにより →
  〜すると); no boilerplate such as 〜するものとします or 〜が求められます
  where 〜してください is meant; no stacked ただし / なお clauses; no
  needlessly formal kanji where kana reads more easily (できる not 出来る).
  The opposite over-correction is also wrong: no よ endings, no
  buddy-casual tone, and ね at most sparingly in tutorial prose, never in
  reference pages.

Example — English: "You don't construct it and you don't configure it. You
ask for it."

- Not this (translationese): 利用者がその構築および構成を実施する必要はなく、
  要求のみを行うものとする。
- Not this either (pronoun + casual): あなたはそれを構築しないし、設定もしない。
  要求するだけだよ。
- This: 自分で組み立てる必要も、設定する必要もありません。要求するだけです。

## 3. Humour and idioms

- Translate the intent of a joke, aside or idiom, never its words. Recast
  it as a friendly plain sentence carrying the same information; if a
  lighthearted phrase carries no information at all, keep the sentence brief
  and natural rather than inventing a Japanese joke. Never drop the technical
  content around it.
- Recurring English tags get fixed renderings: "X has the whole story" /
  "The whole story is in X" → 詳しくは X を参照してください;
  "That's it. It's just Python." → これだけです。ただの Python です。
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → デフォルトでは、この
  アプリは localhost 宛てのリクエストに**だけ**応答します。 — not the literal
  箱から出してすぐ.
- Exclamation marks: drop them by default. Keep a single full-width ！
  only where the English is a genuine exclamation of encouragement, never
  after a warning or instruction, never doubled, never in a heading.
- Emoji: reproduce an emoji only where the English page has one, in the same
  place (the source occasionally closes a step with ✨); never add emoji and
  never put one in a heading.

## 4. Typography

- Punctuation is full-width 「、」 and 「。」; never 「，」「．」, and never a
  half-width `,` or `.` closing Japanese prose. A colon that introduces a
  code block, list or example becomes 「：」, or better a complete sentence
  ending in 「。」 (次のように書きます。).
- Full-width forms inside Japanese text: 「」 for quoted terms and English
  scare quotes, 『』 for nested quotes and titles, ？ and ！ when kept, and
  （） always — Japanese parentheses are full-width even when they enclose
  only Latin text or code, as in the first-use gloss ルート（roots）.
- Widths: kana and kanji full-width, no half-width katakana; Latin letters,
  digits and code half-width. Counting uses half-width Arabic numerals
  (3 つの答え, not 三つ), except in set phrases such as 一度 or 一部.
- Spacing: insert one half-width space between Japanese text and any
  half-width run — an English word, a number, an inline code span, a link
  whose text is Latin: Python の型ヒント, `Context` を受け取ります,
  MCP サーバー. No space next to 「、」「。」 or full-width brackets
  (`ctx.session` を使うと、), and none inside katakana compounds
  (エラーメッセージ, ツール呼び出し). This spacing convention is provisional;
  apply it uniformly.
- No italics: Japanese type has no true italic, so never wrap Japanese text
  in `*…*` or `_…_`. When the English italicises a word that gets
  translated, use 「」 or drop the emphasis; keep `**bold**` where the source
  has it, and keep the bold on negations (**not** → **ではありません** /
  **しません**). Emphasis markers around text that stays in English are
  copied as-is.
- Dashes and ranges: an English em-dash aside is recast with 、, （） or a
  second sentence, not with a ――; ranges use から (3.10 から 3.14), not 〜
  or –.
- Sentence length: one idea per sentence and at most three 「、」. In one
  bulleted list, items either all end in 「。」 (complete sentences) or none
  do (fragments).
- Line breaks: never put a newline between two Japanese characters, not even
  after 「。」 — the renderer turns it into a stray space. Where the English
  wraps a paragraph, list item or admonition body over several lines, or
  gives each sentence its own line, write the Japanese on one line, sentence
  after sentence; block structure and indentation stay as in the source.

## 5. Terminology pointer

The glossary is sent separately and takes precedence over anything here.
It holds every term-by-term rendering — the six core MCP nouns and the
everyday computing vocabulary alike — and marks each one as standard,
provisional or an open question; use its renderings and its first-use
glosses exactly as noted. The rules below are the conventions those
renderings assume.

- Identifiers stay in Latin script exactly as written: class, function,
  method, parameter, environment-variable, error and package names,
  protocol method names such as `tools/call`, and everything in code font.
  Product and standard names, and every term in the glossary's keep list,
  stay in English too (MCP, Streamable HTTP, JSON-RPC, OAuth, the SDK's
  class names, spec revision dates such as 2026-07-28), always in the
  singular: an English plural "s" is dropped, "the APIs" → API. Do not
  append a katakana reading after them.
- Text quoted from what the example code prints or displays — an output
  line, a log message, a UI label — stays exactly as the code emits it
  (usually English); do not translate it or add a Japanese reading.
- A term the glossary marks for a first-use gloss carries the English in
  full-width parentheses on its first appearance in a page — ルート（roots）,
  エリシテーション（elicitation） — and appears alone after that. A glossary
  word used as a wire identifier or a key in code font is code and stays
  Latin.
- Katakana loanwords take the long-vowel mark for -er, -or and -ar endings:
  サーバー (never サーバ), ハンドラー, リゾルバー, ユーザー, パラメーター,
  ヘッダー, フォルダー, プロバイダー. Words ending in -y keep their customary
  short form: プロパティ, ディレクトリ, ライブラリ, セキュリティ, メモリ. Words
  ending in -ware take ウェア: ミドルウェア, ソフトウェア.
- Katakana compounds are written solid, without a space or a 中黒:
  エラーメッセージ, プロトコルバージョン (use ・ only between two proper
  names).
- Prefer the established loanword over an invented native coinage; the
  glossary lists the settled pairs (セッション not 会期, トランスポート not
  輸送手段, ハンドシェイク not 握手).

## 6. Provisional note

These conventions are provisional and awaiting review by native
Japanese-speaking contributors. To propose a change — a better rendering, a
rule that produces awkward Japanese, a term that needs pinning — edit this
file, or `glossary.json` next to it, in a pull request. The generated pages
are never edited by hand; they are regenerated from these inputs.
