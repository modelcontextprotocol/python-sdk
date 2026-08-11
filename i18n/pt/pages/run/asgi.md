---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# Adicione a um app existente {#add-to-an-existing-app}

`mcp.run("streamable-http")` inicia um servidor web para você. Às vezes você não quer isso: seu servidor MCP é uma peça de uma aplicação web maior, ou você já tem um deploy ASGI.

Para esses casos, `mcp.streamable_http_app()` retorna uma **aplicação Starlette**.

Um app Starlette é um app ASGI, então qualquer coisa que hospede ASGI (uvicorn, Hypercorn, outro Starlette, FastAPI) pode hospedar seu servidor MCP.

## O app {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` é uma aplicação ASGI comum. Entregue-o a qualquer servidor ASGI:

```console
uvicorn server:app
```

O endpoint MCP fica em `/mcp`, então um cliente se conecta a `http://127.0.0.1:8000/mcp`.

O app já carrega duas coisas:

* Uma rota, `/mcp`: o endpoint Streamable HTTP.
* Um **lifespan** que inicia o `mcp.session_manager`, o objeto que é dono do trabalho em segundo plano de cada sessão ativa.

Execute o app sozinho (`uvicorn server:app`) e você nunca precisa pensar em nenhuma das duas.

!!! tip
    `streamable_http_app()` aceita os mesmos argumentos nomeados que `mcp.run("streamable-http", ...)`,
    menos `port`: a porta pertence a quem quer que sirva o app. `host` ainda é aceito, mas não faz bind
    de nada aqui; **[Deploy e escala](deploy.md)** explica o que ele controla de fato.
    **[Executando seu servidor](index.md)** cobre as opções em si.

`mcp.sse_app()` faz o mesmo para o transporte SSE, já superado.

## Só localhost, até você dizer o contrário {#localhost-only-until-you-say-otherwise}

Por padrão, o app responde **apenas** a requisições endereçadas ao localhost. `streamable_http_app()`
não tem como saber atrás de qual hostname vai ser servido, então ativa a proteção contra DNS rebinding com a
allowlist mais segura possível; na sua máquina, isso é exatamente o certo. Depois do deploy atrás de um hostname real,
isso significa que **toda requisição é rejeitada com `421 Misdirected Request`** até você passar em
`transport_security=` uma allowlist do que você realmente serve. Nada do que você construiu sequer é
consultado antes. Essa allowlist, e tudo o mais que existe entre um app funcionando e um hostname real,
é assunto de **[Deploy e escala](deploy.md)**.

## Montando o app {#mounting-it}

No momento em que o servidor MCP é *parte* de uma aplicação maior, você coloca o app dentro de um `Mount`. E no momento em que faz isso, o lifespan vira problema seu:

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` mais o caminho padrão `/mcp` mantém o endpoint em `/mcp`. O Starlette testa as rotas em ordem e `Mount("/")` casa com **todo** caminho, então suas próprias rotas vão *antes* dele na lista. Qualquer coisa depois dele fica inalcançável.
* A função `lifespan` entra em `mcp.session_manager.run()` pelo tempo de vida do app **host**. Essa é a linha que todo mundo esquece.
* `mcp.session_manager` só existe *depois* que `streamable_http_app()` foi chamado. É por isso que as rotas são construídas no nível do módulo e o manager só é tocado dentro do lifespan.

A rota `Host` do Starlette funciona do mesmo jeito: troque `Mount("/", ...)` por `Host("mcp.example.com", ...)` para rotear por hostname em vez de por caminho. A regra do lifespan não muda, e a de segurança de transporte também não. Uma rota `Host("mcp.example.com", ...)` só recebe requisições endereçadas àquele hostname, mas a allowlist de Host do próprio transporte (**[Deploy e escala](deploy.md)**) ainda roda primeiro. Sem `"mcp.example.com"` nela, essa rota responde a cada uma delas com um `421`.

!!! warning "O app host é dono do lifespan"
    `streamable_http_app()` conecta `session_manager.run()` ao lifespan do Starlette que
    retorna, mas **o lifespan de uma subaplicação montada nunca roda**. Monte o app e esse
    lifespan embutido vira código morto. Seja qual for o app no topo da sua pilha ASGI, ele precisa entrar em
    `mcp.session_manager.run()` no próprio lifespan.

!!! check
    Apague a linha `lifespan=lifespan` e inicie o servidor. Ele inicia. A rota resolve.
    Aí a primeira requisição a `/mcp` falha com:

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    Nada inicia o session manager a não ser o `run()` dele.

## Dois servidores, um app {#two-servers-one-app}

Cada `MCPServer` é seu próprio app com seu próprio session manager. Monte quantos quiser; entre em cada manager a partir do único lifespan do host:

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` entra nos dois managers; eles iniciam juntos e encerram na ordem inversa.
* Os endpoints são `/notes/mcp` e `/tasks/mcp`: o prefixo do mount mais o caminho padrão.

## Mudando o caminho {#changing-the-path}

Aquele `/mcp` no final é o `streamable_http_path`. Defina-o como `"/"` e o prefixo do mount vira o caminho público inteiro:

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

Agora os clientes se conectam a `/notes`, não a `/notes/mcp`.

## CORS para clientes no navegador {#cors-for-browser-clients}

Um cliente que roda no navegador precisa de duas permissões suas: para **enviar** seus headers de requisição MCP, e para **ler** o que o MCP manda de volta. As duas são configuração de CORS no app host, e a allowlist de segurança de transporte acima precisa concordar com ela:

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` é a metade que todo mundo esquece. O navegador faz **preflight** de toda requisição MCP, porque `Content-Type: application/json` e os headers de requisição `Mcp-*` não estão na safelist do CORS, e um header que o preflight não concede é uma requisição que o navegador nunca envia. (`allow_headers=["*"]` também funciona: o Starlette responde a um preflight com o que quer que ele tenha pedido.)
* `expose_headers=["Mcp-Session-Id"]` é a metade da leitura. O Streamable HTTP retorna o ID de sessão nesse header de resposta, e os navegadores escondem headers de resposta do JavaScript a menos que o CORS os exponha pelo nome. Sem ele, o cliente nunca consegue fazer sua segunda requisição.
* `allow_origins` é decisão sua, não do MCP. Seja preciso, e espelhe isso em `allowed_origins=` acima: o navegador impõe o CORS, mas o servidor verifica `Origin` por conta própria, e uma origem em que o transporte não confia recebe um `403` mesmo depois de um preflight limpo.
* `allow_methods` lista os três métodos que o Streamable HTTP usa: `POST` para enviar mensagens, `GET` para abrir o stream do servidor para o cliente, `DELETE` para encerrar a sessão.

## Rotas customizadas {#custom-routes}

`@mcp.custom_route()` registra um endpoint HTTP comum no mesmo app, para as coisas que todo serviço em produção precisa e que não têm nada a ver com MCP: um health check, um callback OAuth.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* O handler é Starlette puro: uma função `async` de `Request` para `Response`.
* `streamable_http_app()` recolhe toda rota customizada. `app.routes` agora é `/mcp` e `/health`.
* `GET /health` responde `{"status": "ok"}` sem MCP nenhum à vista.

!!! warning
    Rotas customizadas **nunca são autenticadas**, mesmo quando o resto do servidor é. Isso é
    proposital: health checks e callbacks OAuth precisam estar acessíveis antes de existir qualquer token.
    Não coloque nada privado atrás de uma delas.

## Recapitulando {#recap}

* `mcp.streamable_http_app()` retorna um app Starlette com uma rota, `/mcp`. Qualquer servidor ASGI consegue executá-lo.
* Por padrão, o app responde apenas a requisições endereçadas ao localhost, e atrás de um hostname real rejeita tudo com um `421` até você passar em `transport_security=` uma allowlist. **[Deploy e escala](deploy.md)** cuida disso, e do resto do caminho até a produção.
* `Mount` (ou `Host`) o coloca dentro de um app Starlette ou FastAPI maior.
* **Montar desativa o lifespan embutido.** O lifespan do app host precisa entrar em `mcp.session_manager.run()`, ou a primeira requisição falha.
* Vários servidores em um app significa vários mounts e um lifespan que entra em cada session manager.
* `streamable_http_path="/"` move o endpoint para o próprio prefixo do mount.
* Clientes no navegador precisam de CORS: `allow_headers` para os headers de requisição `Mcp-*`, `expose_headers=["Mcp-Session-Id"]` para a resposta.
* `@mcp.custom_route()` adiciona endpoints HTTP comuns, sem autenticação, ao lado de `/mcp`.

Com o servidor acessível em uma URL real, **[O cliente](../client/index.md)** se conecta a ele com essa URL em vez de um objeto servidor.
