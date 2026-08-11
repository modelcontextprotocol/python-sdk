---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# Requisições com múltiplas idas e voltas {#multi-round-trip-requests}

Às vezes uma ferramenta (tool) não consegue terminar em uma única ida e volta. Ela precisa de algo que só o usuário tem: uma escolha, uma confirmação, uma credencial.

Antes de 2026-07-28 o servidor conseguia isso chamando **de volta**: abria sua própria requisição para o cliente (uma elicitação (elicitation), uma chamada de amostragem (sampling)) no meio do tratamento da requisição original. A especificação 2026-07-28 aposenta esse canal de retorno (back-channel).

Em vez disso, o servidor **retorna**.

## Retorne, não chame de volta {#return-dont-call-back}

O servidor responde a `tools/call` com um **`InputRequiredResult`** no lugar de um `CallToolResult`. Dois dos seus campos fazem o trabalho:

* **`input_requests`**: o que o servidor ainda precisa, como um dict cujas chaves são nomes que o próprio servidor escolheu. Cada valor é um `ElicitRequest`, um `CreateMessageRequest` ou um `ListRootsRequest`.
* **`request_state`**: um token opaco. O cliente o devolve ao pé da letra na nova tentativa. Seu servidor é o único que o lê.

O cliente atende cada requisição e então chama a **mesma ferramenta de novo**, levando suas respostas em `input_responses` e o token em `request_state`. Agora o servidor tem o que faltava e retorna um `CallToolResult` normal.

O protocolo inteiro é esse. Cada trecho é uma requisição comum do cliente para o servidor. Nada jamais flui no sentido contrário.

## O lado do servidor {#the-server-side}

Em `@mcp.tool()` você raramente monta isso à mão: declare uma dependência que pergunta ao usuário (`Elicit`), faz amostragem no LLM do cliente (`Sample`) ou lista os roots dele (`ListRoots`) e o SDK retorna o `InputRequiredResult` por você; essa forma está na página **[Dependências](dependencies.md)**. As duas formas não se misturam: uma chamada tem um único canal `input_responses`/`request_state`, então uma ferramenta que usa parâmetros `Resolve(...)` não pode também retornar `InputRequiredResult` do seu corpo. Um retorno `InputRequiredResult` declarado é rejeitado no registro (`InvalidSignature`), e um não declarado faz a chamada falhar em tempo de execução. A forma manual é o `Server` de **baixo nível**, cujo handler `on_call_tool` pode retornar qualquer um dos dois tipos de resultado:

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` tem o tipo `-> CallToolResult | InputRequiredResult`. Retornar o segundo é a API inteira do lado do servidor.
* Na primeira chamada `params.input_responses` é `None`, então a guarda dispara e o handler pergunta em vez de responder.
* Na nova tentativa, o `ElicitResult` que o cliente enviou está sob a **mesma chave** (`"region"`) que o servidor usou em `input_requests`.

Todo o resto naquele arquivo (o `input_schema` explícito, o `CallToolResult` montado à mão) é o `Server` de baixo nível comum, coberto em **[O Server de baixo nível](../advanced/low-level-server.md)**. Esta página só acrescenta o segundo tipo de retorno.

## Além das ferramentas {#beyond-tools}

`tools/call` não é especial: em 2026-07-28 um servidor pode responder a `prompts/get` e `resources/read` do mesmo jeito. No `MCPServer`, uma função `@mcp.prompt()` — ou uma função de **template** `@mcp.resource()` — retorna ela mesma o `InputRequiredResult` e lê as respostas da nova tentativa no contexto:

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* A primeira rodada retorna o `InputRequiredResult`. Na nova tentativa, `ctx.input_responses` traz as respostas sob as mesmas chaves e a função retorna seu resultado comum — mensagens de prompt aqui, conteúdo de recurso para um recurso de template.
* Um `request_state` que você define é selado antes de passar pela rede e verificado no eco, como todo o resto no servidor; **[Protegendo o `requestState`](#protecting-requeststate)** mais abaixo cobre o que o selo oferece e quando você precisa configurar chaves.
* Uma função `@mcp.tool()` pode retornar o resultado diretamente do mesmo jeito, quando a forma por dependência não serve.
* Funções `@mcp.resource()` estáticas não participam: elas não recebem `Context`, então nunca poderiam ler a nova tentativa. Só recursos de template podem perguntar.
* As regras de era mais abaixo valem sem mudança: retornar um `InputRequiredResult` em uma sessão pré-2026 é o mesmo `-32603` que o aviso descreve.

## O lado do cliente {#the-client-side}

O `Client` executa o loop por você.

Registre os callbacks que o servidor pode pedir (`elicitation_callback`, `sampling_callback`, `list_roots_callback`) e chame a ferramenta. Quando chega um `InputRequiredResult`, o `Client` despacha cada entrada de `input_requests` para o callback correspondente, tenta de novo com as respostas e o `request_state` ecoado, e segue em frente até que um `CallToolResult` volte:

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* Esse `elicitation_callback` é o mesmo que o `elicitation/create` do canal de retorno de um servidor pré-2026 teria acionado. O mesmo vale para `sampling_callback` em relação a `sampling/createMessage` e para `list_roots_callback` em relação a `roots/list`: em 2026-07-28 os RPCs avulsos servidor->cliente deixaram de existir, mas os mesmíssimos payloads `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` viajam dentro de `input_requests` e são despachados para os mesmos três callbacks. Um único conjunto de callbacks atende às duas eras.
* `call_tool` retorna um `CallToolResult` simples. As rodadas intermediárias são invisíveis para quem chama.
* `get_prompt` e `read_resource` conduzem o mesmo loop.

!!! check
    Deixe o callback de fora e o loop falha na primeira rodada: o callback substituto do SDK
    responde a toda elicitação com um erro, e `call_tool` lança `MCPError` com a mensagem
    *"Elicitation not supported"*.

O loop tem limite. `Client(..., input_required_max_rounds=10)` é o teto padrão; um servidor que continua retornando `InputRequiredResult` além dele faz `call_tool` lançar. Se uma rodada traz apenas `request_state` e nenhum `input_requests`, o `Client` dorme brevemente (50 ms, dobrando até um teto de 250 ms) antes de tentar de novo, de modo que um servidor que está só dizendo *"ainda não terminei"* não sofre busy-polling.

### Conduzindo o loop você mesmo {#driving-the-loop-yourself}

O loop automático basta para um cliente de processo único. Assuma o loop você mesmo quando:

* Seu cliente é **distribuído**: o processo que exibe a pergunta ao usuário não é o processo que chamou `call_tool`, então um worker diferente emite a nova tentativa. `request_state` é o token persistível que você carrega através dessa fronteira, pelo seu próprio armazenamento, e `input_responses` é o que o outro lado envia de volta junto com ele.
* Você quer **inspecionar** cada rodada: registrar em log ou auditar cada entrada de `input_requests`, recusar certos tipos de requisição ou aplicar seu próprio backoff entre os trechos.
* Você quer um limite de **relógio** em vez de um limite por contagem de rodadas: envolva seu próprio loop em `anyio.fail_after(...)` em vez de depender de `input_required_max_rounds`.

Desça para a sessão subjacente, onde `allow_input_required=True` entrega a união diretamente:

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` amplia o tipo de retorno para `CallToolResult | InputRequiredResult`. O `isinstance` é o que o estreita de volta.
* `request_state` agora está nas suas mãos. Anote-o entre os trechos e a conversa pode ser retomada a partir de um processo novo.
* Para cada entrada em `input_requests` você coloca um `InputResponse` sob a **mesma chave** em `input_responses`. `fulfil` é onde entra sua UI; esta aqui fixa a resposta no código.
* Mesmo nome de ferramenta, mesmos `arguments`, em todo trecho. A nova tentativa é a chamada original realizada de novo, não um método novo.

## Protegendo o `requestState` {#protecting-requeststate}

Tudo acima trata `request_state` como um eco, e na rede é só isso mesmo. Mas o cliente o guarda entre os trechos (anotá-lo entre processos é exatamente o que a seção anterior aprovou), então o que volta é **entrada fornecida pelo cliente**: pode estar modificada, expirada ou ter sido retirada de uma chamada completamente diferente. A especificação exige que os servidores protejam a integridade desse estado e rejeitem a rodada quando a verificação falhar, sempre que o estado puder influenciar autorização, acesso a recursos ou lógica de negócio.

O `MCPServer` o protege por padrão. Todo servidor sela o `requestState` de saída e verifica todo eco — estado de resolvedor e estado montado à mão do mesmo jeito — sob uma chave gerada na inicialização do processo. Você não configura nada, escreve texto puro e lê texto puro; pela rede só passa um token opaco e criptografado.

A chave padrão vive e morre com o processo, e essa é a única coisa que você precisa saber antes de fazer o deploy além de um único processo:

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **O padrão (sem configuração)** serve para um único processo: stdio, ou exatamente um worker HTTP. Uma nova tentativa que cai em um worker diferente, em uma instância diferente atrás de um balanceador de carga ou no mesmo servidor depois de um reinício está selada sob uma chave que aquele processo não tem — o cliente recebe a rejeição fixa mostrada abaixo e precisa recomeçar o fluxo.
* **`keys=[...]`** é obrigatório sempre que uma nova tentativa pode chegar a uma **instância diferente** (`uvicorn` com múltiplos workers, HTTP com balanceamento de carga) ou precisa sobreviver a reinícios: cada instância verifica o que qualquer irmã emitiu. Mesma engrenagem, seu segredo em vez de um gerado.
* Para sua própria criptografia, como um KMS ou um serviço de tokens existente, passe `RequestStateSecurity(codec=...)` em vez de `keys`; **[Traga sua própria criptografia](#bring-your-own-crypto)** mais abaixo cobre o contrato.

### O que o selo carrega {#what-the-seal-carries}

Padrão ou configurado, o `requestState` na rede é um token criptografado e autenticado. Seu código nunca o vê: handlers e resolvedores escrevem texto puro e leem texto puro (`ctx.request_state`); o SDK sela na saída e verifica na entrada. Além da integridade, cada token fica vinculado a:

* **Uma janela de tempo.** Cada rodada sela de novo com uma expiração nova, então `RequestStateSecurity(ttl=...)` (padrão de 600 segundos) limita o tempo de reflexão por rodada, não o fluxo inteiro.
* **O principal autenticado.** Quando a requisição carrega um token de acesso OAuth que o SDK validou, o estado fica vinculado ao cliente, ao emissor e ao sujeito do token: estado emitido para um usuário falha sob outro, mesmo quando os dois compartilham um único cliente OAuth. Um verificador que não fornece sujeito degrada o vínculo para apenas a identidade do cliente, que com IDs de cliente baseados em URL é compartilhada por todos os usuários daquele software cliente. Quando a autenticação é encerrada fora do SDK (um proxy na frente), ou o transporte não é autenticado, não há principal a vincular e essa verificação fica inerte, a menos que `RequestStateSecurity(bind_principal=...)` forneça um a partir do seu próprio sinal de identidade. Quaisquer que sejam os componentes que seu verificador de tokens forneça, ele precisa fornecê-los de forma consistente: um verificador que inclui o sujeito em algumas requisições e o omite em outras muda o principal no meio do fluxo, e as rodadas em andamento são rejeitadas.
* **A requisição de origem.** O método, o nome da ferramenta ou do prompt (ou a URI do recurso) e um digest dos argumentos. Um token reproduzido contra uma ferramenta diferente, argumentos diferentes ou um método diferente falha.
* **A pergunta exata que foi feita.** Toda resposta de resolvedor fica presa à pergunta renderizada que foi mostrada ao cliente, tanto na rodada em que ela chega pela primeira vez quanto quando uma resposta gravada é reutilizada depois. Faça um novo deploy com uma mensagem reformulada ou um schema alterado e o servidor pergunta de novo em vez de consumir uma resposta obsoleta. A mesma amarração também corta no outro sentido: derive as mensagens dos argumentos da ferramenta, não de dados que variam a cada chamada. Uma mensagem montada a partir de um timestamp ou de uma cotação ao vivo renderiza diferente a cada rodada, então toda resposta gravada parece obsoleta e o servidor pergunta de novo até que o limite de rodadas do cliente encerre a chamada.

Tudo isso é trabalho do SDK, não seu, e nem do codec se você trouxer o seu.

### Rotacionando chaves {#rotating-keys}

`keys[0]` sela estado novo; toda chave da lista verifica. A rotação sem downtime tem três fases, cada uma totalmente distribuída antes da próxima:

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

Nunca promova o emissor primeiro: emitir sob uma chave que alguma instância ainda não sabe verificar derruba rodadas em andamento no meio da distribuição.

As chaves têm escopo de um único serviço. O envelope selado também carrega o nome do servidor como uma declaração de audiência, então um token emitido por um serviço diferente que por acaso compartilha um segredo é rejeitado mesmo assim. A declaração é tão distintiva quanto o nome, então um servidor que recebe uma política explícita precisa ter um nome de verdade ou definir `RequestStateSecurity(audience=...)` — um sem nome lança na construção. `audience=` também atende topologias multisserviço deliberadas em que um serviço precisa aceitar estado que outro emitiu. (O padrão sem configuração está isento: sua chave nunca sai do processo, então a declaração de audiência não tem nada a acrescentar.)

### Traga sua própria criptografia {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` aceita qualquer coisa com `seal(bytes) -> str` e `unseal(str) -> bytes` que lance `InvalidRequestState` para qualquer token que não tenha emitido. O formato clássico é a criptografia de envelope contra um KMS, em que você desembrulha uma chave de dados uma vez na inicialização e mantém a criptografia por token local:

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL, vínculo de principal e vínculo de requisição **não** são trabalho do codec: o SDK os grava no payload antes de `seal` e os verifica de novo depois de `unseal`, para todo codec. As únicas obrigações de um codec são integridade (adulterado significa lançar) e, idealmente, confidencialidade.

### Quando a verificação falha {#when-verification-fails}

Toda falha de entrada, seja token adulterado, expirado, reproduzido contra uma requisição ou principal diferente, ou selado sob uma chave que este servidor não conhece, recebe a mesma resposta:

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

Uma única mensagem fixa para toda causa, de modo que a rede nunca revela qual verificação falhou; o motivo real vai para o log do servidor. Todo `requestState` de entrada em `tools/call`, `prompts/get` e `resources/read` é verificado, inclusive um que chega para um handler que nunca emite estado. A rejeição mais comum na prática não é um atacante — é a chave padrão local ao processo encontrando uma nova tentativa de antes de um reinício ou de outra instância; o cliente recomeça o fluxo, e `keys=[...]` é a correção quando isso importa.

### Estado montado à mão {#hand-built-state}

Um `request_state` que você mesmo define (retornando `InputRequiredResult` de uma função de ferramenta, prompt ou template de recurso) é selado e verificado pela mesma engrenagem do estado de resolvedor, sem nenhuma mudança de código: escreva texto puro, leia texto puro, e todo vínculo acima se aplica.

A única coisa que o SDK não consegue amarrar por você, mesmo configurado, é a identidade da pergunta: ele não sabe a qual das *suas* perguntas pertence uma resposta no seu estado. Se você armazena respostas indexadas por pergunta, inclua seu próprio identificador de pergunta no estado e confira-o na nova tentativa.

O `Server` de baixo nível é o nível sem pilhas inclusas: diferente do `MCPServer`, nada é selado até que você mesmo acrescente a fronteira, e seu `request_state` atravessa a rede exatamente como foi escrito até você fazer isso. O opt-in de uma linha aparece em **[O Server de baixo nível](../advanced/low-level-server.md#the-other-handlers)**.

## Um resultado de 2026-07-28 {#a-2026-07-28-result}

`InputRequiredResult` só existe na versão de protocolo **2026-07-28**. O `Client(server)` em memória a negocia por você; pela rede, `mode="auto"` a descobre. Depois de conectar, `client.protocol_version` diz o que você obteve.

!!! warning
    Uma sessão pré-2026 não tem onde colocar um `InputRequiredResult`. Retorne um do seu handler em uma
    conexão `mode="legacy"` e o executor não consegue serializá-lo na versão negociada; o
    cliente recebe de volta um erro `-32603` *"Handler returned an invalid result"*. Um servidor que atende
    às duas eras precisa conferir `ctx.protocol_version` antes de recorrer a ele.

!!! info
    A **elicitação em modo URL** usa exatamente esse mecanismo em uma conexão 2026. A entrada em
    `input_requests` é um `ElicitRequest` cujos params são `ElicitRequestURLParams`; o usuário
    termina o fluxo fora de banda e seu cliente tenta a chamada de novo. Mesmo loop, nenhuma API nova. A
    metade do servidor de alto nível está em **[Elicitação](elicitation.md)**.

## Recapitulando {#recap}

* Em 2026-07-28 um servidor que precisa de entrada no meio de uma chamada **retorna** um `InputRequiredResult`. Ele nunca abre uma requisição para o cliente.
* `input_requests` é o que ele precisa. `request_state` é um token opaco de retomada que só o servidor lê.
* O `Client` executa o loop de novas tentativas por você: registre `elicitation_callback` / `sampling_callback` / `list_roots_callback` e `call_tool` retorna um `CallToolResult` simples. `input_required_max_rounds` (padrão 10) o limita.
* Para inspecionar ou persistir rodadas, use `client.session.call_tool(..., allow_input_required=True)` e assuma você mesmo o loop `while isinstance(result, InputRequiredResult)`.
* Em `@mcp.tool()`, uma dependência que pergunta ao usuário produz esse resultado por você (**[Dependências](dependencies.md)**); o `Server` de **baixo nível** é a forma manual.
* Prompts e recursos também participam: uma função `@mcp.prompt()` ou `@mcp.resource()` de template retorna ela mesma o `InputRequiredResult` e lê `ctx.input_responses` na nova tentativa.
* O `requestState` volta como entrada fornecida pelo cliente, então o `MCPServer` o sela por padrão — estado de resolvedor e estado montado à mão do mesmo jeito — sob uma chave local ao processo; deploys com múltiplas instâncias passam `RequestStateSecurity(keys=[...])` (ou um codec personalizado) para que cada instância possa verificar o que uma irmã emitiu. O selo vincula todo token a uma janela de tempo, à requisição de origem e ao principal autenticado quando a requisição carrega autenticação que o SDK validou ou `bind_principal=` fornece seu próprio sinal de identidade (**[Protegendo o `requestState`](#protecting-requeststate)**).

Este é o mecanismo que substitui a amostragem iniciada pelo servidor e o resto do canal de retorno no estilo push; veja **[Funcionalidades descontinuadas](../deprecated.md)**.
