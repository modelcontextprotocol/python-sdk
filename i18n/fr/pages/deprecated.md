---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# Fonctionnalités obsolètes {#deprecated-features}

La spécification 2026-07-28 retire cinq éléments. Le SDK les implémente toujours tous, et chacun d’eux porte désormais un **avertissement d’obsolescence**. Un utilitaire du SDK est obsolète pour des raisons qui lui sont propres ; il figure [à la fin](#deprecated-sdk-helpers).

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

## `ping` sur une session historique {#ping-on-a-legacy-session}

Un **ping** est une requête vide que chaque côté peut envoyer pour vérifier que l’autre répond toujours. La spécification 2026-07-28 le supprime ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)) : chaque requête qu’envoie un client moderne prouve déjà que le serveur est là, et un serveur moderne n’a aucun canal pour en envoyer un. Les deux méthodes du SDK fonctionnent toujours sur une session de la génération poignée de main (handshake). Depuis le client :

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

Et depuis le serveur, dans n’importe quel gestionnaire (handler) :

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` avertit avec `MCPDeprecationWarning` à chaque appel. Sur une connexion par défaut (`2026-07-28`), le serveur répond à la place `MCPError: Method not found`.
* `ctx.session.send_ping()` ne porte aucun avertissement. Sur une connexion moderne, elle lève la même erreur d’absence de canal de retour (back-channel) que toute autre requête à l’initiative du serveur.
* Aucun des deux côtés n’enregistre quoi que ce soit pour répondre à un ping.

## Notifications de changement des racines {#roots-change-notifications}

Un client de génération 2025 qui a déclaré la capacité des racines peut signaler au serveur que les dossiers de son espace de travail ont changé en envoyant `notifications/roots/list_changed` ; le serveur répond en redemandant `roots/list`. La spécification 2026-07-28 supprime la notification avec le reste du flux des racines en mode push. Côté client, c’est le passage de `list_roots_callback=` (**[Fonctions de rappel du client](client/callbacks.md)**) qui déclare `"roots": {"listChanged": true}`, et un seul appel tient cette promesse :

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

Côté serveur, c’est le `Server` de bas niveau qui accueille le gestionnaire de réception :

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` est la liste que renvoie votre `list_roots_callback`. `client.send_roots_list_changed()` avertit, et il lui faut un client `mode="legacy"` : sur une connexion moderne, la notification est abandonnée silencieusement. Gardez ensuite la session ouverte, car le `roots/list` de suivi du serveur arrive dessus.
* `MCPServer` n’a aucun hook pour la notification. Sur le `Server` de bas niveau, `on_roots_list_changed=` enregistre le gestionnaire (obsolète lui aussi, il avertit à la construction). La notification ne porte aucune charge utile, donc le gestionnaire appelle `ctx.session.list_roots()` pour obtenir la nouvelle liste.

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
    `old_log` qui appelle encore `ctx.info()` cesse de passer : l’appel revient avec
    `is_error=True` et `Error executing tool old_log`, et le journal du serveur capturé
    désigne le coupable :

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Une ligne de configuration pytest, et un appel obsolète ne peut plus jamais se glisser
    de nouveau dans votre base de code sans faire échouer un test.

## Utilitaires du SDK obsolètes {#deprecated-sdk-helpers}

Il ne s’agit pas de changements de la spécification, seulement de rouages internes du SDK qui ont un meilleur remplacement. Ils avertissent avec le même `MCPDeprecationWarning` et seront supprimés dans la version 3.0.

| Obsolète | Ce que vous faites à la place |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` puis `FuncMetadata.call_fn()`. Seul du code qui pilote directement `FuncMetadata` (une sous-classe personnalisée de `Tool`, par exemple) l’a jamais appelée. |

## Récapitulatif {#recap}

* La spécification 2026-07-28 rend obsolètes les **racines**, l’**échantillonnage** à l’initiative du serveur et la **journalisation** par le protocole (toutes via la [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), restreint la **progression** au sens serveur vers client et supprime **`ping`**.
* La colonne des remplacements vous oriente : **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)** pour l’échantillonnage et les racines, **[Journalisation](handlers/logging.md)** pour la journalisation, **[Progression](handlers/progress.md)** pour la progression. `ping` n’a besoin de rien du tout.
* L’obsolescence est indicative : aucun changement sur la liaison, tout continue de fonctionner sur les sessions d’avant 2026, et vous obtenez un `MCPDeprecationWarning` visible (un `UserWarning`, donc actif par défaut).
* L’échantillonnage et les racines ont en plus besoin d’un canal de retour qu’une session 2026-07-28 n’a pas. Sur une connexion moderne, ils avertissent puis lèvent une exception.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` fait taire toute la catégorie ; `"error::mcp.MCPDeprecationWarning"` dans pytest la transforme en échec de test.
* Un utilitaire du SDK, `FuncMetadata.call_fn_with_arg_validation()`, est obsolète séparément, pour suppression dans la version 3.0.
* Aucun nouveau code ne devrait s’appuyer sur l’une de ces fonctionnalités.

Toutes les autres pages de cette documentation enseignent l’API actuelle.
