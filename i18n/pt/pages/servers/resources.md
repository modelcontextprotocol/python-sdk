---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# Recursos {#resources}

Um **recurso** (resource) é um dado que você expõe para a aplicação ler.

A divisão é essa. Uma ferramenta é algo que o **modelo** decide chamar. Um recurso é algo que a **aplicação** decide carregar (um arquivo de configuração, um registro, um documento) e colocar diante do modelo como contexto.

Você declara um colocando `@mcp.resource(uri)` em uma função Python comum.

## Seu primeiro recurso {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

Tem o mesmo formato de uma ferramenta, com uma coisa a mais: a **URI**. Recursos têm endereço, não nome. Um cliente pede `config://app`, nunca `get_config`.

O SDK ainda lê o restante a partir da função:

* O **nome** é o nome da função: `get_config`.
* A **descrição** que o cliente vê é a docstring.
* O **conteúdo** é o que você retornar.

Durante `resources/list`, o cliente recebe isto:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

E quando ele lê `config://app`, sua função roda e o valor de retorno volta como texto:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    Listar é barato. Sua função **não** é chamada durante `resources/list`, só durante
    `resources/read`, e apenas para a URI que foi pedida. Exponha mil recursos
    e você só paga pelos que alguém abrir.

### Experimente {#try-it}

Execute o servidor com o MCP Inspector:

```console
uv run mcp dev server.py
```

Abra a URL que ele imprime e vá até a aba **Resources**. `config://app` está na lista, com sua descrição. Clique nele e o Inspector o lê: ali estão suas duas linhas de configuração.

## Templates de recurso {#resource-templates}

Uma URI por registro não escala. Coloque um **placeholder** na URI e um parâmetro correspondente na função:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

`{user_id}` na URI, `user_id: str` na função. O contrato inteiro é esse.

Agora isso é um **template de recurso** (resource template), e ele se muda: sai de `resources/list` e passa a aparecer em `resources/templates/list`, como um padrão em vez de um endereço:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

O cliente preenche o placeholder e lê uma URI concreta: `users://42/profile`, `users://ada/profile`. Uma única função responde a todas elas, com o valor capturado passado como `user_id`:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

Repare na `uri` do resultado. É a URI **concreta** que o cliente pediu, não o template.

!!! check
    Os placeholders e os parâmetros precisam bater. Renomeie o parâmetro da função para
    `user` enquanto a URI ainda diz `{user_id}` e o decorador se recusa **em tempo de importação**,
    antes que qualquer cliente chegue perto:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    Uma divergência dessas só pode ser bug, então o SDK torna impossível iniciar o servidor com uma.

A sintaxe dos placeholders é a da [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570): `{+path}` para valores com vários segmentos, `{?q,lang}` para parâmetros de query opcionais, e mais. O SDK também aplica, por padrão, verificações de segurança de caminho aos valores extraídos. Veja **[Templates de URI e segurança de caminhos](uri-templates.md)** para a referência completa.

`get_user_profile` também pode receber um parâmetro anotado com `Context`. O SDK o injeta sem nunca tratá-lo como parâmetro da URI, e a página **[O Context](../handlers/context.md)** cobre o que ele oferece a você.

## O que você retorna {#what-you-return}

Você não está limitado a `str`. Dê a cada recurso um `mime_type` e retorne o que fizer sentido:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` retorna uma `str`, então ela é enviada como está. Esse é o caso comum.
* `catalog_stats` retorna um `dict`, então o SDK o serializa em **texto JSON** para você:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` retorna `bytes`, então o cliente recebe um `BlobResourceContents` em vez de um `TextResourceContents`, com seus bytes codificados em base64 no campo `blob`.

A mesma regra vale para qualquer outra coisa serializável em JSON: uma lista, um modelo Pydantic, uma dataclass. Se não é `str` nem `bytes`, vira JSON.

O `mime_type` é você quem declara, e o padrão é `text/plain`. O SDK nunca inspeciona o que você retorna para adivinhá-lo, então um recurso `dict` que você não rotula continua sendo anunciado como texto puro.

!!! tip
    `@mcp.resource()` também aceita `name=`, `title=` e `description=` quando você não
    quer derivá-los da função. E quando não há função nenhuma a escrever,
    `mcp.server.mcpserver.resources` tem classes `Resource` prontas (`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`) que você registra
    com `mcp.add_resource(...)`.

Um cliente também pode **assinar** um recurso e ser notificado quando ele muda; essa metade da história é do cliente e está em **[O cliente](../client/index.md)**.

## Recapitulando {#recap}

* `@mcp.resource(uri)` em uma função a transforma em um recurso. A URI é o endereço, o valor de retorno é o conteúdo, a docstring é a descrição.
* Um `{placeholder}` na URI a transforma em um **template**: ele é listado em `resources/templates/list` e uma única função atende a toda URI que corresponder.
* Os nomes dos placeholders devem ser iguais aos nomes dos parâmetros da função. Erre isso e você descobre em tempo de importação, não em produção.
* Sua função roda quando o recurso é **lido**, não quando é listado.
* `str` vira texto, `bytes` vira um blob em base64, qualquer outra coisa vira texto JSON. `mime_type=` é como você rotula isso.
* Ferramentas são para o modelo agir. Recursos são para a aplicação ler.

A terceira primitiva, aquela que uma pessoa escolhe em um menu, são os **[Prompts](prompts.md)**.
