---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

Un **middleware** est une fonction asynchrone qui enveloppe chaque message que votre serveur reçoit.

Vous l’écrivez sous la forme `async (ctx, call_next)` et vous l’ajoutez à `server.middleware`. C’est toute l’API.

!!! warning
    La liste de middlewares est marquée **provisoire** dans le code source : sa signature et sa
    sémantique peuvent changer dans une version mineure 2.x. Utilisez-la pour *observer*
    (chronométrage, journalisation, traçage) et pour *refuser* des messages ; n’en faites pas la
    fondation sur laquelle repose votre serveur.

`MCPServer` reçoit la liste à la construction (`MCPServer(name, middleware=[...])`) et l’expose sous
`mcp.middleware` ; le `Server` bas niveau expose la même liste sous `server.middleware`. L’exemple
ci-dessous utilise le `Server` bas niveau ; si `Server(name, on_call_tool=...)` est nouveau pour
vous, lisez d’abord **[Le Server bas niveau](low-level-server.md)**.

## Un middleware de chronométrage {#a-timing-middleware}

Un serveur, un outil, un middleware qui journalise le temps pris par chaque message :

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` est le même `ServerRequestContext` que celui que reçoivent vos gestionnaires (handlers).
  `ctx.method` est la chaîne de méthode brute ; `ctx.params` contient les paramètres bruts,
  **avant** toute validation.
* `call_next(ctx)` exécute le reste de la chaîne : la validation, la recherche du gestionnaire,
  votre gestionnaire. Renvoyez ce qu’il a renvoyé et la réponse reste intacte.
* Le `try`/`finally` est délibéré : un gestionnaire qui lève une exception est tout de même
  chronométré, car l’échec atteint votre middleware sous la forme de l’exception qui sort de
  `call_next`.
* `server.middleware.append(...)` l’enregistre. La liste s’exécute de l’extérieur vers
  l’intérieur, donc `middleware[0]` est celui qui est le plus proche de la liaison.

### Essayer {#try-it}

Connectez un client, listez les outils, appelez-en un. Votre journal contient **trois** lignes :

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

Vous avez fait deux appels et obtenu trois lignes. La première est `server/discover` : la requête
que le client a envoyée pour établir la connexion, avant que vous ne demandiez quoi que ce soit.

C’est tout l’intérêt. Le middleware enveloppe **chaque** message entrant :

* La mise en place de la connexion : `server/discover`, ou `initialize` et
  `notifications/initialized` sur une session historique.
* Chaque requête et chaque notification. Pour une notification, `ctx.request_id is None`,
  `call_next(ctx)` renvoie `None`, et tout ce que vous renvoyez est ignoré.
* Même une méthode pour laquelle le serveur n’a pas de gestionnaire : `call_next` lève
  `MCPError(-32601, "Method not found")` *à travers* votre middleware en route vers le client.

## Ce que vous pouvez y faire {#what-you-can-do-inside-one}

Du geste le plus anodin à celui devant lequel vous devriez le plus hésiter :

* **Observer.** Chronométrer, compter, journaliser. C’est l’exemple ci-dessus.
* **Refuser.** Levez une `MCPError` *au lieu* d’appeler `call_next(ctx)` et ce message-là
  reçoit pour réponse une erreur JSON-RPC. La connexion reste ouverte ; le message suivant passe.
  C’est ainsi qu’un serveur contrôle l’accès à `subscriptions/listen` appelant par appelant : la
  section **[Décider qui peut observer](../handlers/subscriptions.md#deciding-who-may-watch)** de
  la page Abonnements détaille la démarche.
* **Réécrire.** `ctx` est une dataclass : `await call_next(dataclasses.replace(ctx, params=...))`
  transmet au reste de la chaîne d’autres paramètres que ceux envoyés par le client. Ne faites
  jamais cela pour `initialize` : le résultat que le client reçoit en retour est construit à
  partir de vos paramètres réécrits, mais le serveur fixe l’état de sa connexion à partir des
  paramètres d’origine reçus sur la liaison. Les deux côtés peuvent terminer la poignée de main
  (handshake) en désaccord sur ce qu’ils ont négocié.
* **Répondre.** Renvoyez un résultat sans appeler `call_next(ctx)` et il part au client comme
  votre réponse. `call_next` vous remet la forme finale telle qu’elle circule sur la liaison, et
  le pipeline ne retouche jamais ce que vous renvoyez ; toute l’enveloppe est donc à votre
  charge : sur une connexion de génération 2026, cela inclut l’estampille `_meta` `serverInfo`,
  que le SDK ajoute aux résultats des gestionnaires mais pas aux vôtres.

!!! check
    `initialize` fait partie de ce que le middleware enveloppe, et c’est le *seul* hook dont
    vous disposez pour lui. Essayez d’en prendre le contrôle avec `add_request_handler` et le
    SDK refuse :

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` est traité en ligne : le serveur ne lit aucun autre message entrant tant que
    votre chaîne de middlewares n’est pas revenue. Attendre une requête du serveur vers le client
    (`ctx.session.send_request(...)`, une élicitation (elicitation)) pendant le traitement de
    `initialize` **provoque donc l’interblocage de la connexion** : la réponse que vous attendez
    ne pourra jamais être lue. Les notifications envoyées sans attente de réponse ne posent pas
    de problème.

## Le seul middleware activé par défaut {#the-one-middleware-that-ships-on-by-default}

Le SDK fournit exactement un middleware, et il figure déjà dans la liste de votre serveur : celui
qui émet un span OpenTelemetry pour chaque message. Vous ne l’ajoutez pas et, la plupart du temps,
vous n’y pensez pas. Il ne fait rien tant que vous n’installez pas d’exporteur, et il a sa propre
page : **[OpenTelemetry](../run/opentelemetry.md)**.

!!! info
    Si vous avez déjà écrit un middleware ASGI, vous connaissez cette forme. Le
    `(scope, receive, send)` de Starlette est devenu `(ctx, call_next)`, et il s’exécute *après*
    le transport, sur le message décodé plutôt que sur la requête HTTP brute. Les deux se
    composent : un middleware Starlette sur `streamable_http_app()` voit du HTTP ; celui-ci voit
    du MCP.

## Récapitulatif {#recap}

* Un middleware est `async (ctx, call_next) -> result`, passé via `MCPServer(middleware=[...])`
  (ou ajouté à `mcp.middleware`), et ajouté à `server.middleware` sur le `Server` bas niveau.
* Il enveloppe **chaque** message entrant (`server/discover`, `initialize`, requêtes,
  notifications, méthodes inconnues) et s’exécute de l’extérieur vers l’intérieur.
* `ctx.request_id is None` est ce qui distingue une notification d’une requête.
* Levez une exception au lieu d’appeler `call_next` pour refuser un message ; la connexion
  survit.
* Le traçage OpenTelemetry du SDK est lui aussi un middleware, déjà dans la liste. Voir
  **[OpenTelemetry](../run/opentelemetry.md)**.
* Toute cette surface est provisoire. Servez-vous-en pour observer ; ne construisez pas dessus.

C’est tout ce qui enveloppe une requête. Quant à savoir si la requête a seulement le droit de
s’exécuter, c’est l’**[Autorisation](../run/authorization.md)** qui en décide.
