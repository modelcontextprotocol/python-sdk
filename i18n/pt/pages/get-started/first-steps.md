---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# Primeiros passos {#first-steps}

A **[página inicial](../index.md)** anda rápido: escrever um servidor, executá-lo, chamar uma ferramenta.

Esta página vai com calma, passando pelas três coisas que um servidor pode expor e dando nome a tudo pelo caminho.

## Host, cliente e servidor {#host-client-and-server}

Três palavras que você vai ver em todas as páginas daqui em diante:

* Um **host** é a aplicação de LLM: o Claude, uma IDE, um runtime de agentes. É com ele que o usuário conversa.
* Um **cliente** vive dentro do host e fala MCP. O host executa um cliente para cada servidor ao qual está conectado.
* Um **servidor** é o que você constrói com este SDK. Ele expõe coisas aos clientes. Nunca fala diretamente com o modelo.

Você escreve o servidor. Os hosts são produto de terceiros. O SDK também traz um `Client`. Você vai usá-lo para testar seus servidores, e ele aparece mais adiante nesta página.

## As três primitivas {#the-three-primitives}

Um servidor expõe exatamente três tipos de coisa. O que as distingue é **quem decide usá-las**:

| Primitiva       | Quem controla   | O que é                                                         | Exemplo                                            |
|-----------------|-----------------|-----------------------------------------------------------------|----------------------------------------------------|
| **Ferramentas** | O modelo        | Uma função que o modelo chama para executar uma ação            | Uma chamada de API, uma escrita no banco de dados  |
| **Recursos**    | A aplicação     | Dados que o host carrega no contexto do modelo                  | O conteúdo de um arquivo, uma resposta de API      |
| **Prompts**     | O usuário       | Um template de mensagem reutilizável que o usuário invoca pelo nome | Um comando de barra, um item de menu           |

"Quem controla" é justamente o sentido da divisão. Uma ferramenta roda porque o **modelo** decidiu chamá-la. Um recurso é anexado porque a **aplicação** decidiu que o modelo precisava dele. Um prompt roda porque o **usuário** o escolheu.

!!! info
    Se você já construiu uma API web, já tem quase toda a intuição: um **recurso** é um `GET`
    (carrega dados e não altera nada) e uma **ferramenta** é um `POST` (realiza trabalho e pode ter
    efeitos colaterais). Um **prompt** não tem equivalente em HTTP; está mais para uma consulta salva
    que o usuário executa pelo nome.

## Um servidor, as três {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Três funções simples, três decoradores. Cada decorador já é o registro completo:

* `@mcp.tool()` transforma `add` em uma **ferramenta**.
* `@mcp.resource("greeting://{name}")` transforma `greeting` em um **template de recurso**: o `{name}` na URI é o parâmetro da função.
* `@mcp.prompt()` transforma `summarize` em um **prompt**. A string que ela retorna vira uma mensagem de usuário.

Todo o resto (o nome, a descrição, o schema dos argumentos) o SDK lê da própria função: o nome dela, a docstring, as anotações de tipo. Você nunca declarou nada disso separadamente.

!!! tip
    As duas metades do SDK têm dois caminhos de importação: `from mcp import Client` e
    `from mcp.server import MCPServer`. Não existe `from mcp import MCPServer`.

### Experimente {#try-it}

Execute com o MCP Inspector:

```console
uv run mcp dev server.py
```

Abra a URL que ele imprime. O Inspector tem uma aba por primitiva; passe por elas na ordem.

**Ferramentas.** Uma entrada: `add`, descrita como *Add two numbers.* O formulário tem um campo inteiro obrigatório para `a` e outro para `b`. Preencha, chame, e o resultado é `3`. O Inspector montou esse formulário a partir de `a: int, b: int`. Qualquer outro cliente faz o mesmo.

**Recursos.** A lista *Resources* está vazia. `greeting` fica em **Resource Templates**, porque `greeting://{name}` tem um parâmetro: não existe um recurso concreto para listar até alguém fornecer um `name`. Passe `World` e leia:

```text
Hello, World!
```

**Prompts.** Uma entrada: `summarize`, com um único argumento obrigatório, `text`. Obtenha-o com algum texto e você recebe uma mensagem com `role: user` e sua string renderizada como conteúdo. Um prompt é só isso: uma função que monta mensagens.

O Inspector executou seu servidor via **stdio**, um dos transportes que um servidor MCP sabe falar. Por enquanto você não escolhe um; **[Executando seu servidor](../run/index.md)** é a página para isso.

## Capacidades {#capabilities}

Você viu três abas no Inspector. Como ele sabia que eram três?

Quando um cliente se conecta, o servidor declara suas **capacidades**: quais famílias de requisições ele vai responder. O cliente usa essa declaração para decidir o que faz sentido pedir. Você nunca escreveu isso; o `MCPServer` declara por você.

Veja você mesmo. O `Client` do SDK aceita o objeto do servidor diretamente e se conecta a ele **em memória** (sem subprocesso, sem porta):

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

Esse dicionário é a declaração de **capacidades** do seu servidor. É a primeira coisa que todo cliente aprende ao se conectar:

| Capacidade  | O cliente agora pode chamar                                   |
|-------------|---------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                     |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                                  |

O `MCPServer` serve as três primitivas, então as três são sempre declaradas.

Repare no que não aparece ali. `completions` (autocompletar de argumentos para templates de recurso e prompts) precisa de um handler escrito por você; este servidor não tem nenhum, então a capacidade fica de fora e um cliente bem-comportado nem pede. Essa é a regra para tudo que é opcional: registre a coisa e a capacidade aparece; **[Completions](../servers/completions.md)** comprova isso.

!!! info
    `Client(mcp)` é o mesmo cliente em memória com que todos os exemplos desta documentação são
    testados, e é assim que você vai testar os seus. Ele ganha uma página inteira: **[Testes](testing.md)**.

## O que você não escreveu {#what-you-did-not-write}

Olhe de novo esta página. Você escreveu três funções Python pequenas. Você **não** escreveu:

* Um JSON Schema. `a: int, b: int` *é* o schema de `add`.
* Um handler de requisição. `tools/list`, `resources/read`, `prompts/get`: o SDK atende todos por você.
* Uma declaração de capacidades. O `MCPServer` fez isso por você.
* Uma linha de protocolo. A negociação de versão, o enquadramento JSON-RPC, a troca de capacidades: tudo isso aconteceu dentro de `mcp dev` e `Client(mcp)`, e você nunca viu.

Essa proporção é a razão de ser do SDK.

## Recapitulando {#recap}

* Um **host** é o app de LLM, um **cliente** é a metade dele que fala MCP, um **servidor** é o que você constrói.
* Ferramentas são controladas pelo **modelo**, recursos pela **aplicação**, prompts pelo **usuário**.
* Um decorador por primitiva: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Nome, descrição e schema vêm da função.
* Uma URI com um `{param}` cria um **template** de recurso, listado separadamente dos recursos concretos.
* As **capacidades** do servidor já vêm declaradas para você, e um cliente só pede o que o servidor declara.
* `Client(mcp)` se conecta ao objeto do servidor em memória: seu ambiente de testes desde o primeiro dia.

A seguir vem **[Conecte a um host real](real-host.md)**: este servidor dentro do Claude Desktop ou de uma IDE, de verdade. Depois, **[Testes](testing.md)**: uma página, um cliente em memória, e você nunca mais fica adivinhando se funciona. Depois disso, cada primitiva ganha sua própria página, começando pela que o modelo comanda: **[Ferramentas](../servers/tools.md)**.
