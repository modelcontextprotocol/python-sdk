---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# Completions {#completions}

Um cliente que monta uma UI em cima do seu servidor quer autocompletar os valores dos argumentos enquanto o usuário digita: nomes de linguagens, nomes de repositórios, caminhos de arquivo.

É com as **completions** que o seu servidor fornece essas sugestões.

## Algo que valha a pena completar {#something-worth-completing}

As completions se aplicam a exatamente duas coisas: os argumentos de um **prompt** e os parâmetros de um **template de recurso**. Então comece com um servidor que tenha um de cada:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

Ainda não há nada de completions aqui.

* `review_code` recebe um `language`. O usuário não deveria precisar adivinhar quais grafias você aceita.
* `github_repo` recebe um `owner` e um `repo`. Campos de texto livre para os dois resultam em um formulário ruim.

## O handler de completion {#the-completion-handler}

Adicione **uma** função decorada com `@mcp.completion()`:

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* Existe um handler por servidor. Toda requisição de completion chega aqui, e você ramifica de acordo com o que está sendo completado.
* Ele precisa ser `async def`: o SDK faz o await dele.
* Ele recebe três argumentos:
  * `ref`: *qual* prompt ou template de recurso, como um `PromptReference` ou um `ResourceTemplateReference`. É com `isinstance` que você distingue um do outro.
  * `argument`: `argument.name` é o argumento que está sendo completado, `argument.value` é o que o usuário digitou até agora.
  * `context`: os argumentos já resolvidos. Ignore-o por enquanto.
* Você retorna um `Completion(values=[...])`, ou `None` quando não tem nada a oferecer.

!!! tip
    `argument.value` é o prefixo que o usuário digitou. O SDK **não** filtra para você: o que
    você colocar em `values` é o que a UI mostra. O `startswith` é você quem escreve.

### Experimente {#try-it}

Use o `Client` em memória de **[Testes](../get-started/testing.md)** para exercitá-lo. Chame
`client.complete()` com `ref=PromptReference(name="review_code")` e
`argument={"name": "language", "value": "py"}`:

```python
result.completion.values  # ['python']
```

* `ref` é o mesmo tipo de referência que o seu handler recebe.
* `argument` é um dict simples com exatamente duas chaves, `name` e `value`.

Envie um `value` vazio e você recebe a lista inteira de volta. `lang.startswith("")` é verdadeiro para toda linguagem:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

Pergunte sobre `code` (um argumento que o seu handler não reconhece) e ele retorna `None`, que o SDK transforma em uma lista vazia:

```python
result.completion.values  # []
```

`None` significa *"sem sugestões"*, nunca um erro. A UI recorre a uma caixa de texto simples.

## Uma capacidade que você nunca declarou {#a-capability-you-never-declared}

Registrar o handler é a declaração. Conecte um cliente e veja:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

Você não listou `completions` em lugar nenhum. O SDK viu o handler e declarou a capacidade por você. Toda capacidade *opcional* funciona assim: o handler é a declaração. (As três primitivas não são opcionais: o `MCPServer` sempre as declara, com ou sem handlers.)

!!! check
    Volte ao primeiro `server.py` (aquele sem handler) e pergunte mesmo assim. A chamada falha
    com um erro JSON-RPC:

    ```text
    Method not found
    ```

    E `client.server_capabilities.completions` é `None`. É para isso que a capacidade existe: um
    cliente bem-comportado a confere e nunca envia uma requisição que você não tem como responder.

## Argumentos dependentes {#dependent-arguments}

`github://repos/{owner}/{repo}` tem dois parâmetros, e os valores úteis para `repo` dependem de qual `owner` foi escolhido antes.

É para isso que serve o `context`. Ele carrega os argumentos que o usuário **já resolveu**:

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* O novo ramo é acionado para o parâmetro `repo` do template.
* `context.arguments` é um `dict[str, str] | None` com os valores escolhidos até agora (aqui, `owner`).
* Sem `owner` ainda, não há sugestões que façam sentido, então o handler retorna `None`.

O cliente envia esses valores resolvidos com `context_arguments=`. Desta vez, `ref` é um
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`. Peça `repo` com um
`value` vazio e passe `context_arguments={"owner": "modelcontextprotocol"}`:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

Tire o `context_arguments=` e a mesma chamada retorna `[]`. O handler não tem como saber quais repositórios oferecer antes de saber quem é o owner.

!!! info
    `Completion` também aceita `total=` e `has_more=`. Defina-os quando `values` for uma fatia de uma
    lista maior, para que a UI possa mostrar *"e mais 200"*. A maioria dos handlers nunca precisa deles.

## Recapitulando {#recap}

* Completions são sugestões para **argumentos de prompt** e **parâmetros de template de recurso**. Nada mais.
* `@mcp.completion()` registra o único handler. Ele é `async def (ref, argument, context) -> Completion | None`.
* Ramifique com base em `isinstance(ref, ...)` e em `argument.name`. Filtre por `argument.value` você mesmo.
* `None` vira uma lista vazia. Nunca é um erro.
* `context.arguments` guarda os valores já resolvidos; o cliente os fornece como `context_arguments=`.
* A capacidade `completions` aparece no momento em que você registra o handler. Sem ele, a requisição dá `Method not found`.

As sugestões ajudam enquanto o usuário ainda está *preenchendo* um prompt ou template; para fazer uma pergunta a ele no *meio* de uma chamada de ferramenta, o que você quer é a **[Elicitação](../handlers/elicitation.md)** (elicitation). Tudo o que uma ferramenta pode retornar além de texto está em **[Imagens, áudio e ícones](media.md)**.
