---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# Asserção de identidade {#identity-assertion}

Um provider OAuth comum (**[Clientes OAuth](oauth-clients.md)**) começa fazendo uma pergunta ao servidor MCP: *em qual servidor de autorização você confia?* Ele segue a resposta para onde quer que ela aponte e, depois, ou uma pessoa faz login ou um segredo pré-compartilhado faz esse papel.

Uma empresa não quer nenhuma das duas coisas decidida servidor por servidor. Ela já opera um provedor de identidade (Okta, Microsoft Entra ID, o seu próprio); o usuário já fez login nele hoje de manhã; e esse é o único lugar onde o time de segurança quer decidir quem pode acessar o quê. A [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), a extensão **Enterprise-Managed Authorization**, leva a decisão para lá. O IdP assina um JWT de curta duração, um **Identity Assertion JWT Authorization Grant**, o **ID-JAG**: uma declaração de que *este usuário*, por meio *deste cliente*, pode acessar *este servidor MCP*. O cliente o troca por um token de acesso comum. Sem navegador, sem tela de consentimento, sem registro dinâmico.

Esta página cobre as duas pontas dessa troca. O servidor MCP em si não muda nada: continua sendo o servidor de recursos de **[Autorização](../run/authorization.md)**, verificando qualquer token que apareça.

## Duas requisições de token {#two-token-requests}

Duas autoridades diferentes estão em jogo, e saber distingui-las pelo nome é quase tudo o que você precisa para entender esta página. O **IdP corporativo** é o provedor de identidade da sua organização: ele sabe quem é o funcionário, é onde as políticas vivem e é quem emite o ID-JAG. O SDK nunca fala com ele. O **servidor de autorização MCP** é a mesma parte que era em **[Autorização](../run/authorization.md)**: o issuer nomeado nos metadados do servidor MCP, aquilo que emite os tokens que esse servidor MCP aceita. Em um fluxo OAuth comum, esses dois papéis costumam ser uma caixa só. Aqui são duas, e o grant inteiro é a segunda concordando em confiar na primeira.

O cliente faz uma requisição de token a cada uma.

1. **Ao IdP corporativo.** O cliente troca o login do usuário (o ID token OpenID Connect dele) pelo ID-JAG. É um token exchange da [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693), é inteiramente a API do seu IdP, e **o SDK não o faz**. Você faz, dentro de um único callback assíncrono. É também onde a decisão de política acontece: um IdP que diz não nunca emite o ID-JAG, e não há nada a apresentar.
2. **Ao servidor de autorização MCP.** O cliente apresenta o ID-JAG sob o grant `jwt-bearer` da [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, o ID-JAG como `assertion`) e recebe o token de acesso. **Esta é a requisição que o SDK faz**, e aceitá-la é a única coisa que esta página acrescenta a um servidor de autorização.

Tudo abaixo é a segunda requisição: o cliente que a envia e o servidor de autorização que a responde.

## O cliente {#the-client}

**`IdentityAssertionOAuthProvider`** fica em `mcp.client.auth.extensions.identity_assertion`. Como todo provider em **[Clientes OAuth](oauth-clients.md)**, ele é um `httpx2.Auth`: construa um, passe em `auth=`, entregue o `httpx2.AsyncClient` ao transporte.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

Leia de baixo para cima.

* `main()` é o `main()` padrão de cliente OAuth (**[Clientes OAuth](oauth-clients.md)**), sem mudar uma linha sequer. Esse é o ponto: uma vez que o provider existe, nada adiante sabe qual grant produziu o token.
* O provider recebe aquilo que os outros providers não conseguem descobrir: um `client_id` e um `client_secret` que alguém **pré-registrou** no servidor de autorização, o `issuer` desse servidor de autorização e `assertion_provider`, um callback assíncrono que retorna um ID-JAG novo sob demanda.
* `storage` é o mesmo protocolo `TokenStorage`. Só os dois métodos de token são chamados; não há registro dinâmico aqui, então não há `client_info` para lembrar.

### O provedor de asserção {#the-assertion-provider}

`fetch_id_jag(audience, resource)` é o único código que você escreve. Ele é aguardado com await uma vez por troca de token, nunca na construção, e só *depois* que os metadados do servidor de autorização foram buscados e validados, de modo que um issuer mal configurado nunca vaza uma asserção. Seus dois argumentos são duas das claims com que o ID-JAG precisa ser emitido: `audience` é o issuer do servidor de autorização (o `aud` do ID-JAG) e `resource` é o identificador canônico do servidor MCP (o `resource` do ID-JAG). A terceira você já tem em mãos: a claim `client_id` do ID-JAG precisa nomear o `client_id` que você deu ao provider, ou o servidor de autorização recusa a troca.

`idp_issue_id_jag`, logo acima, **não é código seu**. Ele faz o papel do provedor de identidade, assinando a asserção no próprio processo para que o arquivo fique completo e você possa ler cada claim que um ID-JAG carrega. Um `fetch_id_jag` de verdade faz, em vez disso, a primeira requisição de token da seção anterior: um token exchange da [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) contra o seu IdP, definido pelo draft Identity Assertion JWT Authorization Grant do qual a [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) é um perfil. O ID token do usuário logado entra como `subject_token`, o `requested_token_type` é a URN própria do ID-JAG (`urn:ietf:params:oauth:token-type:id-jag`), `audience` e `resource` passam direto, e a resposta traz o ID-JAG. Essa troca, com esses nomes, é o que procurar na documentação do seu IdP.

!!! tip
    Um ID-JAG novo é solicitado a cada troca, e esse é o ponto: é um grant de uso único, que vive
    minutos, e o servidor de autorização desta página se recusa a aceitar o mesmo duas vezes. Não
    faça cache dele. O que é reutilizado é o token de acesso que ele compra para você.

### O issuer é configuração {#the-issuer-is-configuration}

Aqui está a inversão. `OAuthClientProvider` pergunta ao servidor de recursos qual servidor de autorização usar e segue a resposta para onde quer que ela aponte. Este provider se recusa a fazer isso: `issuer` é obrigatório, os metadados da [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) são buscados no caminho well-known do próprio issuer, o endpoint de token precisa estar na origem desse issuer, e nada é perguntado ao servidor de recursos.

A extensão não exige isso; é uma escolha deliberadamente mais rígida. Este cliente carrega duas coisas que valem a pena roubar, um segredo pré-registrado e uma asserção vinculada a uma audience, e um cliente que deixasse um servidor MCP comprometido conduzi-lo até o servidor de autorização de um atacante postaria as duas lá. Fixar o issuer na construção elimina essa conversa.

!!! warning
    O `issuer` configurado é comparado com o campo `issuer` do documento de metadados pela
    comparação simples de strings da RFC 8414 §3.3: caractere por caractere, barra final incluída,
    sem normalização. Não chute. Busque `/.well-known/oauth-authorization-server` no seu servidor
    de autorização e copie o valor de `issuer` que ele retorna. Para o servidor de autorização desta
    página, é `https://auth.example.com/`, com a barra, porque seu issuer foi construído a partir de
    um objeto URL do pydantic. Uma divergência para o fluxo em `OAuthFlowError: Authorization server metadata issuer
    mismatch` antes de qualquer credencial ou asserção ser enviada.

### Um cliente confidencial {#a-confidential-client}

`client_secret` é obrigatório; o construtor levanta `ValueError` sem ele. O perfil do IETF por baixo da [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) reserva este grant para clientes confidenciais, a SEP-990 exige que o cliente se autentique, e este SDK impõe as duas coisas insistindo em um segredo compartilhado. `token_endpoint_auth_method` escolhe por onde ele viaja: `client_secret_post` (o padrão, no corpo do formulário) ou `client_secret_basic` (um cabeçalho HTTP Basic). O perfil também permite `private_key_jwt`; este provider não oferece suporte a ele.

!!! tip
    Leia `client_secret` do ambiente ou de um gerenciador de segredos, nunca do controle de versão.

### O que o provider faz por você {#what-the-provider-does-for-you}

A primeira requisição sai sem autenticação, e o `401` do servidor inicia o fluxo.

1. **Descoberta.** Ele busca os metadados do servidor de autorização no caminho well-known da [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) do issuer configurado, verifica que o `issuer` do documento confere e verifica que o endpoint de token está na origem do issuer.
2. **A asserção.** Ele aguarda com await o seu `assertion_provider`.
3. **Troca.** Ele faz POST do grant `jwt-bearer` no endpoint de token, armazena o `OAuthToken` e reenvia sua requisição original com `Authorization: Bearer ...`.

Um `403` cujo `WWW-Authenticate` nomeia `insufficient_scope` executa os passos 2 e 3 de novo com a união do seu `scope` com o do desafio. (`scope` nunca passa de uma solicitação; o servidor de autorização desta página concede o que o ID-JAG diz e nada mais.) Não há refresh token em lugar nenhum disto: quando o token de acesso expira, o próximo `401` emite um ID-JAG novo e troca de novo, e *essa* é a alavanca que o IdP tem nas mãos. As falhas são as mesmas duas exceções do resto de **[Clientes OAuth](oauth-clients.md)**: `OAuthFlowError` para descoberta e validação, sua subclasse `OAuthTokenError` quando o endpoint de token diz não.

## O servidor de autorização {#the-authorization-server}

Na maioria das vezes você para aqui. O servidor de autorização MCP é produto de outra pessoa, aceitar ID-JAGs é uma configuração dele a ser ligada, e a metade da [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) que cabe ao SDK é o cliente acima.

O SDK também pode *ser* o servidor de autorização: `create_auth_routes` retorna as rotas do servidor de autorização como uma lista que qualquer app Starlette pode montar, e é assim que `examples/servers/simple-auth/` no repositório executa um. A SEP-990 acrescenta uma flag e um método a essa superfície:

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` controla tudo. Desligada, que é o padrão, `/token` responde a este grant com `unsupported_grant_type` mesmo que você tenha implementado o hook, e os metadados não o mencionam. Ligada, os metadados ganham o grant type `jwt-bearer` e listam `urn:ietf:params:oauth:grant-profile:id-jag` em `authorization_grant_profiles_supported`, o campo que a extensão usa para anunciar suporte. (O cliente deste SDK nunca o lê: ele é provisionado para um único issuer e simplesmente pede.)
* **`exchange_identity_assertion`** é o hook. Antes de ele rodar, o SDK já autenticou o cliente, recusou clientes públicos e recusou clientes cujo registro não lista o grant. Você recebe um `IdentityAssertionParams` (a `assertion` crua, os `scopes` e o `resource` solicitados) e retorna um `OAuthToken` simples.
* O registro dinâmico de clientes recusa este grant incondicionalmente, então `get_client` aqui serve um cliente provisionado à mão. Um cliente ID-JAG não consegue passar a existir registrando a si mesmo.
* Metade da classe são recusas. `OAuthAuthorizationServerProvider` é o servidor de autorização *inteiro*, então também pede o fluxo authorization code; um servidor que também faz login de usuários implementa esses métodos de verdade, e este aqui tem exatamente uma porta.

!!! warning
    O SDK nunca decodifica a asserção: só o seu deploy sabe em qual IdP confia e quais chaves esse
    IdP publica, então tudo dentro de `exchange_identity_assertion` é o que sustenta a segurança.
    Verifique a assinatura contra as chaves publicadas pelo IdP (o JWKS dele; o segredo
    compartilhado aqui é o da demo), e também `iss` e `exp`, conforme a [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3. Exija que o
    `typ` do cabeçalho do JWT seja `oauth-id-jag+jwt`, a proteção do perfil contra algum outro JWT
    ser reapresentado como grant. Exija que `aud` seja o seu próprio issuer. Exija que a claim
    `client_id` do ID-JAG seja igual ao cliente que o handler autenticou, e que a claim `resource`
    nomeie um recurso que você de fato serve. Rastreie o `jti` até o `exp` da asserção para que ela
    seja aceita uma vez só. E tire os escopos concedidos e, acima de tudo, o `resource` do token
    emitido do ID-JAG validado, nunca da requisição: `params.resource` é o que quer que o cliente
    tenha digitado. As regras completas de processamento estão na
    [especificação Enterprise-Managed Authorization](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).

Rejeite uma asserção ruim com `TokenError("invalid_grant", ...)`. O outro código de erro neste fluxo é `invalid_target`: um ID-JAG que nomeia um recurso que você não serve é recusado com ele, e é isso que impede este servidor de emitir tokens para o recurso de outra pessoa. E os escopos concedidos vêm da claim `scope` do ID-JAG (uma asserção sem ela também é recusada); o seu talvez mapeie os grupos do usuário em vez disso.

E repare no que o `OAuthToken` retornado não carrega: um refresh token. O IdP decide por quanto tempo este usuário mantém o acesso ao decidir se emite o próximo ID-JAG. Um refresh token emitido aqui devolveria essa decisão sem alarde.

!!! info
    Um servidor que ainda embute seu servidor de autorização com `auth_server_provider=` chega ao
    mesmo código por meio de `AuthSettings(identity_assertion_enabled=True)`. **[Autorização](../run/authorization.md)** explica
    por que servidores novos não deveriam começar por aí.

!!! check
    Conecte os dois arquivos desta página e o grant inteiro é um único `POST /token`:

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    Sem `/authorize`, sem `/register`, sem busca de protected-resource metadata. As únicas
    requisições na rede são a que provocou o `401`, a busca do well-known, esta troca e, depois,
    tráfego MCP comum com o bearer anexado. E o `sub` que o seu validador leu do ID-JAG é
    exatamente o que `get_access_token().subject` informa dentro de uma ferramenta.

### Experimente {#try-it}

`examples/stories/identity_assertion/` no repositório do SDK é esta página rodando de verdade: o mesmo validador `exchange_identity_assertion`, um servidor MCP protegido pelos tokens dele, um IdP substituto e o cliente, em um único programa que se autoverifica. `uv run python -m stories.identity_assertion.client --http` executa a troca inteira e confirma com assert que o usuário que o IdP nomeou é o usuário que a ferramenta vê.

## Recapitulando {#recap}

* A [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) deixa o provedor de identidade corporativo, e não o usuário final, decidir quais servidores MCP um cliente pode acessar. O IdP assina essa decisão em um **ID-JAG**.
* Obter o ID-JAG é um token exchange da [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) contra *o seu IdP*, e o SDK não o faz. Apresentá-lo ao servidor de autorização MCP é o grant `jwt-bearer` da [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523), e o SDK faz os dois lados disso.
* `IdentityAssertionOAuthProvider` é mais um `httpx2.Auth`: um cliente confidencial pré-registrado, um `issuer` fixado e um callback `assertion_provider(audience, resource)`. Sem navegador, sem registro, sem refresh token.
* O servidor de autorização nunca é descoberto a partir do servidor de recursos. Configure `issuer` com exatamente a string que o documento de metadados dele serve; a comparação é caractere por caractere.
* Do lado do servidor, `identity_assertion_enabled=True` mais `exchange_identity_assertion`. O SDK autentica o cliente e controla o acesso ao grant; validar o ID-JAG é inteiramente com você, e o token emitido fica vinculado ao `resource` do ID-JAG, não ao da requisição.

A única parte que esta página nunca tocou é o servidor MCP. O que ele faz com o token que você acabou de emitir, ele já fazia em **[Autorização](../run/authorization.md)**.
