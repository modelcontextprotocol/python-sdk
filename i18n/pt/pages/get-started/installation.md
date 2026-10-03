---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Instalação {#installation}

O SDK Python está no PyPI como [`mcp`](https://pypi.org/project/mcp/). Ele requer **Python 3.10+**.

Esta documentação descreve a **v2**, a linha de versões estável atual:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "Vindo da v1?"
    A v2 é uma versão major com quebras de compatibilidade; o **[Guia de migração](../migration.md)**
    cobre todas elas. Se o seu *pacote* depende de `mcp` e ainda não está pronto para migrar, mantenha um
    limite superior `<2` (por exemplo `mcp>=1.28,<2`) para que uma resolução sem versão fixada continue na linha 1.x.

## O que é instalado {#what-gets-installed}

Você não precisa saber nada disso para usar o SDK, mas, se quiser saber para que serve cada dependência:

* `mcp-types`: todos os tipos do protocolo (requisições, resultados, blocos de conteúdo) em um pacote próprio, versionado em sincronia com o SDK. O código que depende de `mcp` o importa pelo alias `mcp.types` (todo `from mcp.types import ...` nesta documentação); importe `mcp_types` diretamente apenas em um projeto que instala `mcp-types` sem o SDK.
* [`anyio`](https://anyio.readthedocs.io/): o runtime assíncrono. O SDK inteiro é escrito sobre o anyio, então roda tanto com `asyncio` quanto com `trio`.
* [`pydantic`](https://docs.pydantic.dev/): a base de todos os modelos de `mcp.types`, além de toda a geração e validação de schemas.
* [`httpx2`](https://pypi.org/project/httpx2/): o cliente HTTP por trás dos transportes de *cliente* Streamable HTTP e SSE, com suporte embutido a server-sent events.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) e [`python-multipart`](https://pypi.org/project/python-multipart/): os transportes HTTP de *servidor*.
* [`jsonschema`](https://pypi.org/project/jsonschema/): valida a saída estruturada de uma ferramenta (tool) contra o schema de saída declarado por ela.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): tratamento de tokens OAuth para autorização.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): apenas a API leve, então o middleware de tracing do SDK não custa nada, a menos que você mesmo instale um SDK e um exporter do OpenTelemetry.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) e [`typing-inspection`](https://pypi.org/project/typing-inspection/): funcionalidades modernas de tipagem no Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): somente no Windows, usado para o gerenciamento de subprocessos `stdio`.

## Extras opcionais {#optional-extras}

* `mcp[cli]` adiciona [`typer`](https://typer.tiangolo.com/) e [`python-dotenv`](https://pypi.org/project/python-dotenv/) para a ferramenta de linha de comando `mcp` (`mcp dev`, `mcp run`, `mcp install`). Você vai querer isso durante o desenvolvimento; talvez não precise dele em um servidor depois do deploy.
* `mcp[rich]` adiciona [`rich`](https://rich.readthedocs.io/) para logs de servidor mais bonitos.
