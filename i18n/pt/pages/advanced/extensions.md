---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# Extensões {#extensions}

Uma **extensão** é um pacote opcional de comportamento MCP reunido sob um único identificador.

Em um servidor, ela pode contribuir com ferramentas (tools), recursos e novos métodos de requisição, e pode envolver `tools/call`. Em um cliente, ela pode reivindicar formatos extras de resultado de `tools/call` e observar notificações de fornecedores. Cada lado se anuncia no seu próprio `capabilities.extensions`, e nada muda para quem não pediu nada. Esse é o contrato ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)), e ele tem uma regra de ouro: **extensões vêm desligadas por padrão**.

## Usando uma extensão {#using-an-extension}

Passe as instâncias na construção:

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

Pronto. O servidor agora anuncia `io.modelcontextprotocol/ui` em `capabilities.extensions` e serve tudo o que a extensão contribui.

`Apps` é a extensão de referência embutida, e ela tem uma página própria: **[MCP Apps](apps.md)**.

!!! note
    As extensões são fixadas na construção. Não existe um `add_extension` para chamar depois: o mapa de capacidades de um servidor não deve mudar enquanto há clientes conectados a ele.

O mapa de capacidades viaja em `server/discover`, que é um caminho da **2026-07-28**. Um handshake `initialize` legado não tem onde colocá-lo, então um cliente legado simplesmente não enxerga a extensão. Projete pensando nisso: uma extensão *amplia* um servidor, ela não pode ser a única forma de usá-lo.

## Escrevendo a sua {#writing-your-own}

Herde de `Extension` e sobrescreva apenas o que precisar. Todo método tem um padrão.

### O identificador {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

O identificador é uma string `vendor-prefix/name` que segue a gramática de chaves `_meta` da especificação: rótulos separados por ponto (cada um começa com uma letra e termina com uma letra ou dígito), uma barra e então o nome. Ele é validado **quando a classe é definida**, então um erro de digitação não espera o servidor subir:

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

Use como prefixo um domínio que você controla. `io.modelcontextprotocol/*` é reservado para extensões especificadas pelo próprio projeto MCP.

### Contribuindo com ferramentas {#contributing-tools}

A menor extensão útil é uma ferramenta e um mapa de configurações:

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` retorna `ToolBinding`s. O servidor registra cada uma exatamente como se você tivesse chamado `mcp.add_tool(...)` por conta própria: mesma geração de schema, mesma injeção de `Context`, tudo igual.
* `settings()` é o valor anunciado em `capabilities.extensions["com.example/stamps"]`. Retorne `{}` (o padrão) para anunciar a extensão sem configurações.
* A extensão nunca recebe o servidor. Ela declara contribuições como dados; o `MCPServer` as consome. Não existe um `self.server` para modificar.

E `main()` é a prova, um cliente em memória direto contra `mcp`:

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### Servindo seus próprios métodos {#serving-your-own-methods}

Uma extensão pode registrar **novos métodos de requisição**: seus próprios verbos, servidos ao lado dos da especificação:

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` herda de `RequestParams`, então o envelope `_meta` de 2026 é analisado de forma uniforme e seu handler recebe parâmetros validados, nunca um dict cru. Limite o que o cliente controla: `Field(ge=1, le=100)` rejeita um `limit` absurdo antes que seu código aloque qualquer coisa para ele.
* `require_client_extension(ctx, EXTENSION_ID)` é a barreira: um cliente que não declarou a extensão recebe o erro `-32021` (capacidade obrigatória do cliente ausente), com o payload `requiredCapabilities` legível por máquina que a especificação pede.
* `protocol_versions=frozenset({"2026-07-28"})` fixa o método em uma única versão de protocolo. Em qualquer outra versão o cliente recebe `METHOD_NOT_FOUND`, exatamente como se o método não existisse ali. Para esse cliente, não existe.

Os métodos são **estritamente aditivos**. O SDK impõe isso na construção, não em tempo de execução:

* Um `MethodBinding` para um método definido pela especificação (`tools/list`, `completion/complete`, ...) lança `ValueError` quando o binding é construído. Os verbos centrais pertencem ao servidor.
* Duas extensões vinculando o mesmo método lançam quando a segunda se registra. A última escrita vencer é como plugins corrompem uns aos outros; não fazemos isso.
* Um conjunto `protocol_versions` vazio também lança: um método que nunca pode ser servido é um bug, não uma configuração.

### O lado do cliente {#the-client-side}

O `main()` do mesmo arquivo é a história inteira do cliente, com as duas metades:

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` declara a extensão. As declarações viram `ClientCapabilities.extensions`: em uma conexão 2026-07-28 o mapa viaja no envelope `_meta` de cada requisição, então o servidor o vê em **toda** requisição; em uma conexão legada ele vai no handshake `initialize`. O código do servidor não se importa com qual: `require_client_extension(ctx, ...)` e `ctx.session.check_client_capability(...)` leem a fonte certa nos dois caminhos.
* Métodos de fornecedor descem uma camada para `client.session.send_request(...)`; `Client` só ganha métodos de primeira classe para verbos da especificação. `send_request` aceita qualquer subclasse de `Request`, então a requisição do fornecedor passa como está.

### Interceptando `tools/call` {#intercepting-toolscall}

O único hook interceptador. Sobrescreva `intercept_tool_call` para observar, curto-circuitar ou vetar uma chamada de ferramenta:

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` é o `CallToolRequestParams` validado: você recebe `params.name` e `params.arguments` sem tocar em JSON cru. É também o que decide qual chamada de ferramenta é executada: passar um contexto reescrito por `call_next` muda o que o handler observa em `ctx`, não a invocação da ferramenta. Reescrita de requisição no nível do protocolo pertence ao [Middleware](middleware.md).
* `call_next(ctx)` executa o resto da cadeia e retorna o resultado do handler. Retorne-o sem alterações (observar), retorne outra coisa (substituir) ou lance um `MCPError` (recusar). O que você retornar é serializado como qualquer resultado de handler, incluindo o carimbo de identidade `serverInfo` da era 2026, então um interceptador que curto-circuita nunca produz uma resposta anônima ou fora do schema.
* Com várias extensões, os interceptadores se aninham na ordem de registro: a primeira extensão em `extensions=[...]` é a mais externa.
* A implementação padrão é um repasse direto, e um servidor cujas extensões nunca sobrescrevem esse hook mantém o handler puro de `tools/call` intocado. Você não paga pelo que não usa.

O hook envolve `tools/call` e nada mais. Para preocupações que valem para toda mensagem, use o [Middleware](middleware.md). É para isso que ele serve.

## Usando uma extensão de cliente {#using-a-client-extension}

Uma **extensão de cliente** é o mesmo contrato visto do lado consumidor: um pacote de comportamento do lado do cliente reunido sob um único identificador. Passe as instâncias para `Client(extensions=[...])` e chame as ferramentas normalmente:

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` retorna um `CallToolResult` comum, como toda outra chamada. O que a extensão mudou: o servidor agora pode responder a `buy` com um **formato de resultado** `receipt` em vez de um resultado final, e `Receipts` o finaliza (aqui, resgatando o recibo com uma chamada seguinte) antes de `call_tool` retornar. Nada muda no ponto da chamada.

Tire a extensão e nada disso existe: a barreira do servidor recusa um cliente que não a declarou (erro -32021), e um formato reivindicado vindo de um servidor que pula a barreira falha na validação, exatamente como a especificação exige para um `resultType` não reconhecido. Desligado por padrão, nas duas pontas da conexão.

Para anunciar um identificador **sem** nenhum comportamento do lado do cliente (o servidor faz a barreira pela capacidade, o cliente não faz nada, como no cliente de busca acima), use `advertise()`:

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## Escrevendo uma extensão de cliente {#writing-a-client-extension}

Herde de `ClientExtension` e sobrescreva apenas o que precisar. Três tipos de contribuição, cada um com um padrão: `settings()`, `claims()` e `notifications()`.

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* O identificador segue a mesma gramática do servidor, validada quando a classe é definida.
* `claims()` retorna `ResultClaim`s: uma tag de protocolo, o modelo que a analisa e o resolvedor que a finaliza. O modelo precisa fixar a tag com `result_type: Literal["receipt"]` e não pode herdar dos tipos de resultado centrais do verbo; as duas coisas são impostas quando a claim é construída. Campos de fornecedor como `receipt_token` viajam pela conexão como estão: um formato substituído chega ao cliente literalmente.
* O resolvedor recebe o modelo analisado e um `ClaimContext`; `ctx.session` é o mesmo handle público que `client.session`, então as chamadas seguintes são chamadas comuns de sessão. Ele retorna o `CallToolResult` normal do verbo.
* `settings()` é o valor anunciado em `ClientCapabilities.extensions[identifier]`, lido uma vez na construção do `Client`.

`notifications()` declara notificações de servidor de fornecedor a observar:

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

O handler recebe parâmetros validados um de cada vez, na ordem de despacho. Ele observa; não pode vetar nem responder.

Duas regras discretas. As claims ficam ativas apenas em conexões 2026-07-28, e o anúncio de capacidade as acompanha: em uma conexão legada as claims se dissolvem e o identificador sai do anúncio junto com elas, então o cliente nunca anuncia uma extensão cujos formatos ele rejeitaria. E quando você mesmo quer o formato reivindicado em vez do resolvedor, chame `client.session.call_tool(..., allow_claimed=True)`; sem essa flag, um formato reivindicado que chega a um chamador no nível da sessão lança `UnexpectedClaimedResult`.

### Verbos de extensão {#extension-verbs}

Os métodos de requisição próprios de uma extensão não precisam de registro no lado do cliente. Um tipo de requisição de fornecedor herda de `mcp.types.Request` e passa por `client.session.send_request`, como em [Servindo seus próprios métodos](#serving-your-own-methods). Um acréscimo: quando uma chave de params precisa viajar no header `Mcp-Name` (especificações de extensão como tasks exigem isso para seus verbos), o tipo de requisição declara `name_param`:

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

A sessão espelha `params["jobId"]` em `Mcp-Name` em todo caminho de envio, e um valor ausente falha de forma explícita em vez de omitir silenciosamente um header obrigatório.

## O que uma extensão não pode fazer {#what-an-extension-cannot-do}

A superfície de contribuição é **fechada** de propósito. No servidor: configurações, ferramentas, recursos, métodos, um interceptador de `tools/call`. No cliente: configurações, claims de resultado, bindings de notificação. Uma extensão não pode:

* **Alcançar o host.** Ela declara dados; não guarda nenhuma referência ao servidor nem ao cliente.
* **Substituir comportamento central.** Métodos da especificação e tags de resultado centrais são rejeitados na construção (`initialize` é reservado pelo runner sem exceção); já um binding de notificação encoberto pelo vocabulário central fica em silêncio com um aviso.
* **Registrar-se depois.** Depois que `MCPServer(...)` ou `Client(...)` retorna, o conjunto de extensões é o que é.

Se você está brigando com essas paredes, não está escrevendo uma extensão. Está escrevendo um fork. As paredes são a funcionalidade: um usuário que lê `extensions=[Apps(), Stamps()]` sabe *tudo* o que essas duas podem ter tocado.
