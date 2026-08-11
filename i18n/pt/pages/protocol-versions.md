---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# Versões do protocolo {#protocol-versions}

O MCP tem duas eras.

Os servidores lançados antes de 2026-07-28 abrem toda conexão com o **handshake `initialize`**: o cliente propõe uma versão, o servidor responde com outra, o cliente confirma, tudo antes da primeira requisição útil. Os servidores em **2026-07-28** abandonam o handshake. O cliente envia uma única sondagem **`server/discover`** e o servidor responde com tudo em um único resultado.

Você quase nunca precisa se preocupar com isso, porque o `Client` negocia por você. Esta página trata do único argumento do construtor que controla isso, `mode=`, e das três situações em que você o altera.

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

Você não passou `mode`, então recebeu o padrão: `"auto"`. Entrar no `async with` envia uma única sondagem `server/discover` na versão mais nova que este SDK fala. Depois:

* Um **servidor moderno** responde. O cliente adota o resultado. Uma ida e volta, pronto.
* Um **servidor mais antigo** nunca ouviu falar de `server/discover` e retorna um erro. O cliente recorre ao handshake clássico `initialize` e fica com o que ele negociar.

De um jeito ou de outro você sai conectado, e `client.protocol_version` diz qual foi o caso:

```text
2026-07-28
```

A funcionalidade inteira é essa. Um `Client`, qualquer era de servidor, sem ramificações no seu código.

!!! info
    O `MCPServer` responde a `server/discover` em todos os transportes — em memória, stdio, streamable
    HTTP — então, contra o seu próprio servidor, `auto` sempre chega em `2026-07-28`. O fallback só
    dispara contra um servidor real anterior a 2026, que é exatamente quando você quer que ele dispare.

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` nunca sonda. Ele executa o handshake `initialize`, a mesma conexão que um cliente anterior a 2026 abre.

```text
2025-11-25
```

Mesmo servidor. Ele fala `2026-07-28` perfeitamente bem; você disse ao cliente para não perguntar.

Você quer isso para as funcionalidades no estilo **push**.

Uma requisição iniciada pelo servidor é o servidor chamando *você*: `ctx.elicit(...)` colocando um formulário na frente do seu usuário, a amostragem (sampling) pedindo uma completion ao seu modelo no meio de uma chamada de ferramenta. Esse canal só existe em uma sessão da era do handshake.

Em 2026-07-28 ele não existe mais. O servidor *retorna* suas perguntas e você repete a chamada com as respostas (**[Requisições com várias idas e voltas](handlers/multi-round-trip.md)**).

`mode="auto"` só dá um handshake a você quando o servidor é antigo demais para qualquer outra coisa. `mode="legacy"` garante um. Recorra a ele sempre que passar ao `Client(...)` um `sampling_callback`, um `elicitation_callback` que você quer acionado como requisição, ou um `message_handler`. **[Callbacks do cliente](client/callbacks.md)** passa por cada um deles.

## Fixando uma versão {#pinning-a-version}

`mode` também aceita uma string de versão moderna do protocolo. Hoje esse conjunto é exatamente `["2026-07-28"]`.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

Uma versão fixada não envia **nada**. Sem sondagem, sem handshake. O cliente adota `2026-07-28` localmente e a conexão está ativa no instante em que `async with` retorna.

Fixar uma versão é uma promessa que *você* faz: você já sabe que o servidor fala aquela versão. O cliente não verifica.

!!! check
    Fixar uma versão não é uma descoberta. Imprima `client.server_info` e o preço está bem ali:

    ```text
    None
    ```

    O cliente nunca perguntou ao servidor quem ele é, então `server_info` é `None`. Com `client.server_capabilities`
    é a mesma história: toda capacidade é `None`. As chamadas de ferramenta continuam funcionando (o protocolo não precisa de nada disso);
    o código que lê `server_capabilities` para decidir o que oferecer, não.

    A próxima seção é a correção.

Só as versões modernas podem ser fixadas. Uma string da era do handshake é rejeitada na construção, antes de qualquer I/O, e o erro diz o que escrever no lugar:

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## Reconectando com `prior_discover` {#reconnecting-with-prior_discover}

A sondagem é barata, mas ainda é uma ida e volta que você paga a cada reconexão, e a resposta quase nunca muda.

Então guarde-a. Depois de uma conexão `auto`, `client.session.discover_result` contém o `DiscoverResult` exato que o servidor enviou: seu `supported_versions`, seu `capabilities`, seu `instructions` e a identidade que o servidor carimbou no `_meta` do resultado. Passe-o de volta como `prior_discover=` na próxima vez:

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

A segunda conexão fez **zero** idas e voltas de negociação e ainda sabe exatamente com quem está falando. Esse é o modo fixado feito direito: `mode=` nomeia a versão, `prior_discover=` fornece a identidade. ✨

`DiscoverResult` é um modelo Pydantic. `saved.model_dump_json()` vai para um arquivo ou um cache; `DiscoverResult.model_validate_json(...)` o traz de volta no próximo processo.

!!! tip
    `prior_discover=` só faz alguma coisa quando `mode` é uma versão fixada. Com `"auto"` o cliente
    sonda o servidor de qualquer forma, e com `"legacy"` ele é ignorado.

## Os quatro modos {#the-four-modes}

| Você escreve | Tráfego de negociação | Você recebe |
| --- | --- | --- |
| `Client(target)` | uma sondagem `server/discover`; o handshake `initialize` se ela falhar | a versão mais nova que os dois lados falam, de qualquer era |
| `Client(target, mode="legacy")` | o handshake `initialize` | uma versão da era do handshake; requisições iniciadas pelo servidor funcionam |
| `Client(target, mode="2026-07-28")` | nenhum | aquela versão, fixada, com `server_info` como `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | nenhum | aquela versão, fixada, *e* a identidade que você salvou da última vez |

## Recapitulando {#recap}

* O MCP tem uma era do handshake (até `2025-11-25`, o handshake `initialize`) e uma era moderna (`2026-07-28`, `server/discover`). O `Client` faz a ponte entre elas.
* `mode="auto"` é o padrão: sondar, recorrer ao fallback. Deixe como está, a menos que uma das outras três linhas descreva o seu caso.
* `client.protocol_version` é sempre a resposta para "o que eu recebi?".
* `mode="legacy"` força o handshake. É disso que você precisa para requisições iniciadas pelo servidor: amostragem, elicitação (elicitation) via push, `message_handler`.
* Uma versão fixada (`mode="2026-07-28"`) não envia nenhum tráfego de negociação, ao custo de `client.server_info` ser `None`.
* `prior_discover=` paga esse custo de volta: salve `client.session.discover_result`, reconecte com ele, fique com os dois.

Uma conexão moderna não tem canal de push, então como um servidor de 2026 faz uma pergunta a você no meio de uma chamada? Ele a retorna: **[Requisições com várias idas e voltas](handlers/multi-round-trip.md)**.
