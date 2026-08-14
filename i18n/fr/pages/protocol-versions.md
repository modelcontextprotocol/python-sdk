---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# Versions du protocole {#protocol-versions}

MCP compte deux générations.

Les serveurs publiés avant la version 2026-07-28 ouvrent chaque connexion par la **poignée de main (handshake) `initialize`** : le client propose une version, le serveur fait une contre-proposition, le client accuse réception, le tout avant la première requête utile. Les serveurs en version **2026-07-28** abandonnent la poignée de main. Le client envoie une seule sonde **`server/discover`** et le serveur y répond avec tout ce qu’il faut en un seul résultat.

Vous n’avez presque jamais à vous en soucier, car `Client` négocie pour vous. Cette page porte sur le seul argument du constructeur qui contrôle cela, `mode=`, et sur les trois cas où vous le changez.

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

Vous n’avez pas passé `mode`, vous avez donc la valeur par défaut : `"auto"`. L’entrée dans `async with` envoie une seule sonde `server/discover` à la version la plus récente que parle ce SDK. Ensuite :

* Un **serveur moderne** y répond. Le client adopte le résultat. Un aller-retour, terminé.
* Un **serveur plus ancien** n’a jamais entendu parler de `server/discover` et renvoie une erreur. Le client se rabat sur la poignée de main classique `initialize` et prend ce qu’elle négocie.

Dans les deux cas, vous ressortez connecté, et `client.protocol_version` vous indique lequel c’était :

```text
2026-07-28
```

C’est toute la fonctionnalité. Un seul `Client`, un serveur de n’importe quelle génération, aucun branchement dans votre code.

!!! info
    `MCPServer` répond à `server/discover` sur tous les transports — en mémoire, stdio, Streamable
    HTTP — donc face à votre propre serveur, `auto` aboutit toujours à `2026-07-28`. Le repli ne
    se déclenche que face à un vrai serveur antérieur à 2026, c’est-à-dire exactement quand vous le souhaitez.

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` ne sonde jamais. Il exécute la poignée de main `initialize`, la même connexion qu’ouvre un client antérieur à 2026.

```text
2025-11-25
```

Même serveur. Il parle parfaitement `2026-07-28` ; vous avez dit au client de ne pas demander.

Vous en avez besoin pour les fonctionnalités **de type push**.

Une requête à l’initiative du serveur, c’est le serveur qui *vous* appelle : `ctx.elicit(...)` qui place un formulaire devant votre utilisateur, l’échantillonnage (sampling) qui demande une complétion à votre modèle en plein appel d’outil. Ce canal n’existe que sur une session de la génération à poignée de main.

En version 2026-07-28, il a disparu. Le serveur *renvoie* ses questions et vous relancez l’appel avec les réponses (**[Requêtes à plusieurs allers-retours (multi-round-trip)](handlers/multi-round-trip.md)**).

`mode="auto"` ne vous donne une poignée de main que lorsque le serveur est trop ancien pour autre chose. `mode="legacy"` en garantit une. Utilisez-le dès que vous passez à `Client(...)` un `sampling_callback`, un `elicitation_callback` que vous voulez piloté comme une requête, ou un `message_handler`. **[Fonctions de rappel du client](client/callbacks.md)** les passe chacun en revue.

## Épingler une version {#pinning-a-version}

`mode` accepte aussi une chaîne de version moderne du protocole. Aujourd’hui, cet ensemble est exactement `["2026-07-28"]`.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

Un épinglage n’envoie **rien**. Ni sonde, ni poignée de main. Le client adopte `2026-07-28` localement et la connexion est active dès l’instant où `async with` rend la main.

Un épinglage est une promesse que *vous* faites : vous savez déjà que le serveur parle cette version. Le client ne vérifie pas.

!!! check
    Un épinglage n’est pas une découverte. Affichez `client.server_info` et le prix à payer saute aux yeux :

    ```text
    None
    ```

    Le client n’a jamais demandé au serveur qui il est, donc `server_info` vaut `None`. Même chose pour
    `client.server_capabilities` : chaque capacité vaut `None`. Les appels d’outils fonctionnent toujours (le protocole n’a besoin de rien de tout cela) ;
    le code qui lit `server_capabilities` pour décider quoi proposer, non.

    La section suivante apporte la solution.

Seules les versions modernes peuvent être épinglées. Une chaîne de la génération à poignée de main est rejetée à la construction, avant toute entrée-sortie, et l’erreur vous indique quoi écrire à la place :

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## Se reconnecter avec `prior_discover` {#reconnecting-with-prior_discover}

La sonde est peu coûteuse, mais cela reste un aller-retour que vous payez à chaque reconnexion, et la réponse ne change presque jamais.

Alors conservez-la. Après une connexion `auto`, `client.session.discover_result` contient le `DiscoverResult` exact que le serveur a envoyé : ses `supported_versions`, ses `capabilities`, ses `instructions` et l’identité que le serveur a inscrite dans le `_meta` du résultat. Repassez-le via `prior_discover=` la fois suivante :

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

La seconde connexion n’a fait **aucun** aller-retour de négociation et sait pourtant exactement à qui elle parle. C’est le mode épinglé bien fait : `mode=` nomme la version, `prior_discover=` fournit l’identité. ✨

`DiscoverResult` est un modèle Pydantic. `saved.model_dump_json()` va dans un fichier ou un cache ; `DiscoverResult.model_validate_json(...)` le restitue dans le processus suivant.

!!! tip
    `prior_discover=` n’a d’effet que lorsque `mode` est un épinglage de version. En `"auto"`, le client
    sonde le serveur de toute façon, et en `"legacy"`, il est ignoré.

## Les quatre modes {#the-four-modes}

| Vous écrivez | Trafic de négociation | Vous obtenez |
| --- | --- | --- |
| `Client(target)` | une sonde `server/discover` ; la poignée de main `initialize` si elle échoue | la version la plus récente que parlent les deux côtés, quelle que soit la génération |
| `Client(target, mode="legacy")` | la poignée de main `initialize` | une version de la génération à poignée de main ; les requêtes à l’initiative du serveur fonctionnent |
| `Client(target, mode="2026-07-28")` | aucun | cette version, épinglée, avec `server_info` à `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | aucun | cette version, épinglée, *et* l’identité que vous avez enregistrée la dernière fois |

## Récapitulatif {#recap}

* MCP a une génération à poignée de main (jusqu’à `2025-11-25`, la poignée de main `initialize`) et une génération moderne (`2026-07-28`, `server/discover`). `Client` fait le pont entre les deux.
* `mode="auto"` est la valeur par défaut : sonder, se replier. N’y touchez pas sauf si l’une des trois autres lignes vous correspond.
* `client.protocol_version` est toujours la réponse à « qu’est-ce que j’ai obtenu ? ».
* `mode="legacy"` force la poignée de main. C’est ce qu’il vous faut pour les requêtes à l’initiative du serveur : échantillonnage, élicitation (elicitation) en push, `message_handler`.
* Un épinglage de version (`mode="2026-07-28"`) n’envoie aucun trafic de négociation, au prix d’un `client.server_info` à `None`.
* `prior_discover=` rembourse ce coût : enregistrez `client.session.discover_result`, reconnectez-vous avec, et obtenez les deux.

Une connexion moderne n’a pas de canal push, alors comment un serveur 2026 vous pose-t-il une question en plein appel ? Il la renvoie : **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)**.
