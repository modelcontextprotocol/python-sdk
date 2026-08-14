---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# Dependências {#dependencies}

Os argumentos de uma ferramenta (tool) vêm do modelo. Alguns valores nunca deveriam vir dele: um preço consultado nos seus registros, uma confirmação que só uma pessoa pode dar, qualquer coisa que o modelo poderia errar se inventasse.

**Dependências** são parâmetros preenchidos por funções suas. Você anota o parâmetro, indica a função, e o SDK a chama antes de a ferramenta rodar.

## Declare uma {#declare-one}

Envolva o tipo do parâmetro em `Annotated[...]` e adicione `Resolve(fn)`:

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` é um **resolvedor**: uma função comum que o SDK executa antes de `reserve_book` e cujo valor de retorno vira o argumento `stock`.
* O parâmetro `title` dele é o próprio argumento `title` da ferramenta, associado **pelo nome**. O resolvedor vê exatamente o valor validado que o corpo da ferramenta vai ver.
* O corpo da ferramenta já parte de um `Stock` que existe. Nada de código de consulta na ferramenta, nada de preâmbulo do tipo "e se estiver faltando".

!!! info
    Se você já usou FastAPI, isto é o `Depends`. Mesma ideia, mesmo motivo: a função declara o que
    precisa, o framework fornece, e a ligação toda fica na anotação de tipo.

### Invisível para o modelo {#invisible-to-the-model}

Este é o schema de entrada que `tools/list` informa para `reserve_book`:

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

Uma única propriedade. Assim como o `Context` em **[O Context](context.md)**, um parâmetro resolvido é um contrato entre você e o SDK: `stock` não está no schema, o modelo nunca fica sabendo dele, e um cliente que mande um valor de `stock` mesmo assim é ignorado. O valor do resolvedor é o único que a sua ferramenta pode receber.

É essa última parte que importa. Um parâmetro que o modelo não pode fornecer é um parâmetro que o modelo não pode errar.

### Experimente {#try-it}

Execute o servidor com o MCP Inspector:

```console
uv run mcp dev server.py
```

O formulário de `reserve_book` tem um único campo `title`. Nem sinal de `stock` nele. Chame a ferramenta com `Dune`:

```text
Reserved 'Dune' (6 copies left).
```

O corpo da ferramenta não consultou nada: `check_stock` rodou primeiro, e o `Stock` que ele retornou chegou como argumento. Experimente `Neuromancer` e o mesmo resolvedor entrega um zero à ferramenta.

!!! tip
    Você poderia simplesmente chamar `check_stock(title)` no corpo da ferramenta. Declare como dependência quando o
    valor merecer mais que uma chamada a uma função auxiliar: toda ferramenta que precisa do estoque declara o mesmo parâmetro,
    e o SDK executa o resolvedor no máximo uma vez por chamada, não importa quantas o declarem. As próximas
    seções acrescentam o resto: resolvedores que dependem uns dos outros e resolvedores que perguntam ao usuário.

## Dependências de dependências {#dependencies-of-dependencies}

Um resolvedor pode declarar as próprias dependências, com a mesma anotação:

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` depende de `check_stock`. O SDK executa o grafo em ordem: primeiro o estoque, depois a estimativa, depois a ferramenta.
* Tanto `stock` quanto `delivery` precisam, no fim das contas, de `check_stock`, mas ele roda **uma vez por chamada**. Uma consulta ao estoque, dois consumidores.
* Não há nada para registrar. O grafo *são* as anotações.

!!! check
    Não aceite o "uma vez por chamada" de olhos fechados. Coloque um `print` em `check_stock` e chame `order_book` pelo
    Inspector: uma linha por chamada. Dois consumidores, uma consulta.

O SDK analisa o grafo quando a ferramenta é registrada, não quando é chamada. Um parâmetro que ele não consegue classificar - que não é um `Context`, nem um `Resolve(...)`, nem o nome de um argumento da ferramenta - e um ciclo de resolvedores levantam, os dois, `InvalidSignature` na inicialização. O servidor falha antes mesmo de qualquer cliente se conectar, com o parâmetro ou resolvedor culpado nomeado no erro.

Os parâmetros de um resolvedor se resolvem exatamente como os de uma ferramenta: outro `Resolve(...)`, os próprios argumentos da ferramenta pelo nome, ou o `Context` - `ctx.headers`, o objeto do lifespan, tudo isso.

!!! warning
    Nos transportes HTTP o `Context` inclui `ctx.headers`. Cabeçalhos são **entrada fornecida pelo cliente**,
    como qualquer argumento de ferramenta: servem para um locale ou uma feature flag, nunca para uma identidade. A identidade
    de quem chama vem da sua camada de autorização (**[Autorização](../run/authorization.md)**), não de um cabeçalho que qualquer um pode definir.

!!! tip
    *Uma vez por chamada* significa exatamente isso: o próximo `tools/call` executa `check_stock` de novo. Um recurso
    que deve viver mais que uma requisição - um pool de banco de dados, um cliente HTTP - tem seu lugar no **[Lifespan](lifespan.md)**, e
    um resolvedor chega até ele por `ctx.request_context.lifespan_context`.

## Pergunte quando for preciso {#ask-when-you-must}

Um resolvedor não precisa saber a resposta. Ele pode retornar `Elicit(message, Model)` e o SDK pergunta ao usuário - o mecanismo de **[Elicitação](elicitation.md)** (elicitation), executado para você:

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* Em estoque: `confirm_backorder` retorna um `Backorder` diretamente. **Sem pergunta, sem ida e volta.** O usuário só é interrompido quando a resposta dele faz diferença.
* Sem estoque: o SDK envia a elicitação, valida a resposta contra `Backorder` e a injeta. O seu resolvedor nunca encosta no protocolo.
* A ferramenta lê `backorder.confirm` como qualquer outro argumento. Responder **não** ainda é uma resposta: a elicitação é aceita com `confirm=False`, a ferramenta roda, e nenhum pedido é feito. Perguntar virou pré-condição, e não código de infraestrutura no corpo da ferramenta.

E se o usuário simplesmente não responder - recusar a pergunta ou cancelá-la?

!!! check
    Execute `order_book` para `Neuromancer` e recuse a pergunta. Com a anotação escrita como
    `Annotated[Backorder, Resolve(...)]` o corpo da ferramenta nunca roda; a chamada falha com um resultado
    de erro que o modelo consegue ler:

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

Esse é o padrão certo para uma pré-condição: sem resposta, sem pedido. Quando a recusa é um desfecho que a sua ferramenta quer tratar - pular a encomenda, mas ainda assim sugerir outro título - anote `ElicitationResult[Backorder]` no lugar, e a ferramenta recebe o desfecho completo de aceitar/recusar/cancelar para decidir o que fazer. **[Elicitação](elicitation.md)** mostra essa forma e todo o resto sobre perguntar: as regras de schema, as três respostas, o lado do cliente na conversa.

!!! info
    O framework escolhe o transporte da pergunta a partir da versão de protocolo negociada; o código
    acima é idêntico nas duas. Em **2026-07-28** e posteriores a pergunta viaja dentro de um
    `tools/call` com múltiplas idas e voltas - o servidor a retorna, o `elicitation_callback` do cliente
    a responde, e o `Client` refaz a chamada para você (**[Requisições com múltiplas idas e voltas](multi-round-trip.md)**). Em
    **2025-11-25** e anteriores ela é uma requisição síncrona de elicitação no meio da chamada. Cada pergunta é
    feita exatamente uma vez por chamada - uma garantia sobre a pergunta, não sobre o resolvedor. Na
    forma com múltiplas idas e voltas, qualquer resolvedor pode rodar de novo sempre que a chamada é retomada depois de uma pergunta,
    então o código antes de um `return Elicit(...)` roda em cada uma dessas rodadas; a resposta registrada então
    satisfaz a pergunta repetida sem consultar o usuário outra vez. Uma resposta registrada só
    é consultada quando o resolvedor pergunta; um resolvedor que responde *sem* perguntar, como
    `check_stock`, sempre fornece o próprio valor calculado. Como cada resposta é associada de volta à
    sua pergunta, um resolvedor que faz elicitação precisa derivar a pergunta de forma determinística a partir dos
    argumentos da ferramenta e das respostas anteriores. Um valor gerado por chamada (um id de `default_factory`, um
    timestamp) é derivado de novo a cada rodada e não pode aparecer em uma pergunta à qual a resposta deva
    ficar vinculada. Uma pergunta montada com dados voláteis assim faz toda resposta registrada parecer obsoleta,
    então o servidor a refaz a cada rodada até o limite de rodadas do cliente encerrar a chamada.

## Pergunte ao cliente, não ao usuário {#ask-the-client-not-the-user}

A elicitação é uma das três perguntas que um resolvedor pode fazer, e o fluxo com múltiplas idas e voltas não permite nenhuma outra. As outras duas vão para o **cliente**, e não para o usuário: retorne `Sample(...)` para executar uma chamada de LLM por meio do cliente (uma requisição `sampling/createMessage`), ou `ListRoots()` para buscar os roots (diretórios raiz) atuais do cliente. Nenhuma das duas tem desfecho de aceitar/recusar; o consumidor anota diretamente o tipo do resultado, `CreateMessageResult` (`CreateMessageResultWithTools` quando a requisição carrega `tools` ou `tool_choice`) ou `ListRootsResult`:

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* O framework roteia essas perguntas exatamente como `Elicit`: dentro do `tools/call` com múltiplas idas e voltas em **2026-07-28**, pela requisição independente servidor->cliente em **2025-11-25**. Uma capacidade não declarada recusa a chamada com um erro de protocolo `-32021` (`sampling`, `roots`, `elicitation` em modo formulário; `sampling.tools` quando a requisição carrega `tools` ou `tool_choice`).
* Tudo o que a caixa de informação acima diz sobre perguntas vale sem mudanças: uma requisição `Sample` é associada ao seu resultado registrado pela sua representação exata, então monte-a de forma determinística a partir dos argumentos da ferramenta e das respostas anteriores; assim o cliente paga pela chamada de LLM uma vez por chamada de ferramenta, não uma vez por rodada. O resultado registrado viaja no `request_state` pelo resto da chamada, então uma resposta de LLM muito grande deixa cada ida e volta restante mais pesada.
* As *funcionalidades* independentes de amostragem (sampling) e roots são descontinuadas em 2026-07-28 (SEP-2577). Servidores novos que precisam do modelo do cliente perguntam por este canal; servidores que não precisam devem se integrar diretamente a um provedor de LLM. Valores de `include_context` diferentes de `"none"` também estão descontinuados; evite-os.

## Recapitulando {#recap}

* `Annotated[T, Resolve(fn)]` em um parâmetro de ferramenta: o SDK executa `fn` e injeta o valor de retorno.
* Um parâmetro resolvido é invisível para o modelo e não pode ser fornecido por um cliente. Valores que o modelo não pode inventar - preços, identidades, permissões - entram aqui.
* Os parâmetros de um resolvedor são resolvidos do mesmo jeito: o `Context`, outro `Resolve(...)`, ou um argumento da ferramenta pelo nome. O grafo executa cada resolvedor no máximo uma vez por rodada, não importa quantos consumidores ele tenha; cada pergunta é feita exatamente uma vez, e qualquer resolvedor pode rodar de novo quando uma chamada é retomada depois de uma pergunta.
* Grafos ruins falham no registro com `InvalidSignature`, não no meio da chamada.
* Retorne `Elicit(message, Model)` para perguntar ao usuário, só quando for preciso. Anotações com o tipo puro abortam na recusa; `ElicitationResult[T]` deixa a ferramenta tratar cada desfecho.
* Retorne `Sample(...)` ou `ListRoots()` para pedir ao cliente uma resposta de LLM ou a lista de roots; o resultado é injetado diretamente.

O estado que o seu servidor monta uma vez na inicialização, e como um handler chega até ele, é assunto da página **[Lifespan](lifespan.md)**.
