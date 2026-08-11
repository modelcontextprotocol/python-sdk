---
translation:
  sections: [20541a40dbdd5980, 01262a123ad9501d, 429db5b574a2ac08, 56b2d49da412cb28, 6a1717123fe4513c]
  tool: 1
---
# Fonctionnalités obsolètes {#deprecated-features}

La spécification 2026-07-28 retire cinq éléments. Le SDK les implémente toujours tous, et chacun d’eux porte désormais un **avertissement d’obsolescence**.

Le tableau ci-dessous nomme chaque fonctionnalité obsolète, la raison de sa disparition et le remplacement sur lequel vous appuyer.

## Ce qui est obsolète {#what-is-deprecated}

| Obsolète | Pourquoi | Ce que vous faites à la place |
|---|---|---|
| **Racines (roots)** : `ctx.session.list_roots()`, `client.send_roots_list_changed()`, le `list_roots_callback=` que vous passez à `Client(...)` | La [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) retire la capacité. | Prenez les chemins comme arguments d’outil ordinaires ou comme URI de ressource, ou intégrez une `ListRootsRequest` dans un `InputRequiredResult` (voir **[Requêtes à plusieurs allers-retours (multi-round-trip)](handlers/multi-round-trip.md)**). |
| **Échantillonnage (sampling) à l’initiative du serveur** : `ctx.session.create_message()`, le `sampling_callback=` que vous passez à `Client(...)` | La SEP-2577 retire la capacité. | Renvoyez `InputRequiredResult` et laissez le client réessayer l’appel (voir **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)**). |
| **Journalisation par le protocole** : `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | La SEP-2577 retire la capacité. Rien dans le protocole ne la remplace. | Un `import logging` ordinaire vers stderr (voir **[Journalisation](handlers/logging.md)**). |
| **`ping`** : `client.send_ping()` | **Supprimé** du protocole, pas simplement obsolète. Il n’y a pas de méthode `ping` en version 2026-07-28. | Rien. Cela ne fonctionne que sur une connexion `mode="legacy"`. |
| **Progression client->serveur** : `client.send_progress_notification()` | La version 2026-07-28 réserve la progression au sens serveur->client. | Rien à envoyer. Votre *serveur* signale sa progression avec `ctx.report_progress()` (voir **[Progression](handlers/progress.md)**). |

Trois choses ressortent de ce tableau :

* Les racines, l’échantillonnage et la journalisation vont ensemble. Une seule proposition, la **SEP-2577**, rend les trois capacités obsolètes d’un coup.
* L’échantillonnage et les racines partagent un problème plus profond : ce sont des endroits où un **serveur** envoie une **requête** au **client**. C’est toute cette direction que la version 2026-07-28 remplace par les **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)**. Ce sont les méthodes RPC autonomes (`sampling/createMessage`, `roots/list` et `elicitation/create` en mode push) qui disparaissent ; les types de charge utile `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` survivent, intégrés dans `InputRequiredResult.input_requests`, et côté client ils aboutissent aux mêmes fonctions de rappel (callbacks).
* `ping` est l’exception. Le protocole ne le rend pas obsolète, il le supprime. La méthode du SDK avertit quand même (son message dit *removed*, pas *deprecated*) et l’appeler sur une connexion moderne répond par *« Method not found »*.

## L’obsolescence est indicative {#deprecated-is-advisory}

Rien ne casse aujourd’hui.

Chaque méthode ci-dessus continue de fonctionner sur toute session qui a négocié la version **2025-11-25 ou antérieure**. Fixez `mode="legacy"` sur le client et vous obtenez exactement le comportement d’avant 2026. Il n’y a aucun changement sur la liaison et la négociation des capacités est inchangée.

Ce qui change, c’est que vous obtenez un avertissement visible la première fois que chacune s’exécute :

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` hérite de `UserWarning`, **pas** de `DeprecationWarning`. C’est délibéré : le filtre par défaut de Python n’affiche `DeprecationWarning` que dans le code exécuté directement en tant que `__main__`, ce qui explique que les bibliothèques rendent des choses obsolètes sans que personne ne le remarque pendant deux ans. Celui-ci apparaît partout, sans option `-W`.

!!! warning
    « Indicatif » s’arrête à la liaison. L’échantillonnage et les racines sont des *requêtes*
    du serveur vers le client, et une session 2026-07-28 n’a aucun canal pour en transporter
    une. Appelez `ctx.session.create_message()` dans un outil sur une connexion moderne :
    l’avertissement se déclenche quand même, puis l’envoi échoue avec une erreur :

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Deux signaux, dans cet ordre. Le `MCPDeprecationWarning` se déclenche dès que vous
    appelez la méthode, sur n’importe quelle connexion. L’erreur est ce qui revient quand le
    SDK tente ensuite l’envoi. Ces deux fonctionnalités ne marchent de bout en bout que sur
    une connexion `mode="legacy"` dont le client a enregistré la fonction de rappel
    correspondante.

## Faire taire l’avertissement {#silencing-the-warning}

Dans du nouveau code, ne le faites pas.

Mais un serveur que vous maintenez et qui sert réellement des clients d’avant 2026 a parfaitement droit à un journal silencieux. Filtrez la catégorie avant l’exécution du premier appel obsolète :

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

C’est toute l’API. Il n’y a pas d’interrupteur par méthode, et vous n’en voulez pas : l’intérêt d’une catégorie unique, c’est qu’une ligne la fait taire et qu’une ligne la rétablit.

!!! check
    Inversez le filtre et vous obtenez gratuitement un test de non-régression. Ajoutez
    `"error::mcp.MCPDeprecationWarning"` au réglage `filterwarnings` de votre configuration
    pytest et l’appel obsolète **lève une exception** au lieu d’avertir. Un outil nommé
    `old_log` qui appelle encore `ctx.info()` cesse de passer et se met à signaler :

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Une ligne de configuration pytest, et un appel obsolète ne peut plus jamais se glisser
    de nouveau dans votre base de code sans faire échouer un test.

## Récapitulatif {#recap}

* La spécification 2026-07-28 rend obsolètes les **racines**, l’**échantillonnage** à l’initiative du serveur et la **journalisation** par le protocole (toutes via la [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), restreint la **progression** au sens serveur vers client et supprime **`ping`**.
* La colonne des remplacements vous oriente : **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)** pour l’échantillonnage et les racines, **[Journalisation](handlers/logging.md)** pour la journalisation, **[Progression](handlers/progress.md)** pour la progression. `ping` n’a besoin de rien du tout.
* L’obsolescence est indicative : aucun changement sur la liaison, tout continue de fonctionner sur les sessions d’avant 2026, et vous obtenez un `MCPDeprecationWarning` visible (un `UserWarning`, donc actif par défaut).
* L’échantillonnage et les racines ont en plus besoin d’un canal de retour (back-channel) qu’une session 2026-07-28 n’a pas. Sur une connexion moderne, ils avertissent puis lèvent une exception.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` fait taire toute la catégorie ; `"error::mcp.MCPDeprecationWarning"` dans pytest la transforme en échec de test.
* Aucun nouveau code ne devrait s’appuyer sur l’une de ces fonctionnalités.

Toutes les autres pages de cette documentation enseignent l’API actuelle.
