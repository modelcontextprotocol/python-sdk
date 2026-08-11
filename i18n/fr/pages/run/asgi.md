---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# Ajouter à une application existante {#add-to-an-existing-app}

`mcp.run("streamable-http")` démarre un serveur web pour vous. Parfois, ce n’est pas ce que vous voulez : votre serveur MCP n’est qu’une pièce d’une application web plus vaste, ou vous avez déjà un déploiement ASGI.

Pour cela, `mcp.streamable_http_app()` renvoie une **application Starlette**.

Une application Starlette est une application ASGI, donc tout ce qui héberge de l’ASGI (uvicorn, Hypercorn, une autre application Starlette, FastAPI) peut héberger votre serveur MCP.

## L’application {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` est une application ASGI ordinaire. Passez-la à n’importe quel serveur ASGI :

```console
uvicorn server:app
```

Le point de terminaison MCP se trouve à `/mcp`, un client se connecte donc à `http://127.0.0.1:8000/mcp`.

L’application embarque déjà deux choses :

* Une route, `/mcp` : le point de terminaison Streamable HTTP.
* Un **cycle de vie** (lifespan) qui démarre `mcp.session_manager`, l’objet responsable du travail d’arrière-plan de chaque session active.

Exécutez l’application seule (`uvicorn server:app`) et vous n’aurez jamais à penser ni à l’un ni à l’autre.

!!! tip
    `streamable_http_app()` accepte les mêmes arguments nommés que `mcp.run("streamable-http", ...)`,
    à l’exception de `port` : le port appartient à ce qui sert l’application. `host` est toujours accepté mais ne lie
    rien ici ; **[Déployer et passer à l’échelle](deploy.md)** explique ce qu’il contrôle réellement.
    **[Exécuter votre serveur](index.md)** détaille les options elles-mêmes.

`mcp.sse_app()` fait la même chose pour le transport SSE, désormais remplacé.

## Localhost uniquement, jusqu’à ce que vous en décidiez autrement {#localhost-only-until-you-say-otherwise}

Par défaut, l’application répond **uniquement** aux requêtes adressées à localhost. `streamable_http_app()`
ne peut pas savoir derrière quel nom d’hôte elle sera servie ; elle active donc la protection contre le DNS rebinding avec la
liste d’autorisation la plus sûre possible ; sur votre machine, c’est exactement ce qu’il faut. Déployée derrière un vrai nom d’hôte,
cela signifie que **chaque requête est rejetée avec `421 Misdirected Request`** tant que vous n’avez pas passé à
`transport_security=` une liste d’autorisation de ce que vous servez réellement. Rien de ce que vous avez construit n’est même
consulté avant. Cette liste d’autorisation, et tout ce qui sépare une application fonctionnelle d’un vrai nom d’hôte,
c’est **[Déployer et passer à l’échelle](deploy.md)**.

## Le monter {#mounting-it}

Dès que le serveur MCP fait *partie* d’une application plus grande, vous placez l’application dans un `Mount`. Et dès que vous faites cela, le cycle de vie devient votre problème :

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` combiné au chemin par défaut `/mcp` garde le point de terminaison à `/mcp`. Starlette essaie les routes dans l’ordre et `Mount("/")` correspond à **tous** les chemins ; vos propres routes vont donc *avant* lui dans la liste. Tout ce qui vient après est inaccessible.
* La fonction `lifespan` entre dans `mcp.session_manager.run()` pour toute la durée de vie de l’application **hôte**. C’est la ligne que tout le monde oublie.
* `mcp.session_manager` n’existe qu’*après* l’appel à `streamable_http_app()`. C’est pourquoi les routes sont construites au niveau du module et que le gestionnaire de sessions n’est manipulé qu’à l’intérieur du cycle de vie.

La route `Host` de Starlette fonctionne de la même façon : remplacez `Mount("/", ...)` par `Host("mcp.example.com", ...)` pour router par nom d’hôte plutôt que par chemin. La règle du cycle de vie ne change pas, et celle de la sécurité du transport non plus. Une route `Host("mcp.example.com", ...)` ne reçoit jamais que les requêtes adressées à ce nom d’hôte, mais la propre liste d’autorisation Host du transport (**[Déployer et passer à l’échelle](deploy.md)**) s’exécute tout de même en premier. Sans `"mcp.example.com"` dedans, cette route répond à chacune d’elles par un `421`.

!!! warning "L’application hôte possède le cycle de vie"
    `streamable_http_app()` branche `session_manager.run()` sur le cycle de vie de l’application Starlette qu’elle
    renvoie, mais **le cycle de vie d’une sous-application montée ne s’exécute jamais**. Montez l’application et ce
    cycle de vie intégré devient du code mort. L’application située au sommet de votre pile ASGI, quelle qu’elle soit, doit entrer dans
    `mcp.session_manager.run()` dans son propre cycle de vie.

!!! check
    Supprimez la ligne `lifespan=lifespan` et démarrez le serveur. Il démarre. La route se résout.
    Puis la première requête vers `/mcp` échoue avec :

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    Rien ne démarre le gestionnaire de sessions, si ce n’est sa méthode `run()`.

## Deux serveurs, une application {#two-servers-one-app}

Chaque `MCPServer` est sa propre application avec son propre gestionnaire de sessions. Montez-en autant que vous voulez ; entrez dans chaque gestionnaire depuis l’unique cycle de vie de l’hôte :

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` entre dans les deux gestionnaires ; ils démarrent ensemble et s’arrêtent dans l’ordre inverse.
* Les points de terminaison sont `/notes/mcp` et `/tasks/mcp` : le préfixe de montage suivi du chemin par défaut.

## Changer le chemin {#changing-the-path}

Ce `/mcp` final, c’est `streamable_http_path`. Définissez-le à `"/"` et le préfixe de montage devient le chemin public complet :

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

Les clients se connectent désormais à `/notes`, et non à `/notes/mcp`.

## CORS pour les clients navigateur {#cors-for-browser-clients}

Un client qui s’exécute dans un navigateur a besoin de deux permissions de votre part : **envoyer** ses en-têtes de requête MCP, et **lire** celui que MCP renvoie. Les deux relèvent de la configuration CORS de l’application hôte, et la liste d’autorisation de la sécurité du transport ci-dessus doit concorder avec elle :

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` est la moitié que tout le monde oublie. Un navigateur envoie une **requête préliminaire** (preflight) avant chaque requête MCP, parce que `Content-Type: application/json` et les en-têtes de requête `Mcp-*` ne figurent pas dans la liste sûre de CORS, et un en-tête que la requête préliminaire n’accorde pas, c’est une requête que le navigateur n’envoie jamais. (`allow_headers=["*"]` fonctionne aussi : Starlette répond à une requête préliminaire avec ce qu’elle a demandé.)
* `expose_headers=["Mcp-Session-Id"]` est la moitié lecture. Streamable HTTP renvoie l’identifiant de session dans cet en-tête de réponse, et les navigateurs masquent les en-têtes de réponse au JavaScript sauf si CORS les expose nommément. Sans lui, le client ne peut jamais faire sa deuxième requête.
* `allow_origins` est votre décision, pas celle de MCP. Soyez précis, et reproduisez-le dans `allowed_origins=` ci-dessus : le navigateur applique CORS, mais le serveur vérifie lui-même l’en-tête `Origin`, et une origine à laquelle le transport ne fait pas confiance reçoit un `403` même après une requête préliminaire réussie.
* `allow_methods` liste les trois méthodes qu’utilise Streamable HTTP : `POST` pour envoyer des messages, `GET` pour ouvrir le flux serveur vers client, `DELETE` pour terminer la session.

## Routes personnalisées {#custom-routes}

`@mcp.custom_route()` enregistre un point de terminaison HTTP ordinaire sur la même application, pour ce dont tout service déployé a besoin et qui n’a rien à voir avec MCP : une vérification d’état, un rappel OAuth.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* Le gestionnaire est du Starlette ordinaire : une fonction `async` de `Request` vers `Response`.
* `streamable_http_app()` récupère chaque route personnalisée. `app.routes` contient maintenant `/mcp` et `/health`.
* `GET /health` répond `{"status": "ok"}` sans la moindre trace de MCP.

!!! warning
    Les routes personnalisées ne sont **jamais authentifiées**, même lorsque le reste du serveur l’est. C’est
    volontaire : les vérifications d’état et les rappels OAuth doivent être joignables avant qu’un quelconque jeton n’existe.
    Ne mettez rien de privé derrière l’une d’elles.

## Récapitulatif {#recap}

* `mcp.streamable_http_app()` renvoie une application Starlette avec une route, `/mcp`. N’importe quel serveur ASGI peut l’exécuter.
* Par défaut, l’application répond uniquement aux requêtes adressées à localhost, et derrière un vrai nom d’hôte elle rejette tout avec un `421` tant que vous n’avez pas passé à `transport_security=` une liste d’autorisation. **[Déployer et passer à l’échelle](deploy.md)** s’occupe de cela, et du reste du chemin vers la production.
* `Mount` (ou `Host`) la place dans une application Starlette ou FastAPI plus grande.
* **Le montage désactive le cycle de vie intégré.** Le cycle de vie de l’application hôte doit entrer dans `mcp.session_manager.run()`, sinon la première requête échoue.
* Plusieurs serveurs dans une même application, c’est plusieurs montages et un seul cycle de vie qui entre dans chaque gestionnaire de sessions.
* `streamable_http_path="/"` déplace le point de terminaison sur le préfixe de montage lui-même.
* Les clients navigateur ont besoin de CORS : `allow_headers` pour les en-têtes de requête `Mcp-*`, `expose_headers=["Mcp-Session-Id"]` pour la réponse.
* `@mcp.custom_route()` ajoute des points de terminaison HTTP ordinaires, non authentifiés, à côté de `/mcp`.

Une fois le serveur joignable à une vraie URL, **[Le client](../client/index.md)** s’y connecte avec cette URL plutôt qu’avec un objet serveur.
