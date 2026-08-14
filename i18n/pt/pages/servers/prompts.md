---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
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
    Se você leu **[Ferramentas](tools.md)**, já sabe tudo o que está nesta página. O mesmo decorador, a mesma
    docstring como descrição, o mesmo `Annotated`/`Field`. As únicas coisas que mudam são quem
    dispara (o usuário) e para onde vai o resultado (para a conversa).

## Recapitulando {#recap}

* `@mcp.prompt()` em uma função faz dela um prompt. O nome vem da função, a descrição vem da docstring.
* Prompts são **controlados pelo usuário**: o cliente os lista, o usuário escolhe um e preenche os argumentos.
* Os argumentos são uma lista plana de strings nomeadas (sem schema). Um parâmetro com valor padrão é opcional.
* Retorne uma `str` e ela vira uma mensagem de usuário. Retorne uma lista de `UserMessage` / `AssistantMessage` para iniciar uma conversa de vários turnos.
* `title=` e `Field(description=...)` são o que um cliente coloca na interface dele.
* Um argumento obrigatório ausente faz a requisição inteira falhar. Não existe um resultado de erro por prompt.

O autocomplete do lado do servidor para os argumentos de um prompt (ou de um template de recurso) é assunto de **[Completions](completions.md)**.
