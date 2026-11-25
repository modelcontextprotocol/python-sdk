---
translation:
  sections: [7be05607887e6853, e7375894888d9750, c36f73fc7e3af13b, 2fec2d7e129e62fe, 809b0e0a7c27295a, b4395a04d2a5d906, 1a436007f5f54779, c6b2078ed1e63ba5]
  tool: 1
---
# Tratando erros {#handling-errors}

Uma ferramenta (tool) pode falhar de três maneiras, e o SDK trata cada uma de forma diferente.

Lance `ToolError` e é o **modelo** que vê a sua mensagem. Lance `MCPError` e é o **protocolo** que a vê. Lance qualquer outra coisa e é um crash: o modelo só fica sabendo que a chamada falhou, e o seu log recebe o traceback.

Esta página é sobre essa escolha.

## Um erro que o modelo consegue corrigir {#an-error-the-model-can-fix}

Pegue uma ferramenta que faz uma consulta e deixe a consulta não encontrar nada:

```python title="server.py" hl_lines="2 12-13"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`ToolError`, de `mcp.server.mcpserver.exceptions`, é como uma ferramenta avisa ao modelo que algo deu errado.

Chame a ferramenta com um título que não está no catálogo e veja o resultado:

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* A requisição **foi bem-sucedida**. Há um resultado; nada foi lançado no lado de quem chamou.
* `is_error` é `True`, e a sua mensagem (prefixada com o nome da ferramenta) está em `content`, exatamente onde o modelo lê.
* `structured_content` é `None`. Uma chamada que falhou não tem valor de retorno para estruturar.

Isso é um **erro de ferramenta**, e é quase sempre o que você quer.

Quem chama a sua ferramenta é o modelo. Foi ele que escolheu os argumentos. Então um erro de ferramenta é um turno na conversa: o modelo lê *"No book titled 'Nothing' in the catalog."*, percebe que chutou o título errado e chama de novo com um melhor. Você escreveu um `raise` e ganhou um agente que se corrige sozinho.

No servidor, um `ToolError` é uma linha `INFO` no log, sem traceback. Você já esperava por ele, então não há nada para investigar.

!!! tip
    Nunca faça `return` de uma mensagem de erro em uma ferramenta. Uma string retornada tem `is_error=False`, então, para o
    modelo (e para toda interface de cliente), parece que a ferramenta funcionou e que aquela string era a resposta.
    Use `raise`. A flag é o sinal.

## Um erro que o modelo não consegue corrigir {#an-error-the-model-cannot-fix}

Agora troque `ToolError` por `MCPError`.

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` é o **erro de protocolo** do SDK. É a única exceção que o wrapper da ferramenta *não* captura: ela se propaga, e a requisição `tools/call` inteira falha com um erro JSON-RPC em vez de um resultado.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **Não há resultado**. Sem `content`, sem `is_error`: nada para o modelo ler.
* Quem recebe o erro é a aplicação **host**, do mesmo jeito que receberia se a ferramenta nem existisse.
* `code`, `message` e `data` chegam intactos. `INVALID_PARAMS` é `-32602`; `mcp.types` exporta esse e os outros códigos de erro JSON-RPC (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...) como constantes, para que você nunca precise digitar um número mágico.

!!! check
    Mesma consulta, mesma falha, mas agora a chamada *lança* a exceção no lado do cliente em vez de retornar:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    A primeira versão entregou ao modelo uma frase à qual ele podia reagir. Esta não entrega nada.
    Para `get_author` isso é estritamente pior, e é esse o ponto da próxima seção.

## Qual delas lançar {#which-one-to-raise}

Os dois caminhos respondem a duas perguntas diferentes.

* **Lance `ToolError`** para uma falha de *execução*: aquilo que a sua ferramenta tentou fazer não funcionou. Foi o modelo que escolheu a chamada, então é o modelo que deve ver a consequência e ter a chance de se recuperar. Um título escrito errado, uma API upstream que deu timeout, uma linha que não existe: tudo erro de ferramenta.
* **Lance `MCPError`** quando a *própria requisição* deve ser rejeitada: o cliente não tem uma capacidade da qual a sua ferramenta depende, o servidor não está em condições de atender ninguém, quem chamou pulou uma etapa obrigatória. Nenhuma nova tentativa do modelo corrige nada disso, então não há nada a ganhar entregando a mensagem a ele.

Uma pergunta decide: **um modelo mais esperto teria evitado isso?** Sim -> `ToolError`. Não -> `MCPError`.

Por esse critério, a segunda versão de `get_author` fez a escolha errada: um título melhor resolve, então o modelo merecia ver a mensagem. Ela está ali para mostrar o mecanismo, não para recomendá-lo.

!!! info
    `MCPError` fica em `from mcp import MCPError` e recebe `code`, `message` e um payload
    `data` opcional. O que você colocar neles é o que o cliente recebe: o SDK repassa um
    `MCPError` lançado tal e qual, em vez de sanitizá-lo.

## Qualquer outra exceção {#any-other-exception}

Agora tire a verificação e deixe a consulta ao dicionário falhar sozinha:

```python title="server.py" hl_lines="11"
--8<-- "docs_src/handling_errors/tutorial004.py"
```

`CATALOG[title]` lança `KeyError`. Você não planejou isso, então o SDK trata como um crash:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool get_author")]
```

A chamada ainda retorna `is_error=True`, então o modelo sabe que falhou e pode seguir em frente. O que ele não recebe é o texto da exceção: um `KeyError` do seu código, ou uma pilha de SQL vinda de um driver três bibliotecas abaixo, pode descrever o funcionamento interno do seu servidor, então nunca sai do servidor.

Quem recebe é você. O servidor registra o crash em `ERROR` com o traceback completo, como `Tool 'get_author' raised an unexpected exception`. Um log de produção em `WARNING`, portanto, fica quieto a cada `ToolError` e se manifesta no instante em que algo está de fato quebrado.

## Um recurso que não existe {#a-resource-that-doesnt-exist}

Recursos fazem a mesma distinção, e vêm com uma exceção nomeada para o caso mais comum.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` é um **template**. Ele casa com *qualquer* título, então "a URI está bem formada" e "o livro existe" são duas perguntas diferentes, e só a sua função consegue responder à segunda.

Quando não consegue, lance `ResourceNotFoundError`. O SDK a transforma no erro de protocolo que a especificação atribui a um recurso ausente: `-32602` com a URI requisitada em `data`, para que o cliente saiba *qual* leitura falhou.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

Repare que aqui não existe um meio-resultado com `is_error=True`. A leitura de um recurso ou retorna conteúdo ou falha: recursos só têm o caminho do protocolo. `ResourceError` é a mesma coisa para uma falha que não é "não encontrado" (`-32603`, com a sua mensagem), e as duas são uma linha `INFO` no seu log. Qualquer outra exceção, exceto `MCPError`, é um crash: o cliente recebe `-32603` citando apenas a URI, e o traceback vai para o seu log em `ERROR`. Templates e todo o resto sobre recursos ficam em **[Recursos](resources.md)**.

## Erros que você nunca lança {#errors-you-never-raise}

Um argumento inválido nunca chega à sua função.

Mande para `get_author` um `title` que não seja uma string e o SDK o rejeita com base no schema de entrada **antes** de chamar você, como o mesmo tipo de erro de ferramenta com `is_error=True` que o modelo consegue ler e corrigir. **[Ferramentas](tools.md)** mostra a mesma rejeição com uma restrição `Field(le=50)`.

Isso significa uma classe inteira de instruções `raise` que você não escreve: não revalide as suas próprias anotações de tipo.

!!! info
    Tudo o que um **cliente** vê nesta página, o `Client` em memória com o qual você vai escrever
    seus testes também vê. Nem `raise_exceptions=True` devolve a exceção de uma ferramenta que falhou
    a quem chamou: no momento em que essa flag poderia agir, a sua exceção já virou o
    resultado com `is_error=True`. Faça o assert no resultado. Se você precisar do traceback de um crash, ele está no
    log do servidor, e o `caplog` do pytest o captura. **[Testes](../get-started/testing.md)** cobre o padrão.

## Recapitulando {#recap}

* Lance **`ToolError`** em uma ferramenta -> a chamada retorna `is_error=True` com a sua mensagem em `content`. O modelo lê e pode tentar de novo.
* Lance **`MCPError`** -> a própria chamada falha com um erro JSON-RPC. O modelo não vê nada; quem lida com isso é o host. `code`, `message` e `data` sobrevivem intactos.
* A pergunta que decide: *um modelo mais esperto teria evitado isso?* Sim -> `ToolError`. Não -> `MCPError`.
* Qualquer **outra exceção** é um crash -> `is_error=True` só com `Error executing tool <name>` para o modelo, e um registro `ERROR` com o traceback para você.
* `ResourceNotFoundError` em um handler de recurso -> o `-32602` do protocolo, com a URI em `data`.
* Argumentos inválidos são rejeitados com base no schema antes de a sua função executar; você não dá `raise` para eles.
* Imports: `from mcp import MCPError`, `from mcp.server.mcpserver.exceptions import ToolError, ResourceError, ResourceNotFoundError`, e as constantes de código de erro de `mcp.types`.

Erros tratados. Isso é tudo o que um servidor *expõe*. O que cada handler pode ler, e fazer de volta ao cliente enquanto executa, é a próxima seção: **[Dentro do seu handler](../handlers/index.md)**.

O texto exato dos erros do SDK que você tem mais chance de encontrar, o que cada um significa e a correção de um passo só para cada um estão em **[Solução de problemas](../troubleshooting.md)**.
