---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# Transportes do cliente {#client-transports}

Todo `Client` conversa com seu servidor por meio de um **transporte**: aquilo que de fato carrega as mensagens.

Você nunca configura um transporte separadamente. `Client` recebe um único argumento posicional e deduz o transporte a partir do tipo dele.

O lado do *servidor* de cada um (o que `mcp.run()` faz e o que você coloca no deploy) está em **[Executando seu servidor](../run/index.md)**.

## Em memória {#in-memory}

Passe o próprio objeto do servidor:

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

Sem subprocesso, sem porta, sem bytes trafegando na rede. O cliente e o servidor são dois objetos no mesmo processo, e a chamada ainda passa pela camada real do protocolo: `search_books` é listada, validada e invocada exatamente como seria sobre HTTP.

Isso faz dele duas coisas ao mesmo tempo:

* **Uma estrutura de testes.** Todo exemplo desta documentação é exercitado dessa forma, e a página **[Testes](../get-started/testing.md)** constrói o padrão inteiro em torno disso.
* **Uma API de embutimento.** Uma aplicação que constrói o servidor não precisa de um salto pela rede para chamar as ferramentas dele.

## Streamable HTTP {#streamable-http}

Passe uma string de URL e você tem **Streamable HTTP**, o transporte atrás do qual você faz o deploy:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

Esse é o cliente de produção inteiro. `Client` envolve a URL em `streamable_http_client(...)` para você, sobre um `httpx2.AsyncClient` configurado do jeito que o MCP precisa: `follow_redirects=True`, um timeout de 30 segundos para connect/write/pool e um timeout de leitura de 300 segundos, porque o servidor pode manter um stream de resposta aberto.

!!! check
    Um `Client` que você construiu **não** está conectado. A construção só escolhe o transporte;
    é o `async with` que o abre. Tente usar a conexão antes de entrar e o SDK avisa:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    Nada foi resolvido, buscado ou iniciado quando você escreveu `Client("http://...")`. Essa linha não custa nada.

### Traga seu próprio `httpx2.AsyncClient` {#bring-your-own-httpx2asyncclient}

No momento em que você precisar de um header `Authorization`, um cookie, um proxy, mTLS ou um timeout diferente, construa o `httpx2.AsyncClient` você mesmo e entregue-o a `streamable_http_client`:

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

Duas coisas para notar:

* Você é o dono do `httpx2.AsyncClient`, então é **você** quem entra e sai dele. O SDK nunca fecha um cliente que não criou.
* `streamable_http_client(url, http_client=...)` retorna um transporte, e `Client(transport)` o aceita como qualquer outra coisa.

Uma observação sobre TLS: `httpx2` verifica certificados contra o repositório de confiança do sistema operacional (via
[`truststore`](https://pypi.org/project/truststore/)), não contra uma lista de CAs embutida. Em um ambiente
sem um repositório de CAs do sistema utilizável (alguns contêineres mínimos), defina as variáveis de ambiente padrão
`SSL_CERT_FILE`/`SSL_CERT_DIR` ou passe um `verify=ssl_context` explícito ao seu `httpx2.AsyncClient`
(contexto em
[`httpx` e `httpx-sse` substituídos por `httpx2`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

!!! warning
    `streamable_http_client` costumava aceitar `headers=` e `timeout=` diretamente. Não aceita mais:
    seus únicos parâmetros são `url`, `http_client` e `terminate_on_close`. Use `headers=` por
    hábito e você recebe:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    Tudo que tem cara de HTTP agora vive no único `httpx2.AsyncClient` que você passa.

!!! info
    `httpx2` mantém a API conhecida do `httpx`, então se você conhece `httpx` já sabe como fazer auth,
    proxies, event hooks, retentativas e limites de conexão aqui. O SDK não acrescenta nada por cima nem
    tira nada. É também onde o OAuth se encaixa:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. Esse fluxo inteiro está em **[Clientes OAuth](oauth-clients.md)**.

## stdio {#stdio}

Um servidor **stdio** é um subprocesso. O cliente o inicia, escreve JSON-RPC no stdin dele e lê JSON-RPC do stdout dele. É assim que um host de desktop executa um servidor na sua máquina: um host *é* este código mais uma interface, e **[Conecte a um host real](../get-started/real-host.md)** é a mesma relação vista do lado do host, como um arquivo de configuração.

Descreva o processo com `StdioServerParameters`, transforme-o em um transporte com `stdio_client` e entregue *isso* ao `Client`:

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` não aceita o objeto de parâmetros sozinho. `StdioServerParameters` é configuração; `stdio_client(server)` é o transporte que sabe como iniciar um processo a partir dela. Sempre envolva.

Sair do bloco `async with` também encerra o subprocesso: fecha o stdin, espera e mata o processo se ele demorar. Você nunca limpa isso por conta própria.

!!! warning
    O processo filho **não** herda o seu ambiente. Ele recebe uma allow-list mínima (`HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` e `USER` no POSIX), para que nada sensível vaze para um processo que talvez
    não tenha sido escrito por você.

    Um servidor que precise de uma chave de API não vai encontrá-la ali. Passe-a explicitamente com `env=`; essas
    variáveis são mescladas por cima da allow-list. É isso que `BOOKSHOP_API_KEY` está fazendo acima.

## SSE {#sse}

`sse_client(url)`, de `mcp.client.sse`, é o transporte HTTP que o Streamable HTTP substituiu. Envolva-o da mesma forma, `Client(sse_client("http://localhost:8000/sse"))`, para conversar com um servidor que ainda o fala, e não construa nada novo em cima dele.

## O protocolo `Transport` {#the-transport-protocol}

Para o `Client`, tudo acima é a mesma coisa.

Um **transporte** é qualquer gerenciador de contexto assíncrono que produz um par `(read, write)` de streams de mensagens: formalmente, o protocolo `Transport` em `mcp.client`. `Client` resolve seu argumento pelo tipo: um objeto de servidor conecta no próprio processo, uma `str` vira `streamable_http_client(url)` e qualquer outra coisa é aberta diretamente como transporte. É por causa dessa última regra que `stdio_client(...)`, `streamable_http_client(...)` e `sse_client(...)` se encaixam todos no mesmo lugar, e que você pode escrever o seu próprio.

## Recapitulando {#recap}

* `Client(mcp)` (o objeto do servidor) conecta em memória. Use para testes e para embutir.
* `Client("http://.../mcp")` (uma URL) conecta por Streamable HTTP, o transporte de produção.
* Headers, auth, proxies e timeouts pertencem a um `httpx2.AsyncClient` que você passa a `streamable_http_client(url, http_client=...)`. Não existe o argumento `headers=`.
* stdio é `Client(stdio_client(StdioServerParameters(...)))`, nunca o objeto de parâmetros sozinho.
* O subprocesso recebe um ambiente em allow-list, não o seu; `env=` acrescenta a ele.
* Um transporte é qualquer coisa com que você possa fazer `async with x as (read, write)`. `Client` entrega direto a esse protocolo tudo que não for um objeto de servidor ou uma URL.
* Construir um `Client` escolhe o transporte. `async with` o abre.

Depois que o transporte está aberto, os dois lados precisam concordar sobre uma versão do protocolo. Normalmente você nunca pensa nisso; quando pensar, **[Versões do protocolo](../protocol-versions.md)** é a página.
