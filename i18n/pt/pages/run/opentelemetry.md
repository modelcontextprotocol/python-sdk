---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

Seu servidor já é rastreado. Você não precisa adicionar nada.

Todo servidor que você cria emite um span do [OpenTelemetry](https://opentelemetry.io/) para cada
mensagem que processa. Você não escreveu isso e não importa isso. Está lá no momento em que você
chama `MCPServer(...)`.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

Esse é um servidor completo e rastreado. Chame `search_books` e um span é criado para a chamada. O
mesmo vale para o `Server` de baixo nível: o rastreamento vive nos dois.

## O que você recebe {#what-you-get}

Cada mensagem recebida vira um span `SERVER` com o nome do método e do seu alvo. Então um
`tools/call` para `search_books` é o span `tools/call search_books`, e um `tools/list` simples
é apenas `tools/list`.

Cada span carrega alguns atributos:

* `mcp.method.name` e `mcp.protocol.version`, em todo span.
* `jsonrpc.request.id`, em uma requisição (uma notificação não tem).
* Um handler que lança uma exceção define o status do span como erro. Um resultado de ferramenta com `is_error=True` também.

E como rastrear uma chamada de ferramenta é algo tão comum de se querer, os spans `tools/call`
falam as [convenções semânticas GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) do OpenTelemetry:

* `gen_ai.operation.name`, definido como `"execute_tool"`.
* `gen_ai.tool.name`, definido como a ferramenta sendo chamada.

Um span `prompts/get` recebe `gen_ai.prompt.name` no mesmo espírito. Os métodos de listagem não
carregam chaves `gen_ai.*`, porque não há nada para nomear.

!!! tip
    Esses atributos GenAI são o motivo pelo qual uma interface de rastreamento agrupa suas chamadas
    de ferramenta do mesmo jeito que agrupa as de qualquer outro agente. Você ganha esse agrupamento
    de graça, sem código extra.

## Não custa nada até você querer {#it-costs-nothing-until-you-want-it}

Aqui está a parte que faz de "ligado por padrão" um padrão confortável.

O SDK depende apenas de `opentelemetry-api`, a metade leve do OpenTelemetry. Sem nenhum SDK e
nenhum exporter instalados, criar um span é um no-op. Então os spans que seu servidor está
emitindo agora mesmo não custam quase nada, e ninguém os está coletando.

No dia em que você quiser *vê-los*, instale a outra metade e aponte-a para algum lugar:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

Configure um exporter do jeito habitual do OpenTelemetry, e cada span que o SDK vinha criando
em silêncio se acende. O código do seu servidor não muda. Nem uma linha.

!!! info
    O [Pydantic Logfire](https://logfire.pydantic.dev/) é um desses backends, e faz a
    configuração para você: `pip install logfire`, `logfire.configure()`, e seus spans MCP
    aparecem na visualização ao vivo. Ele é construído sobre o OpenTelemetry, então tudo o que
    vem abaixo também se aplica a ele.

## Traces que atravessam a rede {#traces-that-cross-the-wire}

Um trace é mais útil quando acompanha uma requisição do cliente até o servidor, em uma única
imagem conectada.

Quando o cliente e o servidor rodam o SDK, essa conexão é automática. O cliente injeta o
[contexto de trace W3C](https://www.w3.org/TR/trace-context/) na requisição, e o servidor o lê de
volta, de modo que o span do servidor fica aninhado sob o span do cliente no mesmo trace. Isso é a
[SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414), e você ganha isso
sem pedir.

Se a mensagem recebida não carrega contexto de trace, por exemplo uma requisição de um cliente que
não é o SDK, o span do servidor simplesmente fica sob o span que já estiver ativo no servidor, em
vez de iniciar um trace órfão novo.

## Desligando {#turning-it-off}

O rastreamento é um middleware, o primeiro da lista do seu servidor. Se você quer mesmo um servidor
que não emite spans, retire-o:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    Esse import tem um underscore inicial, e isso é de propósito. A classe é provisória, do mesmo
    jeito que [`Server.middleware`](../advanced/middleware.md) é provisório, então o caminho de
    import é algo que você deve esperar que mude. Você quase nunca precisa disso: sem um exporter
    instalado os spans são gratuitos, então a resposta habitual é deixá-los ligados e não instalar
    um exporter.

## Recapitulando {#recap}

* Todo `MCPServer` e todo `Server` de baixo nível emite um span `SERVER` por mensagem recebida,
  por padrão. Você não escreve nada.
* Os spans carregam `mcp.method.name` e `mcp.protocol.version`; `tools/call` e `prompts/get`
  também carregam atributos GenAI para que suas chamadas de ferramenta se agrupem como as de
  qualquer outro agente.
* Não custa nada até você instalar um SDK do OpenTelemetry e um exporter, e aí tudo se acende
  sem nenhuma mudança no seu servidor.
* O contexto de trace do cliente para o servidor se propaga automaticamente quando os dois lados
  rodam o SDK.

O que decide se uma requisição chega a rodar é a **[Autorização](authorization.md)**.
