---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# Abonnements {#subscriptions}

Le catalogue d’un serveur n’est pas figé. Des outils apparaissent à l’exécution, et le contenu derrière l’URI d’une ressource change. Un client l’apprend grâce à `client.listen(...)` : une seule requête `subscriptions/listen` dont la réponse *est* le flux. Elle reste ouverte et transporte les notifications de changement que le client a demandées.

Cette page couvre le côté client : ouvrir le flux, le surveiller en parallèle de votre traitement principal, et gérer la façon dont il se termine. Publier les changements, filtrer et servir la méthode relèvent du serveur ; c’est raconté dans **[Abonnements](../handlers/subscriptions.md)**, sous *Dans votre gestionnaire*. Les exemples de cette page dialoguent avec le serveur de tableau de sprint construit là-bas.

## Surveiller le flux {#watching-the-stream}

Un abonnement est un gestionnaire de contexte, un seul. Y entrer envoie la requête, avec vos arguments nommés comme filtre d’abonnement, puis attend la confirmation du serveur : le flux est donc actif au moment où le bloc commence.

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

L’itération produit quatre événements typés : `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged` et `ResourceUpdated(uri=...)`.

Un événement dit *ce qui* a changé, jamais *comment*. C’est pourquoi `follow_board` appelle `read_resource` et `list_tools` : l’événement est un signal pour récupérer à nouveau les données. Lisez `event.uri` plutôt que de supposer quelle ressource a bougé : un filtre peut nommer plusieurs URI, et un serveur peut signaler un changement sur une sous-ressource de l’un d’eux.

Les événements en double qui attendent d’être consommés se fondent en un seul, et une nouvelle récupération vous donne tout de même l’état courant. Seuls les événements identiques se fondent : deux `ResourceUpdated` pour des URI différents sont deux événements.

Deux autres propriétés de l’objet d’abonnement :

* `sub.honored` est le filtre que le serveur a confirmé : un `SubscriptionFilter` avec les champs que vous avez passés, lisibles comme attributs (`sub.honored.prompts_list_changed`). `MCPServer` honore tous les types d’événements que vous demandez, il vous renvoie donc votre requête telle quelle. Un serveur qui prend en charge moins de types en confirme moins, et un type confirmé peut malgré tout ne jamais se déclencher. Un serveur peut aussi refuser la requête entière plutôt que de la confirmer (voir [Décider qui peut surveiller](../handlers/subscriptions.md#deciding-who-may-watch) sur la page serveur), ce qui se manifeste comme l’erreur de la requête.
* `sub.subscription_id` est l’identifiant de la requête listen, celui qui est apposé sur chaque trame de ce flux. Plusieurs abonnements peuvent être ouverts en même temps, chacun démultiplexé par son propre identifiant.

## Surveiller sans bloquer {#watching-without-blocking}

`follow_board` tourne jusqu’à ce que le serveur ferme le flux, ce qui peut ne jamais arriver ; seule, elle monopolise donc votre programme. Les vrais clients veulent l’observateur *à côté* du traitement principal : un agent appelle des outils pendant qu’un observateur maintient à jour un cache ou une interface.

Ouvrez d’abord l’abonnement, puis démarrez l’observateur et poursuivez votre travail.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` importe `BOARD` et `read_board` depuis le premier exemple, que ce dépôt stocke sous
    le nom `tutorial003.py`. Si vous enregistrez les fichiers affichés côte à côte sous les noms
    `client.py` et `app.py`, écrivez plutôt `from client import BOARD, read_board`. L’exemple
    `watch.py`, plus bas, importe `read_board` de la même façon.

L’ordre est tout l’enjeu. Rien n’est rejoué : un événement publié avant que votre flux n’existe est perdu. Entrer dans `client.listen(...)` attend la confirmation, si bien que chaque changement à partir de cet instant atteint votre observateur, et l’instantané que vous prenez dans le bloc ne peut en manquer aucun.

Les requêtes s’exécutent librement à côté d’un flux ouvert, depuis la tâche de l’observateur ou n’importe quelle autre, sur le même client. Comme les événements non consommés *en double* fusionnent, un traitement principal chargé peut produire une seule récupération plutôt que trois. Les événements qui diffèrent ne fusionnent pas : un filtre qui nomme de nombreux URI met en file un événement en attente par URI.

Pour arrêter de surveiller, sortez du bloc : il n’y a pas d’appel `unsubscribe`. Annuler la tâche qui possède le bloc le fait pour vous, et le SDK annule la requête listen comme le transport l’attend : en Streamable HTTP, en fermant le flux de cette requête. Un observateur qui tourne pendant toute la durée de vie de votre application ne revient jamais de lui-même ; annulez-le donc, ou la portée de son groupe de tâches, à l’arrêt.

## Les flux se terminent {#streams-end}

Un flux se termine de l’une de deux façons, toutes deux relevant du flot de contrôle ordinaire. Une fermeture propre côté serveur met fin à la boucle `async for` ; une coupure brutale lève `SubscriptionLost`.

La différence sert au diagnostic, elle ne change pas ce qu’il faut faire ensuite : le flux a disparu, rien n’a été rejoué, et un observateur toujours intéressé réécoute et récupère à nouveau.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Les serveurs ferment proprement les flux pour des raisons qui leur sont propres, notamment pour se délester d’un abonné dont l’arriéré a trop grossi ; une fin propre n’est donc pas un signal pour cesser de surveiller. Temporisez avant de réécouter.

`SubscriptionLost` a aussi une cause locale. Le client conserve au plus 1 024 événements non consommés, et un consommateur qui prend autant de retard perd l’abonnement plutôt que de grossir sans limite. Gardez le corps de la boucle `async for` court et faites le travail lent ailleurs.

`keep_following` n’intercepte que `SubscriptionLost`. Entrer dans `listen()` peut aussi lever `MCPError` (la connexion a échoué, ou le serveur ne sert pas la méthode), `TimeoutError` (aucune confirmation n’est arrivée) et `ListenNotSupportedError` (une connexion antérieure à 2026). Décidez lesquelles votre observateur devrait retenter : la dernière ne se résorbe jamais.

## Récapitulatif {#recap}

* Entrez dans `async with client.listen(...)` ; l’entrée attend la confirmation, donc rien de ce qui est publié ensuite n’est manqué.
* Itérez avec `async for event in sub`. Les événements sont des signaux pour récupérer à nouveau, jamais des charges utiles.
* Ouvrez l’abonnement, puis lancez l’observateur comme tâche, et les appels d’outils continuent de circuler à côté.
* Une fin propre arrête la boucle ; une coupure lève `SubscriptionLost`. Dans les deux cas : réécoutez, récupérez à nouveau, en temporisant d’abord.
* Sortir du bloc, c’est se désabonner.

Publier ces événements, restreindre le filtre et passer à l’échelle au-delà d’un seul processus relèvent du serveur : **[Abonnements](../handlers/subscriptions.md)**. Ces mêmes événements maintiennent aussi à jour un cache côté client, et **[Mise en cache](caching.md)** est la page suivante.
