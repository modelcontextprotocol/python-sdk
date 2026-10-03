---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "Esta documentação cobre a v2, a linha de versões estável atual"
    Começando na v2 ou vindo da v1? **[Novidades da v2](whats-new.md)** é o tour de cinco minutos pelo que mudou, e o **[Guia de migração](migration.md)** cobre todas as mudanças incompatíveis.
    Ainda na v1.x? A documentação dela fica nos [docs da v1.x](https://py.sdk.modelcontextprotocol.io/v1/).
    Encontrou algo mal-acabado ou confuso? [Conte para nós](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

O **Model Context Protocol (MCP)** permite que aplicações forneçam contexto a LLMs de forma padronizada, separando a responsabilidade de *fornecer* contexto da interação com o LLM em si.

Este é o SDK Python oficial do protocolo. Com ele, você pode:

* **Construir servidores MCP** que expõem ferramentas (tools), recursos e prompts a qualquer host MCP.
* **Construir clientes MCP** que se conectam a qualquer servidor MCP.
* Comunicar-se por todos os transportes padrão: stdio, Streamable HTTP e SSE.

## Requisitos {#requirements}

Python 3.10+.

## Instalação {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

O extra `[cli]` instala o comando `mcp`; você vai precisar dele durante o desenvolvimento.
Veja [Instalação](get-started/installation.md) para saber para que serve cada dependência.

## Exemplo {#example}

### Crie {#create-it}

Crie um arquivo `server.py`:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

Esse é um servidor MCP completo.

Ele expõe uma **ferramenta**, `add`, e um **recurso** com template, `greeting://{name}`.

### Execute {#run-it}

```console
uv run mcp dev server.py
```

Isso inicia o seu servidor e abre o [MCP Inspector](https://github.com/modelcontextprotocol/inspector), uma interface interativa para explorá-lo. Abra a URL que ele imprime.

!!! note
    O Inspector é um app Node.js, então `mcp dev` precisa do `npx` no seu `PATH`.

### Experimente {#try-it}

No Inspector, vá em **Tools** e chame `add` com `a=1`, `b=2`.

Você recebe `3` de volta. ✨

O Inspector montou esse formulário (um campo inteiro obrigatório para `a`, outro para `b`) a partir das suas anotações de tipo. O Claude faz o mesmo, assim como qualquer outro host MCP.

Agora vá em **Resources** e leia `greeting://World`:

```text
Hello, World!
```

### Recapitulando {#recap}

Repare de novo no que você **não** escreveu:

* Nenhum JSON Schema. `a: int, b: int` *é* o schema.
* Nenhum parsing de requisição, nenhuma serialização, nenhum código de validação.
* Absolutamente nenhum tratamento do protocolo.

Você escreveu duas funções Python com anotações de tipo e uma docstring. O SDK faz o resto.

## Para onde ir agora {#where-to-go-next}

* **[Comece por aqui](get-started/index.md)** leva você da instalação até um servidor funcionando e testado.
* Construindo uma aplicação que *usa* servidores MCP? Comece por **[Clientes](client/index.md)**.
* Já tem um app FastAPI ou Starlette? **[Adicionar a um app existente](run/asgi.md)** monta um servidor MCP dentro dele.
* Atrás de uma mensagem de erro específica? **[Solução de problemas](troubleshooting.md)** é organizada pelo texto exato das mensagens.
* Quer saber o que mudou na v2? **[Novidades da v2](whats-new.md)** é o tour de cinco minutos.
* Migrando da v1? Comece pelo **[Guia de migração](migration.md)**.
* Atrás de uma assinatura exata? A **[Referência da API](api/mcp/index.md)** é gerada a partir do código-fonte.
* Lendo com um LLM? Esta documentação também é publicada no formato [llms.txt](https://llmstxt.org/):
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) é um índice das páginas, e
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) contém todas as páginas em um único arquivo.
