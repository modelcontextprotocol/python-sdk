---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# Grupos de sessões {#session-groups}

Um `Client` se conecta a um servidor. Aplicações reais frequentemente querem vários (um servidor de busca, um servidor de banco de dados, uma API interna) e acabam fazendo malabarismo com uma conexão e uma lista de ferramentas (tools) para cada um.

**`ClientSessionGroup`** é um único objeto que mantém várias conexões e reúne tudo o que elas expõem em uma única visão.

## Dois servidores {#two-servers}

Comece com dois servidores comuns. Eles não têm nada a ver um com o outro, então ambos naturalmente chamaram sua ferramenta de `search`:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## Um grupo {#one-group}

Crie um `ClientSessionGroup` e chame **`connect_to_server`** uma vez por servidor:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` recebe parâmetros de transporte, não um objeto de servidor: `StdioServerParameters` (de `mcp`) para iniciar um subprocesso, ou `StreamableHttpParameters` / `SseServerParameters` (de `mcp.client.session_group`) para um servidor que já está escutando em uma URL.
* `group.tools` é um `dict[str, Tool]` com as ferramentas de todos os servidores conectados. `group.resources` e `group.prompts` têm o mesmo formato.
* `group.call_tool(name, arguments)` procura o nome, encontra a sessão dona dele e encaminha a chamada. Você nunca diz qual servidor.

!!! check
    Coloque `client.py` ao lado dos dois servidores e execute. O segundo `connect_to_server` recusa:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    Isso é um `MCPError`, lançado antes que qualquer coisa do segundo servidor seja registrada. Um nome precisa
    ser único no grupo **inteiro**, e dois servidores que você não controla vão colidir mais cedo ou mais tarde.

## `component_name_hook` {#component_name_hook}

Você resolve isso no grupo, não nos servidores. Passe uma função de `(name, server_info)` e o grupo a executa em cada nome que registra:

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

Execute de novo. `print(sorted(group.tools))` agora mostra as duas:

```text
['Library.search', 'Web.search']
```

* A **chave** é sua. `by_server` a montou a partir de `server_info.name`, o nome com que cada `MCPServer(...)` foi construído.
* O `Tool` dentro fica intacto: `group.tools["Web.search"].name` ainda é `"search"`, e esse é o nome que `call_tool` coloca na rede. O prefixo nunca sai do seu processo.
* Não são só ferramentas. O recurso `hours` da biblioteca é registrado como `Library.hours`.

!!! tip
    O hook é executado em **cada** nome de **cada** servidor, não só nos conflitos: não existe um
    modo de prefixar apenas em caso de colisão. Escolha um esquema e deixe que ele valha em todo lugar.

## Adicionando e removendo servidores {#adding-and-removing-servers}

`connect_to_server` retorna a `ClientSession` que abriu. Guarde-a se algum dia quiser tirar aquele servidor: `await group.disconnect_from_server(session)` remove do grupo as ferramentas, recursos e prompts dele.

Se você já tem em mãos uma `ClientSession` conectada (`Client.session` é uma), entregue-a a `await group.connect_with_session(server_info, session)` em vez de abrir um novo transporte. Ela é agregada da mesma forma. O grupo nunca fecha uma sessão que não abriu. `server_info` nomeia o servidor para os prefixos dos componentes; em uma conexão da era 2026, `client.server_info` pode ser `None` (a identidade é opcional), então nesse caso passe sua própria `Implementation(name=..., version=...)`.

## O handshake clássico {#the-classic-handshake}

`ClientSessionGroup` é construído sobre `ClientSession`, não sobre `Client`. Cada `connect_to_server` executa o handshake clássico `initialize`. Ele nunca envia a sondagem `server/discover` descrita em **[Versões do protocolo](../protocol-versions.md)**. Todo servidor MCP entende esse handshake, então isso não custa compatibilidade com nada; significa apenas que um grupo segue o caminho mais antigo e mais lento até um servidor que poderia fazer melhor.

## Recapitulando {#recap}

* `ClientSessionGroup` mantém várias conexões de servidor e reúne as ferramentas, recursos e prompts delas em um `dict` para cada tipo.
* `connect_to_server(params)` por servidor. Ele recebe parâmetros de transporte, nunca o objeto de servidor ou a URL que um `Client` recebe.
* `group.call_tool(name, arguments)` roteia para o servidor dono por você.
* Os nomes precisam ser únicos no grupo inteiro; dois servidores com uma ferramenta `search` não conseguem coexistir por conta própria.
* `component_name_hook=` reescreve cada nome registrado. A chave do dict muda, o nome na rede não.
* `connect_with_session` adiciona uma sessão que você já tem; `disconnect_from_server` remove uma.

O handshake que um grupo fala (e o mais rápido que um `Client` prefere) é o assunto de **[Versões do protocolo](../protocol-versions.md)**.
