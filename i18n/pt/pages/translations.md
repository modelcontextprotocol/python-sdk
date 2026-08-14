---
translation:
  sections: [f671b445b16e4f99, 3983a560eb2cece7, b5c8bd4f2b3903e5, c6e2debf1da06eb7, 81d412ed5f399f94]
  tool: 1
---
# Traduções {#translations}

Esta documentação é escrita em inglês. Para torná-la útil a mais pessoas, também publicamos edições dela traduzidas por máquina, e esta página explica o que isso significa para você e como ajudar a melhorá-las.

## O que está disponível {#whats-available}

A documentação traduzida é atualmente uma **prévia** em doze idiomas: Deutsch, español, français, हिन्दी, 日本語, 한국어, português (Brasil), русский язык, Türkçe, українська мова, 简体中文 e 繁體中文. Escolha um no seletor de idioma no topo de qualquer página. Outros idiomas podem vir depois que estes se provarem.

A referência da API não é traduzida: o site traduzido aponta para a única referência, em inglês.

## O inglês é a fonte da verdade {#english-is-the-source-of-truth}

Se uma página traduzida e seu original em inglês discordarem, a página em inglês é a correta. Toda página de um site traduzido abre com uma de três notas dizendo em que pé ela está:

- **Tradução automática** — a página foi traduzida automaticamente e tem um link para o original em inglês.
- **Tradução atrás da página em inglês** — o original em inglês mudou depois que a página foi traduzida. Você ainda está lendo essa tradução, então partes dela podem estar desatualizadas até ela alcançar o original; a nota tem um link para a página atual em inglês.
- **Exibida em inglês** — a página ainda não foi traduzida, então você está lendo o texto em inglês.

## Como as traduções são feitas {#how-the-translations-are-made}

As páginas traduzidas são geradas por máquina por uma ferramenta deste repositório a partir das páginas em inglês em `docs/`, guiadas por dois insumos escritos por humanos para cada idioma: um guia de estilo (registro, tom, tipografia, como lidar com piadas e expressões idiomáticas) e um glossário (quais termos ficam em inglês e as traduções obrigatórias e proibidas para o restante). O texto gerado nunca é editado à mão. Toda melhoria vai para esses insumos, de modo que ela sobrevive à próxima vez que as páginas forem regeneradas.

## Reportando um problema de tradução {#reporting-a-translation-problem}

Encontrou um termo errado, uma frase estranha ou uma tradução que diz algo que o inglês não diz? [Abra uma issue](https://github.com/modelcontextprotocol/python-sdk/issues) com o idioma, a página e o trecho; relatos de falantes nativos são especialmente valiosos. Se você sabe a correção, proponha-a diretamente como um pull request no guia de estilo (`instructions.md`) ou no glossário (`glossary.json`) daquele idioma, em [`i18n/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/i18n) — a correção então chega a todas as páginas afetadas na próxima vez que as traduções forem regeneradas. Problemas com o próprio texto em inglês são corrigidos nas páginas em `docs/`, como qualquer outra mudança na documentação.
