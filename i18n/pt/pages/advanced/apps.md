---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

Um **MCP App** é uma ferramenta (tool) com uma cara: junto com os dados, a ferramenta aponta para um
documento HTML que o host renderiza como uma superfície interativa.

Duas partes, sempre duas partes:

1. **Uma ferramenta** que faz o trabalho e retorna dados, como qualquer outra ferramenta.
2. **Um recurso `ui://`** contendo o HTML que o host mostra para ela.

A ferramenta carrega uma referência `_meta.ui.resourceUri` ao recurso. O host busca esse
recurso com `resources/read`, renderiza em um **iframe em sandbox** e envia o resultado
da ferramenta para dentro desse iframe via `postMessage`. Seu servidor nunca envia nem recebe
nenhuma mensagem `ui/*`: esse tráfego fica entre o host e o iframe. Você serve uma ferramenta
e um documento HTML; o host cuida do espetáculo.

O SDK entrega isso como a extensão embutida `Apps` (`io.modelcontextprotocol/ui`).
Se [Extensões](extensions.md) são novidade para você, dê uma olhada naquela página primeiro. Um minuto,
e depois volte aqui.

## Um relógio com uma cara {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

Quatro movimentos:

* `Apps()`: uma única instância guarda suas ferramentas ligadas a UI e os recursos delas.
* `@apps.tool(resource_uri="ui://clock/app.html")`: uma ferramenta comum, mais o
  carimbo `_meta.ui.resourceUri`. Tudo o que `@mcp.tool()` aceita (name, title,
  description, ...) passa direto.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: o recurso
  correspondente, servido como `text/html;profile=mcp-app`. É exatamente esse MIME type que
  diz ao host "isto é um app, renderize".
* `MCPServer("clock", extensions=[apps])`: você opta por participar. O servidor agora anuncia
  `io.modelcontextprotocol/ui` em `capabilities.extensions`.

O HTML em si escuta o `postMessage` do host e mostra o resultado. Para apps
de verdade, use o SDK de navegador oficial [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps)
dentro do seu HTML. Ele dá a você `ontoolresult`, `callServerTool`,
`getHostContext` e `onhostcontextchanged` em vez de eventos de mensagem crus.

## Degradação elegante {#graceful-degradation}

Nem todo cliente renderiza apps. A especificação é direta sobre o que isso significa para você:

> As ferramentas **DEVEM** retornar um array `content` significativo mesmo quando há UI disponível.

O modelo lê `content`; o iframe é para humanos. Um host com suporte a UI ainda passa
o resultado em texto para o modelo, e um cliente só de texto recebe *apenas* isso. Então o
padrão canônico é uma ferramenta, duas respostas. Olhe `get_time` de novo:

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` é `True` somente quando o cliente declarou a
extensão `io.modelcontextprotocol/ui` **e** listou `text/html;profile=mcp-app`
nas suas configurações `mimeTypes`. O campo é obrigatório, então um cliente que o omite
não conta. É exatamente isso que `main()` no mesmo arquivo declara: a
metade cliente da negociação, e a resposta rica volta.

!!! warning
    Nunca retorne um placeholder como `"[Rendered UI]"` como único conteúdo. Se o
    texto de fallback é inútil, a ferramenta é inútil para todo cliente só de texto e para
    o próprio modelo. Escreva a frase.

## Trancando o iframe {#locking-the-iframe-down}

O lado do recurso carrega os metadados de segurança: o que o iframe pode carregar, quais
permissões do navegador ele quer, como gostaria de ser enquadrado:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` e `permissions` são **pedidos ao host**, não comportamento do servidor. O host
monta a Content-Security-Policy e a Permissions-Policy do iframe a partir deles, e
pode recusar. Faça detecção de funcionalidade no seu JS em vez de presumir que foi concedido.

`ResourceCsp`, campo por campo (nome em Python, chave no protocolo, o que o host faz com ele):

| Python | Protocolo (`_meta.ui.csp`) | Controla |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: para onde `fetch`/XHR podem ir |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: assets estáticos |
| `frame_domains` | `frameDomains` | `frame-src`: iframes aninhados |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: para onde `<base>` pode apontar |

`ResourcePermissions`: cada campo solicita uma permissão do navegador para o iframe.

| Python | Protocolo (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP e permissões vivem no **recurso**, nunca na ferramenta. Os metadados de ferramenta
    da especificação não têm lugar para eles, e os hosts os ignoram ali. O SDK torna o
    erro irrepresentável: `@apps.tool()` simplesmente não tem parâmetro `csp`.

### Visibilidade {#visibility}

`visibility=["app"]` em uma ferramenta diz "isto existe para o iframe, não para o modelo":

* `"model"`: o modelo pode chamá-la.
* `"app"`: o iframe pode chamá-la (via `callServerTool`).
* Omitido: ambos, que é o padrão.

Filtrar é trabalho do **host**. Seu servidor lista as ferramentas só de app em `tools/list`
como qualquer outra; o host as esconde do modelo. Não filtre no lado do servidor.

## As regras que o SDK impõe {#the-rules-the-sdk-enforces}

Todas estas falham na inicialização, não em produção:

* Um `resource_uri` ou URI de recurso que não seja `ui://...` é um `ValueError` no
  momento da decoração/registro.
* Uma ferramenta ligada a uma URI **sem recurso registrado correspondente** é um `ValueError`
  quando `MCPServer(extensions=[apps])` consome a extensão. Uma ferramenta que anuncia
  um HTML que dá 404 em `resources/read` é uma configuração errada, então o servidor se recusa
  a ser construído.
* `meta={"ui": ...}` em `@apps.tool()` é um `ValueError`. O decorator é dono de
  `_meta["ui"]`; diga isso com `resource_uri=` e `visibility=`. Outras chaves em `meta=`
  são mescladas normalmente ao lado.

Nem o SDK ext-apps em TypeScript nem o FastMCP pegam nenhum desses casos hoje; preferimos
que você descubra antes que um host descubra.

## Além do HTML inline {#beyond-inline-html}

`add_html_resource` cobre o caso comum: uma string de HTML. Para qualquer outra coisa,
HTML em disco ou conteúdo gerado, construa o recurso você mesmo e entregue:

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource` preenche o MIME type `text/html;profile=mcp-app` quando o recurso
não define um explicitamente, e rejeita uma incompatibilidade explícita: um recurso `ui://`
sob qualquer outro MIME type é um que nenhum host vai renderizar.

!!! tip
    Mirando um host pré-GA que ainda lê a chave plana depreciada
    `_meta["ui/resourceUri"]`? Mescle você mesmo:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    O objeto `ui` aninhado é o formato da especificação; a chave plana está de saída.

## Veja rodando {#see-it-run}

A história `apps` em `examples/stories/` é esta página como um par executável: um servidor
com uma ferramenta de relógio ligada a UI e um cliente que negocia Apps, lê o
`_meta.ui.resourceUri` da ferramenta, busca o HTML e chama a ferramenta.

```bash
uv run python -m stories.apps.client
```
