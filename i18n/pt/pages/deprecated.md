---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# Funcionalidades descontinuadas {#deprecated-features}

A especificação 2026-07-28 aposenta cinco coisas. O SDK ainda implementa cada uma delas, e cada uma agora carrega um **aviso de descontinuação**. Um helper do SDK está descontinuado por conta própria e aparece listado [no final](#deprecated-sdk-helpers).

A tabela abaixo nomeia cada funcionalidade descontinuada, o motivo de ela estar saindo e o substituto sobre o qual construir.

## O que está descontinuado {#what-is-deprecated}

| Descontinuado | Por quê | O que fazer no lugar |
|---|---|---|
| **Roots**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, o `list_roots_callback=` que você passa para `Client(...)` | A [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) aposenta a capacidade. | Receba os caminhos como argumentos comuns de ferramenta ou URIs de recurso, ou embuta um `ListRootsRequest` em um `InputRequiredResult` (veja **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)**). |
| **Amostragem (sampling) iniciada pelo servidor**: `ctx.session.create_message()`, o `sampling_callback=` que você passa para `Client(...)` | A SEP-2577 aposenta a capacidade. | Retorne `InputRequiredResult` e deixe o cliente repetir a chamada (veja **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)**). |
| **Logging de protocolo**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | A SEP-2577 aposenta a capacidade. Nada dentro do protocolo a substitui. | O `import logging` comum para stderr (veja **[Logging](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | **Removido** do protocolo, não apenas descontinuado. Não existe método `ping` em 2026-07-28. | Nada. Só funciona em uma conexão `mode="legacy"`. |
| **Progresso cliente->servidor**: `client.send_progress_notification()` | A 2026-07-28 torna o progresso exclusivamente servidor->cliente. | Nada a enviar. O seu *servidor* informa progresso com `ctx.report_progress()` (veja **[Progresso](handlers/progress.md)**). |

Três coisas saem dessa tabela:

* Roots, amostragem e logging andam juntos. Uma única proposta, a **SEP-2577**, descontinua as três capacidades de uma vez.
* Amostragem e roots compartilham um problema mais profundo: são pontos em que um **servidor** envia uma **requisição** ao **cliente**. Essa direção inteira é o que a 2026-07-28 substitui por **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)**. O que desaparece são os métodos RPC independentes (`sampling/createMessage`, `roots/list` e o `elicitation/create` no estilo push); os tipos de payload `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` sobrevivem, embutidos em `InputRequiredResult.input_requests`, e no cliente chegam aos mesmos callbacks.
* `ping` é o diferente do grupo. O protocolo não o descontinua, ele o remove. O método do SDK ainda emite o aviso (a mensagem diz *removed*, não *deprecated*) e chamá-lo em uma conexão moderna responde com *"Method not found"*.

## Descontinuado é consultivo {#deprecated-is-advisory}

Nada quebra hoje.

Cada método acima continua funcionando em qualquer sessão que tenha negociado **2025-11-25 ou anterior**. Fixe `mode="legacy"` no cliente e você obtém exatamente o comportamento pré-2026. Não há mudanças no protocolo de transmissão e a negociação de capacidades segue igual.

O que muda é que você recebe um aviso visível na primeira vez que cada um é executado:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` é subclasse de `UserWarning`, **não** de `DeprecationWarning`. Isso é proposital: o filtro padrão do Python só mostra `DeprecationWarning` em código executado diretamente como `__main__`, e é assim que bibliotecas descontinuam coisas sem ninguém perceber por dois anos. Este aparece em todo lugar, sem nenhuma flag `-W`.

!!! warning
    "Consultivo" termina no nível do protocolo de transmissão. Amostragem e roots são
    *requisições* do servidor para o cliente, e uma sessão 2026-07-28 não tem canal para
    carregar uma. Chame `ctx.session.create_message()` dentro de uma ferramenta em uma
    conexão moderna e o aviso ainda dispara, e então o envio falha com um erro:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Dois sinais, nessa ordem. O `MCPDeprecationWarning` dispara no momento em que você
    chama o método, em qualquer conexão. O erro é o que volta quando o SDK tenta enviar
    em seguida. Esses dois só funcionam de ponta a ponta em uma conexão `mode="legacy"`
    cujo cliente registrou o callback correspondente.

## `ping` em uma sessão legacy {#ping-on-a-legacy-session}

Um **ping** é uma requisição vazia que qualquer um dos lados pode enviar para conferir se o outro ainda está respondendo. A especificação 2026-07-28 o remove ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): toda requisição que um cliente moderno envia já prova que o servidor está lá, e um servidor moderno não tem canal para enviar um. Os dois métodos do SDK ainda funcionam em uma sessão da era do handshake. Do cliente:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

E do servidor, dentro de qualquer handler:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` avisa com `MCPDeprecationWarning` a cada chamada. Em uma conexão padrão (`2026-07-28`), o servidor responde `MCPError: Method not found` em vez disso.
* `ctx.session.send_ping()` não carrega aviso nenhum. Em uma conexão moderna, lança o mesmo erro de ausência de canal de retorno (back-channel) que qualquer outra requisição iniciada pelo servidor.
* Nenhum dos lados registra nada para responder a um ping.

## Notificações de mudança de roots {#roots-change-notifications}

Um cliente da era 2025 que declarou a capacidade roots pode contar ao servidor que as pastas do seu workspace mudaram enviando `notifications/roots/list_changed`; o servidor responde requisitando `roots/list` de novo. A especificação 2026-07-28 remove a notificação junto com o resto do fluxo de roots no estilo push. No cliente, passar `list_roots_callback=` (**[Callbacks do cliente](client/callbacks.md)**) é o que declara `"roots": {"listChanged": true}`, e uma chamada cumpre essa promessa:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

No servidor, é o `Server` de baixo nível que aceita o handler do lado receptor:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` é a lista que o seu `list_roots_callback` retorna. `client.send_roots_list_changed()` avisa, e precisa de um cliente `mode="legacy"`: em uma conexão moderna a notificação é descartada silenciosamente. Mantenha a sessão aberta depois, porque o `roots/list` de acompanhamento do servidor chega por ela.
* `MCPServer` não tem hook para a notificação. No `Server` de baixo nível, `on_roots_list_changed=` registra o handler (descontinuado também, e avisa na construção). A notificação não carrega payload, então o handler chama `ctx.session.list_roots()` para obter a nova lista.

## Silenciando o aviso {#silencing-the-warning}

Não faça isso, em código novo.

Mas um servidor que você mantém e que de fato atende clientes pré-2026 tem todo o direito a um log silencioso. Filtre a categoria antes que a primeira chamada descontinuada seja executada:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

A API inteira é essa. Não há uma chave por método, e você não quer uma: o sentido de ter uma única categoria é que uma linha a silencia e uma linha a traz de volta.

!!! check
    Aplique o filtro no sentido contrário e você ganha um teste de regressão de graça.
    Adicione `"error::mcp.MCPDeprecationWarning"` à configuração `filterwarnings` do seu
    pytest e a chamada descontinuada **lança uma exceção** em vez de avisar. Uma ferramenta
    chamada `old_log` que ainda chama `ctx.info()` para de passar: a chamada volta com
    `is_error=True` e `Error executing tool old_log`, e o log capturado do servidor aponta o
    culpado:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Uma linha de configuração do pytest, e uma chamada descontinuada nunca mais consegue
    voltar sorrateiramente ao seu código sem quebrar um teste.

## Helpers descontinuados do SDK {#deprecated-sdk-helpers}

Estas não são mudanças de especificação, apenas detalhes internos do SDK com um substituto melhor. Avisam com o mesmo `MCPDeprecationWarning` e serão removidos na 3.0.

| Descontinuado | O que fazer no lugar |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` e depois `FuncMetadata.call_fn()`. Só código que conduz `FuncMetadata` diretamente (uma subclasse personalizada de `Tool`, digamos) chegou a chamá-lo. |

## Recapitulando {#recap}

* A especificação 2026-07-28 descontinua **roots**, a **amostragem** iniciada pelo servidor e o **logging** de protocolo (todos pela [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), restringe o **progresso** ao sentido servidor para cliente e remove o **`ping`**.
* A coluna de substitutos indica o próximo passo: **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)** para amostragem e roots, **[Logging](handlers/logging.md)** para logging, **[Progresso](handlers/progress.md)** para progresso. `ping` não precisa de nada.
* Descontinuado é consultivo: sem mudanças no protocolo de transmissão, tudo continua funcionando em sessões pré-2026, e você recebe um `MCPDeprecationWarning` visível (um `UserWarning`, então está ligado por padrão).
* Amostragem e roots precisam, além disso, de um canal de retorno que uma sessão 2026-07-28 não tem. Em uma conexão moderna elas avisam e depois lançam uma exceção.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` silencia a categoria inteira; `"error::mcp.MCPDeprecationWarning"` no pytest a transforma em falha de teste.
* Um helper do SDK, `FuncMetadata.call_fn_with_arg_validation()`, está descontinuado separadamente para remoção na 3.0.
* Código novo não deve ser construído sobre nenhuma delas.

Todas as outras páginas desta documentação ensinam a API atual.
