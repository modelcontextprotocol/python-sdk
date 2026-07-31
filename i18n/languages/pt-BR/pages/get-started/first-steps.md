# Primeiros passos {#first-steps}

A **[página inicial](../index.md)** vai direto ao ponto: escreva um servidor, execute-o, chame uma ferramenta.

Esta página vai com calma, passando pelas três coisas que um servidor pode expor e dando nome a tudo pelo caminho.

## Host, cliente e servidor {#host-client-and-server}

Três palavras que você vai ver em todas as páginas daqui em diante:

* Um **host** é a aplicação de LLM: o Claude, uma IDE, um runtime de agente. É com ele que o usuário conversa.
* Um **cliente** vive dentro do host e fala MCP. O host roda um cliente para cada servidor ao qual está conectado.
* Um **servidor** é o que você constrói com este SDK. Ele expõe coisas para os clientes. Nunca fala diretamente com o modelo.

Você escreve o servidor. Os hosts são produto de outra pessoa. O SDK também te dá um `Client`. Você vai usá-lo para testar seus servidores, e ele aparece mais adiante nesta página.

## Os três primitivos {#the-three-primitives}

Um servidor expõe exatamente três tipos de coisa. O que separa um do outro é **quem decide usá-los**:

| Primitivo     | Controlado por  | O que é                                              | Exemplo                               |
|---------------|-----------------|------------------------------------------------------|---------------------------------------|
| **Ferramentas** | O modelo      | Uma função que o modelo chama para executar uma ação | Uma chamada de API, uma escrita em banco |
| **Recursos**  | A aplicação     | Dados que o host carrega no contexto do modelo       | O conteúdo de um arquivo, uma resposta de API |
| **Prompts**   | O usuário       | Um template de mensagem reutilizável que o usuário invoca pelo nome | Um comando de barra, um item de menu |

"Controlado por" é a razão de ser dessa divisão. Uma ferramenta roda porque o **modelo** decidiu chamá-la. Um recurso é anexado porque a **aplicação** decidiu que o modelo precisava dele. Um prompt roda porque o **usuário** escolheu usá-lo.

!!! info
    Se você já construiu uma API web, boa parte da intuição já está aí: um **recurso** é um `GET`
    (carrega dados e não muda nada) e uma **ferramenta** é um `POST` (faz trabalho e pode ter
    efeitos colaterais). Um **prompt** não tem análogo em HTTP; está mais para uma query salva que o
    usuário executa pelo nome.

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
    As duas metades do SDK têm dois caminhos de importação: `from mcp import Client` e
    `from mcp.server import MCPServer`. Não existe `from mcp import MCPServer`.

### Experimente {#try-it}

Execute com o MCP Inspector:

```console
uv run mcp dev server.py
```

Abra a URL que ele imprime. O Inspector tem uma aba por primitivo; percorra elas na ordem.

**Tools.** Uma entrada: `add`, descrita como *Add two numbers.* O formulário tem um campo inteiro obrigatório para `a` e outro para `b`. Preencha, chame, e o resultado é `3`. O Inspector montou esse formulário a partir de `a: int, b: int`. Qualquer outro cliente faz o mesmo.

**Resources.** A lista *Resources* está vazia. `greeting` está em **Resource Templates**, porque `greeting://{name}` tem um parâmetro: não existe um recurso único para listar até alguém fornecer um `name`. Informe `World` e leia:

```text
Hello, World!
```

**Prompts.** Uma entrada: `summarize`, com um único argumento obrigatório `text`. Busque-o com algum texto e você recebe uma mensagem com `role: user` e sua string renderizada como conteúdo. Um prompt é só isso: uma função que monta mensagens.

O Inspector executou seu servidor sobre **stdio**, um dos transportes que um servidor MCP pode falar. Você ainda não precisa escolher um; **[Executando seu servidor](../run/index.md)** é a página para isso.

## Capacidades {#capabilities}

Você viu três abas no Inspector. Como ele soube que eram três?

Quando um cliente se conecta, o servidor declara suas **capacidades**: quais famílias de requisições ele vai atender. O cliente usa essa declaração para decidir o que sequer vale a pena pedir. Você nunca escreveu isso; o `MCPServer` declara por você.

Veja com seus próprios olhos. O `Client` do SDK aceita o objeto do servidor diretamente e se conecta a ele **em memória** (sem subprocesso, sem porta):

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

Esse dicionário são as **capacidades** declaradas do seu servidor. É a primeira coisa que todo cliente aprende ao se conectar:

| Capacidade  | O cliente agora pode chamar                                  |
|-------------|--------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                   |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                                |

O `MCPServer` serve os três primitivos, então os três são sempre declarados.

Repare no que não está ali. `completions` (autocompletar de argumentos para templates de recurso e prompts) precisa de um handler escrito por você; este servidor não tem nenhum, então a capacidade está ausente e um cliente bem-comportado não vai pedir. Essa é a regra para tudo que é opcional: registre a coisa e a capacidade aparece; **[Completions](../servers/completions.md)** comprova isso.

!!! info
    `Client(mcp)` é o mesmo cliente em memória com que todos os exemplos destes docs são testados, e
    é assim que você vai testar os seus. Ele tem uma página inteira: **[Testes](testing.md)**.

## O que você não escreveu {#what-you-did-not-write}

Releia esta página. Você escreveu três funções Python pequenas. Você **não** escreveu:

* Um JSON Schema. `a: int, b: int` *é* o schema de `add`.
* Um handler de requisição. `tools/list`, `resources/read`, `prompts/get`: todos servidos para você.
* Uma declaração de capacidades. O `MCPServer` fez isso por você.
* Uma linha de protocolo. A negociação de versão, o enquadramento JSON-RPC, a troca de capacidades: tudo aconteceu dentro do `mcp dev` e do `Client(mcp)`, e você nunca viu.

Essa proporção é a razão de ser do SDK.

## Recapitulando {#recap}

* Um **host** é o app de LLM, um **cliente** é a metade dele que fala MCP, um **servidor** é o que você constrói.
* Ferramentas são controladas pelo **modelo**, recursos pela **aplicação**, prompts pelo **usuário**.
* Um decorador por primitivo: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Nome, descrição e schema vêm da função.
* Uma URI com um `{param}` cria um **template** de recurso, listado separadamente dos recursos concretos.
* As **capacidades** do servidor são declaradas por você automaticamente, e um cliente só pede aquilo que o servidor declara.
* `Client(mcp)` se conecta ao objeto do servidor em memória: sua bancada de testes desde o primeiro dia.

O próximo passo é **[Conectar a um host real](real-host.md)**: esse servidor dentro do Claude Desktop ou de uma IDE, para valer. Depois, **[Testes](testing.md)**: uma página, um cliente em memória, e você nunca mais fica no chute sobre se aquilo funciona. Em seguida, cada primitivo ganha sua própria página, começando por aquele que o modelo comanda: **[Ferramentas](../servers/tools.md)**.
