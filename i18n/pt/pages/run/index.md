---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# Executando seu servidor {#running-your-server}

`mcp.run()` inicia o servidor.

A única decisão que você toma é o **transporte**: como os bytes entre seu servidor e o cliente realmente trafegam.

## Escolha um transporte {#pick-a-transport}

| Transporte | O que é | Quando |
|---|---|---|
| `stdio` | O host inicia seu arquivo como um subprocesso e conversa pelo stdin e stdout dele. | Servidores locais. O padrão. |
| `streamable-http` | Um servidor HTTP de verdade, escutando em uma porta. | Tudo o que você faz deploy. |
| `sse` | O transporte HTTP antigo. | Nunca. |

!!! warning
    O SSE foi substituído pelo Streamable HTTP na revisão 2025-03-26 do protocolo.
    `mcp.run(transport="sse")` ainda funciona, com suas próprias opções `sse_path=` e `message_path=`,
    mas existe apenas para clientes que ainda não migraram. Não construa nada novo em cima dele.

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` é síncrono. Ele bloqueia durante toda a vida do servidor.
* Sem argumentos, o transporte é `stdio`.
* Ele fica sob `if __name__ == "__main__":` porque tudo o que carrega seu servidor (`mcp dev`, `mcp run`, `mcp install`, seus testes) **importa** este arquivo. A guarda impede que um import vire um servidor em execução.

### stdio {#stdio}

Não há nada para configurar. O host inicia seu arquivo como processo filho, escreve requisições no stdin dele e lê respostas do stdout.

Execute você mesmo e veja a consequência:

```console
python server.py
```

Nada é impresso, e ele não retorna. Está esperando no stdin que um host fale primeiro.

Isso também significa que o stdout **é o canal de comunicação**. Enquanto serve, o SDK move esse canal para um descritor privado e desvia para o stderr a saída que é *descarregada* (flushed) no stdout (um subprocesso escrevendo no stdout herdado, um `print()` com flush), onde ela não pode corromper o fluxo. A saída descarregada no stdout *antes* de o servidor começar a servir (um script wrapper fazendo echo, um print sem buffer em tempo de import) ainda cai no canal, assim como um `print()` que fica no buffer até o interpretador esvaziá-lo na saída. Para a saída que você realmente quer, o módulo `logging` é a ferramenta certa: o handler dele descarrega cada registro no stderr assim que acontece. Essa história está em **[Logging](../handlers/logging.md)**.

### Experimente {#try-it}

```console
uv run mcp dev server.py
```

O Inspector faz exatamente o que um host de verdade faz: inicia `server.py` como subprocesso e se conecta a ele via stdio.

Você nunca informou uma porta. Não existe nenhuma.

## Streamable HTTP {#streamable-http}

Para colocar o mesmo servidor em uma porta, nomeie o transporte (e suas opções) em `run()`:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

Essa única linha monta um app Starlette e o serve com uvicorn. Os clientes se conectam em `http://127.0.0.1:3001/mcp`.

Cada transporte tem seus próprios argumentos nomeados, todos em `run()`:

* `host` / `port`: onde escutar. Padrões `127.0.0.1` e `8000`.
* `streamable_http_path`: onde fica o endpoint MCP. Padrão `/mcp`.
* `json_response=True`: responde a cada POST com um único corpo JSON em vez de um fluxo SSE. Esse corpo tem espaço para a resposta e nada mais, então uma ferramenta que chama o cliente de volta no meio da requisição (`ctx.elicit()`, amostragem (sampling)) lança `NoBackChannelError` nesse trecho, e as notificações ligadas à chamada em andamento (progresso de `ctx.report_progress()`, mensagens de log por chamada) são descartadas; o fluxo `GET` avulso continua transportando as que não têm relação.
* `stateless_http=True`: um transporte novo por requisição, sem rastreamento de sessão.
* `max_request_body_size`: maior corpo de POST aceito, em bytes. O padrão é 4 MiB; requisições maiores
  recebem HTTP 413 antes do parsing ou da criação da sessão. Aumente apenas quando mensagens MCP legítimas
  ultrapassarem esse tamanho.
* `event_store`, `retry_interval`, `transport_security`: retomada e proteção contra DNS rebinding. Podem esperar até você fazer o deploy em algum lugar que não seja o localhost; **[Deploy e escala](deploy.md)** cobre `transport_security`.

!!! warning
    As opções de transporte vão para `run()`, **não** para `MCPServer(...)`. O construtor descreve o que
    seu servidor *é*: nome, versão, instruções. `run()` descreve como ele é servido. Inverta isso
    e o Python responde antes mesmo de o MCP entrar em cena:

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` é o caminho curto. No momento em que você precisar de mais (seu servidor montado dentro de um app existente, dois servidores em um só processo, CORS para clientes no navegador), monte o app ASGI você mesmo e entregue a qualquer host ASGI. Isso está em **[Adicione a um app existente](asgi.md)**.

## Configurações do servidor {#server-settings}

Algumas coisas relacionadas à execução não dizem respeito ao transporte. São argumentos do construtor:

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: passado para `logging.basicConfig()` no momento em que `MCPServer(...)` é construído. Isso configura o logger **raiz**, então define o nível dos seus próprios loggers também, não só os do SDK. Padrão `"INFO"`.
* `debug`: repassado ao app Starlette que os transportes HTTP montam. Padrão `False`.

Ambos vão parar em `mcp.settings`, que você pode ler de volta em tempo de execução.

## O comando `mcp` {#the-mcp-command}

O extra `[cli]` instala uma pequena ferramenta de linha de comando em torno de tudo isso.

`mcp dev` executa seu servidor sob o **MCP Inspector**:

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` adiciona pacotes ao ambiente que ele monta; `--with-editable` instala seu próprio pacote nele. Ele precisa de `npx` no seu `PATH`: o Inspector é um app Node.js.

`mcp run` importa o arquivo, encontra o objeto do servidor (um `mcp`, `server` ou `app` no nível do módulo) e chama `run()` nele:

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

O sufixo `:` nomeia o objeto quando ele não se chama `mcp`, `server` ou `app`.

Seu bloco `if __name__ == "__main__":` nunca executa aqui: o próprio `mcp run` chama `run()`, e a única opção que ele repassa é `--transport`.

`mcp install` registra o servidor no **Claude Desktop**, para que o app o inicie por você:

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` e `-f .env` gravam variáveis de ambiente nessa entrada. O Claude Desktop inicia seu servidor em um processo próprio. O ambiente do seu shell não está lá.

O Claude Desktop é o único host que `mcp install` conhece. Todos os outros hosts (Claude Code, Cursor, VS Code) aceitam o mesmo comando de inicialização no próprio arquivo de configuração, e **[Conecte a um host de verdade](../get-started/real-host.md)** tem cada um deles.

`mcp version` imprime a versão do SDK instalada.

!!! tip
    `mcp dev` e `mcp run` só entendem `MCPServer`. Se você constrói com o `Server` de baixo nível,
    você mesmo o executa. Veja **[O Server de baixo nível](../advanced/low-level-server.md)**.

## Recapitulando {#recap}

* Um **transporte** é como os bytes chegam ao seu servidor: `stdio` para um subprocesso local, `streamable-http` para uma porta. O SSE foi substituído.
* `mcp.run()` escolhe o transporte. Sem argumentos é `stdio`, e ele bloqueia.
* Toda opção de transporte (`host`, `port`, `streamable_http_path`, ...) é um argumento de `run()`, nunca de `MCPServer(...)`.
* Mantenha `run()` sob `if __name__ == "__main__":`. Tudo o que carrega seu servidor importa o arquivo primeiro.
* `log_level=` e `debug=` são argumentos do construtor; eles vão parar em `mcp.settings`.
* `mcp dev` para o Inspector, `mcp run` para executar um arquivo, `mcp install` para o Claude Desktop, `mcp version` para a versão.
* O transporte nunca muda o que seu servidor *é*: os três arquivos desta página expõem exatamente a mesma ferramenta.

Quando o próprio `run()` é o limite (seu servidor dentro de um app que já existe), o caminho é **[Adicione a um app existente](asgi.md)**. Um hostname de verdade e mais de um worker é **[Deploy e escala](deploy.md)**. E se alguns dos seus clientes ainda estão na versão 2025-11-25 da especificação ou anterior, **[Servindo clientes legados](legacy-clients.md)** traz as boas notícias.
