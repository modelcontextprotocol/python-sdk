---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# Prompts {#prompts}

Um **prompt** é um template de mensagem que o usuário escolhe.

Ferramentas são para o modelo. Um prompt é o oposto: o usuário escolhe um em um menu do seu cliente (um comando de barra, um botão), preenche os argumentos, e as mensagens renderizadas entram na conversa como se ele mesmo as tivesse digitado.

Para declarar um, coloque `@mcp.prompt()` em uma função que retorna o texto.

## Seu primeiro prompt {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

O SDK lê as mesmas três coisas que lê de uma ferramenta:

* O **nome** é o nome da função: `review_code`.
* A **descrição** que o cliente exibe é a docstring: `Review a piece of code.`
* Os **argumentos** vêm dos parâmetros. `code` não tem valor padrão, então é obrigatório.

É isso que um cliente recebe de volta de `prompts/list`:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Não há JSON Schema aqui. Os argumentos de um prompt são uma lista plana de **strings nomeadas**: um formulário que uma pessoa preenche, não um payload que um modelo constrói.

### Renderizando {#rendering-it}

O cliente renderiza o template com `prompts/get`, passando os argumentos. Sua função executa e a `str` que você retorna vira **uma mensagem de usuário**:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

Essa é a vida inteira de um prompt: listado pelo nome, renderizado sob demanda, colocado no chat.

!!! check
    `required` é verificado antes que sua função execute. Renderize `review_code` sem `code` e a
    própria requisição falha com um erro JSON-RPC (código `-32603`):

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Não há um resultado de erro no estilo das ferramentas para devolver a um modelo, porque não há
    nenhum modelo envolvido: a chamada levanta uma exceção. O motivo (`Missing required arguments: {'code'}`) vai parar no log do seu servidor.

### Experimente {#try-it}

Execute o servidor com o MCP Inspector:

```console
uv run mcp dev server.py
```

Abra a aba **Prompts** e selecione `review_code`. O Inspector desenha um formulário com um único campo obrigatório, `code`. Preencha, renderize e você recebe de volta exatamente a mensagem de usuário acima.

## Mais de uma mensagem {#more-than-one-message}

Uma revisão de código é uma mensagem só. Uma sessão de depuração é uma conversa, e um prompt pode iniciar a coisa toda.

Retorne uma lista de mensagens em vez de uma `str`:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` e `AssistantMessage` vêm de `mcp.server.mcpserver.prompts.base`. Passe uma `str` para elas e elas a embrulham em `TextContent` para você. O papel (role) é o nome da classe.
* `Message` é a base comum delas. Use-a como anotação de retorno.

Renderizar `debug_error` agora produz três mensagens, nesta ordem:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Repare na última. Pré-preencher um turno de `assistant` é como você direciona a *próxima* resposta do modelo sem fazer o usuário digitar esse direcionamento por conta própria.

## Títulos e descrições dos argumentos {#titles-and-argument-descriptions}

`review_code` é um nome de função, não um rótulo. Dê ao cliente algo melhor para colocar no botão e descreva cada argumento para que o formulário se explique sozinho:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` é o nome legível por humanos, exatamente como o `title` de uma ferramenta.
* `Annotated[str, Field(description=...)]` é o mesmo padrão que **[Ferramentas](tools.md)** usa para descrever os parâmetros de uma ferramenta. Aqui a descrição vai parar no argumento, e não em um schema.
* `language` tem um valor padrão, então deixa de ser obrigatório.

A entrada em `prompts/list` agora traz tudo de que um cliente precisa para desenhar um bom formulário:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    Se você leu **[Ferramentas](tools.md)**, já sabe tudo até este ponto. O mesmo decorador, a mesma
    docstring como descrição, o mesmo `Annotated`/`Field`. As únicas coisas que mudam são quem
    dispara (o usuário) e para onde vai o resultado (para a conversa).

## Mais do que texto {#more-than-text}

`UserMessage` e `AssistantMessage` também aceitam um bloco de conteúdo, ou um helper `Image` / `Audio`, onde quer que aceitem uma `str`. Dois casos aparecem em prompts: anexar um documento e anexar uma imagem.

### Incorporando um arquivo {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* O guia de estilo é um recurso em `style://python` (**[Recursos](resources.md)** trata deles), lido de um `style-guide.md` ao lado de `server.py`. Coloque qualquer arquivo Markdown ali.
* `EmbeddedResource(resource=TextResourceContents(...))`, ambos de `mcp.types`, carrega o arquivo com sua URI e seu tipo MIME como a primeira mensagem; a instrução que faz referência a ele vem em seguida, como texto simples.
* Incorporar, em vez de colar o guia na f-string, permite que o cliente o mostre como um anexo e reabra `style://python` depois, e o modelo recebe o arquivo na íntegra. Para um arquivo binário, use `BlobResourceContents` com um `blob` em base64.

Renderizada, o `content` da primeira mensagem é um bloco `resource`:

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### Anexando uma imagem {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` é o helper de **[Imagens, áudio e ícones](media.md)**. `UserMessage` o converte em um bloco `ImageContent` (o arquivo codificado em base64, o tipo MIME deduzido a partir de `.png`) quando o prompt é renderizado; `Audio` vira um `AudioContent` do mesmo jeito.
* Coloque qualquer PNG chamado `architecture.png` ao lado de `server.py`. Os argumentos de prompt são strings, então a imagem sempre vem do servidor; `component` só fornece as palavras.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## Mudando a lista em tempo de execução {#changing-the-list-at-runtime}

Prompts podem ser adicionados enquanto clientes estão conectados, por exemplo para deixar um usuário salvar uma instrução como uma entrada de menu própria. Registre o prompt e depois notifique:

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` registra uma função exatamente como `@mcp.prompt()` faria, e `mcp.remove_prompt(name)` é o inverso. `add_prompt` mantém uma entrada existente com o mesmo nome em vez de sobrescrevê-la, então a ferramenta remove qualquer entrada antiga primeiro para que salvar seja uma substituição. `prompts/list` reflete a mudança imediatamente.
* `await ctx.notify_prompts_changed()` envia `notifications/prompts/list_changed` a todo cliente `2026-07-28` escutando em um stream `subscriptions/listen` (**[Assinaturas](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()` envia ao cliente que fez a chamada quando esse cliente é anterior a 2026 (**[Atendendo clientes legados](../run/legacy-clients.md)**). Chame os dois; cada um não faz nada quando não há ninguém para avisar.
* Um cliente que recebe a notificação chama `prompts/list` de novo. No `Client` Python isso é `async with client.listen(prompts_list_changed=True) as sub:`, que produz um evento `PromptsListChanged`.

## Recapitulando {#recap}

* `@mcp.prompt()` em uma função faz dela um prompt. O nome vem da função, a descrição vem da docstring.
* Prompts são **controlados pelo usuário**: o cliente os lista, o usuário escolhe um e preenche os argumentos.
* Os argumentos são uma lista plana de strings nomeadas (sem schema). Um parâmetro com valor padrão é opcional.
* Retorne uma `str` e ela vira uma mensagem de usuário. Retorne uma lista de `UserMessage` / `AssistantMessage` para iniciar uma conversa de vários turnos.
* `title=` e `Field(description=...)` são o que um cliente coloca na interface dele.
* Um argumento obrigatório ausente faz a requisição inteira falhar. Não existe um resultado de erro por prompt.
* Embrulhe um `EmbeddedResource` ou um `Image` em uma `UserMessage` para anexar um documento ou uma imagem.
* Adicione ou remova prompts em tempo de execução com `mcp.add_prompt(...)` / `mcp.remove_prompt(...)`, e depois `await ctx.notify_prompts_changed()` e `await ctx.session.send_prompt_list_changed()`.

O autocomplete do lado do servidor para os argumentos de um prompt (ou de um template de recurso) é assunto de **[Completions](completions.md)**.
