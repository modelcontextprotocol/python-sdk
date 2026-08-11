---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# Progresso {#progress}

Uma ferramenta (tool) que leva trinta segundos e não diz nada durante trinta segundos parece quebrada.

**Notificações de progresso** resolvem isso. A ferramenta informa em que ponto está; o cliente decide o que desenhar com isso: uma barra, um spinner, uma linha de log.

## Informe a partir da ferramenta {#report-it-from-the-tool}

Receba um parâmetro **`Context`** e chame `report_progress`:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

Três argumentos, e você decide o que eles significam:

* `progress`: até onde você chegou. A especificação exige que ele **aumente** a cada informe; nunca repita um valor nem volte atrás.
* `total`: quanto há no total, se você souber. Opcional.
* `message`: uma linha legível por humanos sobre *este* passo. Opcional.

`ctx` é injetado por causa da sua anotação de tipo e o modelo nunca o vê: o schema de entrada de `import_catalog` tem uma única propriedade, `urls`. A página **[O Context](context.md)** trata inteiramente desse objeto; progresso é uma das coisas que ele oferece a você.

## Escute a partir do cliente {#listen-for-it-from-the-client}

O cliente opta por receber **por chamada**, passando `progress_callback=` para `call_tool`:

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

O callback é uma função `async` que recebe exatamente o que o servidor informou: `progress`, `total`, `message`.

!!! info
    `Client(mcp)` conecta direto ao objeto do servidor, em memória, o mesmo cliente sobre o qual a página **[Testes](../get-started/testing.md)**
    é construída. `progress_callback` é o mesmo parâmetro seja qual for o transporte que o `Client`
    usa; o *timing* que você está prestes a ver é o da conexão em memória. Ela executa seu callback
    inline, então todo informe chega antes de `call_tool` retornar. Em um transporte real, as
    notificações disputam corrida com o resultado, e um callback lento ainda pode estar executando depois que `call_tool`
    retornou.

### Experimente {#try-it}

Coloque `client.py` ao lado de `server.py` e execute:

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

Cada `await ctx.report_progress(...)` no servidor virou uma chamada a `show` no cliente, em ordem, e as duas linhas foram impressas **antes** de `call_tool` retornar. O progresso não vem embutido no resultado; ele é transmitido enquanto a ferramenta ainda está trabalhando.

!!! warning
    `progress_callback` pertence à **chamada**, não ao `Client`. Não há argumento de construtor
    para ele, porque chamadas diferentes querem callbacks diferentes: uma move uma barra de download, a
    seguinte, uma linha de log.

!!! check
    Agora apague `progress_callback=show` e execute de novo:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    Nenhum erro, nenhum aviso, mesmo resultado. `report_progress` é um **no-op quando quem chamou não pediu
    progresso**, então você informa incondicionalmente e nunca precisa se perguntar se alguém está
    escutando.

## Quando você não sabe o total {#when-you-dont-know-the-total}

`total` serve para quando você conhece o denominador. Muitas vezes você não conhece: está esvaziando um feed, percorrendo um cursor, baixando algo sem cabeçalho de tamanho.

Deixe-o de fora:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

O callback recebe `total=None`. Um cliente ainda consegue mostrar *atividade* ("3 importados até agora...") mas não consegue mostrar uma porcentagem. Não invente um total para ter uma barra mais bonita.

!!! tip
    `progress` não precisa contar nada em particular. Bytes, linhas, páginas: escolha a unidade que o
    usuário reconheceria, e só prometa um `total` que você consiga cumprir.

## Recapitulando {#recap}

* `await ctx.report_progress(progress, total=None, message=None)` a partir de qualquer ferramenta que receba um `Context`.
* O cliente passa `progress_callback=` para `call_tool`: por chamada, nunca no `Client`.
* O callback é `async (progress, total, message) -> None` e dispara enquanto a ferramenta ainda está executando.
* Sem callback na chamada, `report_progress` não faz nada. Informe incondicionalmente.
* Omita `total` quando não o souber; o callback recebe `None`.

Progresso é o que uma ferramenta em execução mostra ao *usuário*. As linhas que ela registra em log para *você*, a pessoa que opera o servidor, são um canal diferente: **[Logging](logging.md)**.
