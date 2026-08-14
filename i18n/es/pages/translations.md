---
translation:
  sections: [f671b445b16e4f99, 3983a560eb2cece7, b5c8bd4f2b3903e5, c6e2debf1da06eb7, 81d412ed5f399f94]
  tool: 1
---
# Traducciones {#translations}

Esta documentación está escrita en inglés. Para que resulte útil a más personas, también publicamos ediciones traducidas automáticamente, y esta página explica qué significa eso para ti y cómo ayudar a mejorarlas.

## Qué hay disponible {#whats-available}

La documentación traducida es por ahora una **vista previa** en doce idiomas: Deutsch, español, français, हिन्दी, 日本語, 한국어, português (Brasil), русский язык, Türkçe, українська мова, 简体中文 y 繁體中文. Elige uno en el selector de idioma de la parte superior de cualquier página. Puede que se añadan más idiomas una vez que estos hayan demostrado su valor.

La referencia de la API no está traducida: el sitio traducido enlaza a la única versión, en inglés.

## El inglés es la fuente de verdad {#english-is-the-source-of-truth}

Si una página traducida y su original en inglés no coinciden, la página en inglés es la correcta. Cada página de un sitio traducido se abre con una de estas tres notas, que indica en qué estado se encuentra:

- **Traducción automática**: la página se tradujo automáticamente y enlaza a su original en inglés.
- **Traducción desactualizada respecto a la página en inglés**: el original en inglés cambió después de traducir la página. Sigues leyendo esa traducción, así que algunas partes pueden estar desactualizadas hasta que se ponga al día; la nota enlaza a la página actual en inglés.
- **Mostrada en inglés**: la página todavía no se ha traducido, así que estás leyendo el texto en inglés.

## Cómo se hacen las traducciones {#how-the-translations-are-made}

Las páginas traducidas las genera automáticamente una herramienta de este repositorio a partir de las páginas en inglés bajo `docs/`, guiada por dos insumos escritos por personas para cada idioma: una guía de estilo (registro, tono, tipografía, cómo tratar los chistes y los modismos) y un glosario (qué términos se quedan en inglés, y las traducciones obligatorias y prohibidas del resto). El texto generado nunca se edita a mano. Todas las mejoras van a esos insumos, de modo que sobreviven la próxima vez que se regeneren las páginas.

## Informar de un problema de traducción {#reporting-a-translation-problem}

¿Encontraste un término incorrecto, una frase forzada o una traducción que dice algo que el inglés no dice? [Abre un issue](https://github.com/modelcontextprotocol/python-sdk/issues) indicando el idioma, la página y el pasaje; los informes de hablantes nativos son especialmente valiosos. Si conoces la solución, proponla directamente como pull request contra la guía de estilo (`instructions.md`) o el glosario (`glossary.json`) de ese idioma bajo [`i18n/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/i18n): la corrección llegará a todas las páginas afectadas la próxima vez que se regeneren las traducciones. Los problemas del propio texto en inglés se corrigen en las páginas bajo `docs/`, como cualquier otro cambio en la documentación.
