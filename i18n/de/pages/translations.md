---
translation:
  sections: [f671b445b16e4f99, 3983a560eb2cece7, b5c8bd4f2b3903e5, c6e2debf1da06eb7, 81d412ed5f399f94]
  tool: 1
---
# Übersetzungen {#translations}

Diese Dokumentation ist auf Englisch verfasst. Damit sie mehr Menschen nützt, veröffentlichen wir zusätzlich maschinell übersetzte Ausgaben davon. Diese Seite erklärt, was das für dich bedeutet und wie du helfen kannst, sie zu verbessern.

## Was verfügbar ist {#whats-available}

Die übersetzte Dokumentation ist derzeit eine **Vorschau** in zwölf Sprachen: Deutsch, español, français, हिन्दी, 日本語, 한국어, português (Brasil), русский язык, Türkçe, українська мова, 简体中文 und 繁體中文. Wähle eine über die Sprachauswahl oben auf jeder Seite. Weitere Sprachen können folgen, sobald sich diese bewährt haben.

Die API-Referenz wird nicht übersetzt: Die übersetzte Website verlinkt auf die eine englische Fassung.

## Maßgeblich ist die englische Fassung {#english-is-the-source-of-truth}

Wenn eine übersetzte Seite und ihr englisches Original voneinander abweichen, gilt die englische Seite. Jede Seite einer übersetzten Website beginnt mit einem von drei Hinweisen, der ihren Stand angibt:

- **Maschinelle Übersetzung** – die Seite wurde automatisch übersetzt und verlinkt auf ihr englisches Original.
- **Übersetzung hinter der englischen Seite zurück** – das englische Original hat sich geändert, nachdem die Seite übersetzt wurde. Du liest weiterhin diese Übersetzung, Teile davon können also veraltet sein, bis sie nachzieht; der Hinweis verlinkt auf die aktuelle englische Seite.
- **Auf Englisch angezeigt** – die Seite wurde noch nicht übersetzt, deshalb liest du den englischen Text.

## Wie die Übersetzungen entstehen {#how-the-translations-are-made}

Übersetzte Seiten erzeugt ein Tool in diesem Repository maschinell aus den englischen Seiten unter `docs/`, gesteuert von zwei von Menschen geschriebenen Vorgaben pro Sprache: einem Styleguide (Anrede, Tonfall, Typografie, Umgang mit Witzen und Redewendungen) und einem Glossar (welche Begriffe auf Englisch bleiben sowie die vorgeschriebenen und verbotenen Wiedergaben für den Rest). Der erzeugte Text wird nie von Hand bearbeitet. Jede Verbesserung fließt stattdessen in diese Vorgaben ein, damit sie die nächste Neuerzeugung der Seiten übersteht.

## Ein Übersetzungsproblem melden {#reporting-a-translation-problem}

Einen falschen Begriff, einen holprigen Satz oder eine Übersetzung gefunden, die etwas anderes sagt als das Englische? [Eröffne ein Issue](https://github.com/modelcontextprotocol/python-sdk/issues) mit der Sprache, der Seite und der Textstelle; Meldungen von Menschen mit der jeweiligen Muttersprache sind besonders wertvoll. Wenn du die Korrektur kennst, schlage sie direkt als Pull Request gegen den Styleguide (`instructions.md`) oder das Glossar (`glossary.json`) der jeweiligen Sprache unter [`i18n/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/i18n) vor – die Korrektur erreicht dann jede betroffene Seite, sobald die Übersetzungen das nächste Mal neu erzeugt werden. Probleme mit dem englischen Text selbst werden in den Seiten unter `docs/` behoben, wie jede andere Änderung an der Dokumentation.
