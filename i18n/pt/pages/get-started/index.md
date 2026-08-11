---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# Comece por aqui {#get-started}

Novo no MCP, ou novo neste SDK? Comece aqui. Estas páginas levam você do zero a um
servidor funcional e testado: [instale o SDK](installation.md), construa seu
[primeiro servidor](first-steps.md), [conecte-o a um host real](real-host.md) e
[teste-o](testing.md) com um cliente em memória.

## Execute o código {#run-the-code}

Todos os blocos de código podem ser copiados e usados diretamente: são arquivos completos e funcionais.

Para acompanhar, cole um bloco em um `server.py` e abra-o no MCP Inspector:

```console
uv run mcp dev server.py
```

É **ALTAMENTE recomendado** que você escreva (ou copie) o código, edite-o e execute-o localmente. Usá-lo no seu próprio editor é o que mostra de verdade qual é a ideia: o pouco que você escreve, o autocompletar, a checagem de tipos pegando erros antes de executar qualquer coisa.

## Você não vai precisar adivinhar {#you-will-not-be-guessing}

Cada exemplo nesta documentação é um arquivo completo em [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) no próprio repositório do SDK, e a suíte de testes do SDK exercita cada um deles por meio de um **cliente em memória**:

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

Sem subprocesso, sem porta, sem transporte. `Client(mcp)` se conecta diretamente ao objeto do servidor.

Se uma mudança no SDK quebrar um exemplo de uma destas páginas, o CI fica vermelho antes que a página quebre. O código que você lê aqui é o código que roda.

Você mesmo vai usar isso em [Testes](testing.md); é assim que você testa seus próprios servidores também.

## Para onde ir agora {#where-to-go-next}

Depois que você tiver um servidor rodando, o resto desta documentação é uma referência, não um curso.
Cada página se sustenta sozinha, então pule direto para o que você precisa:

* O que um servidor expõe (ferramentas, recursos, prompts) está em **[Servidores](../servers/index.md)**.
* O que está disponível dentro das funções que você registra está em **[Dentro do seu handler](../handlers/index.md)**.
* Levar o servidor até os clientes (stdio, HTTP, o app FastAPI que você já tem) está em **[Executando seu servidor](../run/index.md)**.
* Construir o outro lado, uma aplicação que *usa* servidores MCP, está em **[Clientes](../client/index.md)**.
