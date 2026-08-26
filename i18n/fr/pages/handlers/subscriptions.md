---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# Abonnements {#subscriptions}

Le catalogue d’un serveur n’est pas figé. Des outils apparaissent à l’exécution, et le contenu derrière l’URI d’une ressource change.

**Les abonnements** sont le moyen par lequel un client en est informé. Le client envoie une seule requête `subscriptions/listen`, et la réponse à cette requête *est* le flux : elle reste ouverte et transporte les notifications de changement que le client a demandées.

## Publier depuis l’outil {#publish-it-from-the-tool}

Votre part se résume à une ligne : publier le changement.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` atteint chaque flux ouvert abonné à cet URI. Personne d’autre.
* `await ctx.notify_tools_changed()` atteint chaque flux qui a demandé les changements de la liste d’outils. Un client qui la reçoit appelle de nouveau `tools/list`, et voit désormais `sprint_report`.
* Les méthodes sœurs sont `notify_prompts_changed()` et `notify_resources_changed()`.
* Pas d’abonnés, pas de travail. Publier sur un serveur inactif est sans effet, vous ne vérifiez donc jamais si quelqu’un écoute. Vous indiquez ce qui a changé.

`MCPServer` sert `subscriptions/listen` pour vous. Les obligations sur la liaison (l’accusé de réception comme première trame, le filtrage par flux, l’identifiant d’abonnement sur chaque trame) sont l’affaire du SDK.

!!! check
    Sur la liaison, un flux dont le filtre nommait `board://sprint` ressemble à ceci après l’exécution de `complete_task` :

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    Notez ce que la mise à jour ne transporte *pas* : le tableau. Chaque trame porte l’identifiant JSON-RPC de la requête listen sous `_meta`, et cet identifiant est l’identifiant d’abonnement. C’est le client qui le crée : le `Client` Python utilise des chaînes comme `"listen-1"` ; d’autres clients peuvent utiliser des entiers.

## Seulement ce qui a été demandé {#only-what-was-asked-for}

Le filtre est un contrat. Un flux qui a demandé les changements de la liste d’outils et un URI de ressource reçoit ces deux types et rien d’autre. Publiez un changement de prompt et ce flux reste silencieux.

`MCPServer` compare les URI de ressource comme des chaînes exactes, si bien qu’un flux qui a nommé `board://sprint` n’entend rien à propos de `board://sprint/tasks/1`. La spécification permet à un serveur de signaler un changement sur une sous-ressource d’un URI abonné ; `MCPServer` ne le fait jamais, mais les clients sont conçus pour s’y attendre.

Deux choses que le flux n’est *pas* :

* **Ce n’est pas un journal de relecture.** Un flux interrompu est perdu, et les événements publiés pendant que personne n’était connecté ne sont pas mis en file d’attente. Les clients rouvrent l’écoute et récupèrent de nouveau les données.
* **Ce n’est pas le chemin 2025.** Les clients qui ont appelé `resources/subscribe` sont servis par `ctx.session.send_resource_updated(uri)`. Les méthodes `notify_*` n’atteignent que les flux `subscriptions/listen`.

## Décider qui peut observer {#deciding-who-may-watch}

Par défaut, chaque type et chaque URI demandés sont honorés : n’importe quel appelant peut observer n’importe quel URI que vous publiez. Rien ne consulte votre gestionnaire (handler) de lecture, car personne ne lit — un appelant que votre gestionnaire `files://{name}` refuserait peut tout de même ouvrir un flux sur `files://payroll.csv` et apprendre qu’il a changé, et quand. Il n’apprend jamais le contenu, et il ne peut pas sonder ce qui existe, car un URI inconnu est honoré lui aussi et ne se déclenche tout simplement jamais. La faille est étroite mais réelle : mettez donc un contrôle en place avant de publier des URI propres à chaque utilisateur depuis un serveur multi-locataire.

Le contrôle est un middleware. Il voit la requête `subscriptions/listen` avant que le SDK n’en accuse réception et refuse lorsque l’appelant demande quoi que ce soit qu’il n’a pas le droit de lire :

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` est la requête brute ; le middleware la valide donc lui-même en `SubscriptionsListenRequestParams` et lit le filtre demandé par le client.
* Le refus est une `MCPError` levée avant `call_next(ctx)` : le client reçoit cette erreur et aucun flux, et la connexion continue. Gardez le message uniforme, sans nommer d’URI, afin qu’un refus ne confirme jamais quels URI sont protégés.
* Une seule fonction `can_access(user, uri)` répond aux deux questions. Le gestionnaire de ressource la pose sur `resources/read` ; le middleware la pose sur `subscriptions/listen`. Remplacez la table par une base de données ou votre système RBAC et les deux restent synchronisés.
* La décision vaut pour toute la durée de vie du flux. Il n’y a pas de nouvelle vérification par événement ; si l’accès d’un appelant peut expirer en cours de flux (un jeton qui expire), mettez donc fin à la connexion de cet appelant à ce moment-là.

Le contrat complet du middleware, y compris ce qu’il enveloppe d’autre et pourquoi il est marqué comme provisoire, se trouve sur **[Middleware](../advanced/middleware.md)**.

## Côté client {#the-client-end}

Voici un client de l’autre côté de ce flux, qui suit le tableau :

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Entrer dans `client.listen(...)` envoie la requête et attend votre accusé de réception : le flux est donc actif quand le bloc commence, et chaque événement typé est un signal pour récupérer de nouveau les données, jamais une charge utile. C’est tout le contrat, en un seul écran. Tout le reste concernant le côté client a sa propre page : observer à côté d’un traitement principal, fins de flux et réouverture de l’écoute. Voir **[Abonnements](../client/subscriptions.md)** sous *Clients*.

## Passer à l’échelle au-delà d’un seul processus {#scaling-past-one-process}

Les publications voyagent de votre gestionnaire vers les flux ouverts via un `SubscriptionBus`. Le bus par défaut est en mémoire : un processus, et tous les flux qu’il contient. C’est la bonne réponse jusqu’au jour où vous exécutez des réplicas derrière un répartiteur de charge, car le flux d’un client est alors épinglé à un réplica, et une publication sur un autre réplica doit l’atteindre.

Cette jointure est à vous d’implémenter : deux méthodes au-dessus de votre backend pub/sub.

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` est à vous, tout comme la tâche de lecture sur chaque réplica qui décode les messages entrants et appelle chaque écouteur enregistré. Les écouteurs sont synchrones, ne doivent pas lever d’exception et s’exécutent sur la boucle d’événements du serveur.

Le bus transporte des valeurs `ServerEvent` typées, quatre petites dataclasses, jamais du JSON-RPC. Le marquage, le filtrage et le cycle de vie des flux restent dans le SDK, si bien qu’une implémentation de bus ne peut pas casser le protocole. Elle ne peut que déplacer des événements entre processus.

Pour publier en dehors d’une requête, construisez le bus vous-même afin d’en garder la référence. `MCPServer` en construit un en interne lorsque vous ne passez rien, et ne l’expose pas.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## La composition bas niveau {#the-low-level-composition}

Sur le `Server` bas niveau, rien n’est précâblé, et les mêmes pièces s’assemblent en trois lignes :

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* Le bus vous appartient, vous y publiez donc directement : `await bus.publish(ResourceUpdated(uri=...))`. Placez-le là où vos gestionnaires peuvent l’atteindre : la portée du module ici, le cycle de vie (lifespan) dans une application plus grande.
* `ListenHandler(bus)` est le même gestionnaire que celui qu’enregistre `MCPServer`, et `on_subscriptions_listen=` est un emplacement de gestionnaire ordinaire. Mettez votre propre callable dans cet emplacement pour une sémantique différente, et les obligations de la spécification vous reviennent : accuser réception d’abord, marquer chaque trame avec l’identifiant d’abonnement, ne rien livrer en dehors du filtre.
* `ListenHandler.close()` termine proprement chaque flux ouvert. Chacun reçoit le résultat de la requête listen comme dernière trame, ce qui est la manière pour la spécification de dire que le serveur a mis fin à l’abonnement délibérément. Elle rend la main avant que ces flux n’aient fini de se vider : laissez-leur donc un instant avant de démonter le transport. Sans cela, les flux se terminent lorsque le client se déconnecte.

## Récapitulatif {#recap}

* Un client s’inscrit avec une seule requête `subscriptions/listen`, et la réponse est le flux. La prise en charge est intégrée.
* Vous publiez avec `ctx.notify_*`, et le SDK se charge du marquage, du filtrage et du cycle de vie.
* Les événements sont des signaux, pas des charges utiles. Les deux extrémités récupèrent de nouveau les données.
* Le côté client, c’est `async with client.listen(...)` : tous les détails sont dans **[Abonnements](../client/subscriptions.md)** sous *Clients*.
* Sur le `Server` bas niveau, vous assemblez vous-même les mêmes pièces : un bus, `ListenHandler(bus)`, l’emplacement `on_subscriptions_listen`.
* Passer à l’échelle horizontalement signifie implémenter `SubscriptionBus`, deux méthodes, et le passer via `MCPServer(subscriptions=...)`.

Exécuter le serveur qui sert tout cela, derrière un réplica ou vingt, c’est **[Déployer et passer à l’échelle](../run/deploy.md)**.
