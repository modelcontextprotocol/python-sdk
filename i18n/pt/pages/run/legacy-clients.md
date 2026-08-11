---
translation:
  sections: [3d1663c18edc824c, d4fd37009a13f03d, af9f398a5a8b679a, 470c2dd144294d69, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# Atendendo clientes legados {#serving-legacy-clients}

O MCP tem duas eras de protocolo: a era do handshake `initialize`, até a versão da especificação `2025-11-25`, e a era moderna, `2026-07-28`. **[Versões do protocolo](../protocol-versions.md)** é a página sobre a divisão em si.

Esta página trata do lado do servidor dessa divisão, e a resposta cabe em uma frase: **o `streamable_http_app()` que você já faz o deploy atende as duas.**

O SDK roteia cada requisição pelo header `MCP-Protocol-Version`. Uma requisição que indica `2026-07-28` vai para o handler moderno. Uma requisição que indica uma versão da era do handshake, ou que não traz header nenhum (que é como o `initialize` de um cliente pré-2026 chega), vai para o transporte que esses clientes esperam: handshake `initialize`, sessões e tudo mais. Isso acontece por requisição, antes do seu código, no mesmo app.

Então um cliente legado não é algo *para* o qual você constrói. É algo que se conecta *ao* servidor que você já escreveu. Você não configura nada.

!!! note
    Nada, literalmente. Não existe opção `legacy=`, nem allowlist de versões, nem forma de rejeitar ou
    desabilitar uma era: nem em `streamable_http_app()`, nem em `run()`, nem no gerenciador de sessões.
    As duas eras estão sempre ativas. O mais próximo de uma chave por era nessa assinatura é
    `stateless_http`, e ele é a maior parte desta página.

## Um handler, as duas eras {#one-handler-both-eras}

Aqui está uma ferramenta (tool) que precisa perguntar algo ao usuário, e clientes das duas eras chamando-a:

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` precisa de uma coisa que o modelo não forneceu: quantas cópias. `Annotated[..., Resolve(ask_quantity)]` é como uma ferramenta declara isso (**[Dependências](../handlers/dependencies.md)** tem essa história completa). Nada em `reserve` cita uma versão, verifica uma capacidade ou ramifica.

Os dois clientes ficam abertos **ao mesmo tempo**, no mesmo objeto `mcp`. `mode="legacy"` executa o handshake `initialize`: exatamente a conexão que um cliente pré-2026 abre. O outro usa o padrão e cai em `2026-07-28`.

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

Mesmo servidor, mesmo handler, mesma resposta. A funcionalidade inteira é essa.

Vale parar no *como*, porque os dois clientes receberam a mesma pergunta por dois fios completamente diferentes. A conexão `2026-07-28` não tem canal para o servidor enviar uma requisição, então `Resolve` retornou a pergunta dentro do resultado da ferramenta e o cliente repetiu a chamada com a resposta (**[Requisições de múltiplas idas e voltas](../handlers/multi-round-trip.md)**). A conexão `2025-11-25` não tem nada disso; ali, `Resolve` enviou uma requisição `elicitation/create` ao vivo no meio da chamada e esperou. Você não escreveu nenhum dos dois. `Resolve` lê a versão negociada da conexão e escolhe; o corpo da sua ferramenta vê um `AcceptedElicitation` de qualquer forma.

!!! tip
    Essa portabilidade entre eras é *o motivo* de `Resolve` ser a API sobre a qual construir. Seu irmão mais velho, `ctx.elicit()`
    (**[Elicitação](../handlers/elicitation.md)**), só envia `elicitation/create`, então só
    funciona em uma conexão legada. Em uma `2026-07-28`, a chamada falha. Se uma ferramenta ainda o usa,
    a correção é a que você vê acima, não uma verificação de versão.

## Quanto uma sessão legada custa para você {#what-a-legacy-session-costs-you}

O roteamento é grátis. A sessão não.

Uma conexão `2026-07-28` é **sem sessão**: cada requisição é independente, e o handler moderno nunca emite um `Mcp-Session-Id`. Uma conexão legada é o oposto. No momento em que um cliente pré-2026 envia `initialize`, o SDK gera um `Mcp-Session-Id`, retorna-o em um header de resposta e mantém um registro vivo por trás dele para as requisições posteriores do cliente encontrarem: a versão negociada, os streams abertos, uma task em segundo plano conduzindo a sessão.

Esse registro é **um `dict` simples dentro do processo**. Não existe armazenamento distribuído de sessões nem forma de plugar um.

Com um worker, isso é invisível. Com dois, é o problema inteiro: uma requisição que traz um `Mcp-Session-Id` e cai em um worker que não o gerou não encontra nada naquele dict, e a resposta é um `404` (`Session not found`), não o resultado da ferramenta. Então, no momento em que você executa mais de um worker, **clientes legados precisam de roteamento sticky**: toda requisição de uma sessão tem que chegar ao processo que a iniciou. Clientes modernos nunca precisam; eles não têm sessão à qual aderir. **[Deploy e escala](deploy.md)** cobre stickiness e tudo mais sobre executar mais de uma dessas instâncias.

!!! warning
    `event_store=` parece a solução e não é. Ele é **retomabilidade** (reenviar eventos SSE
    perdidos para um cliente que se reconecta à *mesma* sessão), não um armazenamento de sessões. Ele nunca torna uma
    sessão alcançável a partir de outro processo.

## A única chave: `stateless_http` {#the-one-knob-stateless_http}

Se stickiness é um custo que você se recusa a pagar, existe exatamente uma coisa que você pode mudar.

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

Esse é o servidor do topo da página mais uma keyword. `stateless_http=True` faz a perna legada construir uma sessão descartável por requisição: nenhum `Mcp-Session-Id` emitido, nada lembrado entre requisições, então qualquer worker pode atender qualquer requisição e o load balancer pode fazer o que quiser.

Duas coisas sobre ele importam mais do que o que ele faz.

**Ele só afeta a perna legada.** As requisições são roteadas pelo header de versão *antes* de `stateless_http` ser lido, então o caminho moderno nunca o vê. Uma conexão `2026-07-28` já é sem sessão e fica exatamente igual com qualquer um dos valores.

**Ele custa os dois canais servidor-para-cliente nessa perna.** Uma sessão que vive por um `POST` não tem stream para o servidor empurrar uma requisição nem stream independente para empurrar notificações. Toda requisição iniciada pelo servidor levanta `NoBackChannelError`: `ctx.elicit()`, as chamadas aposentadas de amostragem (sampling) e roots (**[Funcionalidades obsoletas](../deprecated.md)**) e, sim, `Resolve` fazendo sua pergunta a um cliente *legado*. As notificações nem recebem erro; são descartadas silenciosamente.

!!! note
    `json_response=True` não é essa chave, mas cobra metade do mesmo custo em *toda* sessão
    legada: um `POST` respondido com um único corpo JSON não tem stream para o canal com escopo de requisição,
    então um `ctx.elicit()` no meio da requisição levanta o mesmo `NoBackChannelError` e as notificações ligadas à
    requisição são descartadas. O stream independente da sessão fica intacto: notificações não relacionadas
    continuam chegando.

!!! check
    Faça a coisa errada. `reserve` é exatamente a ferramenta que acabou de atender os dois clientes. Faça o deploy dela com
    `stateless_http=True`, conecte os mesmos dois clientes via HTTP e chame-a de cada um.

    O cliente moderno ainda recebe `Reserved 2 of 'Dune'.` A perna moderna não mudou.

    A chamada do cliente legado não volta como um resultado `is_error` que o modelo poderia ler.
    A requisição inteira falha, como um erro de protocolo de nível superior:

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` não salvou você. Em uma conexão `2025-11-25` ele *tem* que enviar `elicitation/create`,
    e o canal de que precisa é exatamente o que `stateless_http=True` abriu mão. Código
    portável entre eras não é código sem canal de retorno (back-channel).

Então é uma troca real, e ela só existe na perna legada: **com sessão e sticky, ou sem estado e unidirecional.** Se suas ferramentas nunca chamam o cliente de volta, `stateless_http=True` é grátis e você deve usá-lo. Se chamam, mantenha as sessões e mantenha o roteamento sticky.

## Onde seu código realmente se bifurca {#where-your-code-actually-forks}

Quase em lugar nenhum.

Ferramentas, recursos, prompts, saída estruturada, progresso, erros: nenhum deles se importa com qual era chamou. O handshake `initialize`, o `Mcp-Session-Id`, o stream independente, o `DELETE` que encerra uma sessão: o SDK cuida de tudo isso, e um handler nunca vê nada disso. Entrada interativa é *o* lugar em que as eras genuinamente diferem no fio, e `Resolve` existe para que isso não seja problema seu: você acabou de ver uma ferramenta atender as duas.

Sobra exatamente uma coisa, e são as **notificações de mudança**, porque as duas eras escutam em canais diferentes:

* Um cliente `2026-07-28` abre um stream `subscriptions/listen` e lê o barramento de assinaturas. `ctx.notify_resource_updated()` (e `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`) publicam ali, e *somente* ali. **[Assinaturas](../handlers/subscriptions.md)** é essa página.
* Um cliente legado lê o stream independente que sua sessão mantém aberto. `ctx.session.send_resource_updated()` (e `send_tool_list_changed()` e companhia) escrevem na *conexão* que carregou a requisição: para uma sessão legada, esse é o stream independente dela. Uma conexão moderna não tem lugar para isso: via HTTP não existe tal canal, e via stdio os quatro tipos de notificação de mudança trafegam apenas em streams `subscriptions/listen`, então em uma conexão moderna a notificação é descartada silenciosamente.

Via HTTP, nenhuma das duas chamadas alcança os clientes da outra era. Para avisar todo mundo, chame as duas:

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

Duas linhas, nenhum `if`, nenhuma verificação de versão, e pronto. Essa é a lista inteira de coisas que um handler faz diferente porque um cliente legado existe.

## Recapitulando {#recap}

* Um único `streamable_http_app()` atende as duas eras de protocolo. O SDK roteia cada requisição pelo header `MCP-Protocol-Version`; não há nada para configurar nem chave de era para procurar.
* Um cliente legado custa uma sessão: um registro `Mcp-Session-Id` dentro do processo, sem armazenamento distribuído por trás. Mais de um worker significa **roteamento sticky**, ou o worker errado responde `404 Session not found`. **[Deploy e escala](deploy.md)** tem a história completa de múltiplos workers.
* `stateless_http=True` é a única chave, e ela vale **apenas para a perna legada**. Ela compra balanceamento de carga livre para clientes legados ao preço dos dois canais servidor-para-cliente nessa perna: requisições iniciadas pelo servidor levantam `NoBackChannelError` (um erro de nível superior no cliente, não um resultado `is_error`), e as notificações são descartadas.
* Uma conexão `2026-07-28` é sem sessão de qualquer forma. `stateless_http` nunca a afeta.
* O código do seu handler se bifurca por era em exatamente um lugar: notificações de mudança. `ctx.notify_*` alcança clientes `subscriptions/listen`; `ctx.session.send_*` alcança sessões legadas. Chame os dois.
* Todo o resto (incluindo pedir entrada ao usuário, via `Resolve`) é portável entre eras por construção. Escreva a versão moderna uma vez só.
