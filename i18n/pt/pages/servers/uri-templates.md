---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# Templates de URI e segurança de caminhos {#uri-templates-and-path-safety}

Esta é a referência da sintaxe de templates de URI que
[`@mcp.resource`](resources.md) aceita e da política de segurança de
caminhos que o SDK aplica aos valores extraídos. Para uma introdução ao
que são recursos e quando usá-los, comece por
**[Recursos](resources.md)**; esta página parte do princípio de que você já
está à vontade declarando um recurso e quer o conjunto completo de
operadores, os controles de segurança ou a integração de baixo nível.

A sintaxe dos templates é a [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570).
O SDK dá suporte a um subconjunto escolhido para casar as URIs de
`resources/read` que chegam, mais uma camada de segurança que rejeita
valores que seriam resolvidos para fora do diretório que você pretende
servir. Para os detalhes no nível do protocolo (formatos de mensagem,
ciclo de vida, paginação), veja a
[especificação de recursos do MCP](https://modelcontextprotocol.io/specification/latest/server/resources).

## O conjunto completo de operadores {#the-full-operator-set}

O placeholder simples, `{user_id}`, é o que **[Recursos](resources.md)** apresenta. Existem mais
quatro formas de operador; aqui estão todas em um só servidor, para você
vê-las lado a lado:

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

Cada decorador destacado é um jeito diferente de recortar a URI.
As seções abaixo percorrem todos eles, de cima para baixo.

### Expansão simples: `{name}` {#simple-expansion-name}

`books://{isbn}` é a forma simples, do dia a dia. O placeholder mapeia
para o parâmetro `isbn`, então um cliente que lê `books://978-0441172719`
chama `get_book("978-0441172719")`.

Um `{name}` simples para na primeira `/`. `books://978/extra` não casa
porque a barra depois de `978` encerra a captura e `/extra` fica
sobrando.

### Conversão de tipos {#type-conversion}

Os valores extraídos chegam como strings, mas você pode declarar um tipo
mais específico e o SDK converte. `orders://{order_id}` vai parar em uma
função cujo parâmetro é `order_id: int`, então ler `orders://12345` chama
`get_order(12345)`, e não `get_order("12345")`. O handler faz contas com
ele (`order_id + 1`) sem precisar de cast.

### Caminhos com vários segmentos: `{+name}` {#multi-segment-paths-name}

Para capturar um valor que contém barras, use `{+name}`. Com
`manuals://{+path}`:

* `manuals://returns.md` dá `path = "returns.md"`
* `manuals://printing/setup.md` dá `path = "printing/setup.md"`

Recorra a `{+name}` sempre que o valor for hierárquico: caminhos do
sistema de arquivos, chaves de objetos aninhados, caminhos de URL que
você repassa como proxy.

### Parâmetros de query: `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` coloca `limit` e `sort` depois do `?`.
O caminho identifica *qual* livro; a query ajusta *como* você o lê.

O casamento dos parâmetros de query é tolerante: a ordem não importa, os
extras são ignorados e os parâmetros omitidos caem nos valores padrão da
sua função. Então `reviews://978-0441172719` usa `limit=10, sort="newest"`,
e `reviews://978-0441172719?sort=top` sobrescreve apenas `sort`.

### Segmentos de caminho como lista: `{/name*}` {#path-segments-as-a-list-name}

Se você quer cada segmento do caminho como um item separado de uma lista,
em vez de uma única string com barras, use `{/name*}`. Com
`shelves://browse{/path*}`, um cliente que lê
`shelves://browse/fiction/sci-fi` chama
`browse_shelf(["fiction", "sci-fi"])`.

### Referência de templates {#template-reference}

Os padrões mais comuns:

| Padrão       | Entrada de exemplo    | Você recebe             |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | *não casa* (para na `/`) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### O que o parser rejeita {#what-the-parser-rejects}

Alguns formatos de template são barrados logo de início, em vez de
falharem na primeira requisição. `@mcp.resource` faz o parse do template
quando o decorador executa, então nenhum deles chega a um servidor em
execução.

`UriTemplate.parse()` levanta `InvalidUriTemplate` nestes casos:

* **Duas variáveis sem nada entre elas.** `manuals://{+path}{ext}`
  é rejeitado: o casamento não tem como saber onde `path` termina e
  `ext` começa. Coloque um literal entre elas (`manuals://{+path}/{ext}`)
  ou use um operador que traga seu próprio delimitador.
  `manuals://{+path}{.ext}` é aceito porque `{.ext}` contribui ele mesmo
  com o `.`.
* **Mais de uma variável de vários segmentos.** No máximo uma entre
  `{+var}`, `{#var}` ou uma variável explodida (`{/var*}`, `{.var*}`,
  `{;var*}`) por template. Duas são inerentemente ambíguas: não há um
  critério consistente para decidir qual delas absorve um segmento extra.
* **Os erros de sintaxe de sempre**: uma chave não fechada, um nome de
  variável usado duas vezes ou uma funcionalidade da RFC 6570 à qual o
  SDK não dá suporte, como o modificador de prefixo `{var:3}` ou a
  explosão de query `{?vars*}`.

Além disso, `@mcp.resource` levanta `ValueError` quando um parâmetro do
handler está vinculado a uma variável de query na sequência
`{?...}`/`{&...}` do final do template, mas não tem valor padrão em
Python. O casamento dessas variáveis é tolerante (um cliente pode deixar
qualquer uma delas de fora), então um parâmetro sem valor padrão só
apareceria como um erro interno opaco na primeira requisição que o
omitisse. `reviews://{isbn}{?limit,sort}` no servidor acima é a versão
bem formada: `limit` e `sort` têm, ambos, valores padrão.

## Segurança {#security}

Os parâmetros de template vêm do cliente. Se eles chegarem sem
verificação a operações de sistema de arquivos ou de banco de dados,
valores como `../../etc/passwd` podem ser resolvidos para fora do
diretório que você pretendia servir.

### O que o SDK verifica por padrão {#what-the-sdk-checks-by-default}

Antes de o seu handler executar, o SDK rejeita qualquer parâmetro que:

* escaparia do seu diretório de partida por meio de componentes `..`
* parece um caminho absoluto (`/etc/passwd`, `C:\Windows`) ou um caminho
  do Windows relativo a uma unidade (`C:foo`). Um valor relativo a
  unidade e um identificador com namespace como `x:y` são
  indistinguíveis como strings, então qualquer valor do tipo uma letra
  seguida de dois-pontos é rejeitado por padrão; isente o parâmetro se
  ele recebe valores assim de forma legítima
* contém um byte nulo (`\x00`)

A verificação de `..` é feita por componente, não por busca de
substring. Valores como `v1.0..v2.0` ou `HEAD~3..HEAD` passam porque ali
`..` não é um segmento de caminho isolado.

Essas verificações se aplicam ao valor decodificado, então elas pegam
tentativas de path traversal independentemente de como foram codificadas
na URI (`../etc`, `..%2Fetc`, `%2E%2E/etc`, `..%5Cetc`, `%00` são todos
barrados).

!!! check
    Leia `manuals://../etc/passwd` do servidor acima e a requisição é
    rejeitada na hora: o casamento de templates para na primeira falha,
    então nenhum template posterior (potencialmente mais permissivo) é
    tentado como fallback. O cliente vê o mesmo erro `-32602` "Unknown
    resource" que veria para uma URI que não casa com nenhum template, e
    `read_manual` nunca executa.

### Handlers de sistema de arquivos: use safe_join {#filesystem-handlers-use-safe_join}

As verificações embutidas barram os casos comuns, mas não têm como
conhecer o limite do seu sandbox. Para acesso ao sistema de arquivos,
use `safe_join` para resolver o caminho e verificar que ele continua
dentro do seu diretório base:

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` pega escapes por link simbólico, sequências `..` e truques
com caminhos absolutos que uma verificação simples de string deixaria
passar. Se o caminho resolvido escapa de `DOCS_ROOT`, a função levanta
`PathEscapeError`, que chega ao cliente como um `ResourceError`.

### Quando o comportamento padrão atrapalha {#when-the-defaults-get-in-the-way}

Às vezes as verificações bloqueiam valores legítimos. Uma ferramenta de
importação de catálogo pode receber de propósito um caminho absoluto, ou
um parâmetro pode ser uma referência relativa como `../sibling` que o
seu handler interpreta com segurança sem tocar no sistema de arquivos.
Isente esse parâmetro ou afrouxe a política para o servidor inteiro:

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* `security=ResourceSecurity(exempt_params={"source"})` no decorador
  pula as verificações só para aquele parâmetro, só naquele recurso. O
  resto do servidor mantém a política padrão.
* `resource_security=` no construtor de `MCPServer` define o padrão
  para todos os recursos. Aqui, `relaxed` desliga por completo a
  verificação de `..`.

As verificações configuráveis:

| Configuração            | Padrão  | O que faz                           |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | Rejeita sequências `..` que escapam do diretório de partida |
| `reject_absolute_paths` | `True`  | Rejeita `/foo`, `C:\foo`, caminhos UNC e o `C:foo` relativo a unidade (também pega `x:y`) |
| `reject_null_bytes`     | `True`  | Rejeita valores que contêm `\x00`   |
| `exempt_params`         | vazio   | Nomes de parâmetros para os quais pular as verificações |

Essas verificações são um pré-filtro heurístico; para acesso ao sistema
de arquivos, `safe_join` continua sendo a fronteira de contenção.

!!! tip
    Se o seu handler não consegue atender à requisição (o arquivo não
    existe, o id é desconhecido), levante uma exceção. O SDK a transforma
    em uma resposta de erro. Veja **[Tratamento de erros](handling-errors.md)** para a
    diferença entre um erro de protocolo e um erro de ferramenta.

## Recursos no Server de baixo nível {#resources-on-the-low-level-server}

Se você está construindo sobre o `Server` de baixo nível (veja **[O Server
de baixo nível](../advanced/low-level-server.md)**), registra handlers diretamente para os
métodos de protocolo `resources/list` e `resources/read`. Não há
decorador; quem retorna os tipos do protocolo é você.

### Recursos estáticos {#static-resources}

Para URIs fixas, mantenha um registro e despache por casamento exato:

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

O handler de listagem diz aos clientes o que está disponível; o handler
de leitura serve o conteúdo. Consulte primeiro o seu registro, caia nos
templates (abaixo) se tiver algum, e levante uma exceção para qualquer
outra coisa.

### Templates {#templates}

O motor de templates que o `MCPServer` usa fica em
`mcp.shared.uri_template` e funciona sozinho. Você ganha o mesmo parse e
o mesmo casamento; o roteamento e a política de segurança, você monta por
conta própria.

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

Três coisas acontecem nas linhas destacadas:

* **Faça o parse uma vez, case a cada requisição.** `UriTemplate.parse()`
  monta o template; `template.match(uri)` retorna as variáveis extraídas
  como um `dict`, ou `None` se a URI não se encaixa. A decodificação de
  URL acontece dentro de `match()`; os valores decodificados são
  retornados como estão, sem validação de segurança de caminho. Os
  valores saem como strings: converta-os você mesmo
  (`int(matched["id"])`, `Path(matched["path"])`).
* **Aplique você mesmo as verificações de segurança.** As verificações de
  `..` e de caminho absoluto que o `MCPServer` executa por padrão ficam em
  `mcp.shared.path_security`. `read_manual_safely` as chama antes de
  tocar em `MANUALS`. Se um parâmetro não é um caminho do sistema de
  arquivos (um ISBN, uma consulta de busca), pule as verificações para
  esse valor: você controla a política por handler, e não por meio de um
  objeto de configuração.
* **Liste os templates a partir da mesma fonte.** Os clientes descobrem
  templates por meio de `resources/templates/list`. `str(template)`
  devolve a string original do template, então a listagem e o casamento
  compartilham uma única fonte da verdade.

## Recapitulando {#recap}

* `{name}` casa com um segmento; `{+name}` mantém as barras; `{?a,b}`
  puxa da query string; `{/name*}` divide os segmentos em uma lista.
* Duas variáveis sem nada entre elas, ou uma segunda variável de vários
  segmentos, são rejeitadas na hora do parse. Um parâmetro vinculado a
  uma variável de query em um `{?...}`/`{&...}` final deve declarar um
  valor padrão em Python.
* Anote o parâmetro (`order_id: int`) e o SDK converte.
* A política de segurança padrão rejeita `..`, caminhos absolutos e bytes
  nulos antes de o seu handler executar; sobrescreva por recurso com
  `security=ResourceSecurity(...)` ou no servidor inteiro com
  `resource_security=`.
* Para acesso ao sistema de arquivos, `safe_join` é a fronteira de
  contenção.
* No `Server` de baixo nível, faça o parse com `UriTemplate.parse()`,
  case com `.match()` e aplique `mcp.shared.path_security` você mesmo.
