---
translation:
  sections: [20541a40dbdd5980, 01262a123ad9501d, 429db5b574a2ac08, 56b2d49da412cb28, 6a1717123fe4513c]
  tool: 1
---
# Funcionalidades descontinuadas {#deprecated-features}

A especificação 2026-07-28 aposenta cinco coisas. O SDK ainda implementa cada uma delas, e cada uma agora carrega um **aviso de descontinuação**.

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
    chamada `old_log` que ainda chama `ctx.info()` para de passar e começa a reportar:

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Uma linha de configuração do pytest, e uma chamada descontinuada nunca mais consegue
    voltar sorrateiramente ao seu código sem quebrar um teste.

## Recapitulando {#recap}

* A especificação 2026-07-28 descontinua **roots**, a **amostragem** iniciada pelo servidor e o **logging** de protocolo (todos pela [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), restringe o **progresso** ao sentido servidor para cliente e remove o **`ping`**.
* A coluna de substitutos indica o próximo passo: **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)** para amostragem e roots, **[Logging](handlers/logging.md)** para logging, **[Progresso](handlers/progress.md)** para progresso. `ping` não precisa de nada.
* Descontinuado é consultivo: sem mudanças no protocolo de transmissão, tudo continua funcionando em sessões pré-2026, e você recebe um `MCPDeprecationWarning` visível (um `UserWarning`, então está ligado por padrão).
* Amostragem e roots precisam, além disso, de um canal de retorno (back-channel) que uma sessão 2026-07-28 não tem. Em uma conexão moderna elas avisam e depois lançam uma exceção.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` silencia a categoria inteira; `"error::mcp.MCPDeprecationWarning"` no pytest a transforma em falha de teste.
* Código novo não deve ser construído sobre nenhuma delas.

Todas as outras páginas desta documentação ensinam a API atual.
