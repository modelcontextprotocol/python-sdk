---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# Autorização {#authorization}

Sobre Streamable HTTP, seu servidor MCP é um serviço web comum, e você o protege como protege qualquer serviço web: com bearer tokens do OAuth 2.1.

Nos termos do OAuth, seu servidor é um **resource server**. Ele nunca autentica ninguém e nunca emite um token. Ele faz uma coisa só: olha o header `Authorization` de cada requisição e decide se o token que está ali é válido.

Esta página é o lado do servidor. Um cliente que descobre seu servidor de autorização e busca o token está em **[Clientes OAuth](../client/oauth-clients.md)**.

## As três partes {#the-three-parties}

* O **servidor de autorização** autentica as pessoas e emite tokens de acesso. Você não escreve isso. É o seu provedor de identidade (Auth0, Keycloak, Entra, o seu próprio).
* O **resource server** é o seu servidor MCP. Ele verifica o token em cada requisição.
* O **cliente** descobre em qual servidor de autorização você confia, obtém um token dele e o envia de volta para você como `Authorization: Bearer <token>`.

O triângulo inteiro é esse. Tudo nesta página é o item do meio.

## Um verificador de tokens {#a-token-verifier}

O SDK não tem opinião sobre como é um token válido. Você diz a ele, implementando **`TokenVerifier`**:

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` é um protocolo com um único método assíncrono. `verify_token` recebe o token bruto do header `Authorization` e retorna um **`AccessToken`** se ele for válido, `None` se não for. Não há mais nada a implementar.
* Este aqui procura o token em uma tabela. Um de verdade verifica a assinatura de um JWT ou chama o endpoint de introspecção de tokens do servidor de autorização. Esse código é seu; o SDK apenas o chama.
* `token_verifier=` e `auth=` sempre andam juntos. Passe um sem o outro e `MCPServer(...)` levanta um `ValueError` antes mesmo de atender uma requisição.

`AuthSettings` é a face pública do seu resource server:

* `issuer_url`: o servidor de autorização que emite seus tokens.
* `resource_server_url`: a URL pública deste endpoint MCP. Ela indica *a qual* recurso um token se destina, e é onde fica o documento de descoberta.
* `required_scopes`: todo token deve conter todos eles.

!!! tip
    `examples/servers/simple-auth/` no repositório do SDK tem um `IntrospectionTokenVerifier` que chama
    o endpoint da [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) de um servidor de autorização real. É o formato que a maioria dos verificadores de produção tem.

## O que você recebe sobre HTTP {#what-you-get-over-http}

A autorização vive em headers HTTP, então só existe nos transportes HTTP. Execute-a no transporte em que você faz o deploy: `mcp.run(transport="streamable-http")` a coloca em `http://127.0.0.1:8000/mcp`, e **[Executando seu servidor](index.md)** tem o resto. O app agora tem duas rotas:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

Você registrou uma ferramenta. A segunda rota é do SDK.

### Descoberta {#discovery}

Faça um `GET` nesse caminho well-known e você recebe o **Protected Resource Metadata da [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)**, montado direto a partir do seu `AuthSettings`:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

Esse documento é como um cliente que nunca ouviu falar do seu servidor encontra o caminho de entrada: ele lê `authorization_servers` e vai até lá buscar um token. Você não escreveu nada disso.

!!! check
    Chame `/mcp` sem token (ou com um para o qual seu verificador retornou `None`) e a requisição é
    barrada na porta:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    Nada foi parseado e nenhuma ferramenta foi executada. E aquele ponteiro `resource_metadata` em `WWW-Authenticate` é
    o que torna a descoberta automática: 401 -> documento de metadados -> servidor de autorização -> token -> nova tentativa.

!!! warning
    Nada disso protege o `stdio`. Um pipe não tem header `Authorization`, então `token_verifier` nunca é
    consultado ali. A fronteira de segurança de um servidor `stdio` é o processo que o iniciou. O mesmo
    vale para o `Client(mcp)` em memória que você usa nos testes: ele se conecta direto ao objeto do servidor
    e pula a camada HTTP, autorização incluída.

## A identidade de quem chama {#the-callers-identity}

Dentro de qualquer handler, **`get_access_token()`** é o `AccessToken` que seu verificador retornou para a requisição atual:

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* Funciona em ferramentas, recursos e prompts, e não há nada para passar adiante: o middleware de autenticação o guarda em uma variável de contexto por requisição.
* Você recebe de volta o **mesmo objeto que seu verificador montou**: `client_id`, `scopes`, `subject`, `expires_at` e quaisquer `claims` extras que você anexou. Esse é o gancho para regras por ferramenta: leia os escopos e recuse.
* Fora de uma requisição HTTP autenticada, ele retorna `None`. Em memória e sobre `stdio`, é sempre `None`.

Chame `whoami` com `Authorization: Bearer alice-token` e o modelo lê:

```text
alice (scopes: notes:read)
```

## A metade que o SDK não faz {#the-half-the-sdk-doesnt-do}

O SDK entrega a metade do resource server: verificar, anunciar, recusar. Ele não entrega uma página de login, uma tela de consentimento nem um token.

Para ver as três partes em ação, execute `examples/servers/simple-auth/` do repositório do SDK (um pequeno servidor de autorização e um resource server configurado exatamente como nesta página) e então aponte `examples/clients/simple-auth-client/` para ele e veja a dança completa de descoberta e token.

!!! info
    Existe um segundo argumento do construtor, `auth_server_provider=`, que embute um servidor de autorização
    completo dentro do seu servidor MCP. Ele é anterior à separação AS/RS em torno da qual a especificação
    de autorização do MCP foi construída. Servidores novos não devem recorrer a ele.

Um servidor de autorização também pode aceitar a asserção assinada de um provedor de identidade corporativo no lugar de um usuário clicando em uma tela de consentimento, e o SDK dá suporte aos dois lados dessa troca. O grant, e o cliente que o apresenta, está em **[Asserção de identidade](../client/identity-assertion.md)**.

## Recapitulando {#recap}

* Sobre Streamable HTTP, seu servidor é um **resource server** do OAuth 2.1: ele verifica tokens, nunca os emite.
* `TokenVerifier` é toda a superfície de integração: um método assíncrono, token entra, `AccessToken | None` sai.
* `token_verifier=` e `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` sempre andam juntos.
* O SDK publica o Protected Resource Metadata da [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) em `/.well-known/oauth-protected-resource/...` e responde a requisições não autenticadas com um 401 cujo header `WWW-Authenticate` aponta para ele. A história da descoberta é toda essa.
* `get_access_token()` em qualquer handler diz quem está chamando.
* Autorização é assunto do HTTP. O `stdio` e o cliente em memória nunca a veem.

A metade do cliente (descobrir seu servidor de autorização e buscar o token para você) está em **[Clientes OAuth](../client/oauth-clients.md)**. E um cliente que *afirma* uma identidade em vez de pedir uma ao usuário está em **[Asserção de identidade](../client/identity-assertion.md)**.
