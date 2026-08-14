---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# O cliente {#the-client}

Um **`Client`** é como um programa Python conversa com um servidor MCP.

É um objeto com um ciclo de vida: construa, entre no `async with`, chame os métodos. Cada verbo do protocolo (listar as ferramentas, chamar uma, ler um recurso, renderizar um prompt) é um método `async` nele que retorna um resultado tipado.

## Seu primeiro cliente {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

O servidor no topo só está ali para você ter algo a que se conectar. O cliente são as cinco linhas destacadas.

* `Client(mcp)` recebe o **próprio objeto servidor**. Esse é o transporte em memória: sem subprocesso, sem porta, sem HTTP. É assim que todo exemplo nesta página, e todo teste que você escrever, se conecta.
* `async with` é o **ciclo de vida**. Entrar nele conecta e negocia; sair dele desconecta. Não há um par `connect()` / `close()`, e um `Client` não pode ser reutilizado depois que o bloco termina.
* Dentro do bloco, os fatos da conexão já estão ali como propriedades comuns.

### O que você pode passar para `Client` {#what-you-can-pass-to-client}

`Client` recebe um argumento posicional e resolve o transporte a partir do tipo dele:

* Uma instância de `MCPServer` (ou do `Server` de baixo nível): conectada **no mesmo processo**.
* Uma string de URL (`Client("http://localhost:8000/mcp")`): Streamable HTTP, o caminho de produção.
* Um **transporte**: qualquer coisa com que você possa fazer `async with ... as (read, write)`, como `stdio_client(...)` encapsulando um subprocesso.

Todo o resto desta página é idêntico entre os três. Cabeçalhos, subprocessos, timeouts e o protocolo `Transport` têm sua própria página: **[Transportes do cliente](transports.md)**.

### O que há em um cliente conectado {#whats-on-a-connected-client}

Quatro propriedades somente leitura, preenchidas no instante em que você entra no bloco:

* `client.server_info`: a identidade do servidor, ou `None` para um servidor da era 2026 que não informa uma (servidores do python-sdk informam por padrão). `server_info.name` aqui é `"Bookshop"`, `server_info.version` é o que o servidor informar.
* `client.server_capabilities`: o que o servidor sabe fazer (`tools`, `resources`, `prompts`, `completions`, ...). Uma capacidade que o servidor não tem é `None`.
* `client.protocol_version`: a versão do protocolo em que os dois lados concordaram. Aqui é `"2026-07-28"`.
* `client.instructions`: a string `instructions=` do servidor, ou `None` se ele não definiu uma.

Você nunca escolheu uma versão do protocolo. Por padrão, o `Client` sonda o servidor e recorre ao handshake clássico nos mais antigos, então um único cliente funciona contra servidores de qualquer era. Quando você precisar controlar isso, **[Versões do protocolo](../protocol-versions.md)** tem a história completa.

!!! tip
    `client.session` é a `ClientSession` subjacente, a saída de emergência de baixo nível.
    Você não vai precisar dela para nada nesta página.

## Listando ferramentas {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` retorna um `ListToolsResult`; as ferramentas estão em `.tools`. Cada uma é a definição completa que um host entregaria a um modelo:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

e `tool.input_schema` é o JSON Schema que o servidor derivou das anotações de tipo da função:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Esse schema é tudo o que uma UI precisa para renderizar um formulário de argumentos, e tudo o que um modelo precisa para produzir argumentos válidos.

!!! tip
    `title` é opcional, então uma UI que mostra ferramentas a um humano tem que escolher: o `title` se houver um,
    o `name` se não. `from mcp.shared.metadata_utils import get_display_name` faz exatamente isso,
    para ferramentas, recursos, templates de recurso e prompts.

## Chamando uma ferramenta {#calling-a-tool}

`call_tool(name, arguments)` executa a ferramenta e devolve um `CallToolResult`.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

O `lookup_book` do servidor retorna um `Book` do Pydantic. Eis o que o cliente vê:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Um valor de retorno, três coisas para ler. Cada uma tem um consumidor diferente.

### `content`: o que o modelo lê {#content-what-the-model-reads}

`content` é uma `list` de **blocos de conteúdo**, e um bloco de conteúdo é uma união: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` ou `EmbeddedResource`. Uma ferramenta pode retornar vários, de tipos diferentes.

É por isso que `main` faz o narrowing com `isinstance(block, TextContent)` antes de tocar em `block.text`. Repare que não há `.text` fora do `isinstance`: o verificador de tipos não permite, porque `ImageContent` tem `.data`, não `.text`. A união é honesta sobre o que uma ferramenta pode enviar a você; seu código também deve ser.

### `structured_content`: o que sua aplicação lê {#structured_content-what-your-application-reads}

`structured_content` é o valor de retorno da ferramenta como JSON, correspondendo ao `output_schema` declarado pela ferramenta. Sem parsing de strings, sem adivinhação.

Quando ambos estão presentes, eles dizem a mesma coisa duas vezes de propósito: `content` é para um modelo, `structured_content` é para código. De onde vem a metade estruturada, e como controlá-la, é a página **[Saída estruturada](../servers/structured-output.md)**.

### `is_error`: se a ferramenta falhou {#is_error-whether-the-tool-failed}

Uma ferramenta que lança uma exceção **não** lança no seu cliente. Ela volta como um resultado comum com `is_error=True`.

!!! check
    Peça `"Solaris"` ao `lookup_book` (um título que não está no catálogo) e a função lança
    `ValueError`. A chamada ainda retorna normalmente:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    A mensagem da exceção foi parar em `content`, onde o **modelo** pode lê-la e tentar de novo. Isso
    é proposital: um erro de ferramenta faz parte da conversa, não é um crash. Sempre olhe `is_error`
    antes de confiar em `structured_content`.

!!! warning
    `is_error=True` cobre mais do que o seu próprio `raise`. Peça uma ferramenta que o servidor nem tem
    (`call_tool("does_not_exist", {})`) e nada lança exceção. Você recebe o mesmo formato de volta,
    `is_error=True` com `Unknown tool: does_not_exist` em `content`. Um método de `Client` lança
    `MCPError` apenas quando o servidor responde com um **erro** JSON-RPC em vez de um resultado, e
    **[Tratando erros](../servers/handling-errors.md)** cobre quando um servidor produz cada um.

## Recursos {#resources}

Os verbos de recurso vêm em pares: duas formas de listar, uma forma de ler.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` retorna os recursos **concretos**, os que têm uma URI fixa. Aqui: `['catalog://genres']`.
* `list_resource_templates()` retorna os **parametrizados**. Aqui: `['catalog://genres/{genre}']`. São duas listas diferentes porque um template não pode ser lido até você preenchê-lo.
* `read_resource(uri)` recebe uma URI `str` comum e funciona com ambos: passe `"catalog://genres/poetry"` e o servidor a casa com o template.

`read_resource` retorna `contents`, uma lista de `TextResourceContents` ou `BlobResourceContents`. Mesma ideia do conteúdo de ferramenta: faça o narrowing com `isinstance`, depois leia `.text` (ou `.blob`).

Um cliente também pode ser avisado quando um recurso muda. Em conexões da era 2025 isso é `subscribe_resource(uri)` / `unsubscribe_resource(uri)` - um par de métodos que o `MCPServer` não implementa, então no protocolo 2026-07-28 (onde esses verbos não existem mais) a requisição responde `-32601`, *Method not found*. O substituto de 2026 é um stream `subscriptions/listen`, que o `MCPServer` *serve* sim - `server_capabilities.resources.subscribe` é `True` ali - e consumi-lo com `client.listen(...)` é a página **[Assinaturas](subscriptions.md)** desta seção.

## Prompts {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` diz o que o servidor oferece e do que cada prompt precisa:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` o renderiza. O dict de argumentos é `str -> str`: argumentos de prompt são sempre strings. O resultado é `messages`, uma lista de `PromptMessage`, cada uma com um `role` e um bloco `content`:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Um host entrega essas mensagens direto ao modelo. A funcionalidade inteira é essa.

## Completions {#completions}

Um servidor com um handler de completion pode autocompletar argumentos de prompts e de templates de recurso enquanto o usuário digita.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` diz *qual* prompt ou template você está preenchendo: uma `PromptReference` ou uma `ResourceTemplateReference`.
* `argument` é `{"name": ..., "value": ...}`: o argumento e o que o usuário digitou até agora.

A resposta está em `result.completion.values`. Digite `"p"` e o servidor volta com `['poetry']`. O lado do servidor, e como um handler usa os *outros* argumentos já preenchidos para refinar as sugestões, é a página **[Completions](../servers/completions.md)**.

## Paginação {#pagination}

Todo método `list_*` aceita um argumento nomeado `cursor=` e todo resultado carrega um `next_cursor`. Quando `next_cursor` é `None`, você tem tudo.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Esse loop está correto contra qualquer servidor. O `MCPServer` retorna tudo em uma página só, então `next_cursor` é `None` e o loop roda uma vez, e é por isso que a maioria do código nunca o escreve. Servidores que paginam de verdade, e as regras que os cursores obedecem, estão em **[Paginação](../advanced/pagination.md)**.

## Em testes {#in-tests}

`Client(mcp)`, sem processo e sem porta, já é um harness de teste para o seu servidor.

Existe uma flag do construtor feita para isso: `Client(mcp, raise_exceptions=True)`. Ela só tem efeito em conexões em memória, e **[Testes](../get-started/testing.md)** é a página que a explica e constrói todo o padrão em torno dela.

## Recapitulando {#recap}

* `Client(x)` conecta em memória a um objeto servidor, via Streamable HTTP a uma string de URL, e por qualquer outra coisa via um transporte.
* `async with` é o ciclo de vida inteiro. Dentro dele, `server_capabilities` e `protocol_version` já estão preenchidos; `server_info` e `instructions` também, quando o servidor os fornece.
* `list_tools()` dá a você o `name`, `title`, `description` e `input_schema` de cada ferramenta.
* `call_tool()` retorna `content` para o modelo, `structured_content` para o seu código e `is_error`. Uma ferramenta que lança exceção é um resultado, não uma exceção.
* `content` é uma união de tipos de bloco; faça o narrowing com `isinstance` antes de ler.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` e `complete` completam os verbos.
* Todo `list_*` aceita `cursor=`; itere até `next_cursor` ser `None`.

As coisas que um servidor pode pedir ao *cliente*, e como você as responde, são os **[Callbacks do cliente](callbacks.md)**.
