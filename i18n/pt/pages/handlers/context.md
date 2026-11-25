---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# O Context {#the-context}

Os argumentos de uma ferramenta (tool) vêm do modelo. Todo o resto (a requisição que você está atendendo, o servidor em que você vive, um jeito de falar de volta com o cliente) vem de um único objeto: o **`Context`**.

Você não o constrói nem o configura. Você pede por ele.

## Peça por ele {#ask-for-it}

Adicione a qualquer ferramenta um parâmetro anotado com `Context`:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* O SDK constrói um `Context` novo para cada requisição e o passa para a função.
* O **nome do parâmetro não importa**. `ctx`, `context`, `c`: o SDK o encontra pela anotação.
* Recursos e prompts também podem declarar um, do mesmo jeito.
* `ctx.request_id` é o id da requisição que sua função está atendendo neste momento.

!!! info
    Se você já usou FastAPI, já conhece essa jogada: declare um parâmetro com o tipo do próprio
    framework (`Request` lá, `Context` aqui) e o framework o fornece. Nada para registrar, nada para
    configurar: a anotação de tipo é o mecanismo inteiro.

### Invisível para o modelo {#invisible-to-the-model}

Esta é a parte para internalizar. Aqui está o schema de entrada que `tools/list` informa para `search_books`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Uma única propriedade. `ctx` não é um argumento: ele nunca aparece no schema, o modelo nunca fica sabendo dele e nenhum cliente consegue preenchê-lo. É um contrato entre você e o SDK, invisível no protocolo.

### Experimente {#try-it}

Execute o servidor com o MCP Inspector:

```console
uv run mcp dev server.py
```

O formulário de `search_books` tem um único campo, `query`. Chame-a com `dune`:

```text
[request 3] Found 3 books matching 'dune'.
```

O número é o da requisição da vez. Chame a ferramenta de novo e ele muda: cada requisição recebe seu próprio `Context`.

## O que ele oferece {#what-it-gives-you}

O objeto injetado é pequeno. Além de `request_id`:

* `await ctx.read_resource(uri)`: lê um dos recursos do **próprio** servidor, de dentro de uma ferramenta. É a próxima seção.
* `await ctx.report_progress(progress, total, message)`: envia o progresso de volta a quem chamou, durante uma chamada demorada. **[Progresso](progress.md)** tem a história completa.
* `await ctx.elicit(message, schema)` e `await ctx.elicit_url(...)`: pausam a ferramenta e fazem uma pergunta ao usuário. Isso é **[Elicitação](elicitation.md)** (elicitation).
* `ctx.session`: o lado do servidor na conversa com este cliente. As notificações que você envia ao cliente ficam aqui; a última seção usa isso.
* `ctx.headers`: os cabeçalhos da requisição que o transporte carregou, ou `None` no stdio. Leia um cabeçalho customizado com `(ctx.headers or {}).get("x-...")`. Cabeçalhos são entrada fornecida pelo cliente - servem para um locale ou uma feature flag, nunca para uma identidade.
* `ctx.request_context`: o registro bruto de cada requisição. O campo que você vai querer é `lifespan_context`, o objeto que seu código de inicialização entregou no yield (veja **[Lifespan](lifespan.md)**).

Logging está fora dessa lista de propósito. Um servidor registra logs com o módulo `logging` do Python, como qualquer outro programa Python. **[Logging](logging.md)** é a página curta que explica o porquê.

!!! tip
    A injeção só acontece na função que você registrou. Uma função auxiliar que sua ferramenta chama
    não recebe um `Context` próprio; passe `ctx` adiante como um argumento comum. Não existe um
    "contexto atual" implícito para buscar de algum outro lugar.

## Leia seus próprios recursos {#read-your-own-resources}

Os recursos de um servidor não são só para os clientes. Uma ferramenta também pode lê-los:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` resolve a URI pelo mesmo registro que atende `resources/read`, então uma ferramenta recebe o que um cliente receberia: um iterável de `ReadResourceContents`, um por bloco de conteúdo. Para esta URI existe um só:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` é exatamente o que `genres()` retornou. Uma única fonte da verdade: o cliente navega pelo recurso, suas ferramentas o consomem, ninguém copia a string.
* O único parâmetro de `describe_catalog` é o `Context`, então seu schema de entrada **não tem nenhuma propriedade**. O modelo a chama com `{}`.

## Avise o cliente de que a lista mudou {#tell-the-client-the-list-changed}

O que um servidor oferece não é fixo no momento do import. Registre uma ferramenta em tempo de execução e depois avise o cliente:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` registra uma função comum como ferramenta: nome, descrição e schema derivados exatamente como `@mcp.tool()` faria.
* `await ctx.session.send_tool_list_changed()` envia `notifications/tools/list_changed`. Um cliente que a recebe chama `tools/list` de novo e vê `recommend_book`.

Os irmãos são `send_resource_list_changed()`, `send_prompt_list_changed()` e `send_resource_updated(uri)`, este último para uma mudança em um recurso específico.

Em uma conexão 2026-07-28, os clientes só recebem notificações de mudança em um stream `subscriptions/listen` que eles mesmos abriram, então os métodos `send_*` acima não alcançam esses streams. Os métodos de publicação do `Context` entregam a todos os streams assinantes de uma vez só: `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()` e `await ctx.notify_resource_updated(uri)`. **[Assinaturas](subscriptions.md)** tem a história completa, incluindo como escalar horizontalmente entre réplicas.

!!! check
    Antes de alguém executar `enable_recommendations`, a ferramenta que você está prometendo não
    existe. Chame-a mesmo assim e o resultado é um erro que o modelo consegue ler:

    ```text
    Unknown tool: recommend_book
    ```

    Execute `enable_recommendations` e a mesmíssima chamada dá certo. A lista de ferramentas é
    dinâmica de verdade: `tools/list` reflete o que quer que esteja registrado *neste exato momento*.

## Recapitulando {#recap}

* Anote um parâmetro com `Context` (em uma ferramenta, um recurso ou um prompt) e o SDK o injeta. O nome fica por sua conta.
* Ele é invisível para o modelo: o schema de entrada sempre contém apenas seus argumentos de verdade.
* `ctx.request_id` identifica a requisição; `ctx.request_context.lifespan_context` é o que sua inicialização entregou no yield.
* `await ctx.read_resource(uri)` permite que uma ferramenta leia os recursos do próprio servidor.
* `ctx.session` é o canal de volta para o cliente: `send_tool_list_changed()` e seus irmãos dizem a ele para buscar de novo uma lista que você mudou.
* Relatar progresso e a elicitação também começam no `Context`; cada um tem sua própria página.

Parâmetros que o modelo nunca vê, preenchidos pelas suas próprias funções, são as **[Dependências](dependencies.md)**.
