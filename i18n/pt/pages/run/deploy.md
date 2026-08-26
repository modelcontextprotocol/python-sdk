---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# Deploy e escala {#deploy-scale}

Seu servidor funciona. Agora ele precisa de um hostname de verdade, e de mais de um worker por trás dele.

Quase nada disso é assunto do MCP. Você traz o servidor ASGI, o gerenciador de processos, o balanceador de carga. O que esta página tem é a lista curta das coisas que *são* assunto do MCP: uma configuração que bloqueia todo deploy, e os dois lugares em que "mais de um worker" muda o que o SDK faz.

## Antes de qualquer coisa: a allowlist de Host {#before-anything-else-the-host-allowlist}

`streamable_http_app()` não tem como saber atrás de qual hostname vai ser servido, então assume a resposta mais segura: localhost. Sem `transport_security=`, o app liga a **proteção contra DNS rebinding** e só aceita uma requisição se o header `Host` dela for `127.0.0.1:<port>`, `localhost:<port>` ou `[::1]:<port>`. O header `Origin`, quando existe, tem que ser a forma `http://` do mesmo valor. Na sua máquina isso é exatamente o certo: impede que uma página web maliciosa controle seu servidor local através de um nome DNS que ela religou para `127.0.0.1`.

Depois do deploy atrás de um hostname de verdade, esse mesmo padrão rejeita **toda requisição** até você dizer o contrário. A verificação roda antes de qualquer coisa com cara de MCP, então nada do que você construiu chega a ser consultado:

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

`transport_security=` é a correção. Coloque na allowlist o que você realmente serve:

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* As entradas de `allowed_hosts` são strings exatas: `"mcp.example.com"` casa com um header `Host` sem porta e `"mcp.example.com:*"` casa com qualquer porta. Liste as duas.
* `allowed_origins` só importa para navegadores, porque nada mais envia `Origin`. É o par, do lado do servidor, da configuração de CORS em **[Adicione a um app existente](asgi.md)**.
* Atrás de um proxy reverso que já controla o header `Host`, desligar a verificação é a configuração honesta: `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.
* Passar um `host=` que não seja localhost (por exemplo `host="mcp.example.com"`) **não** coloca esse hostname na allowlist. Só impede que o padrão de localhost arme a proteção, o que deixa todo Host e todo Origin aceitos. Diga o que você quer dizer com `transport_security=` em vez disso.

!!! check
    Apague o argumento `transport_security=security` e faça o deploy do app mesmo assim. Ele sobe, `/mcp`
    roteia, e toda requisição (inclusive de um `curl` simples) volta assim:

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    Você não vai encontrar essas palavras do lado do cliente. Um `421` é uma resposta HTTP em texto puro, não um
    erro JSON-RPC, então o cliente MCP levanta um erro genérico de transporte; o hostname de que ele
    não gostou aparece só no log do **servidor**, como um único warning. Um servidor recém-implantado
    que recusa toda conexão é uma allowlist de Host até que se prove o contrário.
    **[Solução de problemas](../troubleshooting.md)** também começa por aqui.

## Workers, e quem precisa de afinidade {#workers-and-who-has-to-be-sticky}

Quando o hostname responder, coloque mais de um worker atrás dele. Não há botão no SDK para isso; você escala um app Starlette do jeito que escala qualquer app ASGI, entregando o objeto a algo que saiba fazer fork:

```console
uvicorn server:app --workers 4
```

Quatro processos, um socket. E agora a pergunta que todo deploy tem que responder: **uma requisição precisa chegar ao worker que viu a anterior?**

Para um cliente que fala o protocolo **2026-07-28**, não. Uma requisição moderna é um único POST autocontido: nenhum handshake `initialize` antes dela, nenhum `Mcp-Session-Id` na resposta, nada *para onde* uma segunda requisição possa voltar. Roteie para qualquer worker.

Isso não é um modo que você liga. `stateless_http=True` parece que deveria ser, mas o transporte roteia pelo header de requisição `MCP-Protocol-Version`, entrega uma requisição moderna ao handler moderno e **retorna**. A linha que lê `stateless_http` vem *depois* desse retorno. Não é que a flag seja ignorada no caminho 2026-07-28; ela nunca é alcançada. `stateless_http` é um botão só para o ramo **legado**, e o caminho moderno é sem sessão por construção.

Para um cliente legado na versão de spec 2025-11-25 ou anterior, a resposta depende dessa flag:

| Versão de protocolo do cliente | Sessão | O que o balanceador de carga precisa fazer |
| --- | --- | --- |
| **2026-07-28** | Nenhuma. `Mcp-Session-Id` nunca é definido. | Nada. Qualquer worker atende qualquer requisição. |
| **2025-11-25 e anteriores** (o padrão) | `Mcp-Session-Id`, guardado na memória de um worker. | **Sessões com afinidade (sticky sessions).** Uma requisição seguinte que chega a outro worker recebe um `404` *"Session not found"*. |
| **2025-11-25 e anteriores**, com `stateless_http=True` | Nenhuma. | Nada. O custo é o canal de retorno (back-channel) do servidor para o cliente (amostragem (sampling), elicitação por push, `roots/list`) e a retomada de streams. |

Sessões com afinidade e o que o ramo legado custa têm sua própria página, **[Atendendo clientes legados](legacy-clients.md)**; as duas eras em si são **[Versões do protocolo](../protocol-versions.md)**. O que importa aqui é o formato da resposta: *no 2026-07-28 você já é stateless, sem nada para configurar.*

O resto desta página são as duas coisas que ser stateless **não** te compra.

## `requestState` entre workers {#requeststate-across-workers}

Uma ferramenta (tool) **[de múltiplas idas e voltas](../handlers/multi-round-trip.md)** precisa de algo que o cliente tem que ir buscar (uma confirmação, uma escolha, uma credencial), então ela retorna uma pergunta em vez de uma resposta e termina na nova tentativa. Entre as duas rodadas o cliente segura um token opaco `request_state` que o servidor cunhou. Na nova tentativa o servidor tem que abrir esse token de novo.

*Selado com qual chave?* Por padrão, uma que o servidor gerou com `os.urandom(32)` no momento da construção. Com `--workers 4` são quatro construções, em quatro processos: quatro chaves diferentes, nunca gravadas em lugar nenhum, nunca compartilhadas, perdidas no restart.

Aqui está uma ferramenta que pergunta antes de agir, em um servidor que não configura nada:

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

A primeira rodada chega ao worker A. O worker A sela `refund:120` com a chave **dele** e retorna o token. O cliente coloca a pergunta na frente de uma pessoa, recebe um sim e tenta de novo. A nova tentativa é uma requisição HTTP novinha em folha.

!!! check
    Deixe essa nova tentativa chegar ao worker B. B tenta abrir um token que não cunhou, não consegue e recusa a
    rodada inteira. `refund` nunca é chamado; o cliente recebe um erro JSON-RPC:

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    Essa mensagem é **fixa**. Expirado, adulterado, reenviado contra argumentos diferentes ou (de
    longe a causa mais comum em um deploy real) selado por um worker irmão: o cliente ouve
    a mesma coisa toda vez, então o que trafega nunca revela qual verificação falhou. O motivo real é um
    `WARNING` no log do servidor:

    ```text
    requestState rejected on tools/call: unknown key
    ```

    Uma ferramenta de múltiplas idas e voltas que funcionava com um worker e começou a falhar *às vezes* com
    dois é isto. As duas rodadas ainda precisam chegar ao mesmo processo, então ela falha exatamente na mesma
    frequência com que seu balanceador de carga as separa.

As duas rodadas são duas requisições HTTP independentes, e várias coisas corriqueiras as separam: um proxy que balanceia por requisição, uma conexão que caiu no meio, um deploy ou um restart, um cliente que persistiu o `request_state` e está retomando de um processo totalmente diferente (**[Conduzindo o loop por conta própria](../handlers/multi-round-trip.md#driving-the-loop-yourself)**). Qualquer uma delas é "um worker diferente".

A correção é um argumento. Ela tem **duas** metades.

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** é a metade que todo mundo encontra. Dê a cada instância o mesmo segredo (pelo menos 32 bytes dele), e toda instância consegue abrir o que qualquer irmã cunhou. `keys[0]` sela e toda chave da lista abre, e esse é o anel de rotação; **[Rotacionando chaves](../handlers/multi-round-trip.md#rotating-keys)** mostra como girá-lo sem downtime.
* **O nome do servidor** é a metade que quase ninguém encontra, e o motivo pelo qual novas tentativas entre instâncias continuam falhando depois que você compartilha a chave. Todo token selado carrega o `name` do servidor como uma **claim de audiência**, verificada estritamente na volta. Duas instâncias construídas a partir do mesmo código têm o mesmo nome e nunca percebem isso. Dê nomes diferentes a elas (`MCPServer(f"billing-{POD}")` parece boa higiene de observabilidade), e toda nova tentativa entre instâncias é recusada exatamente como acima, com ou sem chave compartilhada. O log diz `audience` em vez de `unknown key`; o cliente não consegue distinguir.

Cunhe o segredo uma vez e entregue o mesmo valor a toda instância. Este é o comando que a própria mensagem de erro do SDK manda você rodar se passar menos de 32 bytes para ele:

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "Mesmas chaves *e* o mesmo nome"
    Um deploy com múltiplas instâncias precisa compartilhar os dois. Se nomes por instância são essenciais para você,
    dê à frota uma audiência explícita em vez disso: `RequestStateSecurity(keys=[...], audience="billing")`.
    Toda instância então cunha e aceita sob `"billing"`, não importa como se chame.

Todo o resto sobre o selo está em **[Protegendo o `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**: o que ele vincula, o `ttl` por rodada (600 segundos por padrão), trazer seu próprio codec, por que o padrão não configurado é exatamente o certo em `stdio`. A contribuição inteira desta página é um checklist de dois itens: *mesmas chaves, mesmo nome.*

!!! info
    Você está neste caminho mesmo que nunca tenha digitado `InputRequiredResult`. Uma ferramenta cujos parâmetros
    usam `Resolve(...)` (**[Dependências](../handlers/dependencies.md)**) é uma ferramenta de múltiplas idas e voltas,
    e o SDK cunha e sela o `request_state` dela por ela. Mesma chave padrão, mesma falha entre
    workers, mesma correção.

## Notificações de mudança entre réplicas {#change-notifications-across-replicas}

O stream `subscriptions/listen` de um cliente é uma única resposta de longa duração, então fica preso a uma réplica pela vida toda. Um `ctx.notify_resource_updated(...)` publicado em uma réplica **diferente** tem que chegar até ele.

A costura entre os dois é o `SubscriptionBus`. Qualquer bus que você dê a um servidor é aquele em que toda publicação entra e que todo stream aberto escuta, então entregue o mesmo bus a toda réplica:

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

Nada no fan-out se importa com qual objeto de servidor um stream está ligado. Dois servidores segurando um único `InMemorySubscriptionBus` já se comportam assim: abra um stream de listen em um, `edit_note` no outro, e o stream fica sabendo. Esse bus em memória só abrange objetos de servidor dentro de um processo, o que faz dele o modelo, não o deploy:

* Entre processos de verdade, **o SDK não traz nenhum bus que possa te ajudar.** `SubscriptionBus` é um `Protocol` de dois métodos (`publish` e `subscribe`) que você implementa sobre seu próprio backend de pub/sub (Redis, NATS, o que você já roda) e passa como `MCPServer(subscriptions=...)`. **[Assinaturas](../handlers/subscriptions.md#scaling-past-one-process)** tem o esboço e o contrato.
* O bus carrega quatro pequenos eventos tipados, nunca JSON-RPC. Confirmação, filtragem e ciclo de vida do stream ficam no SDK, então seu bus não consegue quebrar o protocolo; ele só consegue mover eventos entre processos.
* Streams **não** são retomáveis e eventos **não** são reenviados. Perder uma réplica derruba os streams dela; os clientes escutam de novo e buscam de novo. Não há event store para compartilhar e nada mais para configurar. Este é o único lugar em que escalar horizontalmente é de fato só mais do mesmo.

## O que o SDK não te dá {#what-the-sdk-does-not-give-you}

Um `MCPServer` é uma implementação de protocolo, não um servidor de aplicação. Os botões de deploy que você vai procurar em seguida estão ausentes de propósito:

* **Sem `workers=`.** `mcp.run("streamable-http")` inicia exatamente um processo uvicorn, e isso é tudo o que ele jamais vai iniciar. Multiprocesso é `streamable_http_app()` entregue ao que você já usa para fazer deploy de ASGI: `uvicorn --workers`, gunicorn, o gerenciador de processos da sua plataforma. Esta página deliberadamente não é um tutorial de nenhum deles; a documentação deles é melhor do que uma cópia aqui seria.
* **Sem rota de health check.** `@mcp.custom_route("/health", methods=["GET"])` é a resposta inteira, e nunca é autenticada mesmo quando o resto do servidor é. Isso está certo para uma sonda de liveness, errado para qualquer coisa privada. **[Adicione a um app existente](asgi.md#custom-routes)** mostra uma.
* **Sem objeto de configurações de produção.** Não há lugar no `MCPServer` para anotar timeouts, TLS, shutdown gracioso ou limites de conexão, porque nada disso é trabalho dele. Isso pertence ao seu servidor ASGI, e você configura lá. **[Executando seu servidor](index.md)** cobre o punhado de configurações que o construtor *de fato* aceita.
* **Nenhum `EventStore` incluído, e no 2026-07-28 nenhum uso para um.** A retomada de streams é uma funcionalidade do ramo legado com estado; uma troca moderna é um POST, uma resposta, e nada para retomar.

## Recapitulando {#recap}

* Por padrão, o app responde apenas a requisições endereçadas ao localhost. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` é o portão para ir ao ar: até você passar isso, toda requisição atrás de um hostname de verdade é um `421` e o motivo só está no log do servidor.
* No 2026-07-28 não há sessão e nada em que um balanceador de carga possa ter afinidade. `stateless_http=True` é um botão só para o legado porque uma requisição moderna é roteada e respondida antes de essa flag ser lida.
* A chave padrão do `requestState` é `os.urandom(32)`, cunhada por processo. Uma nova tentativa de múltiplas idas e voltas que chega a um worker diferente falha com `-32602` *"Invalid or expired requestState"*.
* A correção é `RequestStateSecurity(keys=[...])` **e** o mesmo nome de servidor em toda instância. O nome é a claim de audiência padrão do token. Mesmas chaves, mesmo nome.
* Notificações de mudança atravessam réplicas por um único `SubscriptionBus` compartilhado. A única implementação do SDK é dentro do processo; o `Protocol` de dois métodos sobre seu próprio pub/sub é seu para escrever.
* Não há `workers=`, nem rota de health, nem objeto de configurações de produção. Traga seu próprio servidor ASGI.

A outra coisa que um hostname de verdade precisa na frente dele é um token: **[Autorização](authorization.md)**.
