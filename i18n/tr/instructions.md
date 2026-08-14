# Turkish (tr) — translation instructions

Target language: Turkish (Türkçe), directory and URL code `tr`, page language
tag `tr`. This file is sent verbatim with every translation request for this
language, on top of the shared rules in `../general-prompt.md`. The termbase
in `glossary.json` is sent alongside it and wins any terminology conflict with
this file.

## 1. Register

Write the clear, instructional Turkish of good developer documentation: polite
but not ceremonial, addressed to a colleague.

- The reader is siz, almost always left implicit. Steps and instructions take
  the polite-plural imperative in -in / -ın / -un / -ün by vowel harmony
  (çalıştırın, kurun, ekleyin, açın): "Install the SDK, then run the server" →
  SDK'yı kurun, ardından sunucuyu çalıştırın. Never the over-formal -iniz
  (çalıştırınız), never the bare sen imperative (çalıştır), never a mix.
- Statements about what code does use the aorist: "The SDK does the rest" →
  Gerisini SDK halleder; "You can pass a schema" → Bir şema geçirebilirsiniz.
  Not the bureaucratic -mektedir / -maktadır, not a needless -ecektir. "Your
  server" is usually just sunucu; sunucunuz only where ownership is the point;
  siz as an explicit subject only when the sentence contrasts actors.
- Headings, table headers and content-tab labels are noun phrases in sentence
  case, typically the -ma / -me verbal noun, with no final punctuation:
  "Running your server" → Sunucunuzu çalıştırma, "Handling errors" → Hataları
  ele alma, "Inside your handler" → İşleyicinin içinde. Not an imperative
  (Sunucuyu çalıştırın) and not a question unless the English heading is one.
- A first-person-plural aside (bir bakalım) is fine where the English says
  "let's", not for plain instructions. One page, one register: drifting
  between -in and -iniz, or into -mektedir, is wrong even if each sentence is
  fine alone.

## 2. Voice

The English is warm, direct and confident: short sentences, second person, the
occasional one-line payoff ("That's the whole API."). Rewrite it as natural
Turkish, as if the page had been written in Turkish, keeping every claim exact.

- Follow Turkish word order; split a long English sentence into two rather
  than mirroring its clause chain, and use everyday connectives (Ancak, Yani,
  Bu yüzden) where they help. Never merge, drop or reorder the claims.
- Use concrete verbs (çalıştırın, geçirin, döndürür, bildirir, engeller) and
  the active voice: "The tool is called by the model" → Aracı model çağırır,
  not Araç model tarafından çağrılır. Keep the payoff lines short: "That's a
  complete MCP server." → Bu, eksiksiz bir MCP sunucusu.
- Avoid officialese: -mektedir chains, gerçekleştirmek + noun (çalıştırma
  işlemini gerçekleştirin → çalıştırın), söz konusu, işbu, tarafınızca, and
  bulunmak as padding (yer almaktadır → var). Avoid word-for-word English too:
  bir before every noun, o / onlar pronoun crutches, possessive chains
  (sunucunuzun aracının şemasının), sahip olmak for every "has" (Sunucu üç
  araca sahiptir → Sunucuda üç araç var).
- No hedging the English does not have ("don't" is kullanmayın, not
  kaçınmanız iyi olabilir) — and no over-correction either: no sen, no chat
  tone (hadi, süper, falan), no smileys, no Turkish verb endings on English
  words (deploylamak — see §5).

Example — English: "You don't construct it and you don't configure it. You ask
for it."

- Not this (officialese): Söz konusu nesnenin oluşturulması ve yapılandırılması
  tarafınızca gerçekleştirilmemektedir; yalnızca talep edilmesi gerekmektedir.
- Not this either (sen, chatty): Onu sen oluşturmuyorsun, ayarlamıyorsun da.
  İstiyorsun, o kadar.
- This: Onu siz oluşturmazsınız, yapılandırmazsınız da. Yalnızca istersiniz.

## 3. Humour and idioms

- Translate the intent of a joke, aside or idiom, never its words: recast it
  as a short, natural Turkish sentence in the same register, or keep it brief
  where it carries nothing. Never drop the technical content around it.
- Recurring English tags get fixed renderings: "**[X](…)** has the whole
  story" / "The whole story is in **[X](…)**" → Ayrıntıların tamamı
  **[X](…)** sayfasında.; "That's the whole API." / "That's the whole
  protocol." → API'nin tamamı bu. / Protokolün tamamı bu.; "That's it. It's
  just Python." → Hepsi bu. Bildiğiniz Python.; "You get `3` back. ✨" →
  Geriye `3` döner. ✨
- Idioms take the plain meaning, not the picture: "Out of the box the app
  answers **only** requests addressed to localhost." → Varsayılan olarak
  uygulama **yalnızca** localhost'a gönderilen istekleri yanıtlar. — not
  kutudan çıktığı gibi; "under the hood" → arka planda, not kaputun altında;
  "on the wire" → iletilen veride / ağ üzerinde, never kabloda.
- Keep an exclamation mark only where the English is a genuine exclamation of
  encouragement — never after a warning or a step, never doubled, never in a
  heading. Reproduce an emoji only where the English has one, in the same
  place (two payoff lines end in ✨); never add one.

## 4. Typography

- Quotation marks are the double quotes the source uses ("…"), nested quotes
  single ('…'); no «…», no „…“. When the English quotes a word the example
  code prints or a UI label, it stays exactly as emitted: "Tools" sekmesi.
- Suffixes on Latin-script words. A proper name, keep-list term, acronym,
  number, kept English word or inline code span takes its suffix after an
  apostrophe, following vowel harmony for the word **as pronounced**:
  - English words and names by their English sound: Python'ı, Python'da;
    Claude'u, Claude'a; GitHub'ı; `Client`'ı, `Client`'a, `Client`'ta;
    `Context`'i, `Context`'e; token'ı, token'lar; callback'i, callback'ler;
    prompt'u, prompt'lar; localhost'a, localhost'ta.
  - Acronyms letter by letter in Turkish: API'yi, API'ye, API'nin; SDK'yı,
    SDK'nın, SDK'lar; MCP'yi, MCP'de; HTTP'nin; URL'yi, URL'ler; LLM'lere;
    SSE'yi — except acronyms read as a word: JSON'u, JSON'a, JSON'da.
  - After a voiceless final sound (p, ç, t, k, f, h, s, ş) the suffix
    consonant hardens (`dict`'te, stdout'ta, `Client`'tan); a vowel-final word
    takes the buffer letter (stdio'yu, stdio'da, anyio'nun).
  - On a code span the apostrophe and suffix sit directly after the closing
    backtick, never inside it, never after a space: `call_tool()`'u çağırın,
    `ctx`'i isteyin. Suffixes stack the normal way: token'ları, prompt'larda.
  - Never respell, re-case or hyphenate a term to suit the suffix. Where the
    pronunciation is unclear (symbols, flags, paths, mixed digits), let a
    Turkish noun carry the suffix: `--port` seçeneğini, `server.py` dosyasını,
    `greeting://{name}` kaynağını, 8000 numaralı port.
- Dotted and dotless i. Turkish words follow Turkish casing — İstemci, İlk
  adımlar; the capital of i is İ, the lowercase of I is ı. Words that stay in
  English keep their letters untouched in every position: Inspector (never
  İnspector), API (never APİ), `id`. Never re-case an English word or an
  identifier yourself; a heading that starts with one leaves it as spelled.
- Sentence case everywhere: headings, admonition titles, tab labels and table
  headers capitalise the first word and proper nouns only (Sunucunuzu
  çalıştırma, not Sunucunuzu Çalıştırma); language names stay capitalised
  (İngilizce).
- Digits stay ASCII. Protocol revision strings such as `2026-07-28` are
  identifiers, copied byte for byte — never 28.07.2026, never 28 Temmuz 2026.
  Version numbers, ports, status codes, RFC and SEP numbers are copied exactly.
- Prose quantities take the decimal comma only when nothing but the separator
  changes (2.5 seconds → 2,5 saniye); when in doubt keep the number as written.
  The percent sign precedes the number (%100); a unit follows a space (100 MB).
- e.g. → örneğin; i.e. → yani; etc. → vb.; "&" → ve. Emphasis lands on the
  same words the source emphasises; a bolded "**not**" becomes a bolded değil
  or negated verb (**does not** raise → hata **fırlatmaz**). Kept English words
  are set in plain type, no italics or quotes. An em-dash aside usually becomes
  a comma pair, parentheses or its own sentence; colons before lists stay.

## 5. Terminology pointer

The glossary (`glossary.json`) is injected separately and overrides this file
on every term it covers; each entry marks its choice as standard or provisional
and says whether it takes a first-use gloss. Its renderings assume:

- Identifiers stay in Latin script exactly as written: class, function,
  method, parameter, module and header names, protocol method strings such as
  `tools/call`, and everything in code font. So do the keep-list terms,
  acronyms and product names, which drop the English plural "s" and take a
  Turkish one where needed: "the SDKs" → SDK'lar.
- Two tracks, and the glossary decides per term. Translate where Turkish
  developers use the Turkish word: sunucu, istemci, araç, kaynak, istek,
  yanıt, bildirim, oturum, bağımlılık, işleyici, bağlam, şema, istisna,
  yetkilendirme, kimlik doğrulama, varsayılan, sürüm, dağıtım. Keep the English
  word — lower-case, plain type, suffixed with an apostrophe — where that is
  what Turkish developers say: token, callback, middleware, endpoint, host,
  prompt, lifespan, commit, log. Nouns are borrowed, verbs are not: commit
  etmek, dağıtmak for "deploy" — never commitlemek, deploylamak.
- Text quoted from what the example code prints or displays — an output line,
  a log message, an Inspector tab or button label — stays exactly as the code
  emits it (usually English), in or out of code font; never translate it.
- First-use gloss, both ways, as the glossary marks it: a translated concept
  carries the English once per page — örnekleme (sampling) — and a kept
  English one may carry a Turkish explanation once — elicitation (kullanıcıdan
  bilgi isteme). A glossary word used as an identifier in code font stays as
  written: "the `sampling` capability" → `sampling` yeteneği.
- One rendering per term per page: the glossary target, every time. Do not
  alternate yanıt and cevap, or istemci and client, for the same source term.

## 6. Provisional note

Every decision in this file, and every entry in `glossary.json`, is
provisional pending review by native Turkish-speaking developers. To propose a
change — a better rendering, a suffix rule that produces wrong forms, a term
that should switch tracks — edit this file or `glossary.json` in a pull
request; never edit the generated `pages/` or `notices.md`.
