---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# Clients OAuth {#oauth-clients}

Certains serveurs MCP sont protégés. Envoyez-leur une requête sans jeton et ils répondent `401 Unauthorized`.

**`OAuthClientProvider`** est le moyen d’obtenir ce jeton. Ce n’est pas du tout un objet MCP. C’est un `httpx2.Auth`, le hook standard de httpx2 pour « faire quelque chose à chaque requête ». Vous l’attachez à un `httpx2.AsyncClient`, vous confiez ce client au transport Streamable HTTP, et vous n’y pensez plus.

Cette page couvre le côté client. Pour que votre propre serveur exige un jeton, voyez **[Autorisation](../run/authorization.md)**.

## Le fournisseur {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

Vous lui donnez quatre choses :

* `server_url` : le point de terminaison MCP auquel vous vous connectez. Le fournisseur découvre tout le reste à partir de lui.
* `client_metadata` : ce que vous saisiriez dans le formulaire « enregistrer une application » d’un serveur d’autorisation.
* `storage` : là où les jetons vivent entre deux exécutions.
* `redirect_handler` et `callback_handler` : les deux moments où un humain intervient.

Rien d’autre dans le fichier ne mentionne OAuth. `main()` ne voit jamais un jeton.

### Métadonnées du client {#client-metadata}

`OAuthClientMetadata` est le véritable document d’enregistrement de la [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591), sous forme de modèle Pydantic.

Vous définissez trois champs. Les valeurs par défaut remplissent le reste : `grant_types` vaut déjà `["authorization_code", "refresh_token"]` et `response_types` vaut déjà `["code"]`, ce qui correspond exactement au flux qu’exécute ce fournisseur.

!!! check
    Comme c’est un modèle Pydantic, il valide **avant qu’un seul octet ne parte sur le réseau**.
    Omettez `redirect_uris` et la construction échoue immédiatement avec une `ValidationError` qui
    nomme le champ :

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    Aucun navigateur ouvert, aucun enregistrement à moitié terminé laissé derrière sur le serveur d’autorisation.

### Stockage des jetons {#token-storage}

**`TokenStorage`** est un `Protocol` avec quatre méthodes asynchrones. Vous n’héritez de rien ; écrivez les méthodes et n’importe quelle classe devient un magasin de jetons :

* `get_tokens` / `set_tokens` conservent l’objet `OAuthToken` : jeton d’accès, jeton d’actualisation, expiration, portée.
* `get_client_info` / `set_client_info` conservent l’objet `OAuthClientInformationFull` que le serveur d’autorisation a émis lorsque le fournisseur vous a enregistré, y compris votre `client_id`.

La version en mémoire ci-dessus fonctionne. Elle oublie aussi tout quand le processus se termine, si bien que l’exécution suivante refait toute la procédure. Persistez-la dans un fichier ou dans le trousseau de votre plateforme et l’exécution suivante est silencieuse.

!!! tip
    Stockez `client_info`, pas seulement les jetons. Le fournisseur s’enregistre dynamiquement la première fois qu’il
    ne trouve aucun `client_info` stocké. Jetez-le et vous créez un nouvel enregistrement à chaque exécution.

### Les deux gestionnaires {#the-two-handlers}

Le flux du code d’autorisation a besoin d’un humain exactement une fois : quelqu’un doit se connecter et cliquer sur « autoriser ».

* **`redirect_handler`** est attendu (await) avec l’URL d’autorisation entièrement construite. Le `client_id`, le `redirect_uri`, le `state` et le défi PKCE y figurent déjà. Votre seul travail est d’y amener un navigateur. Une application de bureau appelle `webbrowser.open` ; ce fichier l’affiche.
* **`callback_handler`** est attendu ensuite. Il patiente jusqu’à ce que l’utilisateur revienne sur votre `redirect_uri` et renvoie les paramètres de requête de cette redirection sous la forme d’un `AuthorizationCodeResult`.

Un vrai client fait tourner un petit serveur HTTP local sur l’URI de redirection au lieu d’appeler `input()`. La forme est identique : recevoir la redirection, rendre `code`, `state` et `iss`.

!!! warning
    Transmettez `state` et `iss` exactement tels qu’ils sont arrivés. Le fournisseur compare `state` à celui
    qu’il a généré et `iss` à l’émetteur qu’il a découvert, et refuse toute divergence. Ce sont les défenses
    contre le CSRF et contre la confusion de serveurs (mix-up).

### Dans le `Client` {#into-the-client}

Regardez `main()`. Le fournisseur va sur le **client httpx2**, le client httpx2 va dans `streamable_http_client(url, http_client=...)`, et ce transport va dans `Client`.

`streamable_http_client` n’a pas de mot-clé `auth=`. Tout ce qui relève du niveau HTTP (authentification, en-têtes, délais d’expiration, proxys) appartient au `httpx2.AsyncClient` que vous apportez. Cette superposition de couches est décrite dans **[Transports client](transports.md)**.

## Ce que le fournisseur fait pour vous {#what-the-provider-does-for-you}

La première fois que `Client` envoie une requête, le serveur répond `401`. Le fournisseur prend le relais :

1. **Découverte.** Il lit l’en-tête `WWW-Authenticate`, récupère les Protected Resource Metadata du serveur depuis `/.well-known/oauth-protected-resource`, apprend quel serveur d’autorisation protège cette ressource, et récupère les métadonnées de *ce* serveur-là.
2. **Enregistrement.** Rien dans le stockage ? Il vous enregistre dynamiquement avec votre `OAuthClientMetadata` et stocke le résultat.
3. **Autorisation.** Il génère la paire PKCE et un `state`, construit l’URL d’autorisation, attend votre `redirect_handler`, puis attend votre `callback_handler` pour obtenir le code.
4. **Échange.** Il échange le code contre un `OAuthToken`, le stocke, et rejoue votre requête d’origine avec `Authorization: Bearer ...`.

Après cela, il se fait discret. Les jetons sortent du stockage, un jeton d’accès expiré est actualisé avec le jeton d’actualisation, et ce n’est que lorsque rien de tout cela ne fonctionne qu’il relance le flux.

Vous n’avez rien écrit de tout cela. Il reste deux arguments nommés (`client_metadata_url` et `validate_resource_url`), et ce fichier n’a besoin d’aucun des deux. `client_metadata_url` est celui qui mérite d’être connu ; il a sa propre section plus bas.

### Essayer {#try-it}

La plupart des exemples de cette documentation se vérifient avec un `Client(server)` en mémoire. Pas celui-ci : tout l’intérêt du flux est un `401` HTTP, et il n’y a pas de HTTP entre un client en mémoire et son serveur.

Le dépôt fournit la version réelle. `examples/servers/simple-auth/` exécute un serveur d’autorisation autonome et un serveur MCP protégé ; `examples/clients/simple-auth-client/` est le client de cette page devenu une petite CLI. Son README donne les deux commandes : démarrez les serveurs, lancez le client contre eux, et vous voyez défiler les quatre étapes.

## Client ID Metadata Documents {#client-id-metadata-documents}

La révision 2026-07-28 de la spécification rend obsolète l’enregistrement dynamique des clients au profit des **Client ID Metadata Documents** (CIMD). Au lieu d’envoyer par POST un nouvel enregistrement à chaque serveur d’autorisation qu’il rencontre, votre client publie un unique document JSON le décrivant à une URL HTTPS stable, et cette URL *est* son `client_id`. Le serveur d’autorisation récupère le document ; le fournisseur n’y touche jamais.

Le SDK le parle déjà : passez l’URL dans `client_metadata_url=` quand vous construisez le fournisseur. Lorsque les métadonnées du serveur d’autorisation annoncent `client_id_metadata_document_supported: true`, le fournisseur saute entièrement la requête `/register` : l’URL entre dans le flux en tant que `client_id`, et il n’y a pas de `client_secret`. Lorsque le serveur ne l’annonce pas (la plupart ne le font pas encore), ou que vous ne passez jamais d’URL, le fournisseur se rabat **silencieusement** sur l’enregistrement dynamique, et tout ce qui précède fonctionne exactement comme décrit. Un `client_info` stocké l’emporte toujours sur les deux.

L’URL doit être en HTTPS avec un chemin autre que la racine ; tout le reste lève une `ValueError` à la construction, avant le moindre échange réseau. L’exemple fourni `examples/clients/simple-auth-client/` la reçoit via la variable d’environnement `MCP_CLIENT_METADATA_URL`.

## De machine à machine {#machine-to-machine}

Une tâche nocturne, une étape de CI, un autre service. Il n’y a pas de navigateur et personne pour cliquer sur « autoriser ». C’est le type d’octroi **client credentials** : vous détenez déjà un `client_id` et un `client_secret`, et le point de terminaison de jeton constitue tout le flux.

`ClientCredentialsOAuthProvider` est le même `httpx2.Auth`, l’humain en moins :

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

Ce qui a changé :

* Aucun `OAuthClientMetadata`, aucun gestionnaire. Vous passez `client_id` et `client_secret` ; le fournisseur construit autour d’eux un enregistrement `client_credentials` minimal et saute entièrement l’enregistrement dynamique.
* `scope` est une chaîne séparée par des espaces, le format qu’OAuth utilise sur la liaison.
* Tout ce qui se trouve en aval est identique : le même `TokenStorage`, le même `httpx2.AsyncClient(auth=...)`, le même `streamable_http_client`.

Par défaut, le secret voyage en authentification HTTP Basic sur la requête de jeton (`client_secret_basic`). Passez `token_endpoint_auth_method="client_secret_post"` pour le placer plutôt dans le corps du formulaire. Certains serveurs d’autorisation n’acceptent que l’une des deux méthodes.

!!! tip
    Lisez `client_secret` depuis l’environnement ou un gestionnaire de secrets, jamais depuis le contrôle de version.

!!! info
    Un fournisseur de plus se trouve dans `mcp.client.auth.extensions.client_credentials` :
    **`PrivateKeyJWTOAuthProvider`**, pour les clients qui s’authentifient avec un JWT plutôt qu’avec un
    secret partagé (`private_key_jwt`, la variante à paire de clés et identité de charge de travail). Il suit
    le même schéma : construisez-en un, placez-le sur `auth=`. Le même module fournit
    `SignedJWTParameters` et `static_assertion_provider`, deux utilitaires qui construisent son assertion.

Il existe une autre situation sans humain : le client appartient à une entreprise dont le fournisseur d’identité, et non l’utilisateur, décide quels serveurs MCP il peut atteindre. C’est un type d’octroi différent, avec son propre modèle de confiance et sa propre page, **[Assertion d’identité](identity-assertion.md)**.

## En cas d’échec {#when-it-fails}

Quand le flux OAuth tourne mal, le fournisseur lève une `OAuthFlowError` depuis `mcp.client.auth`. Elle a deux sous-classes. `OAuthRegistrationError` signifie que l’enregistrement n’a pas produit un client utilisable : le serveur d’autorisation a refusé de vous enregistrer, ou il vous a bien enregistré mais avec des identifiants que ce flux ne peut pas utiliser (par exemple une méthode d’authentification qu’il n’implémente pas). `OAuthTokenError` signifie qu’un jeton n’a pas pu être obtenu : le point de terminaison de jeton a dit non, ou une fiche client stockée porte une méthode d’authentification que ce client ne peut pas appliquer, ce qui est signalé pendant la construction de la requête de jeton plutôt qu’envoyé. Un seul `except OAuthFlowError:` couvre la découverte, l’enregistrement, l’autorisation et l’échange.

Tout n’est pas une erreur de flux. Le réseau peut toujours échouer ; ce sont des exceptions `httpx2` ordinaires et elles passent sans être modifiées.

## Récapitulatif {#recap}

* `OAuthClientProvider` est un `httpx2.Auth`. Placez-le sur un `httpx2.AsyncClient`, passez celui-ci à `streamable_http_client(url, http_client=...)`, et `Client` ne sait jamais qu’OAuth a eu lieu.
* Vous fournissez quatre choses : l’URL du serveur, un `OAuthClientMetadata`, un `TokenStorage` et la paire de gestionnaires redirect/callback.
* `TokenStorage` est un `Protocol` : quatre méthodes asynchrones, pas de classe de base. Persistez `client_info` en plus des jetons.
* La découverte, l’enregistrement (dynamique, ou via un **Client ID Metadata Document**), PKCE, les vérifications de `state` et `iss`, et l’actualisation des jetons sont l’affaire du fournisseur, pas la vôtre.
* `ClientCredentialsOAuthProvider` est la version sans humain : `client_id` + `client_secret`, pas de gestionnaires, pas de navigateur.
* Tout échec OAuth est une `OAuthFlowError` ; `OAuthRegistrationError` et `OAuthTokenError` en sont les sous-classes.

L’autre moitié de cette poignée de main, faire en sorte que votre *serveur* exige le jeton, se trouve dans **[Autorisation](../run/authorization.md)**.
