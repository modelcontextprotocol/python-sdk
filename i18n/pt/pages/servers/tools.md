---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# Ferramentas {#tools}

Uma **ferramenta** (tool) é uma função que o modelo pode chamar.

Você declara uma colocando `@mcp.tool()` em uma função Python comum. A API inteira é essa.

## Sua primeira ferramenta {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

Veja o que você escreveu. Não há schemas, nem JSON, nem protocolo, só uma função. O SDK lê três coisas dela:

* O **nome** da ferramenta é o nome da função: `search_books`.
* A **descrição** que o modelo vê é a docstring: `Search the catalog by title or author.`
* Os **argumentos** que o modelo pode passar vêm das anotações de tipo: `query: str` e `limit: int`.

### O schema de entrada {#the-input-schema}

A partir dessas anotações de tipo, o SDK gera um JSON Schema e o envia ao cliente durante `tools/list`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

Os dois argumentos estão em `required` porque nenhum deles tem valor padrão. Você vai resolver isso daqui a pouco. (As chaves `title` são artefatos do Pydantic; as propriedades, seus tipos e `required` são o contrato.)

!!! tip
    Aqui, as anotações de tipo não são documentação. Elas são **o contrato**. Se um cliente enviar `"limit": "ten"`,
    o SDK rejeita isso antes mesmo de a sua função executar.

### O que o modelo recebe de volta {#what-the-model-gets-back}

Chame a ferramenta com `{"query": "dune", "limit": 5}` e o resultado tem duas partes:

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` é o texto que o **modelo** lê. `structured_content` são dados tipados para a **aplicação cliente**. Ele está ali porque você declarou o tipo de retorno como `-> str`.

Não se preocupe com `structured_content` por enquanto. Retorne objetos Python de verdade das suas ferramentas e a coisa certa acontece; a página **[Saída estruturada](structured-output.md)** trata exatamente disso.

### Experimente {#try-it}

Execute o servidor com o MCP Inspector:

```console
uv run mcp dev server.py
```

Abra a URL que ele imprime, vá até a aba **Tools** e chame `search_books`.

O Inspector renderiza um formulário com um campo de texto obrigatório `query` e um campo numérico obrigatório `limit`. Ele montou esse formulário a partir das suas anotações de tipo. Todos os outros clientes MCP vão fazer o mesmo.

## Argumentos opcionais {#optional-arguments}

Dê um valor padrão a um parâmetro e ele deixa de ser obrigatório. É só isso. É apenas Python.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

O schema acompanha:

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

`limit` saiu de `required` e ganhou `"default": 10`. Um cliente que o omite recebe `10`, exatamente como aconteceria em Python.

## Schemas mais ricos com `Field` {#richer-schemas-with-field}

As anotações de tipo levam você longe, mas às vezes você quer *descrever* um argumento, ou restringi-lo.

Envolva o tipo em `Annotated` e adicione um `Field` do Pydantic:

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

Três novidades, todas nos parâmetros:

* `Field(description=...)`: uma descrição por argumento que o modelo lê junto com a docstring.
* `Field(ge=1, le=50)`: limites numéricos. Eles entram no schema como `"minimum": 1, "maximum": 50`.
* `Literal["fiction", "non-fiction", "poetry"]`: um enum. O modelo só pode escolher um desses valores.

!!! check
    Restrições não são enfeite. Chame a ferramenta com `limit=999` e o SDK responde com um
    erro de ferramenta **antes de a sua função executar**:

    ```text
    Input should be less than or equal to 50
    ```

    Esse erro volta para o modelo como o resultado da ferramenta, e o modelo o lê e tenta de novo com
    um valor válido. Você escreveu `le=50` uma vez e ganhou de graça agentes que se corrigem sozinhos.

!!! info
    Se você já usou FastAPI ou Pydantic, já sabe tudo isso. É o mesmo `Field`,
    o mesmo `Annotated`, a mesma validação. Não há nada específico de MCP para aprender aqui.

## Um modelo como parâmetro {#a-model-as-a-parameter}

Quando uma ferramenta recebe mais do que alguns poucos argumentos, agrupe-os em um modelo Pydantic:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

O schema de `Book` fica aninhado dentro do schema de entrada da ferramenta (como uma referência em `$defs`), o modelo o preenche como um objeto JSON, e sua função recebe uma **instância real de `Book`**, já validada, com os atributos `.title`, `.author` e `.year`.

Você pode misturar à vontade: parâmetros simples ao lado de parâmetros de modelo, modelos aninhados, listas de modelos. É Pydantic de ponta a ponta.

## `async def` {#async-def}

Se uma ferramenta faz I/O (chama uma API, lê um arquivo, consulta um banco de dados), declare-a como `async def` e use `await` dentro dela. O SDK se encarrega de aguardá-la.

Uma ferramenta com `def` comum também funciona: o SDK a executa em uma thread, então ela nunca bloqueia o servidor.

Não há mais nada para configurar.

## Nomes, títulos e anotações {#names-titles-and-annotations}

Tudo o que o SDK infere, você pode sobrescrever no decorador:

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` é um nome legível por humanos, pensado para interfaces. Os clientes mostram *"Search the catalog"* em vez de `search_books`.
* `annotations` são **dicas** de comportamento para o cliente:
  * `read_only_hint=True`: esta ferramenta não altera nada.
  * `open_world_hint=False`: ela opera sobre um conjunto fechado de coisas (este catálogo), não sobre a web aberta.
  * As outras duas, `destructive_hint` e `idempotent_hint`, descrevem uma ferramenta que *escreve*: ela pode
    apagar alguma coisa? E chamá-la duas vezes dá no mesmo que chamá-la uma vez? A especificação define as duas
    apenas para ferramentas que não são somente leitura, então elas não diriam nada em `search_books`.

Um cliente bem-comportado as usa para decidir coisas como *"preciso perguntar ao usuário antes de executar isto?"*. São dicas, não segurança. Nunca conte com um cliente respeitando-as.

!!! tip
    `@mcp.tool()` também aceita `name=` e `description=` se você não quiser derivá-los
    do nome da função e da docstring. Na maioria das vezes você quer.

## Recapitulando {#recap}

* `@mcp.tool()` em uma função a transforma em ferramenta. O nome vem da função, a descrição vem da docstring.
* As anotações de tipo **são** o schema de entrada. Valores padrão tornam os argumentos opcionais.
* `Annotated[..., Field(...)]` adiciona descrições e restrições; `Literal` adiciona enums.
* Um modelo Pydantic como parâmetro é a forma de receber um "corpo" estruturado.
* Argumentos inválidos são rejeitados para você, com um erro que o modelo consegue ler e do qual consegue se recuperar.
* `async def` para I/O, `def` comum para todo o resto.

**[Saída estruturada](structured-output.md)** é o que acontece com o valor que você devolve no `return`.
