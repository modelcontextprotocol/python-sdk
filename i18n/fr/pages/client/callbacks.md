---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# Fonctions de rappel du client {#client-callbacks}

Presque toutes les requêtes dans MCP vont dans un seul sens : du client vers le serveur.

Un serveur peut aussi demander des choses au **client** : poser une question à l’utilisateur, échantillonner le modèle de l’utilisateur, lister les dossiers de son espace de travail. Vous répondez à ces requêtes en passant des **fonctions de rappel** (callbacks) à `Client(...)`.

## Un serveur qui demande {#a-server-that-asks}

Voici un serveur dont l’outil ne peut pas terminer tout seul :

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` envoie une requête `elicitation/create` **au client** et attend.
* L’outil ne renvoie rien tant que quelqu’un (une personne devant un formulaire, ou votre code) n’a pas fourni un `name`.

C’est la moitié serveur, et la page **[Élicitation](../handlers/elicitation.md)** la couvre en détail. Cette page-ci se tient à l’autre bout de la liaison.

## La fonction de rappel d’élicitation {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* Une fonction de rappel d’élicitation (elicitation) a pour signature `async (context, params) -> ElicitResult`.
* `params.message` est la question. `params.requested_schema` est le JSON Schema de la réponse que le serveur attend. Un vrai client en tire un formulaire ; celui-ci le remplit automatiquement.
* Vous renvoyez `ElicitResult(action="accept", content={...})`, ou `action="decline"`, ou `action="cancel"`. La seule autre option est `ErrorData(...)`, qui refuse la requête et fait échouer l’appel entier.
* `context` est un `ClientRequestContext` : la `session` active, le `request_id` du serveur et les éventuelles `meta` qu’il a jointes.

!!! tip
    `params` est une union des deux modes d’élicitation. Ici `params.mode` vaut `"form"` ; une requête `"url"`
    porte `params.url` au lieu d’un schéma. Une seule fonction de rappel gère les deux ; branchez sur `params.mode`.
    **[Élicitation](../handlers/elicitation.md)** montre le motif complet.

### Essayer {#try-it}

Appelez `issue_card` et observez les deux extrémités.

Votre fonction de rappel reçoit la question du serveur, déjà analysée :

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

Elle répond, `ctx.elicit(...)` reprend à l’intérieur de l’outil, et l’outil termine :

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

Un `tools/call` de votre part, un `elicitation/create` en retour du serveur, auquel votre fonction répond, le tout à l’intérieur d’un seul appel d’outil.

!!! info
    `mode="legacy"` dans l’appel `Client(...)` fait un vrai travail. Par défaut, `Client(...)` négocie le chemin
    moderne du protocole, et ce chemin n’a pas de canal de retour (back-channel) pour les requêtes du serveur vers le client : `ctx.elicit`
    échoue avant même que votre fonction de rappel ne s’exécute. Ce n’est pas le transport qui en décide ; c’est le
    protocole négocié, en mémoire comme via une URL. Fixez `mode="legacy"` dès que votre client doit
    répondre à l’une d’elles ; tous les tests derrière cette page le font. Tous les détails sont dans **[Versions du protocole](../protocol-versions.md)**.

    Sur une session 2026-07-28, la fonction de rappel n’est pas morte, elle est alimentée autrement : quand un outil renvoie un
    `InputRequiredResult` portant une `ElicitRequest`, `Client` transmet cette entrée à la même
    `elicitation_callback` et relance l’appel pour vous. Ce flux est décrit dans **[Requêtes à plusieurs allers-retours](../handlers/multi-round-trip.md)** (multi-round-trip).

## Une fonction de rappel est une capacité {#a-callback-is-a-capability}

Vous n’avez jamais dit au serveur que votre client sait répondre aux requêtes d’élicitation. Le SDK l’a fait.

Quand un client se connecte, il déclare ses `capabilities`, l’image miroir de celles du serveur. Vous n’écrivez pas cet objet. **Enregistrer une fonction de rappel vaut déclaration.**

| vous passez | le client déclare |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| aucune d’elles | `{}` |

Les sous-capacités d’échantillonnage (sampling) sont le seul raffinement : passez `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` en plus de `sampling_callback` lorsque votre échantillonneur gère les paramètres `tools` / `tool_choice`. Les serveurs doivent voir `sampling.tools` déclaré avant de pouvoir les envoyer.

`logging_callback` et `message_handler` ne figurent pas dans le tableau. Ils traitent des notifications, et les notifications n’exigent aucune capacité.

Le serveur relit la déclaration avec `ctx.session.check_client_capability(...)`. Ajoutez un outil qui le fait :

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

Connectez-vous avec seulement `elicitation_callback` et appelez-le :

```python
result.structured_content  # {'result': ['elicitation']}
```

Passez les trois fonctions de rappel et vous obtenez `['elicitation', 'sampling', 'roots']`. N’en passez aucune et vous obtenez `[]`.

!!! check
    Faites maintenant ce qu’il ne faut pas : connectez-vous **sans** `elicitation_callback` et appelez `issue_card` quand même.

    La requête `elicitation/create` du serveur atteint toujours votre client, et le SDK y répond à votre
    place, par une erreur, puisque vous n’avez jamais dit pouvoir la traiter. Cette erreur coule l’appel entier.
    `call_tool` ne renvoie pas un résultat `is_error` ; il lève une exception :

    ```text
    MCPError: Elicitation not supported
    ```

    C’est une erreur de protocole (`-32600`, *requête invalide*), pas une erreur d’outil : le modèle n’a rien
    à lire ni à retenter. C’est pourquoi `client_features` vaut la peine : un serveur bien élevé
    vérifie avant de demander.

## La paire obsolète {#the-deprecated-pair}

`sampling_callback` répond à `sampling/createMessage` : le serveur demande à *votre* modèle de compléter quelque chose. `list_roots_callback` répond à `roots/list` : le serveur demande dans quels répertoires il peut travailler.

Les deux fonctionnent. Les deux suivent la règle ci-dessus. Et les deux servent des RPC que la **spécification 2026-07-28 supprime** : un serveur moderne ne rappelle pas votre client en pleine requête, il vous rend la requête dans le résultat de l’outil (**[Requêtes à plusieurs allers-retours](../handlers/multi-round-trip.md)**). Les fonctions de rappel elles-mêmes ne sont pas mortes. Quand un `InputRequiredResult` porte une `CreateMessageRequest` ou une `ListRootsRequest`, la boucle automatique de `Client` la transmet à la même `sampling_callback` ou `list_roots_callback` que vous avez enregistrée ici. La liste complète est dans **[Fonctionnalités obsolètes](../deprecated.md)**.

Vous avez encore besoin de ces fonctions de rappel pour parler aux serveurs qui n’ont pas migré. Les signatures :

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* Une fonction de rappel d’échantillonnage reçoit le `CreateMessageRequestParams` complet (`messages`, `model_preferences`, `max_tokens`) et renvoie un `CreateMessageResult`. C’est *vous* qui exécutez le modèle, comme bon vous semble ; le SDK ne fait que transporter la requête.
* Une fonction de rappel de racines (roots) ne prend aucun paramètre et renvoie un `ListRootsResult`.
* L’une comme l’autre peut renvoyer `ErrorData(...)` à la place, pour refuser.

Passez-les à `Client(...)` exactement comme `elicitation_callback`.

## Les fonctions de rappel de notification {#the-notification-callbacks}

Deux de plus. Aucune ne déclare quoi que ce soit.

`logging_callback` reçoit les `notifications/message` qu’un serveur envoie, sous forme de `LoggingMessageNotificationParams` (`level`, `logger`, `data`). La journalisation par le protocole est elle-même rendue obsolète par la spécification 2026-07-28 (**[Journalisation](../handlers/logging.md)** explique quoi faire à la place), donc cette fonction de rappel existe pour les serveurs qui l’émettent encore. Sur une connexion de génération 2026, la fonction de rappel seule ne vous apporte rien, car les serveurs 2026 n’envoient des messages de journal qu’aux requêtes qui en font la demande : passez `log_level="info"` (ou un autre niveau) à `Client(...)` pour apposer cette demande sur chaque requête et recevoir ce niveau et les niveaux supérieurs. Les serveurs antérieurs à 2026 l’ignorent et conservent leur comportement `logging/setLevel`.

`message_handler` est le fourre-tout : chaque notification serveur que la session remonte lui parvient (en plus de sa fonction de rappel spécifique), et sur un transport adossé à un flux, chaque `Exception` de niveau transport aussi. Deux n’y parviennent jamais : `notifications/cancelled` est appliquée par le SDK plutôt que remontée, et l’accusé de réception d’abonnement d’un flux `listen()` actif est consommé par ce flux. Annotez le paramètre avec `IncomingMessage` (`ServerNotification | Exception`, exporté depuis `mcp.client`). Le seul motif à connaître est `if isinstance(message, Exception): raise message`, pour qu’une connexion rompue échoue bruyamment au lieu de disparaître en silence.

## Récapitulatif {#recap}

* Un serveur peut envoyer des requêtes au client. Vous y répondez avec des fonctions de rappel passées à `Client(...)`.
* La fonction de rappel d’élicitation est celle d’actualité : `async (context, params) -> ElicitResult`, une seule fonction pour les modes formulaire et URL.
* **Enregistrer une fonction de rappel, c’est déclarer la capacité.** Sans elle, le SDK refuse la requête du serveur à votre place et l’appel entier échoue avec `MCPError`.
* Un serveur le sait avant de demander grâce à `ctx.session.check_client_capability(...)`.
* `sampling_callback` et `list_roots_callback` fonctionnent de la même manière mais servent des fonctionnalités obsolètes ; les serveurs modernes utilisent à la place les requêtes à plusieurs allers-retours.
* `logging_callback` et `message_handler` reçoivent des notifications. Ils ne déclarent rien.

Le premier argument de `Client(...)` est un objet transport. **[Transports client](transports.md)** couvre tous les types.
