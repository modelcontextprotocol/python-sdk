---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# O Server de baixo nível {#the-low-level-server}

`@mcp.tool()` é uma camada. Por baixo dela existe uma segunda classe de servidor, `Server`, que fala MCP cru: você entrega os objetos do protocolo e ela os coloca no fio, sem alterar nada.

O `MCPServer` é construído em cima dela. Você desce um nível quando a camada de conveniência atrapalha:

* Você precisa emitir um schema **exato** (carregado de um arquivo, gerado a partir de um banco de dados), não um derivado de uma assinatura Python.
* Você precisa de controle total do resultado: `_meta`, `is_error`, cada chave de `structured_content`.
* Você precisa tratar um método que o MCP não define.

Para todo o resto, fique no `MCPServer`.

## A mesma ferramenta, à mão {#the-same-tool-by-hand}

Esta é a ferramenta (tool) `search_books` que **[Ferramentas](../servers/tools.md)** escreve em nove linhas de `@mcp.tool()`, com o açúcar removido:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Três coisas mudaram, e elas são a API de baixo nível inteira:

* **Os handlers são parâmetros do construtor.** `on_list_tools=` e `on_call_tool=` entram em `Server(...)`. Não há decoradores aqui embaixo, e todo handler tem o mesmo formato: `async (ctx, params) -> result`.
* **Você escreve o schema de entrada.** `Tool.input_schema` é um `dict` JSON Schema comum. Ninguém o deriva de anotações de tipo, porque não há anotações de tipo de onde derivar.
* **Você monta o resultado.** `CallToolResult(content=[TextContent(...)])`, à mão. Nada é encapsulado, convertido ou inferido de uma anotação de retorno.

`params` é a requisição já parseada: `CallToolRequestParams` dá `.name` e `.arguments`. `ctx` é um `ServerRequestContext`: `ctx.session` para falar de volta com o cliente, `ctx.lifespan_context`, `ctx.request_id` e `ctx.meta`, o `_meta` de entrada da requisição.

!!! info
    Se você já usou FastAPI, já conhece essa relação. O `MCPServer` é a camada de decoradores e anotações de tipo; o `Server` é o Starlette por baixo. Eles não são rivais: o `MCPServer` constrói um `Server` e registra nele handlers exatamente como esses.

### Experimente {#try-it}

Não existe Inspector para este aqui: `mcp dev` e `mcp run` só aceitam um `MCPServer`. O `Client` em memória não se importa; ele recebe um `Server` de baixo nível exatamente como recebe um `MCPServer`:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

O mesmo texto que a versão com `@mcp.tool()` produziu. Duas diferenças honestas:

* `result.structured_content` é `None`. O servidor de alto nível encapsula um `-> str` em `{"result": ...}` para você; aqui ninguém monta o que você não montou.
* `list_tools` retorna o schema que **você** digitou, caractere por caractere. A versão de alto nível tinha `"title": "Query"` em cada propriedade e um `"title": "search_booksArguments"` na raiz: artefatos do Pydantic. Aqui embaixo, se está no fio, foi você quem colocou lá.

## Nada é verificado por você {#nothing-is-checked-for-you}

O `MCPServer` rejeita um argumento ruim antes mesmo de a sua função executar, validando a chamada contra o schema que ele gerou (**[Ferramentas](../servers/tools.md)**).

O `Server` não faz isso. O seu `input_schema` é *anunciado* ao cliente; ele nunca é *aplicado* a `params.arguments`.

!!! check
    Chame `search_books` sem `limit` e o seu `args["limit"]` levanta `KeyError`. O cliente vê:

    ```text
    MCPError: Internal server error
    ```

    Um erro JSON-RPC, código `-32603`, com uma mensagem deliberadamente genérica: o SDK não vaza o seu traceback para um chamador remoto. O modelo nunca descobre o que fez de errado, então não consegue tentar de novo. (Em um teste, `raise_exceptions=True` expõe a exceção real; veja **[Testes](../get-started/testing.md)**.)

Isso se generaliza. Uma exceção levantada de um handler de baixo nível é **sempre** um erro de protocolo, nunca um resultado de ferramenta com `is_error=True`. Se você quer que o modelo leia a falha e se recupere, valide `params.arguments` você mesmo e retorne `CallToolResult(content=[TextContent(...)], is_error=True)`. Os dois tipos de falha são o assunto de **[Tratando erros](../servers/handling-errors.md)**.

## Duas ferramentas, um handler {#two-tools-one-handler}

`on_call_tool` é o único ponto de entrada para todas as ferramentas do servidor. Você roteia por `params.name`:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` anuncia as duas. `call_tool` despacha pelo nome.
* O ramo `else` importa: o `Server` encaminha sem reclamar um `tools/call` para um nome que você nunca listou direto para o seu handler. Levantar uma exceção ali transforma a chamada no mesmo `-32603` de cima.

## Saída estruturada, à mão {#structured-output-by-hand}

Declare `output_schema` na `Tool` e coloque `structured_content` no resultado. Os dois são seus:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Chame e o resultado carrega as duas representações:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

O bloco `_meta` é o carimbo de identidade do servidor: o SDK o adiciona a todo resultado da era 2026, com a `version` vinda do construtor (um servidor que não define nenhuma reporta uma string vazia). Um servidor que não deve se identificar pode remover a chave com um middleware, que é dono dos resultados que retorna.

O servidor nunca compara os dois campos. O `Client` deste SDK compara: retorne um `structured_content` que não satisfaz o `output_schema` que você declarou e `call_tool` levanta um `RuntimeError` que começa com `Invalid structured content returned by tool search_books` e segue citando a falha do `jsonschema`. Prometer um schema é barato; cumprir a promessa é com você. A escada inteira de tipos de retorno e schemas está em **[Saída estruturada](../servers/structured-output.md)**.

## `_meta`: para a aplicação, não para o modelo {#\_meta-for-the-application-not-the-model}

`content` é a parte da resposta que o modelo lê. `structured_content` é a mesma resposta como dados tipados. `_meta` é o terceiro canal: dados que viajam junto com o resultado para a **aplicação cliente**, sem fazer parte da resposta de forma alguma.

Use para IDs de registro, IDs de trace, qualquer coisa de que a sua UI precisa e o seu prompt não:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* Você o constrói como `_meta=`, o nome no fio. O cliente o lê de volta como `result.meta`.
* Use namespace nas suas chaves (`bookshop/record_ids`). As chaves `io.modelcontextprotocol/*` são reservadas pelo protocolo.

!!! warning
    `_meta` é uma convenção entre você e a aplicação cliente, não uma garantia sobre o que chega
    ao modelo. O host decide o que renderiza. Nunca coloque um segredo em nenhuma parte de um resultado de ferramenta.

## As capacidades seguem os seus handlers {#capabilities-follow-your-handlers}

Um `Server` anuncia exatamente as famílias de métodos para as quais você deu handlers. O `Bookshop` acima passa `on_list_tools` e `on_call_tool` e nada mais, então um cliente que se conecta a ele vê:

```json
{"tools": {"listChanged": false}}
```

Sem `resources`, sem `prompts`: não há nada que os sustente. Passe `on_list_prompts` e `prompts` aparece; passe `on_completion` e `completions` aparece.

O `MCPServer` sempre anuncia ferramentas, recursos e prompts, tenha você registrado algum ou não, porque os seus managers sempre existem. Aqui embaixo a declaração *é* a chamada ao construtor.

## O genérico do lifespan {#the-lifespan-generic}

O `Server` é genérico no tipo que o seu lifespan produz. Anote uma vez e o objeto fica tipado em todo lugar onde aparece:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* O lifespan é um `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`; `@asynccontextmanager` em um gerador `async` dá exatamente isso.
* O que quer que ele produza com `yield` vira `ctx.lifespan_context`, e como os handlers são anotados com `ServerRequestContext[Catalog]`, `.search(...)` tem autocompletar e passa na checagem de tipos.
* Ele é aberto uma vez quando o servidor inicia e fechado uma vez quando para. Inicialização, encerramento e a versão do `MCPServer` da mesma ideia estão em **[Lifespan](../handlers/lifespan.md)**.

Sem um `lifespan=`, `ctx.lifespan_context` é um `dict` vazio.

## Um método só seu {#a-method-of-your-own}

O construtor cobre os métodos que o MCP define. `add_request_handler` cobre todo o resto:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* O primeiro argumento é a string do método. Notificações têm um irmão gêmeo, `add_notification_handler`.
* `params_type` é o modelo contra o qual os `params` recebidos são validados **antes** de o seu handler executar, então métodos personalizados *recebem* a validação que as ferramentas não recebem. Faça subclasse de `RequestParams` para que o campo `_meta` seja parseado como o de qualquer outro método.
* O handler retorna um `BaseModel`, um `dict` ou `None`. O SDK serializa isso no resultado JSON-RPC.

Uma ressalva honesta: o `Client` de alto nível só tem verbos para os métodos que o MCP define, então não existe `client.reindex()`. Um método de fornecedor é para um par que já sabe que ele existe: um cliente que você também distribui, ou outro serviço seu falando JSON-RPC.

Um método que você não pode reivindicar:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

O handshake pertence ao runner. `server/discover`, `ping` e todos os outros embutidos são seus para substituir.

!!! tip
    `Server.middleware`, mencionado naquele erro, envolve **toda** mensagem de entrada, inclusive `initialize`. Se o que você quer é observar ou reescrever o tráfego em vez de responder a um método novo, comece por **[Middleware](middleware.md)**.

## Os outros handlers {#the-other-handlers}

Cada um destes é uma ideia para a qual você já tem o vocabulário; cada um tem sua própria página.

* `on_call_tool`, `on_get_prompt` e `on_read_resource` podem retornar um `InputRequiredResult` em vez do resultado normal para pausar a chamada e pedir entrada ao cliente; veja **[Requisições de múltiplas idas e voltas](../handlers/multi-round-trip.md)**. Fiel a este nível, nada é instalado para você: enquanto o `MCPServer` sela o `requestState` por padrão, aqui o `request_state` que você define atravessa o fio exatamente como foi escrito até você optar com `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))`: uma linha (os dois nomes são importados de `mcp.server.request_state`) para a mesma selagem e verificação que o `MCPServer` faz (**[Protegendo o `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` têm o mesmo formato `(ctx, params) -> result` para as outras primitivas.
* `on_subscriptions_listen` serve o stream `subscriptions/listen` de 2026-07-28. Passe um `ListenHandler` construído sobre um `SubscriptionBus` e publique eventos no bus a partir dos seus outros handlers; veja **[Assinaturas](../handlers/subscriptions.md)** para a composição completa.
* `server.streamable_http_app()` retorna o mesmo app Starlette que o do `MCPServer`; faça o deploy dele do jeito que **[Executando o seu servidor](../run/index.md)** faz o deploy de qualquer outro app ASGI. Não existe `server.run(transport=...)` aqui embaixo: `server.run(read_stream, write_stream, server.create_initialization_options())` conduz uma conexão sobre um par de streams, e essa única linha é a história completa.

## Recapitulando {#recap}

* O `Server` de baixo nível recebe os seus handlers como **parâmetros do construtor** `on_*`; todo handler é `async (ctx, params) -> result`.
* Você escreve o dict `input_schema` e você monta o `CallToolResult`. Nada é derivado, encapsulado ou validado por você.
* Uma exceção em um handler é um erro de protocolo `-32603`. Um erro de ferramenta que o modelo consegue ler é um `CallToolResult` com `is_error=True` que **você** retorna.
* O `_meta` no resultado é endereçado à aplicação cliente, não ao modelo.
* `Server[T]` é genérico no que o seu lifespan produz; `ctx.lifespan_context` é um `T` tipado.
* `add_request_handler(method, params_type, handler)` serve qualquer método. `initialize` é reservado.
* As capacidades que um `Server` anuncia são derivadas de quais handlers você registrou.

`Client(server)` tratou os dois servidores de forma idêntica porque eles *são* o mesmo protocolo, e essa é justamente a ideia. A próxima camada abaixo nem é uma classe: é **[Middleware](middleware.md)**.
