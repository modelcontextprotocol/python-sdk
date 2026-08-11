---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# Assinaturas {#subscriptions}

O catálogo de um servidor não é fixo. Ferramentas aparecem em tempo de execução, e o conteúdo por trás da URI de um recurso muda.

As **assinaturas** (subscriptions) são como um cliente fica sabendo disso. O cliente envia uma única requisição `subscriptions/listen`, e a resposta a essa requisição *é* o stream: ela fica aberta e carrega as notificações de mudança que o cliente pediu.

## Publique a partir da ferramenta {#publish-it-from-the-tool}

A sua parte é uma linha: publicar a mudança.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` chega a todo stream aberto que assinou essa URI. A mais ninguém.
* `await ctx.notify_tools_changed()` chega a todo stream que pediu mudanças na lista de ferramentas. Um cliente que recebe isso chama `tools/list` de novo e agora vê `sprint_report`.
* Os irmãos são `notify_prompts_changed()` e `notify_resources_changed()`.
* Sem assinantes, sem trabalho. Publicar em um servidor ocioso é um no-op, então você nunca verifica se há alguém ouvindo. Você declara o que mudou.

O `MCPServer` serve `subscriptions/listen` para você. As obrigações do protocolo na conexão (o acknowledgment como primeiro frame, a filtragem por stream, o id da assinatura em cada frame) são trabalho do SDK.

!!! check
    Na conexão, um stream cujo filtro nomeou `board://sprint` fica assim depois que `complete_task` executa:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    Repare no que a atualização *não* carrega: o quadro. Cada frame carrega o id JSON-RPC da requisição listen em `_meta`, e esse id é o id da assinatura. Quem o gera é o cliente: o `Client` em Python usa strings como `"listen-1"`; outros clientes podem usar inteiros.

## Só o que foi pedido {#only-what-was-asked-for}

O filtro é um contrato. Um stream que pediu mudanças na lista de ferramentas e uma URI de recurso recebe esses dois tipos e nada mais. Publique uma mudança de prompt e esse stream fica em silêncio.

O `MCPServer` compara URIs de recurso como strings exatas, então um stream que nomeou `board://sprint` não ouve nada sobre `board://sprint/tasks/1`. A especificação permite que um servidor reporte uma mudança em um sub-recurso de uma URI assinada; o `MCPServer` nunca faz isso, mas os clientes são construídos para esperar por isso.

Duas coisas que o stream *não* é:

* **Não é um log de replay.** Um stream que caiu já era, e eventos publicados enquanto ninguém estava conectado não ficam em fila. Os clientes refazem o listen e buscam de novo.
* **Não é o caminho de 2025.** Clientes que chamaram `resources/subscribe` são atendidos por `ctx.session.send_resource_updated(uri)`. Os métodos `notify_*` chegam apenas a streams de `subscriptions/listen`.

## Decidindo quem pode observar {#deciding-who-may-watch}

Por padrão, todo tipo e toda URI pedidos são atendidos: qualquer chamador pode observar qualquer URI que você publica. Nada consulta o seu handler de leitura, porque ninguém está lendo — um chamador que o seu handler de `files://{name}` recusaria ainda pode abrir um stream em `files://payroll.csv` e saber que o arquivo mudou, e quando. Ele nunca descobre o conteúdo, e não consegue sondar o que existe, porque uma URI desconhecida também é atendida e simplesmente nunca dispara. Estreito, mas real, então bloqueie isso antes de publicar URIs por usuário a partir de um servidor multi-tenant.

O bloqueio é um middleware. Ele vê a requisição `subscriptions/listen` antes de o SDK fazer o acknowledgment e recusa quando o chamador pede qualquer coisa que não pode ler:

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` é a requisição crua, então o próprio middleware a valida em `SubscriptionsListenRequestParams` e lê o filtro que o cliente pediu.
* A recusa é um `MCPError` lançado antes de `call_next(ctx)`: o cliente recebe esse erro e nenhum stream, e a conexão segue em frente. Mantenha a mensagem uniforme, sem nomear nenhuma URI, para que uma recusa nunca confirme quais URIs são protegidas.
* Um único `can_access(user, uri)` responde às duas perguntas. O handler do recurso o consulta em `resources/read`; o middleware o consulta em `subscriptions/listen`. Troque a tabela por um banco de dados ou pelo seu sistema de RBAC e os dois continuam em sintonia.
* A decisão vale por toda a vida do stream. Não há nova verificação por evento, então se o acesso de um chamador pode expirar no meio do stream (um token que vence), encerre a conexão desse chamador quando isso acontecer.

O contrato completo do middleware, incluindo o que mais ele envolve e por que está marcado como provisório, está em **[Middleware](../advanced/middleware.md)**.

## A ponta do cliente {#the-client-end}

Aqui está um cliente do outro lado desse stream, acompanhando o quadro:

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Entrar em `client.listen(...)` envia a requisição e espera pelo seu acknowledgment, então o stream já está ativo quando o bloco começa, e cada evento tipado é um sinal para buscar de novo, nunca um payload. Esse é o contrato inteiro em uma tela. Todo o resto sobre a ponta do cliente mora na sua própria página: observar ao lado de um fluxo principal, fim de streams e refazer o listen. Veja **[Assinaturas](../client/subscriptions.md)** em *Clientes*.

## Escalando além de um processo {#scaling-past-one-process}

As publicações viajam do seu handler até os streams abertos por um `SubscriptionBus`. O padrão é em memória: um processo, todos os streams dentro dele. Essa é a resposta certa até você rodar réplicas atrás de um balanceador de carga, porque aí o stream de um cliente fica preso a uma réplica, e uma publicação em outra réplica precisa chegar até ele.

Essa costura é sua para implementar: dois métodos sobre o seu backend de pub/sub.

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` é seu, assim como a task leitora em cada réplica que decodifica as mensagens que chegam e chama cada listener registrado. Os listeners são síncronos, não podem lançar exceções e rodam no loop de eventos do servidor.

O bus carrega valores `ServerEvent` tipados, quatro dataclasses pequenas, nunca JSON-RPC. Carimbo, filtragem e ciclos de vida dos streams ficam no SDK, então uma implementação de bus não consegue quebrar o protocolo. Ela só consegue mover eventos entre processos.

Para publicar de fora de uma requisição, construa o bus você mesmo para ficar com a referência. O `MCPServer` monta um internamente quando você não passa nada, e não o expõe.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## A composição de baixo nível {#the-low-level-composition}

Lá embaixo, no `Server` de baixo nível, nada vem pré-conectado, e as mesmas peças se montam em três linhas:

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* O bus é seu, então você publica nele diretamente: `await bus.publish(ResourceUpdated(uri=...))`. Coloque-o onde os seus handlers consigam alcançá-lo: escopo de módulo aqui, o lifespan em um app maior.
* `ListenHandler(bus)` é o mesmo handler que o `MCPServer` registra, e `on_subscriptions_listen=` é um slot de handler comum. Coloque o seu próprio callable nesse slot para ter uma semântica diferente, e as obrigações da especificação passam para você: fazer o acknowledgment primeiro, carimbar cada frame com o id da assinatura, não entregar nada fora do filtro.
* `ListenHandler.close()` encerra cada stream aberto de forma graciosa. Cada um recebe o resultado da requisição listen como seu frame final, que é o jeito da especificação de dizer que o servidor encerrou a assinatura de propósito. Ele retorna antes de esses streams terminarem de descarregar, então dê um instante a eles antes de derrubar o transporte. Sem ele, os streams terminam quando o cliente desconecta.

## Recapitulando {#recap}

* Um cliente opta por participar com uma única requisição `subscriptions/listen`, e a resposta é o stream. Servir isso já vem embutido.
* Você publica com `ctx.notify_*`, e o SDK cuida do carimbo, da filtragem e do ciclo de vida.
* Eventos são sinais, não payloads. As duas pontas buscam de novo.
* A ponta do cliente é `async with client.listen(...)`: **[Assinaturas](../client/subscriptions.md)** em *Clientes* conta essa história.
* No `Server` de baixo nível você monta as mesmas peças por conta própria: um bus, `ListenHandler(bus)`, o slot `on_subscriptions_listen`.
* Escalar horizontalmente significa implementar `SubscriptionBus`, dois métodos, e passá-lo como `MCPServer(subscriptions=...)`.

Rodar o servidor que serve tudo isso, atrás de uma réplica ou de vinte, é **[Deploy e escala](../run/deploy.md)**.
