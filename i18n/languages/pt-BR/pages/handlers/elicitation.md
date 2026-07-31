# Elicitação {#elicitation}

Uma ferramenta que está na metade do trabalho e à qual falta uma resposta não precisa falhar.

**Elicitação** (elicitation) permite que ela pergunte. No meio de uma chamada de ferramenta, o usuário recebe uma pergunta, e a resposta dele volta para a mesma chamada de função.

Há dois modos:

* **Modo formulário**: você precisa de um valor (uma confirmação, uma data, uma quantidade). Você descreve os campos e o cliente renderiza o formulário.
* **Modo URL**: você precisa que o usuário vá a outro lugar (uma tela de consentimento OAuth, uma página de pagamento). Nada do que ele faz lá passa pelo protocolo.

E há duas formas de perguntar. A que você deve escolher é um **resolvedor**: você pendura a pergunta em um parâmetro e o SDK pergunta - em qualquer conexão, seja qual for a era do protocolo que o cliente fala. A forma direta, `await ctx.elicit(...)`, é uma requisição do *servidor* para o *cliente*, um canal que só existe para um cliente em uma conexão legada (versão da especificação 2025-11-25 ou anterior). As duas estão nesta página; comece pelo resolvedor.

## Pergunte com um resolvedor {#ask-with-a-resolver}

Uma pergunta que controla a ferramenta inteira - *tem certeza? qual das três contas correspondentes?* - pode sair do corpo da ferramenta e virar um **resolvedor**, e o framework pergunta por você.

Um parâmetro anotado com `Annotated[T, Resolve(fn)]` é preenchido executando `fn` antes do corpo da ferramenta. O resolvedor retorna o valor direto quando já o conhece, ou retorna `Elicit(...)` para que o framework pergunte:

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` lê pelo nome o próprio argumento `path` da ferramenta, lista a pasta e **só elicita quando é necessário** - uma pasta vazia resolve para `Confirm(ok=True)` sem nenhuma ida e volta até o cliente.
* `delete_folder` anota `ElicitationResult[Confirm]`, então o framework injeta o resultado inteiro e a ferramenta faz `match` em todos os casos: aceitar-e-confirmar, aceitar-mas-manter (`ok=False`), recusar, cancelar.
* O parâmetro `confirm` nunca aparece no schema de entrada da ferramenta - o cliente fornece `path`, o resolvedor fornece `confirm`.

Anote o modelo sem o invólucro (`Annotated[Confirm, Resolve(confirm_delete)]`) quando a ferramenta não precisar ramificar: ela recebe o modelo no accept e a chamada aborta com um erro no decline ou no cancel.

Um resolvedor funciona em **todas** as conexões. Para um cliente em uma conexão legada, o SDK envia a pergunta diretamente; em uma conexão **2026-07-28**, o SDK *retorna* a pergunta a partir da chamada, e a próxima tentativa do cliente carrega a resposta. Seu resolvedor nunca percebe a diferença; o que acontece por baixo dos panos é **[Requisições com múltiplas idas e voltas](multi-round-trip.md)**.

Perguntar é só uma das coisas que um resolvedor pode fazer. O mecanismo geral - dependências que computam sem perguntar, dependências de dependências, o que o modelo pode e não pode fornecer - está na página **[Dependências](dependencies.md)**.

## Pergunte de dentro da ferramenta {#ask-from-inside-the-tool}

Uma ferramenta também pode parar no meio do próprio corpo e perguntar.

!!! warning
    `ctx.elicit()` e `ctx.elicit_url()` são requisições do *servidor* para o *cliente* - um
    canal que só existe para um cliente em uma conexão legada (versão da especificação **2025-11-25**
    ou anterior). Em uma conexão **2026-07-28** não existem requisições iniciadas pelo servidor, então
    essas chamadas falham. Um resolvedor funciona nas duas. **[Versões do protocolo](../protocol-versions.md)**
    tem a história completa.

`await ctx.elicit()` recebe uma mensagem e um modelo Pydantic:

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* O parâmetro **`Context`** é o que dá acesso a `ctx.elicit`; qualquer ferramenta pode receber um. Esse objeto tem uma página só dele: **[O Context](context.md)**.
* `AlternativeDate` é o **schema** da resposta que você quer.
* A ferramenta é `async def`. Tem que ser: ela para no meio e espera por uma pessoa.
* Em qualquer outra data, a ferramenta retorna na hora. Ela só pergunta quando precisa.
* A data que o usuário aceita volta pela própria `book_table`. Uma resposta é entrada como qualquer outra: uma alternativa que também está lotada gera uma nova pergunta, em vez de ser confirmada às cegas.

### O que o cliente recebe {#what-the-client-receives}

O cliente recebe a sua mensagem e, ao lado dela, um JSON Schema gerado a partir do modelo:

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

Esse schema é o formulário. `Field(description=...)` é o rótulo; um valor padrão preenche o campo de antemão e o torna opcional. É a mesma maquinaria de Pydantic para JSON Schema que **[Ferramentas](../servers/tools.md)** descreve para os argumentos de uma ferramenta.

!!! warning
    Um schema de elicitação não é tão expressivo quanto o schema de entrada de uma ferramenta. Só campos
    planos e primitivos: `str`, `int`, `float`, `bool`, ou um `Literal` de strings (que vira um `enum`).
    Coloque um modelo dentro do modelo e `ctx.elicit` levanta um erro antes de qualquer coisa ser enviada ao cliente:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    Você está interrompendo uma pessoa no meio de uma tarefa. Se a resposta precisa de aninhamento, ela deveria ter sido um
    argumento da ferramenta.

### As três respostas {#the-three-answers}

`result.action` informa o que o usuário fez, e há exatamente três possibilidades:

* `"accept"`: ele enviou o formulário. `result.data` é uma instância de `AlternativeDate`, já validada.
* `"decline"`: ele disse não.
* `"cancel"`: ele dispensou a pergunta sem escolher.

`result.data` só existe no `"accept"`, e é por isso que o exemplo verifica `result.action` primeiro. Seu verificador de tipos garante a ordem: depois de `result.action == "accept"`, `result.data` é um `AlternativeDate`; antes disso, não existe `.data` nenhum.

Uma recusa não é um erro. A ferramenta decide o que recusar significa (aqui, nenhuma reserva) e responde ao modelo normalmente.

!!! tip
    A resposta é validada contra o seu modelo antes de o seu código vê-la. Um cliente que envia
    `"maybe"` para um `bool` não corrompe a sua reserva: a chamada falha com um
    erro de incompatibilidade de schema e o seu `if` nunca executa.

## Envie o usuário para uma URL {#send-the-user-to-a-url}

Algumas coisas não podem passar pelo modelo nem pelo cliente: credenciais, números de cartão, consentimento OAuth. Para essas você não pede dados; você pede que o usuário vá a algum lugar:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` recebe a mensagem, a **URL** a ser visitada e um `elicitation_id` que você escolhe: qualquer string que identifique essa elicitação dentro do seu servidor.
* O resultado tem uma ação e nada mais. `"accept"` significa que o usuário concordou em abrir a URL, **não** que ele terminou o que havia do outro lado.
* O pagamento acontece fora de banda, entre o navegador do usuário e o seu provedor de pagamento. Nenhum conteúdo volta pelo MCP.

Olhe para a segunda ferramenta. Quando o seu servidor descobre que o fluxo fora de banda terminou (um webhook, um polling; aqui isso está modelado como uma segunda ferramenta), `ctx.session.send_elicit_complete(...)` envia `notifications/elicitation/complete` com o mesmo `elicitation_id`. É assim que o cliente sabe que pode parar de mostrar *"aguardando pagamento..."*. Sem isso, o cliente só pode adivinhar.

## O lado do cliente {#the-client-side}

Servidores perguntam. Clientes respondem passando um **`elicitation_callback`** para `Client(...)`:

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* Um único callback cobre os dois modos. `params` é uma união de `ElicitRequestFormParams` e `ElicitRequestURLParams`; `isinstance` faz a ramificação.
* Para uma URL, você mostra `params.url` ao usuário e retorna a ação que ele escolheu. Nunca nenhum `content`.
* Para um formulário, uma aplicação de verdade renderiza `params.requested_schema` e retorna a entrada do usuário como `content`. Este aqui sempre diz sim com uma resposta pronta, que é exatamente o callback que você quer em um teste.
* Passar o callback também é a **declaração de capacidade**: é assim que o servidor descobre que esse cliente pode ser questionado. As outras coisas que um cliente pode responder para um servidor estão em **[Callbacks do cliente](../client/callbacks.md)**.

!!! info
    A elicitação é uma requisição do *servidor* para o *cliente*, e essas só existem em uma
    sessão com handshake clássico, e é por isso que este cliente passa `mode="legacy"`.
    Em uma conexão **2026-07-28**, uma ferramenta pergunta *retornando* a pergunta a partir da chamada;
    esse fluxo é **[Requisições com múltiplas idas e voltas](multi-round-trip.md)**.

### Experimente {#try-it}

Inicie o `server.py` de modo formulário com `ctx.elicit` (o do `book_table`) em Streamable HTTP (**[Executando seu servidor](../run/index.md)** tem o comando de uma linha), depois execute o `main()` do cliente e peça uma mesa ao `book_table` para o dia de Natal.

O callback imprime a pergunta que recebeu:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

Ele responde com `{"accept_alternative": True, "date": "2025-12-27"}`, e a ferramenta, que esteve esperando dentro de `await ctx.elicit(...)` esse tempo todo, conclui a reserva:

```text
Booked a table for 2 on 2025-12-27.
```

Agora troque pelo `server.py` de modo URL e aponte o mesmo `main()` para `pay_deposit`: o mesmo callback segue o outro ramo, imprime o link de pagamento, e a ferramenta volta com *"Complete the payment in your browser."* Uma ida e volta, no meio da chamada, nos dois sentidos.

!!! check
    Agora remova `elicitation_callback=` do `Client` e chame `book_table` para o dia de Natal
    de novo. A chamada inteira falha com um erro de protocolo:

    ```text
    Elicitation not supported
    ```

    Um cliente que não registrou nenhum callback nunca declarou a capacidade `elicitation`, então não há
    ninguém a quem perguntar. Sua ferramenta não recebeu um `"decline"`; ela recebeu uma exceção. Projete pensando nisso: toda
    elicitação precisa de uma resposta sensata para "e se eu não puder perguntar?".

## Resumo {#recap}

* Um parâmetro anotado com `Annotated[T, Resolve(fn)]` é preenchido por um resolvedor, que retorna `Elicit(...)` quando precisa perguntar. Funciona em todas as conexões.
* O schema é um modelo Pydantic plano: só campos primitivos, validados na volta.
* `result.action` é `"accept"`, `"decline"` ou `"cancel"`; `result.data` só existe no accept.
* `await ctx.elicit(message, schema=Model)` pergunta de dentro do corpo da ferramenta, e `await ctx.elicit_url(message, url, elicitation_id)` serve para tudo que não pode passar pelo modelo (`ctx.session.send_elicit_complete(elicitation_id)` avisa que a parte fora de banda terminou). Ambas são requisições do servidor para o cliente: precisam do cliente em uma conexão legada.
* O cliente responde com um único `elicitation_callback`, ramificando pelo tipo dos params; registrá-lo é o que declara a capacidade.
* Em uma conexão 2026-07-28, o servidor retorna a pergunta em vez de empurrá-la; o mesmo callback é alimentado por **[Requisições com múltiplas idas e voltas](multi-round-trip.md)**.

Tudo o que está por baixo desse retorno (o loop de retry, proteger o `requestState`, conduzir o processo você mesmo) está em **[Requisições com múltiplas idas e voltas](multi-round-trip.md)**.
