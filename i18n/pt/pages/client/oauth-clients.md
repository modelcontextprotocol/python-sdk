---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# Clientes OAuth {#oauth-clients}

Alguns servidores MCP são protegidos. Envie a eles uma requisição sem token e a resposta é `401 Unauthorized`.

**`OAuthClientProvider`** é como você consegue o token. Ele não é um objeto MCP. É um `httpx2.Auth`, o hook padrão do httpx2 para "fazer algo em toda requisição". Você o anexa a um `httpx2.AsyncClient`, entrega esse cliente ao transporte Streamable HTTP e para de pensar no assunto.

Esta página é o lado do cliente. Fazer o seu próprio servidor exigir um token está em **[Autorização](../run/authorization.md)**.

## O provider {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

Você entrega quatro coisas a ele:

* `server_url`: o endpoint MCP ao qual você está se conectando. O provider descobre todo o resto a partir dele.
* `client_metadata`: o que você digitaria no formulário "registrar uma aplicação" de um servidor de autorização.
* `storage`: onde os tokens ficam entre uma execução e outra.
* `redirect_handler` e `callback_handler`: os dois momentos em que um humano participa.

Nada mais no arquivo menciona OAuth. `main()` nunca vê um token.

### Metadados do cliente {#client-metadata}

`OAuthClientMetadata` é o documento de registro real da [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591), na forma de um modelo Pydantic.

Você define três campos. Os valores padrão preenchem o resto: `grant_types` já é `["authorization_code", "refresh_token"]` e `response_types` já é `["code"]`, que é exatamente o fluxo que este provider executa.

!!! check
    Por ser um modelo Pydantic, ele valida **antes de um único byte trafegar pela rede**.
    Deixe `redirect_uris` de fora e a construção falha na hora com um `ValidationError` que
    nomeia o campo:

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    Nenhum navegador aberto, nenhum registro pela metade deixado para trás no servidor de autorização.

### Armazenamento de tokens {#token-storage}

**`TokenStorage`** é um `Protocol` com quatro métodos async. Você não herda de nada; escreva os métodos e qualquer classe vira um armazenamento de tokens:

* `get_tokens` / `set_tokens` guardam o `OAuthToken`: token de acesso, refresh token, expiração, escopo.
* `get_client_info` / `set_client_info` guardam o `OAuthClientInformationFull` que o servidor de autorização emitiu quando o provider registrou você, incluindo o seu `client_id`.

A versão em memória acima funciona. Ela também esquece tudo quando o processo termina, então a próxima execução refaz a dança inteira. Persista em um arquivo ou no keyring da sua plataforma e a próxima execução fica silenciosa.

!!! tip
    Armazene `client_info`, não só os tokens. O provider faz o registro dinâmico na primeira vez em que
    não encontra um `client_info` armazenado. Jogue-o fora e você cria um registro novo a cada execução.

### Os dois handlers {#the-two-handlers}

O fluxo de authorization code precisa de um humano exatamente uma vez: alguém tem que fazer login e clicar em "permitir".

* **`redirect_handler`** recebe um await com a URL de autorização já montada. O `client_id`, a `redirect_uri`, o `state` e o desafio PKCE já estão nela. Seu único trabalho é levar um navegador até lá. Um app desktop chama `webbrowser.open`; este arquivo imprime a URL.
* **`callback_handler`** recebe o await em seguida. Ele espera até o usuário voltar para a sua `redirect_uri` e retorna os parâmetros de query desse redirecionamento como um `AuthorizationCodeResult`.

Um cliente real executa um pequeno servidor HTTP local na URI de redirecionamento em vez de chamar `input()`. O formato é idêntico: receber o redirecionamento, devolver `code`, `state` e `iss`.

!!! warning
    Repasse `state` e `iss` exatamente como chegaram. O provider compara `state` com o que
    ele gerou e `iss` com o issuer que descobriu, e recusa qualquer divergência. Eles são as defesas
    contra CSRF e contra confusão de servidor (server mix-up).

### Para dentro do `Client` {#into-the-client}

Veja `main()`. O provider vai no **cliente httpx2**, o cliente httpx2 vai em `streamable_http_client(url, http_client=...)`, e esse transporte vai em `Client`.

`streamable_http_client` não tem o parâmetro nomeado `auth=`. Tudo que é de nível HTTP (auth, cabeçalhos, timeouts, proxies) pertence ao `httpx2.AsyncClient` que você traz. Essa divisão em camadas está em **[Transportes do cliente](transports.md)**.

## O que o provider faz por você {#what-the-provider-does-for-you}

Na primeira vez que `Client` envia uma requisição, o servidor responde `401`. O provider assume:

1. **Descoberta.** Ele lê o cabeçalho `WWW-Authenticate`, busca os Protected Resource Metadata do servidor em `/.well-known/oauth-protected-resource`, descobre qual servidor de autorização protege este recurso e busca os metadados *desse* servidor.
2. **Registro.** Nada no armazenamento? Ele registra você dinamicamente com o seu `OAuthClientMetadata` e armazena o resultado.
3. **Autorização.** Ele gera o par PKCE e um `state`, monta a URL de autorização, faz await no seu `redirect_handler` e depois faz await no seu `callback_handler` para obter o code.
4. **Troca.** Ele troca o code por um `OAuthToken`, armazena e reenvia a sua requisição original com `Authorization: Bearer ...`.

Depois disso ele fica quieto. Os tokens saem do armazenamento, um token de acesso expirado é renovado com o refresh token, e só quando nada disso funciona ele executa o fluxo de novo.

Você não escreveu nada disso. Restam dois argumentos nomeados (`client_metadata_url` e `validate_resource_url`), e este arquivo não precisa de nenhum dos dois. `client_metadata_url` é o que vale a pena conhecer; ele ganha uma seção própria abaixo.

### Experimente {#try-it}

A maioria dos exemplos nesta documentação você consegue conferir com um `Client(server)` em memória. Este não: o ponto central do fluxo é um `401` HTTP, e não há HTTP entre um cliente em memória e o seu servidor.

O repositório traz a versão ao vivo. `examples/servers/simple-auth/` executa um servidor de autorização independente e um servidor MCP protegido; `examples/clients/simple-auth-client/` é o cliente desta página crescido até virar uma pequena CLI. O README dele tem os dois comandos: inicie os servidores, execute o cliente contra eles e veja as quatro etapas passarem.

## Client ID Metadata Documents {#client-id-metadata-documents}

A revisão 2026-07-28 da especificação torna obsoleto o registro dinâmico de clientes em favor dos **Client ID Metadata Documents** (CIMD). Em vez de fazer POST de um registro novo em cada servidor de autorização que encontra, o seu cliente publica um único documento JSON sobre si mesmo em uma URL HTTPS estável, e essa URL *é* o `client_id` dele. O servidor de autorização busca o documento; o provider nunca toca nele.

O SDK já fala isso: passe a URL como `client_metadata_url=` ao construir o provider. Quando os metadados do servidor de autorização anunciam `client_id_metadata_document_supported: true`, o provider pula completamente a requisição a `/register`: a URL entra no fluxo como `client_id`, e não há `client_secret`. Quando o servidor não anuncia isso (a maioria ainda não anuncia), ou você nunca passa uma URL, o provider recorre ao registro dinâmico **silenciosamente**, e tudo acima funciona exatamente como descrito. Um `client_info` armazenado ainda prevalece sobre ambos.

A URL precisa ser HTTPS com um caminho que não seja a raiz; qualquer outra coisa é um `ValueError` na construção, antes de qualquer tráfego de rede. O `examples/clients/simple-auth-client/` do repositório recebe a URL pela variável de ambiente `MCP_CLIENT_METADATA_URL`.

## Máquina para máquina {#machine-to-machine}

Um job noturno, uma etapa de CI, outro serviço. Não há navegador nem ninguém para clicar em "permitir". Esse é o grant **client credentials**: você já possui um `client_id` e um `client_secret`, e o endpoint de token é o fluxo inteiro.

`ClientCredentialsOAuthProvider` é o mesmo `httpx2.Auth`, sem o humano:

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

O que mudou:

* Sem `OAuthClientMetadata`, sem handlers. Você passa `client_id` e `client_secret`; o provider monta um registro `client_credentials` mínimo em torno deles e pula o registro dinâmico por completo.
* `scope` é uma string separada por espaços, o formato OAuth usado na comunicação.
* Tudo a partir daí é idêntico: o mesmo `TokenStorage`, o mesmo `httpx2.AsyncClient(auth=...)`, o mesmo `streamable_http_client`.

Por padrão, o secret viaja como HTTP Basic auth na requisição de token (`client_secret_basic`). Passe `token_endpoint_auth_method="client_secret_post"` para colocá-lo no corpo do formulário. Alguns servidores de autorização só aceitam um dos dois.

!!! tip
    Leia `client_secret` do ambiente ou de um gerenciador de segredos, nunca do controle de versão.

!!! info
    Mais um provider mora em `mcp.client.auth.extensions.client_credentials`:
    **`PrivateKeyJWTOAuthProvider`**, para clientes que se autenticam com um JWT em vez de um
    segredo compartilhado (`private_key_jwt`, a variante de par de chaves e workload identity). Ele segue
    o mesmo padrão: construa um, coloque em `auth=`. O mesmo módulo traz
    `SignedJWTParameters` e `static_assertion_provider`, dois helpers que montam a assertion dele.

Há mais uma situação sem humano: o cliente pertence a uma empresa cujo provedor de identidade, e não o usuário, decide quais servidores MCP ele pode alcançar. Esse é um grant diferente, com seu próprio modelo de confiança e sua própria página, **[Asserção de identidade](identity-assertion.md)**.

## Quando falha {#when-it-fails}

Quando o fluxo OAuth dá errado, o provider levanta um `OAuthFlowError` de `mcp.client.auth`. Ele tem duas subclasses. `OAuthRegistrationError` significa que o registro não rendeu um cliente que você possa usar: o servidor de autorização se recusou a registrar você, ou até registrou, mas com credenciais que este fluxo não consegue usar (por exemplo, um método de autenticação que ele não implementa). `OAuthTokenError` significa que não foi possível obter um token: o endpoint de token disse não, ou um registro de cliente armazenado carrega um método de autenticação que este cliente não consegue aplicar, o que é reportado durante a montagem da requisição de token em vez de ser enviado. Um único `except OAuthFlowError:` cobre descoberta, registro, autorização e troca.

Nem tudo é erro de fluxo. A rede ainda pode falhar; essas são exceções comuns do `httpx2` e passam intactas.

## Recapitulando {#recap}

* `OAuthClientProvider` é um `httpx2.Auth`. Coloque-o em um `httpx2.AsyncClient`, passe esse cliente para `streamable_http_client(url, http_client=...)`, e `Client` nunca fica sabendo que houve OAuth.
* Você fornece quatro coisas: a URL do servidor, um `OAuthClientMetadata`, um `TokenStorage` e o par de handlers redirect/callback.
* `TokenStorage` é um `Protocol`: quatro métodos async, sem classe base. Persista `client_info` além dos tokens.
* Descoberta, registro (dinâmico ou via um **Client ID Metadata Document**), PKCE, as verificações de `state` e `iss` e a renovação de tokens são trabalho do provider, não seu.
* `ClientCredentialsOAuthProvider` é a versão sem humano: `client_id` + `client_secret`, sem handlers, sem navegador.
* Toda falha OAuth é um `OAuthFlowError`; `OAuthRegistrationError` e `OAuthTokenError` são suas subclasses.

A outra metade desse handshake, fazer o seu *servidor* exigir o token, está em **[Autorização](../run/authorization.md)**.
