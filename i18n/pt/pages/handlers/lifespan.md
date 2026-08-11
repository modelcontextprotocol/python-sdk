---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Lifespan {#lifespan}

A maioria dos servidores reais mantém alguma coisa durante a vida inteira: um pool de banco de dados, um cliente HTTP, um modelo carregado.

Você não quer construir isso a cada chamada, e quer fechar tudo de forma limpa. É para isso que serve o **lifespan** (ciclo de vida do servidor).

## Um lifespan tipado {#a-typed-lifespan}

Um lifespan é um `@asynccontextmanager` que recebe o servidor e faz `yield` de **um único objeto**. Seja qual for o objeto que você entregar, ele fica disponível para todos os handlers enquanto o servidor estiver rodando.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

Leia de baixo para cima:

* `app_lifespan` conecta o `Database` **antes** do `yield` e o desconecta **depois**, dentro de um `finally`. Isso é a inicialização e o encerramento.
* Ele entrega um `AppContext`, uma dataclass comum que agrupa o que você configurou. Um campo hoje, dez amanhã.
* `MCPServer("Bookshop", lifespan=app_lifespan)` é toda a ligação necessária.
* Dentro da ferramenta (tool), o objeto entregue é `ctx.request_context.lifespan_context`.

O lifespan executa **uma vez**. O servidor entra nele ao iniciar (antes da primeira requisição) e sai dele ao parar. Todas as requisições nesse intervalo compartilham o mesmo `AppContext`.

!!! info
    Se você já escreveu um `lifespan` do FastAPI, já conhece isso. Mesmo decorador, mesmo `yield`, mesmo `finally`.

### O que o modelo vê {#what-the-model-sees}

Nada de novo. `ctx` é um parâmetro **Context**, então o SDK o injeta e ele nunca chega ao schema de entrada:

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` é o único argumento que o modelo pode passar. O lifespan é assunto do seu servidor.

Funções `@mcp.resource()` e `@mcp.prompt()` também podem receber um parâmetro `ctx`, escrito como um `Context` puro por um motivo que a próxima seção explica. Tudo o que `ctx` carrega está em **[O Context](context.md)**.

### É tipado de verdade {#it-really-is-typed}

Olhe de novo a anotação: `ctx: Context[AppContext]`.

Esse único parâmetro de tipo é o motivo pelo qual `ctx.request_context.lifespan_context` **é** um `AppContext` para o seu verificador de tipos. `.db` autocompleta; `.dbb` é um erro antes mesmo de você executar o servidor.

Escreva um `Context` puro no lugar e `lifespan_context` passa a ser tipado como `dict[str, Any]`: o verificador de tipos não tem como saber o que o seu lifespan entregou. O objeto continua lá em tempo de execução; o que você perdeu foi a ajuda.

!!! warning
    `Context[AppContext]` é uma grafia **só para ferramentas**. Coloque-a em uma função
    `@mcp.resource()` ou `@mcp.prompt()` e toda chamada a esse handler falha. O cliente recebe um
    erro de volta, e o log do servidor mostra o porquê:

    ```text
    Context is not available outside of a request
    ```

    Em recursos e prompts, escreva o `ctx: Context` puro. O objeto que o seu lifespan entregou
    continua sendo `ctx.request_context.lifespan_context` em tempo de execução; você abre mão do
    parâmetro de tipo, não do objeto.

!!! tip
    Sempre existe um lifespan. Se você não passar um, o padrão do SDK entrega um `dict` vazio,
    então `ctx.request_context.lifespan_context` é `{}`, nunca `None`. Esse padrão também é o
    motivo de um `Context` puro tipá-lo como `dict[str, Any]`.

## Veja acontecer {#watch-it-happen}

"A inicialização roda antes da primeira requisição" é o tipo de afirmação em que você não deveria ter que acreditar sem ver.

Reduza o servidor só ao ciclo de vida: dê ao `Database` uma flag `connected`, inverta-a em `connect()` e `disconnect()`, e adicione uma ferramenta que informe o valor dela.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` fica no nível do módulo por um único motivo: para que você possa observá-lo de *fora* do servidor.

!!! check
    Três momentos, três valores:

    * Antes de o servidor iniciar, `database.connected` é `False`. Importar o módulo não conectou nada.
    * Enquanto ele está rodando, chame `database_status` e o resultado é `"connected"`.
    * Pare o servidor e o bloco `finally` executa: `database.connected` é `False` de novo.

    O trabalho aconteceu exatamente onde você o colocou: em volta do `yield`, não na importação e nem a cada requisição.

## Recapitulando {#recap}

* `lifespan=` aceita um `@asynccontextmanager` que recebe o servidor e faz `yield` de um único objeto.
* O código antes do `yield` é a inicialização. O `finally` depois dele é o encerramento.
* Ele executa uma vez, em torno da vida inteira do servidor, não a cada requisição.
* O que você entregar no `yield` é `ctx.request_context.lifespan_context` em toda ferramenta, recurso e prompt.
* `ctx: Context[AppContext]` deixa esse acesso totalmente tipado em ferramentas. Recursos e prompts recebem o `Context` puro.
* Não passar `lifespan=` significa um `dict` vazio, nunca `None`.

Um handler que para no meio da chamada para perguntar ao usuário algo que só ele sabe é **[Elicitação (elicitation)](elicitation.md)**.
