---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# Callbacks do cliente {#client-callbacks}

Quase toda requisição no MCP vai em um só sentido: do cliente para o servidor.

Um servidor também pode pedir coisas ao **cliente**: fazer uma pergunta ao usuário, amostrar o modelo do usuário, listar as pastas do workspace do usuário. Você responde a essas requisições passando **callbacks** para `Client(...)`.

## Um servidor que pergunta {#a-server-that-asks}

Aqui está um servidor cuja ferramenta não consegue terminar sozinha:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` envia uma requisição `elicitation/create` **para o cliente** e espera.
* A ferramenta não retorna até que alguém (uma pessoa em um formulário, ou o seu código) forneça um `name`.

Essa é a metade do servidor, e a página **[Elicitação](../handlers/elicitation.md)** cuida dela. Esta página é a outra ponta do fio.

## O callback de elicitação {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* Um callback de elicitação (elicitation) é `async (context, params) -> ElicitResult`.
* `params.message` é a pergunta. `params.requested_schema` é o JSON Schema da resposta que o servidor quer. Um cliente de verdade renderiza um formulário a partir dele; este aqui preenche automaticamente.
* Você retorna `ElicitResult(action="accept", content={...})`, ou `action="decline"`, ou `action="cancel"`. A única outra opção é `ErrorData(...)`, que recusa a requisição e faz a chamada inteira falhar.
* `context` é um `ClientRequestContext`: a `session` ativa, o `request_id` do servidor e qualquer `meta` que ele tenha anexado.

!!! tip
    `params` é uma união dos dois modos de elicitação. Aqui `params.mode` é `"form"`; uma requisição `"url"`
    traz `params.url` em vez de um schema. Um único callback trata os dois; ramifique em `params.mode`.
    **[Elicitação](../handlers/elicitation.md)** mostra o padrão completo.

### Experimente {#try-it}

Chame `issue_card` e observe as duas pontas.

Seu callback recebe a pergunta do servidor, já analisada:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

Ele responde, `ctx.elicit(...)` retoma dentro da ferramenta, e a ferramenta termina:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

Um `tools/call` seu, um `elicitation/create` de volta do servidor, respondido pela sua função, tudo dentro de uma única chamada de ferramenta.

!!! info
    O `mode="legacy"` na chamada `Client(...)` está fazendo trabalho de verdade. Por padrão, `Client(...)` negocia o caminho
    moderno do protocolo, e esse caminho não tem canal de retorno (back-channel) para requisições do servidor ao cliente: `ctx.elicit`
    falha antes mesmo de o seu callback rodar. Não é o transporte que decide isso; é o protocolo
    negociado, tanto em memória quanto por uma URL. Fixe `mode="legacy"` sempre que o seu cliente tiver
    que responder a uma; todos os testes por trás desta página fazem isso. **[Versões do protocolo](../protocol-versions.md)** tem a história completa.

    Em uma sessão 2026-07-28 o callback não está morto, ele é alimentado de outro jeito: quando uma ferramenta retorna um
    `InputRequiredResult` carregando um `ElicitRequest`, o `Client` despacha essa entrada para o mesmo
    `elicitation_callback` e refaz a chamada para você. Esse fluxo está em **[Requisições de múltiplas idas e voltas](../handlers/multi-round-trip.md)**.

## Um callback é uma capacidade {#a-callback-is-a-capability}

Você nunca disse ao servidor que o seu cliente consegue responder a requisições de elicitação. O SDK disse.

Quando um cliente se conecta, ele declara suas `capabilities`, a imagem espelhada das do servidor. Você não escreve esse objeto. **Registrar um callback é a declaração.**

| você passa | o cliente declara |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| nenhum deles | `{}` |

As subcapacidades de amostragem (sampling) são o único refinamento: passe `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` junto com `sampling_callback` quando o seu amostrador trata os parâmetros `tools` / `tool_choice`. Os servidores precisam ver `sampling.tools` declarado antes de poderem enviá-los.

`logging_callback` e `message_handler` não estão na tabela. Eles tratam notificações, e notificações não precisam de capacidade.

O servidor lê a declaração de volta com `ctx.session.check_client_capability(...)`. Adicione uma ferramenta que faça isso:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

Conecte com apenas `elicitation_callback` e chame-a:

```python
result.structured_content  # {'result': ['elicitation']}
```

Passe os três callbacks e você recebe `['elicitation', 'sampling', 'roots']`. Não passe nenhum e você recebe `[]`.

!!! check
    Agora faça a coisa errada: conecte **sem** `elicitation_callback` e chame `issue_card` mesmo assim.

    A requisição `elicitation/create` do servidor ainda chega ao seu cliente, e o SDK a responde por
    você, com um erro, porque você nunca disse que conseguiria tratá-la. Esse erro afunda a chamada inteira.
    `call_tool` não retorna um resultado `is_error`; ele levanta uma exceção:

    ```text
    MCPError: Elicitation not supported
    ```

    Isso é um erro de protocolo (`-32600`, *invalid request*), não um erro de ferramenta: não há nada para
    o modelo ler e tentar de novo. É por isso que vale a pena ter `client_features`: um servidor bem-comportado
    verifica antes de perguntar.

## O par descontinuado {#the-deprecated-pair}

`sampling_callback` responde a `sampling/createMessage`: o servidor pedindo ao *seu* modelo que complete algo. `list_roots_callback` responde a `roots/list`: o servidor perguntando em quais diretórios ele pode trabalhar.

Os dois funcionam. Os dois seguem a regra acima. E os dois atendem RPCs que a **spec 2026-07-28 remove**: um servidor moderno não chama de volta o seu cliente no meio de uma requisição, ele devolve a requisição para você como parte do resultado da ferramenta (**[Requisições de múltiplas idas e voltas](../handlers/multi-round-trip.md)**). Os callbacks em si não estão mortos. Quando um `InputRequiredResult` carrega um `CreateMessageRequest` ou um `ListRootsRequest`, o loop automático do `Client` o despacha para o mesmo `sampling_callback` ou `list_roots_callback` que você registrou aqui. A lista inteira está em **[Funcionalidades descontinuadas](../deprecated.md)**.

Você ainda precisa dos callbacks para falar com servidores que não migraram. As assinaturas:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* Um callback de amostragem recebe o `CreateMessageRequestParams` completo (`messages`, `model_preferences`, `max_tokens`) e retorna um `CreateMessageResult`. *Você* executa o modelo, do jeito que quiser; o SDK só transporta a requisição.
* Um callback de roots não recebe parâmetro nenhum e retorna um `ListRootsResult`.
* Qualquer um dos dois pode retornar `ErrorData(...)` no lugar, para recusar.

Passe-os para `Client(...)` exatamente como `elicitation_callback`.

## Os callbacks de notificação {#the-notification-callbacks}

Mais dois. Nenhum deles declara nada.

`logging_callback` recebe as `notifications/message` que um servidor envia, como `LoggingMessageNotificationParams` (`level`, `logger`, `data`). O logging de protocolo em si foi descontinuado pela spec 2026-07-28 (**[Logging](../handlers/logging.md)** diz o que fazer no lugar), então esse callback existe para os servidores que ainda o emitem. Em uma conexão da era 2026, o callback sozinho não te dá nada, porque servidores 2026 enviam mensagens de log apenas para requisições que optam por recebê-las: passe `log_level="info"` (ou outro nível) para `Client(...)` para carimbar essa opção em toda requisição e receber esse nível e acima. Servidores pré-2026 o ignoram e mantêm o comportamento de `logging/setLevel`.

`message_handler` é o pega-tudo: toda notificação do servidor que a sessão expõe chega até ele (além do callback específico dela), e em um transporte baseado em stream toda `Exception` no nível do transporte também. Duas nunca chegam: `notifications/cancelled` é aplicada pelo SDK em vez de exposta, e a confirmação de assinatura de um stream `listen()` ativo é consumida por esse stream. Anote o parâmetro com `IncomingMessage` (`ServerNotification | Exception`, exportado de `mcp.client`). O único padrão que vale conhecer é `if isinstance(message, Exception): raise message`, para que uma conexão quebrada falhe em alto e bom som em vez de sumir.

## Recapitulando {#recap}

* Um servidor pode enviar requisições ao cliente. Você as responde com callbacks passados para `Client(...)`.
* O callback de elicitação é o atual: `async (context, params) -> ElicitResult`, uma função para os modos formulário e URL.
* **Registrar um callback é declarar a capacidade.** Sem ele, o SDK recusa a requisição do servidor em seu nome e a chamada inteira falha com `MCPError`.
* Um servidor descobre antes de perguntar com `ctx.session.check_client_capability(...)`.
* `sampling_callback` e `list_roots_callback` funcionam do mesmo jeito, mas atendem funcionalidades descontinuadas; servidores modernos usam requisições de múltiplas idas e voltas no lugar.
* `logging_callback` e `message_handler` recebem notificações. Eles não declaram nada.

O primeiro argumento de `Client(...)` é um objeto de transporte. **[Transportes do cliente](transports.md)** cobre todos os tipos.
