---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# Assertion d’identité {#identity-assertion}

Un fournisseur OAuth ordinaire (**[Clients OAuth](oauth-clients.md)**) commence par poser une question au serveur MCP : *à quel serveur d’autorisation faites-vous confiance ?* Il suit la réponse où qu’elle mène, puis soit une personne se connecte, soit un secret pré-partagé en tient lieu.

Une entreprise ne veut voir ni l’un ni l’autre décidé serveur par serveur. Elle exploite déjà un fournisseur d’identité (Okta, Microsoft Entra ID, le vôtre) ; l’utilisateur s’y est déjà connecté ce matin ; et c’est l’unique endroit où l’équipe sécurité veut décider qui peut accéder à quoi. La [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), l’extension **Enterprise-Managed Authorization**, y déplace la décision. L’IdP signe un JWT de courte durée, un **Identity Assertion JWT Authorization Grant**, l’**ID-JAG** : une déclaration selon laquelle *cet utilisateur*, via *ce client*, peut accéder à *ce serveur MCP*. Le client l’échange contre un jeton d’accès ordinaire. Pas de navigateur, pas d’écran de consentement, pas d’enregistrement dynamique.

Cette page couvre les deux extrémités de cet échange. Le serveur MCP lui-même ne change jamais : il reste le serveur de ressources de **[Autorisation](../run/authorization.md)**, qui vérifie le jeton qui se présente, quel qu’il soit.

## Deux requêtes de jeton {#two-token-requests}

Deux autorités différentes sont en jeu, et bien les distinguer, c’est l’essentiel pour comprendre cette page. L’**IdP d’entreprise** est le fournisseur d’identité de votre organisation : il sait qui est l’employé, c’est là que réside la politique d’accès, et il émet l’ID-JAG. Le SDK ne lui parle jamais. Le **serveur d’autorisation MCP** est le même acteur que dans **[Autorisation](../run/authorization.md)** : l’émetteur nommé dans les métadonnées du serveur MCP, celui qui émet les jetons que ce serveur MCP accepte. Dans un flux OAuth ordinaire, ces deux rôles tiennent généralement dans une seule boîte. Ici ils sont deux, et tout le grant consiste en ce que le second accepte de faire confiance au premier.

Le client adresse une requête de jeton à chacun.

1. **Vers l’IdP d’entreprise.** Le client échange la connexion de l’utilisateur (son jeton d’identité OpenID Connect) contre l’ID-JAG. C’est un échange de jetons [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693), c’est entièrement l’API de votre IdP, et **le SDK ne l’effectue pas**. C’est vous qui le faites, dans une seule fonction de rappel (callback) asynchrone. C’est aussi là que se prend la décision de politique : un IdP qui dit non n’émet jamais l’ID-JAG, et il n’y a rien à présenter.
2. **Vers le serveur d’autorisation MCP.** Le client présente l’ID-JAG sous le grant `jwt-bearer` de la [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, l’ID-JAG comme `assertion`) et reçoit le jeton d’accès. **C’est la requête que le SDK effectue**, et l’accepter est la seule chose que cette page ajoute à un serveur d’autorisation.

Tout ce qui suit concerne la seconde requête : le client qui l’envoie et le serveur d’autorisation qui y répond.

## Le client {#the-client}

**`IdentityAssertionOAuthProvider`** se trouve dans `mcp.client.auth.extensions.identity_assertion`. Comme tous les fournisseurs de **[Clients OAuth](oauth-clients.md)**, c’est un `httpx2.Auth` : construisez-en un, placez-le sur `auth=`, passez le `httpx2.AsyncClient` au transport.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

Lisez-le en partant du bas.

* `main()` est le `main()` standard d’un client OAuth (**[Clients OAuth](oauth-clients.md)**), inchangé ligne pour ligne. C’est tout l’intérêt : une fois le fournisseur en place, rien en aval ne sait quel grant a produit le jeton.
* Le fournisseur prend ce que les autres fournisseurs ne peuvent pas découvrir : un `client_id` et un `client_secret` que quelqu’un a **pré-enregistrés** auprès du serveur d’autorisation, la valeur `issuer` de ce serveur d’autorisation, et `assertion_provider`, une fonction de rappel asynchrone qui renvoie un ID-JAG tout neuf à la demande.
* `storage` est le même protocole `TokenStorage`. Seules les deux méthodes de jeton sont appelées ; il n’y a pas d’enregistrement dynamique ici, donc pas de `client_info` à mémoriser.

### Le fournisseur d’assertion {#the-assertion-provider}

`fetch_id_jag(audience, resource)` est le seul code que vous écrivez. Il est attendu (await) une fois par échange de jeton, jamais à la construction, et seulement *après* que les métadonnées du serveur d’autorisation ont été récupérées et validées, si bien qu’un émetteur mal configuré ne laisse jamais fuiter une assertion. Ses deux arguments sont deux des claims avec lesquels l’ID-JAG doit être émis : `audience` est l’émetteur du serveur d’autorisation (le `aud` de l’ID-JAG) et `resource` est l’identifiant canonique du serveur MCP (le `resource` de l’ID-JAG). Le troisième, vous le détenez déjà : le claim `client_id` de l’ID-JAG doit nommer le `client_id` que vous avez donné au fournisseur, faute de quoi le serveur d’autorisation refuse l’échange.

`idp_issue_id_jag`, juste au-dessus, n’est **pas votre code**. Il tient lieu de fournisseur d’identité et signe l’assertion dans le processus même, pour que le fichier soit complet et que vous puissiez lire chaque claim que porte un ID-JAG. Un vrai `fetch_id_jag` effectue à la place la première requête de jeton de la section précédente : un échange de jetons [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) auprès de votre IdP, défini par le draft Identity Assertion JWT Authorization Grant dont la [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) définit un profil. Le jeton d’identité de l’utilisateur connecté y entre comme `subject_token`, le `requested_token_type` est l’URN propre à l’ID-JAG (`urn:ietf:params:oauth:token-type:id-jag`), `audience` et `resource` sont transmis tels quels, et la réponse porte l’ID-JAG. Cet échange, sous ces noms-là, est ce qu’il faut chercher dans la documentation de votre IdP.

!!! tip
    Un nouvel ID-JAG est demandé à chaque échange, et c’est voulu : c’est un grant à usage unique,
    valable quelques minutes, et le serveur d’autorisation de cette page refuse d’accepter deux fois
    le même. Ne le mettez pas en cache. C’est le jeton d’accès qu’il vous procure qui est réutilisé.

### L’émetteur relève de la configuration {#the-issuer-is-configuration}

Voici l’inversion. `OAuthClientProvider` demande au serveur de ressources quel serveur d’autorisation utiliser et suit la réponse où qu’elle mène. Ce fournisseur-ci s’y refuse : `issuer` est obligatoire, les métadonnées [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) sont récupérées depuis le chemin well-known de cet émetteur même, le point de terminaison de jeton doit se trouver sur l’origine de cet émetteur, et rien n’est jamais demandé au serveur de ressources.

L’extension ne l’exige pas ; c’est un choix délibérément plus strict. Ce client transporte deux choses qui valent d’être volées, un secret pré-enregistré et une assertion liée à une audience, et un client qui laisserait un serveur MCP compromis l’aiguiller vers le serveur d’autorisation d’un attaquant y posterait les deux. Épingler l’émetteur à la construction supprime purement et simplement cette conversation.

!!! warning
    La valeur `issuer` configurée est comparée au champ `issuer` du document de métadonnées par la
    comparaison de chaînes simple de la RFC 8414 §3.3 : caractère par caractère, barre oblique finale
    comprise, sans normalisation. Ne la devinez pas. Récupérez `/.well-known/oauth-authorization-server`
    auprès de votre serveur d’autorisation et copiez la valeur `issuer` qu’il renvoie. Pour le serveur
    d’autorisation de cette page, c’est `https://auth.example.com/`, avec la barre oblique, parce que
    son émetteur a été construit à partir d’un objet URL pydantic. Une discordance arrête le flux
    sur `OAuthFlowError: Authorization server metadata issuer
    mismatch` avant qu’un seul identifiant ou une seule assertion ne soit envoyé.

### Un client confidentiel {#a-confidential-client}

`client_secret` est obligatoire ; sans lui, le constructeur lève `ValueError`. Le profil IETF sous-jacent à la [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) réserve ce grant aux clients confidentiels, la SEP-990 exige que le client s’authentifie, et ce SDK fait respecter les deux en imposant un secret partagé. `token_endpoint_auth_method` choisit par où il transite : `client_secret_post` (la valeur par défaut, dans le corps du formulaire) ou `client_secret_basic` (un en-tête HTTP Basic). Le profil autorise aussi `private_key_jwt` ; ce fournisseur ne le prend pas en charge.

!!! tip
    Lisez `client_secret` depuis l’environnement ou un gestionnaire de secrets, jamais depuis le dépôt de code.

### Ce que le fournisseur fait pour vous {#what-the-provider-does-for-you}

La première requête part sans authentification, et le `401` du serveur démarre le flux.

1. **Découverte.** Il récupère les métadonnées du serveur d’autorisation depuis le chemin well-known [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) de l’émetteur configuré, vérifie que la valeur `issuer` du document correspond, et vérifie que le point de terminaison de jeton se trouve sur l’origine de l’émetteur.
2. **L’assertion.** Il attend (await) votre `assertion_provider`.
3. **Échange.** Il envoie en POST le grant `jwt-bearer` au point de terminaison de jeton, stocke le `OAuthToken`, et rejoue votre requête d’origine avec `Authorization: Bearer ...`.

Un `403` dont le `WWW-Authenticate` nomme `insufficient_scope` relance les étapes 2 et 3 avec l’union de votre `scope` et de celui du défi. (`scope` n’est jamais qu’une demande ; le serveur d’autorisation de cette page accorde ce que dit l’ID-JAG et rien d’autre.) Il n’y a de jeton d’actualisation nulle part ici : quand le jeton d’accès expire, le `401` suivant fait émettre un nouvel ID-JAG et relance l’échange, et c’est *là* le levier que détient l’IdP. Les échecs sont les deux mêmes exceptions que dans le reste de **[Clients OAuth](oauth-clients.md)** : `OAuthFlowError` pour la découverte et la validation, sa sous-classe `OAuthTokenError` quand le point de terminaison de jeton dit non.

## Le serveur d’autorisation {#the-authorization-server}

La plupart du temps, vous vous arrêtez ici. Le serveur d’autorisation MCP est le produit de quelqu’un d’autre, accepter les ID-JAG est une option de sa configuration à activer, et la moitié de la [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) qui revient au SDK est le client ci-dessus.

Le SDK peut aussi *être* le serveur d’autorisation : `create_auth_routes` renvoie les routes du serveur d’autorisation sous forme d’une liste que n’importe quelle application Starlette peut monter, et c’est ainsi que `examples/servers/simple-auth/` dans le dépôt en fait tourner un. La SEP-990 ajoute un drapeau et une méthode à cette surface :

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` conditionne tout. Désactivé, ce qui est la valeur par défaut, `/token` répond à ce grant par `unsupported_grant_type` même si vous avez implémenté le hook, et les métadonnées n’en font pas mention. Activé, les métadonnées gagnent le type de grant `jwt-bearer` et listent `urn:ietf:params:oauth:grant-profile:id-jag` dans `authorization_grant_profiles_supported`, le champ par lequel l’extension annonce sa prise en charge. (Le client de ce SDK ne le lit jamais : il est provisionné pour un seul émetteur et demande, tout simplement.)
* **`exchange_identity_assertion`** est le hook. Avant qu’il ne s’exécute, le SDK a authentifié le client, refusé les clients publics, et refusé les clients dont l’enregistrement ne liste pas le grant. Vous recevez un `IdentityAssertionParams` (la valeur `assertion` brute, les `scopes` et `resource` demandés) et renvoyez un simple `OAuthToken`.
* L’enregistrement dynamique des clients refuse ce grant sans condition, si bien que `get_client` sert ici un client provisionné à la main. Un client ID-JAG ne peut pas se faire exister en s’enregistrant lui-même.
* La moitié de la classe est faite de refus. `OAuthAuthorizationServerProvider` est le serveur d’autorisation *tout entier*, il réclame donc aussi le flux authorization code ; un serveur qui connecte aussi des utilisateurs implémente ces méthodes pour de bon, et celui-ci n’a qu’une seule porte.

!!! warning
    Le SDK ne décode jamais l’assertion : seul votre déploiement sait à quel IdP il fait confiance et
    quelles clés cet IdP publie, donc tout ce qui se trouve dans `exchange_identity_assertion` est
    déterminant. Vérifiez la signature par rapport aux clés publiées de l’IdP (son JWKS ; le secret
    partagé ici est celui de la démo), ainsi que `iss` et `exp`, selon la [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3. Exigez
    que le `typ` de l’en-tête JWT soit `oauth-id-jag+jwt`, le garde-fou du profil contre le rejeu
    d’un autre JWT comme grant. Exigez que `aud` soit votre propre émetteur. Exigez que le claim
    `client_id` de l’ID-JAG soit égal au client que le gestionnaire (handler) a authentifié, et que
    son claim `resource` nomme une ressource que vous servez réellement. Suivez `jti` jusqu’à la
    valeur `exp` de l’assertion pour qu’elle ne soit acceptée qu’une fois. Et tirez les scopes
    accordés et, surtout, le `resource` du jeton émis de l’ID-JAG validé, jamais de la requête :
    `params.resource` est ce que le client a tapé, quoi que ce soit. Les règles de traitement
    complètes sont dans la
    [spécification Enterprise-Managed Authorization](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).

Rejetez une mauvaise assertion avec `TokenError("invalid_grant", ...)`. L’autre code d’erreur de ce flux est `invalid_target` : un ID-JAG qui nomme une ressource que vous ne servez pas est refusé avec lui, et c’est ce qui empêche ce serveur d’émettre des jetons pour celle de quelqu’un d’autre. Et les scopes accordés viennent du claim `scope` de l’ID-JAG (une assertion qui n’en a pas est refusée elle aussi) ; le vôtre pourrait plutôt faire correspondre les groupes de l’utilisateur.

Et remarquez ce que le `OAuthToken` renvoyé ne porte pas : un jeton d’actualisation. L’IdP décide combien de temps cet utilisateur garde l’accès en décidant d’émettre ou non le prochain ID-JAG. Un jeton d’actualisation émis ici reprendrait en douce cette décision à l’IdP.

!!! info
    Un serveur qui embarque encore son serveur d’autorisation avec `auth_server_provider=` atteint le
    même code via `AuthSettings(identity_assertion_enabled=True)`. **[Autorisation](../run/authorization.md)** explique pourquoi
    les nouveaux serveurs ne devraient pas commencer par là.

!!! check
    Reliez les deux fichiers de cette page et tout le grant tient en un seul `POST /token` :

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

    Pas de `/authorize`, pas de `/register`, pas de récupération des métadonnées de ressource
    protégée. Les seules requêtes sur la liaison sont celle qui a provoqué le `401`, la récupération
    well-known, cet échange, puis le trafic MCP ordinaire avec le jeton porteur attaché. Et le `sub`
    que votre validateur a lu dans l’ID-JAG est exactement ce que `get_access_token().subject`
    rapporte à l’intérieur d’un outil.

### Essayer {#try-it}

`examples/stories/identity_assertion/` dans le dépôt du SDK, c’est cette page exécutée pour de bon : le même validateur `exchange_identity_assertion`, un serveur MCP protégé par ses jetons, un IdP de substitution et le client, dans un seul programme qui se vérifie lui-même. `uv run python -m stories.identity_assertion.client --http` exécute tout l’échange et vérifie par assertion que l’utilisateur nommé par l’IdP est bien celui que voit l’outil.

## Récapitulatif {#recap}

* La [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) laisse le fournisseur d’identité de l’entreprise, et non l’utilisateur final, décider quels serveurs MCP un client peut atteindre. L’IdP signe cette décision dans un **ID-JAG**.
* Obtenir l’ID-JAG est un échange de jetons [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) auprès de *votre IdP*, et le SDK ne l’effectue pas. Le présenter au serveur d’autorisation MCP relève du grant `jwt-bearer` de la [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523), et le SDK en assure les deux côtés.
* `IdentityAssertionOAuthProvider` est un `httpx2.Auth` de plus : un client confidentiel pré-enregistré, un `issuer` épinglé, et une fonction de rappel `assertion_provider(audience, resource)`. Pas de navigateur, pas d’enregistrement, pas de jeton d’actualisation.
* Le serveur d’autorisation n’est jamais découvert à partir du serveur de ressources. Configurez `issuer` avec exactement la chaîne que sert son document de métadonnées ; la comparaison se fait caractère par caractère.
* Côté serveur, `identity_assertion_enabled=True` plus `exchange_identity_assertion`. Le SDK authentifie le client et conditionne le grant ; valider l’ID-JAG vous revient entièrement, et le jeton émis est lié au `resource` de l’ID-JAG, pas à celui de la requête.

Le seul acteur auquel cette page n’a jamais touché est le serveur MCP. Ce qu’il fait du jeton que vous venez d’émettre, il le faisait déjà dans **[Autorisation](../run/authorization.md)**.
