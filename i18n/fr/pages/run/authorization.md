---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# Autorisation {#authorization}

Sur Streamable HTTP, votre serveur MCP est un service web ordinaire, et vous le protégez comme n’importe quel service web : avec des jetons porteurs OAuth 2.1.

En termes OAuth, votre serveur est un **serveur de ressources**. Il ne connecte jamais personne et n’émet jamais de jeton. Il fait une seule chose : examiner l’en-tête `Authorization` de chaque requête et décider si le jeton qu’il contient est valable.

Cette page traite du côté serveur. Un client qui découvre votre serveur d’autorisation et récupère le jeton, c’est **[Clients OAuth](../client/oauth-clients.md)**.

## Les trois parties {#the-three-parties}

* Le **serveur d’autorisation** connecte les utilisateurs et émet les jetons d’accès. Vous ne l’écrivez pas. C’est votre fournisseur d’identité (Auth0, Keycloak, Entra, le vôtre).
* Le **serveur de ressources**, c’est votre serveur MCP. Il vérifie le jeton à chaque requête.
* Le **client** découvre à quel serveur d’autorisation vous faites confiance, en obtient un jeton et vous le renvoie sous la forme `Authorization: Bearer <token>`.

C’est tout le triangle. Toute cette page porte sur le point du milieu.

## Un vérificateur de jetons {#a-token-verifier}

Le SDK n’a aucun avis sur ce à quoi ressemble un jeton valide. C’est vous qui le lui dites, en implémentant **`TokenVerifier`** :

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` est un protocole avec une seule méthode asynchrone. `verify_token` reçoit le jeton brut de l’en-tête `Authorization` et renvoie un **`AccessToken`** s’il est valide, `None` sinon. Il n’y a rien d’autre à implémenter.
* Celui-ci cherche le jeton dans une table. Un vérificateur réel vérifie la signature d’un JWT ou appelle le point de terminaison d’introspection de jetons du serveur d’autorisation. Ce code est le vôtre ; le SDK ne fait que l’appeler.
* `token_verifier=` et `auth=` vont toujours de pair. Passez l’un sans l’autre et `MCPServer(...)` lève une `ValueError` avant même de servir la moindre requête.

`AuthSettings` est la face publique de votre serveur de ressources :

* `issuer_url` : le serveur d’autorisation qui émet vos jetons.
* `resource_server_url` : l’URL publique de ce point de terminaison MCP. Elle désigne *quelle* ressource un jeton vise, et c’est là que réside le document de découverte.
* `required_scopes` : chaque jeton doit tous les porter.

!!! tip
    `examples/servers/simple-auth/` dans le dépôt du SDK contient un `IntrospectionTokenVerifier` qui appelle
    le point de terminaison [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) d’un véritable serveur d’autorisation. C’est la forme que prennent la plupart des vérificateurs en production.

## Ce que vous obtenez sur HTTP {#what-you-get-over-http}

L’autorisation vit dans les en-têtes HTTP, elle n’existe donc que sur les transports HTTP. Lancez-la sur celui que vous déployez : `mcp.run(transport="streamable-http")` la place sur `http://127.0.0.1:8000/mcp`, et le reste est dans **[Exécuter votre serveur](index.md)**. L’application possède désormais deux routes :

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

Vous avez enregistré un seul outil. La seconde route est celle du SDK.

### Découverte {#discovery}

Faites un `GET` sur ce chemin well-known et vous obtenez les **métadonnées de ressource protégée de la [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)** (Protected Resource Metadata), construites directement à partir de vos `AuthSettings` :

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

C’est grâce à ce document qu’un client qui n’a jamais entendu parler de votre serveur trouve son chemin : il lit `authorization_servers` et s’y rend pour obtenir un jeton. Vous n’en avez rien écrit.

!!! check
    Appelez `/mcp` sans jeton (ou avec un jeton pour lequel votre vérificateur a renvoyé `None`) et la requête
    est arrêtée à la porte :

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    Rien n’a été analysé et aucun outil n’a été exécuté. Et ce pointeur `resource_metadata` dans `WWW-Authenticate` est
    ce qui rend la découverte automatique : 401 -> document de métadonnées -> serveur d’autorisation -> jeton -> nouvelle tentative.

!!! warning
    Rien de tout cela ne protège `stdio`. Un tube n’a pas d’en-tête `Authorization`, donc `token_verifier` n’y est
    jamais consulté. La frontière de sécurité d’un serveur `stdio` est le processus qui l’a lancé. Il en va de
    même pour le `Client(mcp)` en mémoire que vous utilisez dans les tests : il se connecte directement à l’objet serveur
    et saute la couche HTTP, autorisation comprise.

## L’identité de l’appelant {#the-callers-identity}

Dans n’importe quel gestionnaire (handler), **`get_access_token()`** est l’objet `AccessToken` que votre vérificateur a renvoyé pour la requête en cours :

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* Cela fonctionne dans les outils, les ressources et les prompts, et il n’y a rien à transmettre : le middleware d’authentification le stocke dans une variable de contexte par requête.
* Vous récupérez le **même objet que celui construit par votre vérificateur** : `client_id`, `scopes`, `subject`, `expires_at` et tous les `claims` supplémentaires que vous y avez attachés. C’est le point d’accroche pour des règles par outil : lisez les scopes et refusez.
* En dehors d’une requête HTTP authentifiée, elle renvoie `None`. En mémoire et sur `stdio`, c’est toujours `None`.

Appelez `whoami` avec `Authorization: Bearer alice-token` et le modèle lit :

```text
alice (scopes: notes:read)
```

## La moitié que le SDK ne fait pas {#the-half-the-sdk-doesnt-do}

Le SDK vous donne la moitié serveur de ressources : vérifier, annoncer, refuser. Il ne vous donne ni page de connexion, ni écran de consentement, ni jeton.

Pour voir les trois parties en action, lancez `examples/servers/simple-auth/` depuis le dépôt du SDK (un petit serveur d’autorisation et un serveur de ressources configuré exactement comme sur cette page), puis pointez `examples/clients/simple-auth-client/` dessus pour la chorégraphie complète découverte-puis-jeton.

!!! info
    Il existe un second argument de constructeur, `auth_server_provider=`, qui embarque un serveur d’autorisation
    complet dans votre serveur MCP. Il est antérieur à la séparation AS/RS autour de laquelle la spécification
    d’autorisation MCP est construite. Les nouveaux serveurs ne devraient pas y recourir.

Un serveur d’autorisation peut aussi accepter l’assertion signée d’un fournisseur d’identité d’entreprise à la place d’un utilisateur qui valide un écran de consentement, et le SDK prend en charge les deux côtés de cet échange. Ce mode d’octroi (grant), et le client qui le présente, c’est **[Assertion d’identité](../client/identity-assertion.md)**.

## Récapitulatif {#recap}

* Sur Streamable HTTP, votre serveur est un **serveur de ressources** OAuth 2.1 : il vérifie les jetons, il n’en émet jamais.
* `TokenVerifier` est toute la surface d’intégration : une méthode asynchrone, un jeton en entrée, `AccessToken | None` en sortie.
* `token_verifier=` et `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` vont toujours de pair.
* Le SDK publie les métadonnées de ressource protégée (Protected Resource Metadata) de la [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) sur `/.well-known/oauth-protected-resource/...` et répond aux requêtes non authentifiées par un 401 dont l’en-tête `WWW-Authenticate` pointe vers elles. C’est tout le mécanisme de découverte.
* `get_access_token()` dans n’importe quel gestionnaire indique qui appelle.
* L’autorisation est une affaire de HTTP. `stdio` et le client en mémoire ne la voient jamais.

La moitié client (découvrir votre serveur d’autorisation et récupérer le jeton pour vous), c’est **[Clients OAuth](../client/oauth-clients.md)**. Et un client qui *affirme* une identité au lieu d’en demander une à un utilisateur, c’est **[Assertion d’identité](../client/identity-assertion.md)**.
