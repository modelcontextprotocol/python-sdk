---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# O que há de novo na v2 {#whats-new-in-v2}

Duas coisas aconteceram ao mesmo tempo na v2. O **SDK foi reconstruído**: um motor novo por baixo tanto do cliente quanto do servidor, um `Client` de primeira classe e um conjunto de renomeações em que uma base de código v1 esbarra logo no primeiro import. E o **protocolo mudou**: a v2 fala a revisão 2026-07-28 do MCP, que remove o handshake de conexão, a sessão e toda requisição iniciada pelo servidor, sem abandonar os clientes que você já tem.

Esta página é o tour pelas duas metades, uma seção por destaque, cada uma terminando na página responsável pelo assunto. Não é o manual de como portar. Esse é o **[Guia de migração](migration.md)**: cada quebra de compatibilidade, com o código de antes e de depois.

!!! note "A v2 é a linha estável"
    `pip install mcp` instala a 2.x, e **[Instalação](get-started/installation.md)** tem a linha de
    instalação para copiar e colar. Se algo na v2 quebrar, surpreender ou atrasar você,
    [conte para nós](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

## O SDK: da v1 para a v2 {#the-sdk-v1-to-v2}

### `FastMCP` agora é `MCPServer` {#fastmcp-is-now-mcpserver}

A classe de servidor de alto nível foi renomeada, e o módulo dela junto. É a primeira coisa em que todo servidor v1 esbarra, porque o caminho de import antigo sumiu em vez de ficar obsoleto:

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

Para um servidor feito com decoradores, isso também é a maior parte do trabalho de portar. `@mcp.tool()`, `@mcp.resource()` e `@mcp.prompt()` aceitam o que aceitavam na v1 (`@mcp.resource()` ganha um argumento nomeado opcional, `security=`), e o schema de entrada continua vindo das suas anotações de tipo. Em volta disso: tudo que ficava em `mcp.server.fastmcp.*` agora vive em `mcp.server.mcpserver.*`, `ctx.fastmcp` virou `ctx.mcp_server`, `get_context()` sumiu (declare um parâmetro `ctx: Context` no lugar), e a exceção base `FastMCPError` virou `MCPServerError`. O **[Guia de migração](migration.md#fastmcp-renamed-to-mcpserver)** tem a tabela de imports.

### `Resolve`: o novo jeito de pedir informações ao usuário {#resolve-the-new-way-to-ask-the-user-for-input}

Nem tudo de que uma ferramenta (tool) precisa deve vir do modelo. Novidade na v2: um parâmetro de ferramenta anotado com `Resolve(fn)` é preenchido por uma função que você escreve, de forma invisível para o modelo, e essa função pode retornar `Elicit(...)` para apresentar uma pergunta ao usuário. Esse é o jeito preferido de obter qualquer coisa do cliente no meio de uma chamada: o SDK leva a pergunta pelo mecanismo que a conexão suportar (uma requisição de elicitação (elicitation) ao vivo para um cliente legado, um multi-round-trip na 2026-07-28), então um único corpo de ferramenta atende as duas eras. **[Dependências](handlers/dependencies.md)** é a página.

!!! note
    As outras duas formas continuam lá para quando você precisar delas: `ctx.elicit()` ainda
    funciona para clientes em conexões legadas (**[Elicitação](handlers/elicitation.md)**), e um
    handler pode retornar ele mesmo um `InputRequiredResult` e conduzir as rodadas à mão, que é
    também como as requisições de amostragem (sampling) e de roots trafegam na 2026-07-28
    (**[Requisições multi-round-trip](handlers/multi-round-trip.md)**).

### Um `Client` de primeira classe {#a-first-class-client}

A v1 entregava três camadas aninhadas: um gerenciador de contexto de transporte que produzia streams brutos, uma `ClientSession` em volta deles e um `await session.initialize()` chamado à mão. A v2 tem um objeto só:

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` recebe um objeto de servidor (em memória, sem transporte: é o cenário dos testes), uma URL (Streamable HTTP) ou qualquer gerenciador de contexto de transporte, como `stdio_client(...)`. Entrar no `async with` conecta e negocia a versão do protocolo, seja qual for a era que o servidor fale; `client.server_capabilities` e `client.protocol_version` simplesmente estão lá depois disso, e `client.server_info` também, quando o servidor se identifica (agora ele é `Implementation | None`, já que na era 2026 a identidade é opcional). Os callbacks de amostragem e de elicitação que você registrou na v1 continuam funcionando (o corpo deles passa pela mesma renomeação de atributos para snake_case que todo o resto desta página), agora também respondem às requisições-dentro-de-resultados no estilo 2026 (abaixo), e rodam de forma concorrente em vez de um por vez. `ClientSession` continua por baixo para quem quer a superfície de baixo nível, e `client.session` a entrega para você; ela também mudou (roda sobre o novo motor de dispatcher, e algumas das próprias assinaturas dela mudaram), então leia o **[Guia de migração](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)** antes de descer de nível.

**[O Client](client/index.md)** o apresenta, **[Transportes do cliente](client/transports.md)** cobre as três formas de conexão, **[Callbacks do cliente](client/callbacks.md)** cobre os callbacks em si, e **[Testes](get-started/testing.md)** mostra o padrão em memória que substitui o helper `create_connected_server_and_client_session()` da v1.

### O `Server` de baixo nível foi reconstruído, não renomeado {#the-low-level-server-was-rebuilt-not-renamed}

Se você trabalha na camada JSON-RPC, esta é a parte "tudo é diferente" da v2. Aqui está o mesmo servidor de uma ferramenta só das duas formas; clique nos marcadores para ver o que mudou de lugar.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. Os handlers são registrados com decoradores (chamados, com parênteses), a qualquer momento depois que o servidor existe.
2. Você retorna uma `list[Tool]` pura e o SDK a embrulha em um `ListToolsResult`.
3. Os campos são camelCase em Python, e o schema é **aplicado**: o SDK valida os argumentos de `call_tool` contra ele com jsonschema antes de a sua função rodar, e é por isso que `arguments["query"]` abaixo é seguro.
4. Um único handler `call_tool` atende todas as ferramentas, e recebe o nome da ferramenta e os argumentos já validados, desempacotados e nunca `None`.
5. Lançar uma exceção é como uma ferramenta v1 sinaliza falha: qualquer exceção é capturada e retornada como `CallToolResult(isError=True)` com `str(e)` como texto, então o modelo que fez a chamada lê essa mensagem e pode tentar de novo.
6. O contexto vem de uma ContextVar ambiente, alcançada pelo objeto do servidor no meio da requisição.
7. Blocos de conteúdo puros são embrulhados em um `CallToolResult` para você.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Os campos agora são snake_case, e o schema é **anunciado, mas nunca aplicado**: nada confere os argumentos antes de o seu handler rodar.
2. Todo handler tem o mesmo formato: `async (ctx, params) -> result`. O contexto é o primeiro argumento (`ctx.session`, `ctx.request_id`, `ctx.protocol_version` moram nele); é aqui que `server.request_context` foi parar.
3. Você monta o `ListToolsResult` completo por conta própria. Retornar uma lista pura agora é um `TypeError` no lado do servidor, não algo que o SDK embrulha.
4. Entram params tipados (`params.name`, `params.arguments`), sai um resultado completo. Nada é desempacotado, embrulhado ou convertido para você.
5. A mesma verificação, outro verbo. Um `ValueError` aqui chegaria ao modelo como um `-32603` opaco (veja abaixo), então um erro de protocolo deliberado é lançado como `MCPError`: ele passa direto, com código e mensagem intactos, e `-32602` com esse texto é a resposta da própria especificação para uma ferramenta desconhecida.
6. `params.arguments` pode ser `None`; a v1 o trocava por `{}` antes mesmo de o seu código vê-lo. Sem validação na frente do handler, esta linha é indispensável.
7. Uma exceção inesperada lançada aqui vira um erro de protocolo **sanitizado**, `-32603` `"Internal server error"`: o modelo nunca vê a mensagem. Para uma falha que o modelo deva ler e à qual deva reagir, retorne `CallToolResult(is_error=True, ...)`.
8. Os handlers são argumentos do construtor, então a superfície do servidor está completa no instante em que ele existe; `add_request_handler()` é a saída de emergência pós-construção, e a porta para métodos personalizados.

O exemplo é o padrão. De forma mais geral: todo handler tem o mesmo formato, com params tipados na entrada e um tipo de resultado completo na saída; a antiga verificação com jsonschema dos argumentos de ferramenta sumiu; uma exceção é um erro de protocolo, nunca um resultado de ferramenta com `is_error=True`; e a ContextVar ambiente `server.request_context` sumiu. Métodos personalizados, com namespace de fornecedor, são de primeira classe via `add_request_handler(method, params_type, handler)`, que valida os params de entrada contra o seu modelo antes de o seu handler rodar. E uma lista `middleware` (marcada como provisória de propósito) envolve toda mensagem de entrada, substituindo os métodos privados `_handle_*` que as pessoas costumavam sobrescrever.

Por baixo dos panos, o loop de recebimento do `BaseSession` da v1 foi substituído por um motor de dispatcher que cliente e servidor agora compartilham, e é ele que torna várias coisas desta página verdadeiras ao mesmo tempo: um único objeto `Server` atende as duas eras do protocolo, `Client(server)` despacha dentro do processo sem o enquadramento JSON-RPC, e uma requisição de cliente que estoura o timeout agora cancela de fato o handler do lado do servidor.

**[O Server de baixo nível](advanced/low-level-server.md)** é a página; o **[Guia de migração](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** percorre cada hook removido. Se você nunca desceu abaixo do `MCPServer`, nada disso afeta você.

### Os tipos do protocolo foram para `mcp-types`, e todo campo é snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

Os tipos do protocolo agora vivem em uma distribuição própria, `mcp-types`. Ela não depende de nada além de pydantic e typing-extensions, então um gateway, um proxy ou um gerador de código consegue consumir os formatos de mensagem do MCP sem instalar uma pilha HTTP: um projeto assim instala `mcp-types` e importa `mcp_types`. O próprio `mcp` depende desse pacote em uma versão exata e o reexpõe, então o código que depende do SDK continua escrevendo `import mcp.types as types` e `from mcp.types import Tool` (um alias permanente, cada nome é o mesmo objeto) e declara apenas a sua única dependência real, `mcp`. A regra prática: importe pelo pacote do qual você de fato depende.

Nesses tipos, todo atributo Python agora é snake_case: `result.is_error`, `tool.input_schema`, `listing.next_cursor`. O JSON que trafega é camelCase, exatamente como antes; só a grafia dos atributos mudou. Dois padrões mais rígidos vêm junto: campos desconhecidos são ignorados em vez de preservados na ida e volta (coloque os extras em `_meta`), e os dois lados validam o tráfego contra a versão do protocolo que negociaram. Veja o **[Guia de migração](migration.md#field-names-changed-from-camelcase-to-snake_case)** para a tabela de renomeações.

### A configuração de transporte foi para `run()` {#transport-configuration-moved-to-run}

`MCPServer(...)` diz respeito ao que o seu servidor *é*: o nome, as instruções, o lifespan, a autenticação. Como ele é *servido* agora é assunto de `run()` e dos construtores de app, e foi para lá que `host`, `port`, `stateless_http`, `json_response`, os caminhos dos endpoints e `transport_security` foram (`MCPServer("x", port=9000)` é um `TypeError`). As sobrecargas são tipadas por transporte, então o seu editor diz quais opções `stdio` aceita e quais `streamable-http` aceita. Uma remoção que vale conhecer: `mount_path` sumiu; montar o app ASGI é o jeito suportado de servir sob um prefixo.

**[Executando seu servidor](run/index.md)** cobre as opções; **[Adicionar a um app existente](run/asgi.md)** cobre a montagem.

### Comportamento que muda sem erro de import {#behavior-that-changes-without-an-import-error}

As renomeações se anunciam sozinhas. Estas aqui, não:

* **Funções síncronas rodam em uma thread de trabalho.** Uma ferramenta `def` (ou recurso, prompt ou resolvedor) não bloqueia mais o loop de eventos; a contrapartida é que o corpo dela não roda mais *na* thread do loop de eventos, o que importa para código com afinidade de thread. Handlers `async def` ficam intocados. **[Guia de migração](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**.
* **`MCPError` (o `McpError` da v1) lançado dentro de uma ferramenta agora é um erro de protocolo.** O modelo nunca o vê. Toda outra exceção continua virando um resultado `is_error=True` que o modelo pode ler e ao qual pode reagir. **[Tratando erros](servers/handling-errors.md)** explica a divisão.
* **Os resultados são validados antes de sair.** Uma `Tool` montada à mão cujo `input_schema` é `{}` agora falha em `tools/list` (a especificação exige `"type": "object"`). Servidores construídos com `@mcp.tool()` nunca veem isso; o SDK escreve os schemas deles.
* **O seu cliente valida o que recebe.** `list_tools()` e `call_tool()` conferem a resposta do servidor contra a versão de protocolo negociada, então um servidor quase válido que o parsing tolerante da v1 aceitava agora lança `pydantic.ValidationError`. Se você se conecta a servidores que não controla, espere ser você quem os descobre; o **[Guia de migração](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)** tem os detalhes.
* **Templates de URI agora são RFC 6570 de verdade.** `{+path}`, `{?query}` e companhia funcionam, a correspondência é exata em vez de frouxa à base de regex, e path traversal nos valores extraídos é rejeitado por padrão. Templates mais rígidos falham no momento da decoração, não na primeira requisição. **[Templates de URI](servers/uri-templates.md)**.
* **O lifespan do Streamable HTTP roda uma vez só**, na inicialização, e o estado dele é compartilhado por toda sessão e requisição. Na v1 ele rodava uma vez por sessão, e uma vez por requisição com `stateless_http=True`. Pools e caches montados em um lifespan ficam drasticamente mais baratos; qualquer coisa que adquiria ali um recurso por conexão agora pertence ao corpo do handler. **[Lifespan](handlers/lifespan.md)**.
* **`mcp dev` e `mcp install` fixam o ambiente que criam** na versão do SDK que você tem instalada. Os dois comandos rodam o seu servidor em um ambiente `uv run --with ...` novo, que antes resolvia `mcp` para a versão estável mais recente em vez da versão contra a qual você está desenvolvendo. **[Guia de migração](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**.
* **O cliente HTTP agora é `httpx2`, não `httpx`.** A troca de dependência muda o que o seu código captura e repassa (`httpx2.AsyncClient`, `httpx2.ConnectError`), e muda como os certificados TLS são verificados: `httpx2` valida via `truststore` contra o repositório de certificados confiáveis do sistema operacional em vez da lista de CAs embutida do certifi. A maioria dos ambientes nem percebe; um contêiner mínimo sem repositório de CAs do sistema, ou uma CA privada que só o bundle do certifi conhecia, começa a falhar no handshake TLS. Defina `SSL_CERT_FILE`/`SSL_CERT_DIR` ou passe `verify=ssl_context` para o seu cliente. **[Guia de migração](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**.

### Removidos de vez {#removed-outright}

Cada um destes é uma seção no **[Guia de migração](migration.md)**:

* O **transporte WebSocket**, dos dois lados, e o extra `mcp[ws]`. Nunca fez parte da especificação do MCP.
* A API **experimental de Tasks** (`mcp.*.experimental`). A 2026-07-28 tira as tasks do núcleo do protocolo e as leva para uma extensão oficial ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)), que este SDK ainda não implementa.
* `mcp.shared.version`, `mcp.shared.progress` e `mcp.shared.session` (junto com o stub `RequestResponder` que as anotações de `message_handler` da v1 importavam) como caminhos de import. (`mcp.types` *não* foi removido: continua como alias permanente do pacote independente `mcp_types`.)
* A grafia obsoleta `streamablehttp_client`, e o callback `get_session_id` de `streamable_http_client` (que agora produz exatamente dois streams).
* `McpError`, renomeado para **`MCPError`** com um construtor direto `(code, message, data)`.
* `MCPServer.get_context()`, `mount_path=`, e os métodos decoradores, a ContextVar e os dicts de handlers do `Server` de baixo nível.

## O protocolo: de 2025-11-25 para 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

A v2 implementa a revisão 2026-07-28 e serve **as duas** revisões ao mesmo tempo: o mesmo `streamable_http_app()` (e o mesmo servidor stdio) responde ao `initialize` de um cliente da era 2025 e às requisições de um cliente da era 2026 sem nada para configurar, sem flag para virar e sem deploy separado. Servir a revisão nova não abandona um cliente que está na antiga. O que vem a seguir é o que a revisão nova em si muda.

### Sem handshake, sem sessão {#no-handshake-no-session}

Um cliente 2026-07-28 não abre uma conexão, negocia e só então conversa. Toda requisição carrega a versão do protocolo, as informações do cliente e as capacidades do cliente em `_meta`, e a única chamada de descoberta, `server/discover`, é uma requisição comum como qualquer outra. `Client` faz a coisa certa por padrão: sonda `server/discover` uma vez e recua para o handshake `initialize` se o servidor for mais antigo.

Sobre Streamable HTTP não existe `Mcp-Session-Id` no caminho 2026, e esse é o grande destaque operacional: **nada amarra uma requisição moderna a um worker**, então qualquer réplica atrás de um balanceador de carga round-robin simples pode respondê-la. Duas ressalvas honestas. Os seus clientes da era 2025 (hoje, isso é a maioria dos clientes) ainda abrem sessões e ainda precisam de toda a afinidade de sessão de que precisavam na v1; nada muda para eles. E a única coisa que uma nova tentativa *multi-round-trip* precisa carregar entre workers é o seu `request_state` selado, cuja chave padrão é gerada por processo, então um deploy com escala horizontal passa `RequestStateSecurity(keys=[...])`. (`stateless_http=True` não tem relação: ele só afeta como os clientes da era 2025 são servidos, e o tráfego 2026 nunca o lê; se você já o definia na v1, nada muda.)

**[Versões do protocolo](protocol-versions.md)** é o lado do cliente disso, **[Deploy e escala](run/deploy.md)** é o checklist do operador (a allowlist de Host, a chave do `request_state`, notificações entre réplicas), e **[Servindo clientes legados](run/legacy-clients.md)** é a história das duas eras ao mesmo tempo.

### O servidor não pode chamar o cliente: requisições multi-round-trip {#the-server-cannot-call-the-client-multi-round-trip-requests}

Toda requisição iniciada pelo servidor sumiu na 2026-07-28: elicitação por push, amostragem, `roots/list`. Em uma conexão 2026 não há canal para elas, então `ctx.elicit()` e `ctx.session.create_message()` falham ali com `NoBackChannelError` (continuam funcionando para clientes legados).

A substituição inverte a chamada. Uma ferramenta que precisa de algo do usuário *retorna* a pergunta (`InputRequiredResult`), o cliente a responde com os mesmos callbacks que sempre teve, e a chamada é repetida com as respostas anexadas. `Client` conduz esse loop para você. No servidor você raramente monta o resultado por conta própria, porque uma **[dependência](handlers/dependencies.md)** faz isso: anote um parâmetro com `Resolve(ask_quantity)`, onde `ask_quantity` é uma função comum que você escreve, e o SDK pergunta pelo mecanismo que a conexão suportar, uma requisição de elicitação ao vivo em uma sessão legada ou um multi-round-trip na 2026. Um corpo de ferramenta, as duas eras:

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

Esse arquivo é a proposta inteira em um lugar só: um servidor, uma ferramenta apoiada em `Resolve`, e um cliente legado mais um cliente moderno, os dois recebendo a sua resposta, em memória. **[Requisições multi-round-trip](handlers/multi-round-trip.md)** explica o mecanismo (incluindo o `request_state`, que o SDK sela e verifica para você); **[Elicitação](handlers/elicitation.md)** cobre a parte de perguntar.

!!! warning "Este é o único lugar em que um servidor v1 portado muda de comportamento"
    Os seus próprios testes esbarram nisso primeiro: `Client(mcp)` negocia 2026-07-28 com o seu
    servidor v2 por padrão, então uma ferramenta que chama `ctx.elicit()` falha em um teste que
    passava na v1. Mova a pergunta para um parâmetro `Resolve(...)` (portável entre eras), ou fixe o
    cliente de teste em `mode="legacy"` se você quer mesmo o comportamento de push.

### Roots, amostragem e logging de protocolo estão obsoletos; `ping` foi removido {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

A [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) marca como obsoletas três *capacidades* inteiras, em toda versão do protocolo: roots, amostragem e logging no nível do MCP (`ctx.info()` e companhia). Esse é um eixo separado do canal de retorno (back-channel) ausente acima; obsoleto é só um aviso, tudo continua funcionando em sessões da era 2025, e nada muda no que trafega. O que você nota é o `MCPDeprecationWarning`, que é um `UserWarning`, então ele aparece por padrão; espere que o seu primeiro `ctx.info(...)` depois da atualização avise isso.

`ping` é mais severo: removido do protocolo, não obsoleto. Dois dos métodos avulsos das funcionalidades obsoletas são removidos na 2026-07-28 do mesmo jeito, `logging/setLevel` e o `notifications/roots/list_changed` do cliente, e as notificações de progresso agora vão apenas do servidor para o cliente.

**[Funcionalidades obsoletas](deprecated.md)** tem a tabela completa, o substituto de cada uma, e o filtro de uma linha caso você precise de um log silencioso enquanto serve clientes legados.

### Notificações de mudança viram um stream só {#change-notifications-become-one-stream}

Na 2026-07-28, o stream HTTP GET avulso e `resources/subscribe` são substituídos por `subscriptions/listen`: o cliente abre um stream de longa duração e informa os tipos de notificação que quer. O `MCPServer` o serve por padrão; você publica com `await ctx.notify_resource_updated(uri)` (e `notify_tools_changed()`, e assim por diante), um middleware pode recusar uma requisição de listen por chamador, e deploys com várias réplicas encaixam um `SubscriptionBus` compartilhado. No cliente, `async with client.listen(...)` abre o stream: o filtro entra como argumentos nomeados, eventos de mudança tipados voltam, e `sub.honored` é o subconjunto que o servidor concordou em entregar.

**[Assinaturas](handlers/subscriptions.md)** cobre publicar e servir, **[a página gêmea em Clientes](client/subscriptions.md)** a ponta que observa, e **[Deploy e escala](run/deploy.md)** o barramento.

### O resto, rapidamente {#the-rest-quickly}

* **A identidade é um metadado opcional, por mensagem.** A chave `clientInfo` de `_meta` no lado da requisição é opcional (o par obrigatório é `protocolVersion` + `clientCapabilities`), e `serverInfo` saiu do corpo do resultado de `server/discover`: em vez disso, os servidores o carimbam no `_meta` de todo resultado da era 2026 ([especificação #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). O SDK sempre carimba; `client.server_info` é `None` quando um servidor não se identifica (por exemplo, um middleware removeu a chave). **[O Server de baixo nível](advanced/low-level-server.md)** mostra o carimbo no tráfego real.
* **As requisições são roteáveis sem fazer parse do corpo.** Requisições HTTP modernas carregam `Mcp-Method` (e, para as três chamadas no estilo de ferramenta, `Mcp-Name`); uma propriedade do schema de entrada de uma ferramenta anotada com `x-mcp-header` é espelhada em um cabeçalho `Mcp-Param-*` e conferida pelo servidor ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). Gateways e rate limiters podem rotear só pelos cabeçalhos; o **[Guia de migração](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)** tem as regras.
* **Os resultados carregam dicas de cache.** Resultados de listagem e de leitura declaram `ttlMs` e `cacheScope` ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)); você os define por método com `cache_hints=`, e `Client` os respeita com um cache de respostas embutido. Um servidor que não envia dicas (todo servidor pré-2026) vê tráfego idêntico, sem cache. **[Dicas de cache](client/caching.md)**.
* **Extensões são de primeira classe.** Servidores e clientes declaram conjuntos opcionais de capacidades sob identificadores em DNS reverso ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)); a extensão embutida `Apps` (MCP Apps) é a referência. **[Extensões](advanced/extensions.md)** e **[MCP Apps](advanced/apps.md)**.
* **Os códigos de erro foram padronizados.** Um recurso inexistente é `-32602` com a URI em `error.data`, e os novos códigos reservados pela especificação aparecem como `-32020` (cabeçalho divergente), `-32021` (capacidade obrigatória ausente) e `-32022` (versão de protocolo não suportada). **[Solução de problemas](troubleshooting.md)** é organizada pelas mensagens exatas.
* **A autorização ficou mais difícil de usar errado.** O cliente valida o `iss` retornado com o código de autorização ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207); o seu `callback_handler` agora retorna um `AuthorizationCodeResult`), envia `application_type` quando se registra, e nunca reutiliza credenciais em um servidor de autorização diferente. Novidade no lado corporativo: o fluxo de asserção de identidade da [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990). O **[Guia de migração](migration.md)** lista cada mudança de OAuth; **[OAuth para clientes](client/oauth-clients.md)** e **[Asserção de identidade](client/identity-assertion.md)** são as páginas.
* **Todo servidor é rastreável.** O OpenTelemetry vem ativado por padrão como middleware: toda requisição ganha um span de servidor, sem custo até o processo configurar um exportador. Quando as duas pontas rodam o SDK, o cliente também propaga o contexto de trace W3C em `_meta`, então os traces se conectam. **[OpenTelemetry](run/opentelemetry.md)**.

## Atualizando a partir da v1? {#upgrading-from-v1}

* O **[Guia de migração](migration.md)** é a lista completa e exata do que mudar; esta página foi o porquê.
* **A v1.x não vai a lugar nenhum.** Ela entra em manutenção, continua recebendo correções críticas e patches de segurança, e nada no lançamento da especificação 2026-07-28 a quebra; a documentação dela fica em [/v1/](https://py.sdk.modelcontextprotocol.io/v1/). Se você publica uma biblioteca que depende de `mcp` e ainda não está pronto para migrar, mantenha um limite superior (por exemplo `mcp>=1.28,<2`) para que uma resolução sem versão fixada fique na 1.x.
* Algo mal-acabado, confuso ou quebrado? **[Envie feedback da v2](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**; tudo é lido.
