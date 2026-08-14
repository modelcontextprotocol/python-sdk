---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

Um **middleware** é uma única função async que envolve toda mensagem que o seu servidor recebe.

Você o escreve como `async (ctx, call_next)` e o adiciona ao fim de `server.middleware`. A API inteira é essa.

!!! warning
    A lista de middlewares está marcada como **provisória** no código-fonte: a assinatura e a
    semântica podem mudar em uma versão minor 2.x. Use-a para *observar* (tempo, logs, tracing) e
    para *recusar* mensagens; não faça dela o alicerce sobre o qual o seu servidor se apoia.

`MCPServer` recebe a lista na construção (`MCPServer(name, middleware=[...])`) e a expõe como
`mcp.middleware`; o `Server` de baixo nível expõe a mesma lista como `server.middleware`. O exemplo
abaixo usa o `Server` de baixo nível; se `Server(name, on_call_tool=...)` é novidade para você, leia
**[O Server de baixo nível](low-level-server.md)** primeiro.

## Um middleware de medição de tempo {#a-timing-middleware}

Um servidor, uma ferramenta, um middleware que registra no log quanto tempo cada mensagem levou:

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` é o mesmo `ServerRequestContext` que os seus handlers recebem. `ctx.method` é a string
  bruta do método; `ctx.params` são os params brutos, **antes** de qualquer validação.
* `call_next(ctx)` executa o restante da cadeia: a validação, a busca do handler, o seu handler.
  Retorne o que ele retornou e a resposta fica intacta.
* O `try`/`finally` é proposital: um handler que lança exceção ainda é cronometrado, porque a falha
  chega ao seu middleware como a exceção que sai de `call_next`.
* `server.middleware.append(...)` faz o registro. A lista executa do mais externo para o mais
  interno, então `middleware[0]` é o que fica mais perto do fio.

### Experimente {#try-it}

Conecte um cliente, liste as ferramentas, chame uma. O seu log tem **três** linhas:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

Você fez duas chamadas e recebeu três linhas. A primeira é `server/discover`: a requisição que o
cliente enviou para estabelecer a conexão, antes de você pedir qualquer coisa.

É justamente esse o ponto. O middleware envolve **toda** mensagem de entrada:

* O estabelecimento da conexão: `server/discover`, ou `initialize` e `notifications/initialized`
  em uma sessão legada.
* Toda requisição e toda notificação. Para uma notificação, `ctx.request_id is None`,
  `call_next(ctx)` retorna `None` e o que quer que você retorne é descartado.
* Até um método para o qual o servidor não tem handler: `call_next` lança o
  `MCPError(-32601, "Method not found")` *através* do seu middleware a caminho do cliente.

## O que você pode fazer dentro de um {#what-you-can-do-inside-one}

Em ordem crescente do quanto você deveria hesitar:

* **Observar.** Cronometre, conte, registre no log. O exemplo acima.
* **Recusar.** Lance um `MCPError` *em vez de* chamar `call_next(ctx)` e essa única mensagem é
  respondida com um erro JSON-RPC. A conexão continua de pé; a próxima mensagem passa. É assim
  que um servidor controla o acesso a `subscriptions/listen` por chamador:
  **[Decidindo quem pode observar](../handlers/subscriptions.md#deciding-who-may-watch)**, na
  página de Assinaturas, percorre o passo a passo.
* **Reescrever.** `ctx` é uma dataclass: `await call_next(dataclasses.replace(ctx, params=...))`
  entrega ao restante da cadeia params diferentes dos que o cliente enviou. Nunca faça isso com
  `initialize`: o resultado que o cliente recebe de volta é construído a partir dos seus params
  reescritos, mas o servidor grava o estado da conexão a partir dos params originais do fio. Os
  dois lados podem terminar o handshake discordando sobre o que negociaram.
* **Responder.** Retorne um resultado sem chamar `call_next(ctx)` e ele vai para o cliente como a
  sua resposta. `call_next` entrega a você a forma final do fio, e o pipeline nunca altera o que
  você retorna, então o envelope inteiro é seu: em uma conexão da era 2026 isso inclui o carimbo
  `_meta` de `serverInfo`, que o SDK adiciona aos resultados dos handlers, mas não aos seus.

!!! check
    `initialize` é uma das coisas que o middleware envolve, e é o *único* gancho que você tem
    para ele. Tente assumi-lo com `add_request_handler` e o SDK recusa:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` é tratado inline: o servidor não lê mais nenhuma mensagem de entrada até a sua
    cadeia de middlewares retornar. Aguardar uma requisição do servidor para o cliente
    (`ctx.session.send_request(...)`, uma elicitação (elicitation)) enquanto trata `initialize`,
    portanto, **trava a conexão em deadlock**: a resposta que você está esperando nunca poderá ser
    lida. Notificações do tipo fire-and-forget não têm problema.

## O único middleware que já vem ligado por padrão {#the-one-middleware-that-ships-on-by-default}

O SDK traz exatamente um middleware, e ele já está na lista do seu servidor: o que emite um span
do OpenTelemetry para cada mensagem. Você não o adiciona, e na maior parte do tempo nem pensa
nele. Ele é um no-op até você instalar um exportador, e tem a própria página:
**[OpenTelemetry](../run/opentelemetry.md)**.

!!! info
    Se você já escreveu middleware ASGI, já conhece esse formato. O `(scope, receive, send)`
    do Starlette virou `(ctx, call_next)`, e ele executa *depois* do transporte, sobre a mensagem
    decodificada em vez da requisição HTTP bruta. Os dois se compõem: o middleware do Starlette
    em `streamable_http_app()` enxerga HTTP; este enxerga MCP.

## Recapitulando {#recap}

* Um middleware é `async (ctx, call_next) -> result`, passado como `MCPServer(middleware=[...])` (ou
  adicionado a `mcp.middleware`) e adicionado a `server.middleware` no `Server` de baixo nível.
* Ele envolve **toda** mensagem de entrada (`server/discover`, `initialize`, requisições,
  notificações, métodos desconhecidos) e executa do mais externo para o mais interno.
* `ctx.request_id is None` é como você distingue uma notificação de uma requisição.
* Lance uma exceção em vez de chamar `call_next` para recusar uma mensagem; a conexão sobrevive.
* O tracing do OpenTelemetry do próprio SDK também é um middleware, já na lista. Veja
  **[OpenTelemetry](../run/opentelemetry.md)**.
* Toda essa superfície é provisória. Observe com ela; não construa em cima dela.

Isso é tudo o que envolve uma requisição. **[Autorização](../run/authorization.md)** é o que decide
se a requisição chega a ser executada.
