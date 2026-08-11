---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# Logging {#logging}

Faça log de uma ferramenta (tool) do mesmo jeito que faz de qualquer outra função Python: com a biblioteca padrão.

O MCP tem uma **capacidade de logging** no nível do protocolo: um servidor poderia enviar suas mensagens de log para o cliente como notificações, por meio de métodos do objeto `Context`. A revisão 2026-07-28 da especificação **torna essa capacidade obsoleta e não a substitui**, por isso esta documentação não a ensina. A lista completa do que foi marcado como obsoleto e do que fazer no lugar está em **[Funcionalidades obsoletas](../deprecated.md)**.

O que você faz no lugar é o que faz em qualquer outro programa Python: a biblioteca padrão.

## Uma ferramenta que faz log {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` dá a você um logger com o nome do seu módulo. Crie-o uma vez, no topo.
* Dentro da ferramenta você chama `logger.info(...)` como em qualquer outra função. Nada para injetar, nada para fazer `await`, nada específico do MCP.

!!! check
    Chame a ferramenta e olhe o resultado inteiro:

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    A linha de log não aparece em lugar nenhum. O logging é para **você**, a pessoa que opera o servidor. O modelo
    nunca o vê. Se o modelo precisa ler alguma coisa, faça `return` dela.

## Para onde vai {#where-it-goes}

Para um servidor **stdio**, essa pergunta importa mais do que o normal. O host iniciou seu servidor como um subprocesso e está lendo mensagens MCP do **stdout** dele. O erro padrão (stderr) é seu.

A biblioteca padrão já faz a coisa certa: a saída de log vai para `sys.stderr` por padrão. Suas linhas de `logger.info(...)` caem no terminal (ou onde quer que o host colete o stderr do subprocesso), e o fluxo do protocolo fica limpo.

!!! tip
    Não use `print()` em um servidor stdio. `print` escreve no **stdout**, e o stdout pertence ao protocolo.
    Enquanto serve, o SDK desvia para o stderr o stdout que de fato recebe *flush*, então ele não consegue corromper a
    comunicação, mas um `print()` em um processo com buffer em bloco costuma ficar sem flush no buffer de `sys.stdout`
    até o interpretador esvaziá-lo na saída, direto no fluxo do protocolo. Mesmo quando é desviada,
    a linha cai crua no meio da saída de log, sem nível, sem nome de logger e sem jeito de filtrá-la.

    `logger.debug("got here")` dá o mesmo trabalho de uma linha e vai para o lugar certo.

## O nível {#the-level}

Você não precisa chamar `logging.basicConfig()` por conta própria. Construir um `MCPServer` já fez isso, com um handler apontado para o erro padrão, no nível que você passa em `log_level=`, então `MCPServer("Bookshop", log_level="DEBUG")` é tudo o que precisa para ver suas linhas de `logger.debug(...)`.

O padrão é `"INFO"`.

`logging.basicConfig()` nunca substitui handlers que já existem. Se você configurar o logging por conta própria antes de criar o servidor, sua configuração vence.

## Experimente {#try-it}

Execute o servidor com o MCP Inspector:

```console
uv run mcp dev server.py
```

Chame `search_books` na aba **Tools**. O Inspector mostra o resultado: apenas o valor de retorno. A linha

```text
Searching for 'dune'
```

foi para o erro padrão: o terminal, não a comunicação com o cliente.

!!! info
    Se o que você quer de verdade é *tracing* (cada requisição, quanto tempo levou, se falhou), você
    não quer linhas de log, quer spans. Seu servidor já os emite: o SDK faz tracing de cada
    mensagem com OpenTelemetry por padrão. Veja **[OpenTelemetry](../run/opentelemetry.md)**.

## Recapitulando {#recap}

* A capacidade de logging do protocolo MCP foi tornada obsoleta pela especificação 2026-07-28 e não foi substituída. Não construa em cima dela.
* `logger = logging.getLogger(__name__)` no nível do módulo, `logger.info(...)` na ferramenta. O padrão inteiro é esse.
* A saída de log nunca chega ao modelo. Só o valor que você faz `return` chega.
* O erro padrão é seu; o stdout pertence ao protocolo. O SDK desvia para o stderr o stdout perdido que recebe flush enquanto serve, mas um `print()` sem flush ainda pode vazar para a comunicação na saída, e as linhas desviadas chegam sem rótulo; use `logging`, cujo handler faz flush de cada registro.
* `MCPServer(..., log_level="DEBUG")` define o nível, e uma configuração de logging que você tenha feito antes fica intacta.

Avisar os clientes conectados de que algo no seu servidor mudou (a lista de ferramentas, um recurso) é assunto de **[Assinaturas](subscriptions.md)**.
