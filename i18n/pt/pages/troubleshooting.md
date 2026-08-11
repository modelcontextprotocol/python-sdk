---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Solução de problemas {#troubleshooting}

Cada título desta página é o texto exato de um erro que o SDK produz, seguido do que ele significa e da correção de um passo só. Procure aqui a última linha do seu traceback (ou do log do seu servidor) com a busca na página do navegador e leia apenas aquela entrada.

Várias entradas usam este mesmo servidor. Uma ferramenta (tool) e um recurso com template, cada um lançando uma exceção para uma cidade que não conhece:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Os erros que esta página cita são reais: a própria suíte de testes do SDK reproduz cada um deles.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Isto não é um erro do MCP. É ruído do anyio, e o seu erro de verdade é a **última linha** do que você colou.

`Client.__aenter__` inicia um task group. O anyio embrulha tudo o que sai de um task group em um `ExceptionGroup`, então *toda* exceção que escapa de um bloco `async with Client(...)`, seja ela qual for, chega dentro de um:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

Duas coisas a fazer com isso:

1. **Leia o final.** `MCPError: No forecast for 'Atlantis'.` é a falha; procure o texto *dela* nesta página.
2. **Capture dentro do bloco.** O `ExceptionGroup` só aparece quando a exceção *sai* do `async with`. Capturada lá dentro, a mesma falha é o `MCPError` puro, sem grupo nenhum:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    Uma falha durante a *conexão* (uma URL errada, um servidor que não está rodando, o `421` mais
    abaixo nesta página) escapa do próprio `async with`, então não existe um "dentro" onde
    capturá-la. Para essas, leia o final do grupo.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` só constrói o objeto. Nada se conecta até o `async with`, então todo método recusa:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Entre nele. `__aenter__` é a conexão:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` é a desconexão, e é por isso que não existe um `client.close()` para esquecer. **[Testes](get-started/testing.md)** se baseia exatamente nesse padrão.

## `Error executing tool <name>: <message>` e `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Você está lendo um **resultado**, não uma exceção. `call_tool` não lançou exceção, e nunca vai lançar para uma ferramenta que falha.

Chame `forecast` para uma cidade que o servidor não conhece, e a exceção que ela lança volta com a requisição marcada como *bem-sucedida*:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` é o mesmo formato para um nome que o servidor nunca registrou, e um argumento inválido é rejeitado do mesmo jeito, contra o schema de entrada da ferramenta, antes de a sua função sequer executar.

A correção está no seu cliente: **verifique `result.is_error`**. Um `try/except` em volta de `call_tool` não captura nenhum desses, porque não há nada para capturar. Isso é proposital, e é a coisa mais útil desta página para internalizar: foi o *modelo* que escolheu a chamada, então é o modelo que recebe a mensagem e uma chance de tentar de novo. **[Tratamento de erros](servers/handling-errors.md)** tem a história completa, incluindo o caminho do `MCPError` que *de fato* lança.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

Você escreveu `@mcp.tool` em vez de `@mcp.tool()`. `tool()` é uma *fábrica* de decoradores: sem os parênteses, o Python entrega a sua função ao parâmetro `name=` dela.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Adicione os parênteses. `@mcp.resource(...)` e `@mcp.prompt()` dizem a mesma coisa para o mesmo deslize.

!!! note
    Isso lança quando o módulo é **importado**, antes de qualquer cliente se conectar. Então um host
    que mostra o seu servidor como *falha ao iniciar* (ou *desconectado*), em vez de conectado com
    zero ferramentas, tem esse formato: execute `python server.py` você mesmo e leia o traceback. Um
    verificador de tipos também pega isso: uma função não é um `name=` válido.

## `Tool already exists: <name>` {#tool-already-exists-name}

Dois registros usaram o mesmo nome de ferramenta. O **primeiro** vence, o segundo é descartado em silêncio, e este aviso no *log do servidor* é o único sinal:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` reporta um `forecast`, e é o `forecast_today`. Renomeie um deles. `MCPServer(..., warn_on_duplicate_tools=False)` silencia o aviso sem mudar o resultado, então deixe ligado. Recursos e prompts têm a mesma regra e a mesma linha de log (`Resource already exists:`, `Prompt already exists:`).

## Meu host lista zero ferramentas {#my-host-lists-zero-tools}

Não existe string de erro para isso, e é exatamente por isso que é difícil de pesquisar. O SDK nunca descarta uma ferramenta registrada do `tools/list`, então vá de dentro para fora:

* **O servidor chegou a iniciar?** `@mcp.tool` sem parênteses lança no momento do import, e um servidor que caiu se parece muito com um vazio em alguns hosts. Execute `python server.py` você mesmo.
* **A ferramenta está no `mcp` que o host está executando?** Um segundo `MCPServer(...)` em outro módulo é um servidor diferente e vazio. Confira qual objeto o comando do host realmente importa.
* **Duas ferramentas compartilharam um nome?** Então uma delas sumiu. Procure `Tool already exists:` no log do servidor.
* **A lista do host está desatualizada?** Adicionar uma ferramenta depois da inicialização só chega a clientes que tratam `notifications/tools/list_changed`. Reiniciar o host é a correção bruta.
* **Algo escreveu em `stdout` fora da janela desviada?** Enquanto serve, o SDK desvia para stderr o stdout perdido que já passou por *flush* (na medida do possível: um ambiente que substitui os streams padrão é servido como está), mas saída descarregada em stdout antes disso (um script wrapper ecoando, um `print()` em tempo de import num processo sem buffer) ou um `print()` em buffer esvaziado na saída do interpretador cai no stream do protocolo, e uma única linha de lixo pode fazer o host derrubar a conexão, o que alguns hosts mostram como um servidor sem nada dentro. Use o módulo `logging` para registrar logs. O resto do checklist do lado do host está em **[Conecte a um host real](get-started/real-host.md)**.

Um nome de ferramenta "inválido" *não* está nessa lista: um nome fora do padrão registra um aviso no log, mas a ferramenta é registrada e listada mesmo assim.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

O servidor recusou a requisição HTTP de cara, com um corpo que não é JSON-RPC, então o `Client` python não tem nada melhor para mostrar do que este substituto.

De longe a causa mais comum é um servidor Streamable HTTP que acabou de passar pelo deploy. `streamable_http_app()` (e `mcp.run("streamable-http")`) sem `transport_security=` usa por padrão a **proteção contra DNS rebinding**: aceita apenas requisições cujo header `Host` é localhost. Esse é o padrão certo no seu laptop e o errado atrás de um hostname real:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Faça o deploy disso, aponte um cliente para ele, e a conexão falha no handshake:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

As palavras que o servidor de fato enviou, `421` e `Invalid Host header`, nunca chegam até você: o corpo do 421 não tem `Content-Type: application/json`, então o cliente não consegue fazer o parse dele. Elas estão no **log do servidor**, que é onde olhar em seguida:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

A correção é `transport_security=`. Coloque na allowlist o hostname que você de fato serve:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    A mudança inteira é essa. O cliente idêntico agora conecta, negocia `2026-07-28` e
    chama `forecast`.

**[Deploy e escala](run/deploy.md)** cobre o que cada campo significa, o caso do proxy reverso e tudo o mais que muda na hora do deploy. E `421 Misdirected Request` / `Invalid Host header`, logo abaixo, é a mesma falha vista do outro lado.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

Isto é `Server returned an error response`, visto de qualquer coisa que *não* seja o `Client` python: curl, a aba de rede de um navegador, o log de acesso de um proxy reverso ou outro SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` é a reason phrase do próprio HTTP para o status; `Invalid Host header` é o corpo de resposta do SDK; e o `Client` python mostra o mesmo evento como `Server returned an error response`. Os três são uma única recusa. A verificação roda contra o **header `Host` que a requisição carrega**, não contra o endereço em que o servidor fez o bind, então um proxy reverso que repassa o hostname público a dispara exatamente como um cliente direto.

A correção é o mesmo `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` mostrado em `Server returned an error response`. Vale nomear dois dos seus casos-limite:

* Uma entrada de `allowed_hosts` é uma string exata. `"mcp.example.com"` casa com um header `Host` sem porta e `"mcp.example.com:*"` casa com qualquer porta explícita. Liste as duas.
* Um `403` com o corpo `Invalid Origin header` é a verificação irmã no header `Origin`. Ela só dispara para navegadores (nada mais envia `Origin`), e `allowed_origins=` é a allowlist dela.

**[Deploy e escala](run/deploy.md)** tem o tratamento completo, inclusive quando desligar a verificação é a configuração honesta.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

Seu app MCP está montado dentro de outro app ASGI, e nada iniciou o **session manager** dele.

`mcp.streamable_http_app()` retorna um app Starlette cujo próprio lifespan inicia o manager, e `uvicorn server:app` executa esse lifespan para você. Mas o Starlette **nunca executa o lifespan de uma subaplicação montada**, então no momento em que o app vai para dentro de um `Mount`, o manager nunca inicia e a primeira requisição explode:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

O servidor inicia. A rota resolve. Aí o `uvicorn` imprime isto para cada requisição:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

O cliente vê um 500. A correção é um lifespan no app **host** que entra em `mcp.session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

**[Adicione a um app existente](run/asgi.md)** é a página para isso, incluindo vários servidores em um app só e FastAPI. Duas strings vizinhas da mesma classe:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` O manager é de uso único; entrar duas vezes no lifespan do mesmo app bate nela.
* `mcp.session_manager` só existe **depois** que `streamable_http_app()` foi chamado, então monte as rotas primeiro e toque no manager apenas dentro do lifespan.

## `MCPError: Session not found` {#mcperror-session-not-found}

O servidor não reconhece o `Mcp-Session-Id` que o seu cliente enviou, quase sempre porque o servidor **reiniciou** (ou você foi roteado para uma instância diferente). As sessões vivem na memória daquele único processo.

Não há bug de servidor para encontrar. A resposta HTTP é um `404` cujo corpo *é* JSON-RPC, então, ao contrário do `421` acima, o `Client` python mostra esta aqui palavra por palavra:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

A correção é reconectar: saia do bloco `async with Client(...)` e entre em um novo, que negocia uma sessão nova. Para um cliente de vida longa, isso significa capturar `MCPError` em volta das suas chamadas e reconectar ao ver esta mensagem, em vez de tentar de novo dentro de uma sessão morta.

Se isso acontece *sem* um reinício, você está rodando mais de um worker sem sticky sessions: cada worker mantém a própria tabela de sessões, então uma requisição roteada para o errado cai aqui. **[Deploy e escala](run/deploy.md)** e **[Atendendo clientes legados](run/legacy-clients.md)** são donos dessa história e das suas duas correções (roteamento sticky, ou `stateless_http=True`).

Para quem opera o servidor, a linha de log correspondente é `Rejected request with unknown or expired session ID: <id>`. Ela é registrada em `INFO`, então é invisível no limite usual de `WARNING`. Vê-la em rajadas logo depois de um deploy é normal; todo cliente conectado está reconectando.

## `MCPError: Method not found` {#mcperror-method-not-found}

Um lado enviou uma requisição JSON-RPC para a qual o outro não tem handler, e `e.error.data` nomeia o método. A causa usual é um **descompasso de era**: um método que existe em uma revisão do protocolo e não na outra, enviado a um par que está na errada, como um `resources/subscribe` da era `2025` chegando a uma conexão `2026-07-28`, ou um `subscriptions/listen` exclusivo de `2026` enviado por um cliente fixado em `mode="legacy"`. **[Versões do protocolo](protocol-versions.md)** é o mapa de qual lado fala o quê, e a outra causa honesta (uma capacidade opcional para a qual você nunca registrou um handler) está em **[Completions](servers/completions.md)**.

Uma coisa **não** produz este erro, apesar de ser uma requisição que o protocolo moderno removeu: uma ferramenta chamando `ctx.elicit()` em uma conexão `2026-07-28`. O servidor se recusa a sequer *enviar* essa requisição, então o que você recebe em vez disso é `Cannot send 'elicitation/create': ...`, mais abaixo nesta página.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Seu servidor quer perguntar algo ao usuário, e este cliente nunca disse que pode receber perguntas.

Um resolvedor de elicitação (elicitation) recusa logo de início quando o cliente conectado não declarou elicitação por formulário, e `e.error.data` nomeia exatamente o que falta:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Passe `elicitation_callback=` para `Client(...)`. Registrar o callback *é* a declaração da capacidade; não existe uma segunda chave:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[Callbacks do cliente](client/callbacks.md)** lista os outros (`sampling_callback`, `list_roots_callback`), cada um dos quais é uma declaração do mesmo jeito.

!!! info
    `-32021` é `MISSING_REQUIRED_CLIENT_CAPABILITY`, um dos três códigos de erro que a especificação
    2026-07-28 adiciona. Nenhum deles é uma classe de exceção: todos chegam como `MCPError`, e
    `e.error.code` é onde olhar. `mcp.types` exporta as constantes. Os outros dois são
    `-32020` `HEADER_MISMATCH` (um header HTTP discorda do corpo da requisição que ele acompanha)
    e `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (a requisição nomeou uma versão que este servidor não
    fala). Um cliente SDK em conformidade não consegue produzir nenhum dos dois, então, se você vir
    um, olhe para o que quer que esteja reescrevendo requisições entre o seu cliente e o seu servidor.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

A mesma lacuna de `Client did not declare the form elicitation capability ...`, escrita pelos caminhos que não verificam de início: o servidor precisava de uma elicitação respondida, e o cliente conectado não registrou nenhum `elicitation_callback`.

Você vê esta a partir de `ctx.elicit()` em uma conexão legada, e em qualquer conexão a partir de uma pergunta de múltiplas idas e voltas retornada (**[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)**) que chega a um cliente sem callback para respondê-la. A correção é idêntica: passe `elicitation_callback=` para `Client(...)`. Não existe versão de "o usuário não foi perguntado" que a sua ferramenta receba como um `decline`; um cliente que não pode receber perguntas é uma chamada que falhou, então projete as suas ferramentas para isso.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

Seu handler tentou alcançar o cliente no meio da requisição, em uma conexão cuja chamada não tem canal capaz de carregar uma requisição vinda do servidor. Há três configurações de servidor que colocam uma chamada nessa situação.

**Uma conexão `2026-07-28`: qualquer transporte, sempre.** O protocolo moderno não tem nenhuma requisição iniciada pelo servidor, então o servidor recusa antes que qualquer coisa seja enviada. `ctx.elicit()` dentro de uma ferramenta é o jeito clássico de topar com isso (logo no primeiro teste em memória, já que `Client(server)` negocia `2026-07-28` sem que ninguém peça), e passar `elicitation_callback=` não muda nada, porque nenhuma requisição chega ao cliente para ele responder:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**Uma conexão legada em um servidor `stateless_http=True`.** Ser stateless significa que cada requisição é um mundo próprio: sem sessão, sem stream do servidor para o cliente e, portanto, sem lugar para enviar um `elicitation/create` (ou `sampling/createMessage`, ou `roots/list`) mesmo na era que os tem:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**Uma conexão legada em um servidor `json_response=True`.** O `POST` é respondido com um único corpo JSON, e um único corpo carrega só a resposta, então o stream com escopo de requisição de que um `ctx.elicit()` no meio da requisição precisa também não existe aqui. A sessão, o `Mcp-Session-Id` dela e o stream avulso dela continuam todos lá; só o canal com escopo de requisição sumiu.

A mensagem nomeia o método que não conseguiu enviar. `NoBackChannelError` é a classe que o servidor lança, mas na rede trafega apenas o `MCPError` base, então a frase acima é a última linha do seu traceback, não o nome da classe.

Para um cliente `2026-07-28`, a correção é a mesma nas três: não tente voltar ao cliente no meio da chamada. Mova a pergunta para um **resolvedor** (ou retorne você mesmo um `InputRequiredResult`) e ela vira parte da *resposta*, que toda conexão consegue carregar:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Mesma pergunta, mesmo `elicitation_callback` no cliente. A diferença está por baixo dos panos: um resolvedor deixa o servidor *retornar* a pergunta a partir da chamada em vez de empurrá-la, então nada nunca flui do servidor para o cliente. Isso salva todo cliente `2026-07-28`, em qualquer das três configurações em que o servidor esteja. Um cliente *legado* não é salvo só pela reescrita: `2025-11-25` não tem como retornar uma pergunta, então em uma conexão legada o resolvedor ainda envia `elicitation/create` pelo canal com escopo de requisição, e ainda precisa de um servidor que o mantenha — nem `stateless_http=True` nem `json_response=True`. **[Elicitação](handlers/elicitation.md)** cobre resolvedores; **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md)** cobre o que acontece na rede.

!!! check
    A ferramenta com `ctx.elicit()` não está errada, ela é *pré-2026*. Conecte com `mode="legacy"`
    (o handshake `initialize` clássico, especificação `2025-11-25` e anteriores) a um servidor que não
    seja nem `stateless_http=True` nem `json_response=True`, e funciona, porque o canal do servidor
    para o cliente existe ali.
    **[Versões do protocolo](protocol-versions.md)** é a página sobre o que cada versão tem.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

O servidor não conseguiu verificar o token `requestState` que o seu cliente devolveu, então recusou a rodada.

`requestState` é o token opaco de retomada que uma chamada de **[múltiplas idas e voltas](handlers/multi-round-trip.md)** carrega entre um trecho e outro. O `MCPServer` o sela na saída e verifica cada devolução, e verifica *todo* `request_state` de entrada em `tools/call`, `prompts/get` e `resources/read`, mesmo para um handler que nunca emite um. Então um token que este processo não selou é recusado onde quer que ele caia:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

A mensagem é congelada de propósito: a rede nunca revela qual verificação falhou. O motivo vai para o **log do servidor**, e lê-lo é o diagnóstico inteiro:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Os motivos que você vai ver de fato:

* **`unknown key`** é o que importa. A chave de selagem padrão é gerada na inicialização do processo, então uma nova tentativa que cai em um **worker diferente**, em uma instância diferente atrás de um balanceador de carga, ou no mesmo servidor **depois de um reinício** foi selada com uma chave que este processo nunca teve. Isso não é um atacante; é o padrão encontrando mais de um processo.
* **`audience`**: o token foi selado por uma instância com um *nome de servidor diferente*. O nome é a claim de audience padrão do selo, então uma frota precisa compartilhar o nome (ou definir um `RequestStateSecurity(audience=...)` explícito) além das chaves.
* **`expired`**: a rodada demorou mais que o `ttl` do selo, que é de 600 segundos e por rodada, não por chamada.
* **`malformed`** / **`codec error`**: o token foi alterado em trânsito, ou nunca foi um token selado.
* **`request binding`**: o token voltou com uma ferramenta diferente, argumentos diferentes ou um método diferente.

A correção para múltiplos processos é um argumento (as *mesmas* `keys` em toda instância) mais uma coisa que nem argumento é: o mesmo *nome* de servidor (ou um `audience=` compartilhado explícito).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` sela; toda chave da lista verifica, e é isso que torna possível a rotação sem downtime. **[Requisições de múltiplas idas e voltas](handlers/multi-round-trip.md#protecting-requeststate)** explica o que o selo protege e a sequência de rotação, e **[Deploy e escala](run/deploy.md)** percorre a falha completa com dois workers e a sua correção em duas partes.

!!! tip
    `keys=[...]` recusa uma chave fraca na hora, com uma mensagem incomumente útil:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Faça o que ela diz.

## Ainda travado? {#still-stuck}

* Se uma mensagem que o SDK produziu não está nesta página, isso é um bug de documentação que vale reportar por si só.
* Pesquise no [issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues); a maioria das strings de erro que aparecem lá já é o relato de alguém.
* Não achou nada? [Abra uma issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) com o traceback completo, ou pergunte no [#python-sdk-dev no Discord MCP Contributors](https://discord.gg/6CSzBmMkjX).

## Recapitulando {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` nunca é o erro. Leia a **última linha**; capturar `MCPError` *dentro* do bloco `async with Client(...)` pula o embrulho por completo.
* `call_tool` não lança exceção para uma ferramenta que falha. `Error executing tool ...` e `Unknown tool: ...` são resultados: verifique `result.is_error`.
* `Client must be used within an async context manager` -> use `async with`. `Use @tool() instead of @tool` -> adicione os parênteses.
* `Tool already exists:` no log do servidor é o único sinal de que duas ferramentas com o mesmo nome viraram uma só.
* Um 421, três grafias: `Server returned an error response` (o `Client` python), `421 Misdirected Request` / `Invalid Host header` (todo o resto), `Invalid Host header: <host>` (o log do servidor). Correção: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> um app montado cujo lifespan do host nunca entrou em `mcp.session_manager.run()`.
* `Session not found` -> o servidor reiniciou; reconecte.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` precisa de um canal do servidor para o cliente: uma conexão `2026-07-28` nunca tem um, `stateless_http=True` tira o legado, e `json_response=True` tira o de escopo de requisição. Use um resolvedor (um cliente legado também precisa de um servidor que mantenha o canal). O vizinho `Method not found` é uma requisição para um método que a revisão do protocolo do outro lado não tem.
* `Client did not declare the form elicitation capability ...` e `Elicitation not supported` -> falta `elicitation_callback=` no cliente.
* `Invalid or expired requestState` nunca diz o porquê na rede. O log do servidor diz; `unknown key` significa compartilhar `RequestStateSecurity(keys=[...])` entre os workers.
