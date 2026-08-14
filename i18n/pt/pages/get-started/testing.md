---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Testes {#testing}

O SDK Python traz uma classe `Client` com um **transporte em memória**: passe a ela o objeto do seu servidor e ela se conecta diretamente a ele.

Sem subprocesso. Sem porta. Sem transporte nenhum. É a mesma ideia do `TestClient` do FastAPI.

## Uso básico {#basic-usage}

Vamos supor que você tenha um servidor simples com uma única ferramenta (tool):

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Para executar o teste abaixo, você vai precisar de duas dependências extras (de desenvolvimento):

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Esta documentação pressupõe que você já conhece o [`pytest`](https://docs.pytest.org/en/stable/).

    O [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) é o que o teste abaixo
    usa para fazer a asserção sobre o objeto de resultado inteiro em uma única linha. Ele grava a saída
    de um teste como o literal `snapshot(...)` que você vê. Se preferir não usá-lo, remova o import e
    faça as asserções sobre os campos que interessam (`result.content[0].text == "3"`), como em
    qualquer outro teste.

Agora o teste:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. Se você estiver usando `trio`, retorne `"trio"` no lugar. Veja a [documentação do anyio](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) para os detalhes.
2. A fixture entrega um cliente já conectado. Todo teste que recebe `client` ganha uma conexão em memória nova com o mesmo servidor.

Pronto! Agora você pode estender seus testes para cobrir mais cenários.

## Por que `raise_exceptions=True`? {#why-raise_exceptionstrue}

Duas coisas diferentes podem dar errado, e essa flag só mexe em uma delas.

Uma exceção dentro de uma das **suas ferramentas** não é uma falha de protocolo. Ela vira um resultado normal com
`is_error=True`, e o modelo lê a mensagem. `raise_exceptions` não muda isso: com ou
sem ela, `call_tool` retorna o mesmo resultado com `is_error=True`. Há uma página inteira sobre isso:
**[Tratamento de erros](../servers/handling-errors.md)**.

Uma falha **fora** do corpo de uma ferramenta é diferente. Na conexão que `Client(mcp)` entrega, o
servidor a sanitiza em um genérico `"Internal server error"` antes que o cliente a veja. Você nunca
deve vazar os detalhes de um crash inesperado para um chamador remoto. Em um teste, isso é exatamente o que
você *não* quer, e é isso que `raise_exceptions=True` muda: seu teste vê a mensagem real
em vez da sanitizada.

Deixe-a ligada nos testes. Em código de produção, ela não significa nada.

## No mesmo processo por padrão {#in-process-by-default}

!!! note
    `Client(mcp)` se conecta no mesmo processo e é **neutro quanto à era** por padrão: ele sonda o servidor e
    escolhe o caminho de protocolo adequado. Fixe `mode="legacy"` se o seu teste exercita semântica
    específica do modo legado (push de amostragem (sampling) ou de elicitação (elicitation), `message_handler`), e remova `raise_exceptions=True`
    nesse caso: uma conexão legada nem sequer sanitiza, e a flag relança a
    falha dentro da task do servidor em vez de no seu teste.

Essa única linha é também o motivo pelo qual esta documentação pode prometer que os exemplos funcionam: cada
arquivo de exemplo é exercitado pela própria suíte de testes do SDK, quase todos exatamente por meio deste
cliente. Você está usando a mesma ferramenta que o SDK usa em si mesmo.

Você tem um servidor funcionando e testado. Colocá-lo dentro de uma aplicação real (Claude Desktop, uma
IDE) é o tema de **[Conecte-se a um host real](real-host.md)**; todas as outras formas de servi-lo estão em
**[Executando seu servidor](../run/index.md)**.
