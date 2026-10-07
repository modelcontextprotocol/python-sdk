---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# Cancelamento {#cancellation}

Um cliente pode desistir de uma chamada: o usuário apertou o botão de parar, ou um timeout se esgotou.

Quando isso acontece, o SDK **cancela o seu handler**. O `await` em que ele está esperando lança uma exceção, a função é desempilhada, e nada do que ela retornar é enviado. A maioria dos handlers não precisa fazer nada a respeito.

Dois tipos precisam: um handler com algo para limpar, e um handler que é um `def` comum.

## Faça a limpeza em uma ferramenta `async def` {#clean-up-in-an-async-def-tool}

Coloque a limpeza em um `finally`:

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* O `finally` executa não importa como a ferramenta termine: ela retornou, lançou uma exceção ou foi cancelada.
* Uma limpeza que precisa fazer `await` exige `shield=True`. Em um handler cancelado, todo `await` seguinte também lança uma exceção, então sem a proteção `release_hold` pararia na primeira linha.
* Nada consegue cancelar um bloco protegido, então dê a ele um limite de tempo. Aqui são `5` segundos.

!!! tip
    Use `finally`, não `except`. O cancelamento precisa continuar subindo depois que a sua limpeza
    termina, e um `finally` permite isso.

## Pare antes do fim em uma ferramenta `def` comum {#stop-early-in-a-plain-def-tool}

Uma ferramenta `def` comum roda em uma thread, e nada consegue interromper uma thread de fora. A ferramenta precisa perguntar:

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` não faz nada enquanto a chamada está ativa, e lança uma exceção assim que ela é cancelada. Chame essa função entre unidades de trabalho.
* Aqui a limpeza também vai em um `finally`. Nada em uma thread faz await, então a limpeza não precisa de proteção.
* Uma ferramenta `def` que nunca pergunta roda até o fim, e o resultado dela é descartado.

## Onde se aplica {#where-it-applies}

As funções de prompt e de recurso são canceladas exatamente como as ferramentas.

Funciona do mesmo jeito sobre stdio e Streamable HTTP. Com o `Client` deste SDK, desistir significa cancelar a tarefa que aguarda `call_tool`, ou deixar o `read_timeout_seconds` da chamada se esgotar.

!!! warning
    Duas opções do Streamable HTTP impedem que a notícia chegue ao seu handler: `json_response=True` em uma
    conexão `2026-07-28`, e `stateless_http=True` em uma conexão legada. Nesses casos, o handler roda até
    o fim, não importa o que o cliente tenha feito.

## Resumo {#recap}

* Quando o cliente desiste de uma chamada, o SDK cancela o handler: ferramenta, prompt ou recurso.
* `async def`: faça a limpeza em um `finally`, e coloque a limpeza que faz await dentro de `anyio.move_on_after(seconds, shield=True)`.
* `def` comum: chame `anyio.from_thread.check_cancelled()` entre unidades de trabalho, ou a ferramenta roda até o fim. Um `finally` simples faz a limpeza.
* `json_response=True` (conexões modernas) e `stateless_http=True` (conexões legadas) desligam o cancelamento.

Progresso e cancelamento ficam entre uma ferramenta em execução e quem a *chamou*. As linhas que ela registra em log para *você*, a pessoa que opera o servidor, são um canal diferente: **[Logging](logging.md)**.
