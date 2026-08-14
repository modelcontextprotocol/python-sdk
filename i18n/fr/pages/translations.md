---
translation:
  sections: [f671b445b16e4f99, 3983a560eb2cece7, b5c8bd4f2b3903e5, c6e2debf1da06eb7, 81d412ed5f399f94]
  tool: 1
---
# Traductions {#translations}

Cette documentation est rédigée en anglais. Pour qu’elle soit utile à davantage de personnes, nous en publions aussi des éditions traduites automatiquement. Cette page explique ce que cela signifie pour vous et comment contribuer à les améliorer.

## Ce qui est disponible {#whats-available}

La documentation traduite est actuellement une **préversion** en douze langues : Deutsch, español, français, हिन्दी, 日本語, 한국어, português (Brasil), русский язык, Türkçe, українська мова, 简体中文 et 繁體中文. Choisissez-en une dans le sélecteur de langue en haut de n’importe quelle page. D’autres langues pourront suivre une fois que celles-ci auront fait leurs preuves.

La référence de l’API n’est pas traduite : le site traduit renvoie vers l’unique version anglaise.

## L’anglais fait foi {#english-is-the-source-of-truth}

Si une page traduite et son original anglais divergent, c’est la page anglaise qui a raison. Chaque page d’un site traduit s’ouvre sur l’une de ces trois mentions, qui indique où elle en est :

- **Traduction automatique** — la page a été traduite automatiquement et renvoie vers son original anglais.
- **Traduction en retard sur la page anglaise** — l’original anglais a changé après la traduction de la page. Vous lisez toujours cette traduction ; certaines parties peuvent donc être obsolètes jusqu’à ce qu’elle rattrape son retard ; la mention renvoie vers la page anglaise actuelle.
- **Affichée en anglais** — la page n’a pas encore été traduite ; vous lisez donc le texte anglais.

## Comment les traductions sont produites {#how-the-translations-are-made}

Les pages traduites sont générées automatiquement par un outil de ce dépôt à partir des pages anglaises situées sous `docs/`, guidé par deux documents rédigés par des humains pour chaque langue : un guide de style (registre, ton, typographie, traitement des plaisanteries et des expressions idiomatiques) et un glossaire (les termes qui restent en anglais, ainsi que les traductions imposées et interdites pour les autres). Le texte généré n’est jamais modifié à la main. Chaque amélioration va dans ces documents, de sorte qu’elle survit à la prochaine régénération des pages.

## Signaler un problème de traduction {#reporting-a-translation-problem}

Vous avez repéré un terme incorrect, une phrase maladroite ou une traduction qui dit autre chose que l’anglais ? [Ouvrez un ticket](https://github.com/modelcontextprotocol/python-sdk/issues) en indiquant la langue, la page et le passage ; les signalements de locuteurs natifs sont particulièrement précieux. Si vous connaissez la correction, proposez-la directement sous forme de pull request sur le guide de style (`instructions.md`) ou le glossaire (`glossary.json`) de la langue concernée, sous [`i18n/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/i18n) — la correction se propage alors à toutes les pages concernées lors de la prochaine régénération des traductions. Les problèmes du texte anglais lui-même se corrigent dans les pages sous `docs/`, comme toute autre modification de la documentation.
