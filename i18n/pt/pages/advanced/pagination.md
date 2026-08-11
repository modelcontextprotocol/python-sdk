---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# Paginação {#pagination}

A maioria dos servidores nunca precisa disso.

O `MCPServer` responde a toda requisição `list_*` com tudo o que tem, em uma única página, `next_cursor=None`. Para algumas dezenas de ferramentas, recursos ou prompts, essa é a resposta certa e não há nada para configurar.

A paginação é para o servidor cuja lista de recursos é, na verdade, um banco de dados: milhares de linhas que ele se recusa a serializar em uma única resposta. A resposta do protocolo é um **cursor**: o servidor retorna uma página mais um token opaco, e o cliente envia esse token de volta para obter a próxima página.

O `@mcp.resource()` não tem nenhum gancho para isso. Para paginar, você mesmo escreve o handler de listagem, no **[Server de baixo nível](low-level-server.md)**.

## Um servidor que pagina {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* Em um `Server` de baixo nível, os handlers são argumentos do construtor, não decoradores. O `on_list_resources` responde a toda requisição `resources/list`; a ligação inteira é essa.
* Todo handler paginado é tipado como `params: PaginatedRequestParams | None`, e o exemplo aceita os dois. Em uma conexão, porém, o SDK nunca entrega `None` para você (uma requisição sem o membro `params` chega ao handler como o modelo com seus valores padrão), então o sinal que importa é `params.cursor is None`: **comece do início**.
* Você decide o que um cursor *é*. Aqui é um offset representado como string. Um timestamp, uma chave primária, um blob em base64: qualquer coisa que você consiga gerar na saída e reconhecer na volta.
* `next_cursor=None` é como você diz "essa foi a última página". Não há contagem, nem total, nem `has_more`. O `None` é o sinal inteiro.

!!! tip
    Um `PAGE_SIZE` de 10 deixa o exemplo legível. Escolha o seu por endpoint: uma lista de
    recursos de uma linha comporta uma página de 500; uma lista de templates de prompt pesados, não.
    O cliente não tem voz nisso, e é assim de propósito.

### Experimente {#try-it}

`Client(server)` se conecta a um `Server` de baixo nível em memória exatamente como se conecta a um `MCPServer`.

Chame `list_resources()` sem argumentos. Você recebe dez recursos, de `book-1` a `book-10`, e `next_cursor` é a string `"10"`.

Devolva-a com `list_resources(cursor="10")` e o primeiro recurso é `book-11`, o novo `next_cursor` é `"20"`.

A décima página volta com `next_cursor` definido como `None`. Pronto.

## O loop do cliente {#the-client-loop}

Todo método `list_*` do `Client` (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) aceita a palavra-chave `cursor=`. Esgotar uma lista paginada é um único `while True`:

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` começa como `None`, então a primeira requisição não carrega nenhum cursor.
* Acumule **antes** de olhar para `next_cursor`: a última página também tem recursos.
* `next_cursor is None` é a saída. Qualquer outra coisa volta direto para `cursor=`, intocada.

Execute o `main()` dele e ele imprime `100 resources`: dez páginas de dez, costuradas por um loop que nunca soube que havia dez páginas.

Este é o mesmo loop que **[O cliente](../client/index.md)** mostra para todo verbo `list_*`, e ele não custa nada contra um servidor que não pagina: `next_cursor` é `None` na primeira resposta e o loop roda uma vez.

## As três regras {#the-three-rules}

**Cursores são opacos.** Um cliente nunca deve interpretar, construir ou adivinhar um. A única fonte legítima de um cursor é o `next_cursor` da página anterior, literalmente.

**O servidor escolhe o tamanho da página.** Não existe `limit=` no protocolo. Se você precisa de um tamanho de página diferente, altere o servidor.

**Um cliente que ignora a paginação continua funcionando.** Ele chama `list_resources()` uma vez, recebe os dez primeiros e nunca percebe o `next_cursor` que jogou fora. Nada quebra; ele só vê menos.

!!! check
    Opaco quer dizer opaco. Invente um cursor (`list_resources(cursor="page-2")`) e não há
    nada que o protocolo possa fazer por você. Este servidor tenta `int("page-2")`, o handler lança uma exceção,
    e o que volta para o cliente é:

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    Um cursor que você não recebeu do servidor é um bug, não um pedido de funcionalidade.

## Recapitulando {#recap}

* O `MCPServer` retorna tudo em uma página. A paginação é opcional, e você opta por ela no `Server` de baixo nível.
* `on_list_resources` (e `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) recebe `PaginatedRequestParams | None`; `params.cursor` é `None` na primeira página.
* Você retorna uma página mais `next_cursor`: qualquer string que você vá reconhecer depois, ou `None` quando não sobrar nada.
* O loop do cliente: passe `cursor=`, acumule, repita até `next_cursor is None`.
* Cursores são opacos, o servidor é dono do tamanho da página, e um cliente que não pagina ainda recebe a primeira página.

O restante da API do `Server` escrita à mão (`on_call_tool`, dicts `input_schema`, `_meta`) está em **[O Server de baixo nível](low-level-server.md)**.
