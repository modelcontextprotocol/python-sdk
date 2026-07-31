# Primeiros passos {#first-steps}

A **[página inicial](../index.md)** vai rápido: escreva um servidor, execute-o, chame uma ferramenta.

Esta página vai devagar, com as três coisas que um servidor pode expor e um nome para cada uma delas pelo caminho.

## Host, cliente e servidor {#host-client-and-server}

Três palavras que você vai ver em todas as páginas daqui em diante:

* Um **host** é a aplicação de LLM: Claude, uma IDE, um runtime de agente. É com ele que o usuário conversa.
* Um **cliente** vive dentro do host e fala MCP. O host roda um cliente para cada servidor ao qual está conectado.
* Um **servidor** é o que você constrói com este SDK. Ele expõe coisas para os clientes. Nunca fala diretamente com o modelo.

Você escreve o servidor. Os hosts são produto de outra pessoa. O SDK também te dá um `Client`. Você vai usá-lo para testar seus servidores, e ele aparece mais adiante nesta página.

## As três primitivas {#the-three-primitives}

Um servidor expõe exatamente três tipos de coisa. O que as separa é **quem decide usá-las**:

| Primitiva      | Controlada por  | O que é                                               | Exemplo                                |
|----------------|-----------------|-------------------------------------------------------|----------------------------------------|
| **Ferramentas** | O modelo        | Uma função que o modelo chama para executar uma ação  | Uma chamada de API, uma escrita no banco |
| **Recursos**   | A aplicação     | Dados que o host carrega no contexto do modelo        | O conteúdo de um arquivo, uma resposta de API |
| **Prompts**    | O usuário       | Um template de mensagem reutilizável que o usuário invoca pelo nome | Um comando de barra, um item de menu |

"Controlada por" é justamente o ponto da divisão. Uma ferramenta roda porque o **modelo** decidiu chamá-la. Um recurso é anexado porque a **aplicação** decidiu que o modelo precisava dele. Um prompt roda porque o **usuário** o escolheu.

!!! info
    Se você já construiu uma API web, já tem quase toda a intuição: um **recurso** é um `GET`
    (carrega dados e não muda nada) e uma **ferramenta** é um `POST` (faz trabalho e pode ter
    efeitos colaterais). Um **prompt** não tem análogo em HTTP; está mais perto de uma query salva
    que o usuário executa pelo nome.

## Um servidor, os três {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Três funções simples, três decoradores. Cada decorador é o registro inteiro:

* `@mcp.tool()` transforma `add` em uma **ferramenta**.
* `@mcp.resource("greeting://{name}")` transforma `greeting` em um **template de recurso**: o `{name}` na URI é o parâmetro da função.
* `@mcp.prompt()` transforma `summarize` em um **prompt**. A string que ele retorna vira uma mensagem do usuário.

Todo o resto (o nome, a descrição, o schema dos argumentos) o SDK lê da própria função: o nome dela, a docstring, as type hints. Você nunca declarou nada disso separadamente.

!!! tip
    As duas metades do SDK têm dois caminhos de import: `from mcp import Client` e
    `from mcp.server import MCPServer`. Não existe `from mcp import MCPServer`.

### Experimente {#try-it}

Execute com o MCP Inspector:

```console
uv run mcp dev server.py
```

Abra a URL que ele imprime. O Inspector tem uma aba por primitiva; percorra-as na ordem.

**Ferramentas.** Uma entrada: `add`, descrita como *Add two numbers.* O formulário tem um campo inteiro obrigatório para `a` e outro para `b`. Preencha, chame e o resultado é `3`. O Inspector montou esse formulário a partir de `a: int, b: int`. Todo outro cliente faz o mesmo.

**Recursos.** A lista *Resources* está vazia. `greeting` está em **Resource Templates**, porque `greeting://{name}` tem um parâmetro: não há um recurso único para listar até que alguém forneça um `name`. Dê `World` a ele e leia:

```text
Hello, World!
```

**Prompts.** Uma entrada: `summarize`, com um único argumento obrigatório `text`. Obtenha-o com algum texto e você recebe uma mensagem com `role: user` e a sua string renderizada como conteúdo. Um prompt é só isso: uma função que monta mensagens.

O Inspector executou seu servidor sobre **stdio**, um dos transportes que um servidor MCP pode falar. Você ainda não escolhe um; **[Executando seu servidor](../run/index.md)** é a página para isso.

## Capacidades {#capabilities}

Você viu três abas no Inspector. Como ele soube que eram três?

Quando um cliente se conecta, o servidor declara suas **capacidades**: quais famílias de requisições ele vai atender. O cliente usa essa declaração para decidir o que sequer pedir. Você nunca escreveu isso; o `MCPServer` declara por você.

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

Esse dicionário são as **capacidades** declaradas do seu servidor. É a primeira coisa que todo cliente que se conecta descobre:

| Capacidade  | O cliente agora pode chamar                                  |
|-------------|--------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                   |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                                |

O `MCPServer` serve as três primitivas, então as três são sempre declaradas.

Repare no que não está lá. `completions` (autocompletar de argumentos para templates de recursos e prompts) precisa de um handler que você escreve, este servidor não tem um, então a capacidade está ausente e um cliente bem-comportado não vai pedir. Essa é a regra para tudo que é opcional: registre a coisa e a capacidade aparece; **[Completions](../servers/completions.md)** prova isso.

!!! info
    `Client(mcp)` é o mesmo cliente em memória com o qual todo exemplo destes docs é testado, e
    é assim que você vai testar os seus. Ele tem uma página inteira: **[Testes](testing.md)**.

## O que você não escreveu {#what-you-did-not-write}

Revise esta página. Você escreveu três pequenas funções Python. Você **não** escreveu:

* Um JSON Schema. `a: int, b: int` *é* o schema de `add`.
* Um handler de requisições. `tools/list`, `resources/read`, `prompts/get`: todos servidos para você.
* Uma declaração de capacidades. O `MCPServer` fez isso por você.
* Uma linha de protocolo. A negociação de versão, o framing JSON-RPC, a troca de capacidades: tudo aconteceu dentro de `mcp dev` e `Client(mcp)`, e você nunca viu nada disso.

Essa proporção é exatamente o propósito do SDK.

## Resumo {#recap}

* Um **host** é o app de LLM, um **cliente** é a metade dele que fala MCP, um **servidor** é o que você constrói.
* Ferramentas são controladas pelo **modelo**, recursos pela **aplicação**, prompts pelo **usuário**.
* Um decorador por primitiva: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Nome, descrição e schema vêm da função.
* Uma URI com um `{param}` cria um **template** de recurso, listado separadamente dos recursos concretos.
* As **capacidades** do servidor são declaradas por você automaticamente, e um cliente só pede o que um servidor declara.
* `Client(mcp)` se conecta ao objeto do servidor em memória: seu ambiente de testes desde o primeiro dia.

O próximo passo é **[Conectar a um host real](real-host.md)**: este servidor dentro do Claude Desktop ou de uma IDE, de verdade. Depois **[Testes](testing.md)**: uma página, um cliente em memória, e você nunca mais fica adivinhando se funciona. Em seguida, cada primitiva ganha sua própria página, começando pela que o modelo dirige: **[Ferramentas](../servers/tools.md)**.
