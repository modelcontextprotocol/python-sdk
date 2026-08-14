---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# Requêtes à plusieurs allers-retours (multi-round-trip) {#multi-round-trip-requests}

Parfois, un outil ne peut pas terminer en un seul aller-retour. Il lui faut quelque chose que seul l’utilisateur détient : un choix, une confirmation, un identifiant d’accès.

Avant la version 2026-07-28, le serveur l’obtenait en **rappelant** le client : il ouvrait sa propre requête vers le client — une élicitation (elicitation), un appel d’échantillonnage (sampling) — au beau milieu du traitement de la requête d’origine. La spécification 2026-07-28 retire ce canal de retour (back-channel).

À la place, le serveur **renvoie un résultat**.

## Renvoyer, ne pas rappeler {#return-dont-call-back}

Le serveur répond à `tools/call` par un **`InputRequiredResult`** au lieu d’un `CallToolResult`. Deux de ses champs font le travail :

* **`input_requests`** : ce qu’il manque encore au serveur, sous la forme d’un dictionnaire dont les clés sont des noms choisis par le serveur. Chaque valeur est une `ElicitRequest`, une `CreateMessageRequest` ou une `ListRootsRequest`.
* **`request_state`** : un jeton opaque. Le client le renvoie tel quel lors de la nouvelle tentative. Votre serveur est le seul à le lire.

Le client satisfait chaque requête, puis appelle **à nouveau le même outil**, en transportant ses réponses dans `input_responses` et le jeton dans `request_state`. Le serveur dispose désormais de ce qui lui manquait et renvoie un `CallToolResult` normal.

C’est tout le protocole. Chaque étape est une requête ordinaire du client vers le serveur. Rien ne circule jamais dans l’autre sens.

## Côté serveur {#the-server-side}

Avec `@mcp.tool()`, vous construisez rarement cela à la main : déclarez une dépendance qui interroge l’utilisateur (`Elicit`), échantillonne le LLM du client (`Sample`) ou liste ses racines (roots) (`ListRoots`), et le SDK renvoie l’objet `InputRequiredResult` à votre place ; cette forme fait l’objet de la page **[Dépendances](dependencies.md)**. Les deux formes ne se mélangent pas : un appel ne dispose que d’un seul canal `input_responses`/`request_state`, si bien qu’un outil qui utilise des paramètres `Resolve(...)` ne peut pas en plus renvoyer un `InputRequiredResult` depuis son corps. Un retour `InputRequiredResult` déclaré est refusé à l’enregistrement (`InvalidSignature`), et un retour non déclaré fait échouer l’appel à l’exécution. La forme manuelle, c’est le `Server` **bas niveau**, dont le gestionnaire (handler) `on_call_tool` a le droit de renvoyer l’un ou l’autre type de résultat :

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` est typé `-> CallToolResult | InputRequiredResult`. Renvoyer le second constitue toute l’API côté serveur.
* Au premier appel, `params.input_responses` vaut `None` : la garde se déclenche et le gestionnaire pose la question au lieu de répondre.
* Lors de la nouvelle tentative, le résultat `ElicitResult` envoyé par le client se trouve sous la **même clé** (`"region"`) que celle utilisée par le serveur dans `input_requests`.

Tout le reste de ce fichier (le `input_schema` explicite, le `CallToolResult` construit à la main) relève du `Server` bas niveau ordinaire, traité dans **[Le Server bas niveau](../advanced/low-level-server.md)**. Cette page n’ajoute que le second type de retour.

## Au-delà des outils {#beyond-tools}

`tools/call` n’a rien de particulier : en version 2026-07-28, un serveur peut répondre de la même façon à `prompts/get` et à `resources/read`. Sur `MCPServer`, une fonction `@mcp.prompt()` — ou une fonction `@mcp.resource()` **modèle** (template) — renvoie elle-même l’objet `InputRequiredResult` et lit les réponses de la nouvelle tentative dans le contexte :

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* Le premier tour renvoie l’objet `InputRequiredResult`. Lors de la nouvelle tentative, `ctx.input_responses` contient les réponses sous les mêmes clés et la fonction renvoie son résultat ordinaire — ici des messages de prompt, du contenu de ressource pour une ressource modèle.
* Un `request_state` que vous définissez est scellé avant de franchir la liaison et vérifié à son retour en écho, comme tout le reste côté serveur ; **[Protéger `requestState`](#protecting-requeststate)** ci-dessous explique ce que le sceau vous apporte et quand vous devez configurer des clés.
* Une fonction `@mcp.tool()` peut renvoyer le résultat directement de la même façon, quand la forme par dépendance ne convient pas.
* Les fonctions `@mcp.resource()` statiques ne participent pas : elles ne prennent pas de `Context`, elles ne pourraient donc jamais lire la nouvelle tentative. Seules les ressources modèles peuvent poser une question.
* Les règles de génération ci-dessous s’appliquent telles quelles : renvoyer un `InputRequiredResult` sur une session antérieure à 2026 donne le même `-32603` que celui décrit par l’avertissement.

## Côté client {#the-client-side}

`Client` exécute la boucle pour vous.

Enregistrez les fonctions de rappel (callbacks) que le serveur pourrait solliciter (`elicitation_callback`, `sampling_callback`, `list_roots_callback`) et appelez l’outil. Quand un `InputRequiredResult` arrive, `Client` répartit chaque entrée de `input_requests` vers la fonction de rappel correspondante, relance l’appel avec les réponses et le `request_state` renvoyé en écho, et continue jusqu’à ce qu’un `CallToolResult` revienne :

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* Cette `elicitation_callback` est celle-là même qu’aurait atteinte le `elicitation/create` du canal de retour d’un serveur antérieur à 2026. Il en va de même de `sampling_callback` pour `sampling/createMessage` et de `list_roots_callback` pour `roots/list` : en version 2026-07-28, les RPC autonomes du serveur vers le client ont disparu, mais les charges utiles `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest`, identiques, voyagent à l’intérieur de `input_requests` et sont distribuées aux trois mêmes fonctions de rappel. Un seul jeu de fonctions de rappel sert les deux générations.
* `call_tool` renvoie un simple `CallToolResult`. Les tours intermédiaires sont invisibles pour l’appelant.
* `get_prompt` et `read_resource` pilotent la même boucle.

!!! check
    Omettez la fonction de rappel et la boucle échoue dès le premier tour : la fonction de rappel
    de substitution du SDK répond à chaque élicitation par une erreur, et `call_tool` lève une
    `MCPError` avec le message *« Elicitation not supported »*.

La boucle est bornée. `Client(..., input_required_max_rounds=10)` est le plafond par défaut ; un serveur qui continue de renvoyer des `InputRequiredResult` au-delà fait lever une exception à `call_tool`. Si un tour ne transporte que `request_state` sans `input_requests`, `Client` marque une courte pause (50 ms, doublés jusqu’à un plafond de 250 ms) avant de réessayer, de sorte qu’un serveur qui se contente de dire *« pas encore terminé »* ne soit pas sollicité en boucle.

### Piloter la boucle vous-même {#driving-the-loop-yourself}

La boucle automatique suffit pour un client à processus unique. Prenez plutôt la boucle en main quand :

* Votre client est **distribué** : le processus qui affiche la question à l’utilisateur n’est pas celui qui a appelé `call_tool`, c’est donc un autre worker qui émet la nouvelle tentative. `request_state` est le jeton persistant que vous transportez à travers cette frontière, via votre propre stockage, et `input_responses` est ce que l’autre côté renvoie avec lui.
* Vous voulez **inspecter** chaque tour : journaliser ou auditer chaque entrée de `input_requests`, refuser certains types de requêtes, ou appliquer votre propre temporisation entre les étapes.
* Vous voulez une borne en **temps réel** plutôt qu’en nombre de tours : enveloppez votre propre boucle dans `anyio.fail_after(...)` au lieu de compter sur `input_required_max_rounds`.

Descendez à la session sous-jacente, où `allow_input_required=True` vous remet directement l’union :

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` élargit le type de retour à `CallToolResult | InputRequiredResult`. C’est le `isinstance` qui le resserre à nouveau.
* `request_state` est désormais entre vos mains. Notez-le entre deux étapes et la conversation peut reprendre depuis un processus tout neuf.
* Pour chaque entrée de `input_requests`, vous placez une `InputResponse` sous la **même clé** dans `input_responses`. `fulfil` est l’endroit où va votre interface utilisateur ; celle-ci code la réponse en dur.
* Même nom d’outil, mêmes `arguments`, à chaque étape. La nouvelle tentative, c’est l’appel d’origine exécuté de nouveau, pas une nouvelle méthode.

## Protéger `requestState` {#protecting-requeststate}

Tout ce qui précède traite `request_state` comme un écho, et sur la liaison ce n’est rien d’autre. Mais le client le conserve entre deux étapes (le noter pour le passer d’un processus à l’autre est précisément ce que la section précédente a approuvé), si bien que ce qui revient est une **entrée fournie par le client** : elle peut avoir été modifiée, avoir expiré, ou avoir été prélevée sur un tout autre appel. La spécification impose aux serveurs de protéger l’intégrité de cet état et de rejeter le tour quand la vérification échoue, dès lors que l’état peut influencer l’autorisation, l’accès aux ressources ou la logique métier.

`MCPServer` le protège par défaut. Chaque serveur scelle le `requestState` sortant et vérifie chaque écho — l’état des résolveurs comme l’état construit à la main — sous une clé générée au démarrage du processus. Vous ne configurez rien, vous écrivez du texte en clair et vous lisez du texte en clair ; la liaison ne transporte jamais qu’un jeton chiffré opaque.

La clé par défaut vit et meurt avec le processus ; c’est la seule chose que vous devez savoir avant de déployer au-delà d’un processus unique :

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **La valeur par défaut (aucune configuration)** convient à un processus unique : stdio, ou exactement un worker HTTP. Une nouvelle tentative qui atterrit sur un autre worker, une autre instance derrière un répartiteur de charge, ou le même serveur après un redémarrage, est scellée sous une clé que ce processus ne possède pas — le client reçoit le rejet figé ci-dessous et doit recommencer le flux depuis le début.
* **`keys=[...]`** est obligatoire dès qu’une nouvelle tentative peut atteindre une **autre instance** (`uvicorn` à plusieurs workers, HTTP derrière répartiteur de charge) ou doit survivre aux redémarrages : chaque instance vérifie ce que n’importe quelle instance sœur a émis. Même mécanique, votre secret à la place d’un secret généré.
* Pour votre propre cryptographie, par exemple un KMS ou un service de jetons existant, passez `RequestStateSecurity(codec=...)` au lieu de `keys` ; **[Apporter votre propre cryptographie](#bring-your-own-crypto)** ci-dessous décrit le contrat.

### Ce que porte le sceau {#what-the-seal-carries}

Par défaut ou configuré, `requestState` sur la liaison est un jeton chiffré et authentifié. Votre code ne le voit jamais : gestionnaires et résolveurs écrivent du texte en clair et lisent du texte en clair (`ctx.request_state`) ; le SDK scelle à la sortie et vérifie à l’entrée. Au-delà de l’intégrité, chaque jeton est rattaché à :

* **Une fenêtre temporelle.** Chaque tour scelle de nouveau avec une échéance fraîche, si bien que `RequestStateSecurity(ttl=...)` (600 secondes par défaut) borne le temps de réflexion par tour, pas le flux entier.
* **Le principal authentifié.** Quand la requête porte un jeton d’accès OAuth validé par le SDK, l’état est rattaché au client, à l’émetteur et au sujet du jeton : un état émis pour un utilisateur échoue pour un autre, même quand les deux utilisateurs partagent un même client OAuth. Un vérificateur qui ne fournit aucun sujet réduit le rattachement à la seule identité du client, laquelle, avec des identifiants de client fondés sur une URL, est partagée par tous les utilisateurs de ce logiciel client. Quand l’authentification se termine en dehors du SDK (un proxy frontal), ou que le transport n’est pas authentifié, il n’y a aucun principal auquel se rattacher et cette vérification est inerte, sauf si `RequestStateSecurity(bind_principal=...)` en fournit un à partir de votre propre signal d’identité. Quels que soient les composants que votre vérificateur de jetons fournit, il doit les fournir de façon cohérente : un vérificateur qui inclut le sujet sur certaines requêtes et l’omet sur d’autres change de principal en plein flux, et les tours en cours sont rejetés.
* **La requête d’origine.** La méthode, le nom de l’outil ou du prompt (ou l’URI de la ressource), et une empreinte des arguments. Un jeton rejoué contre un autre outil, d’autres arguments ou une autre méthode échoue.
* **La question exacte posée.** Chaque réponse de résolveur est épinglée à la question rendue qui a été montrée au client, aussi bien au tour où elle arrive pour la première fois que lorsqu’une réponse enregistrée est réutilisée plus tard. Redéployez avec un message reformulé ou un schéma modifié et le serveur repose la question au lieu de consommer une réponse périmée. Le même épinglage joue aussi dans l’autre sens : dérivez les messages des arguments de l’outil, pas de données propres à chaque appel. Un message construit à partir d’un horodatage ou d’un taux en direct se rend différemment à chaque tour, si bien que chaque réponse enregistrée paraît périmée et que le serveur repose la question jusqu’à ce que la limite de tours du client mette fin à l’appel.

Tout cela est le travail du SDK, pas le vôtre, ni celui du codec si vous apportez le vôtre.

### Rotation des clés {#rotating-keys}

`keys[0]` scelle le nouvel état ; chaque clé de la liste vérifie. Une rotation sans interruption se fait en trois phases, chacune entièrement déployée avant la suivante :

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

Ne promouvez jamais la clé d’émission en premier : émettre sous une clé qu’une instance ne sait pas encore vérifier fait tomber des tours en cours au milieu du déploiement.

Les clés sont limitées à un seul service. L’enveloppe scellée porte aussi le nom du serveur comme revendication d’audience, si bien qu’un jeton émis par un autre service qui se trouverait partager un secret est rejeté de toute façon. La revendication n’est distinctive que dans la mesure où le nom l’est : un serveur doté d’une politique explicite doit donc avoir un vrai nom ou définir `RequestStateSecurity(audience=...)` — un serveur sans nom lève une exception à la construction. `audience=` sert aussi aux topologies multi-services délibérées où un service doit accepter un état émis par un autre. (La valeur par défaut sans configuration est exemptée : sa clé ne quitte jamais le processus, la revendication d’audience n’a donc rien à ajouter.)

### Apporter votre propre cryptographie {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` accepte tout objet doté de `seal(bytes) -> str` et `unseal(str) -> bytes` qui lève `InvalidRequestState` pour tout jeton qu’il n’a pas émis. La forme classique est le chiffrement d’enveloppe adossé à un KMS : vous déchiffrez une clé de données une seule fois au démarrage et gardez la cryptographie par jeton en local :

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

Le TTL, le rattachement au principal et le rattachement à la requête ne sont **pas** l’affaire du codec : le SDK les inscrit dans la charge utile avant `seal` et les revérifie après `unseal`, pour chaque codec. Les seules obligations d’un codec sont l’intégrité (altéré signifie lever une exception) et, idéalement, la confidentialité.

### Quand la vérification échoue {#when-verification-fails}

Chaque échec entrant, qu’il s’agisse d’un jeton altéré, expiré, rejoué contre une autre requête ou un autre principal, ou scellé sous une clé que ce serveur ne connaît pas, reçoit la même réponse :

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

Un seul message figé pour toutes les causes, afin que la liaison ne révèle jamais quelle vérification a échoué ; la vraie raison va dans le journal du serveur. Chaque `requestState` entrant sur `tools/call`, `prompts/get` et `resources/read` est vérifié, y compris celui qui arrive pour un gestionnaire qui n’émet jamais d’état. Le rejet le plus courant en pratique n’est pas un attaquant — c’est la clé par défaut, locale au processus, qui rencontre une nouvelle tentative antérieure à un redémarrage ou venue d’une autre instance ; le client relance le flux, et `keys=[...]` est le correctif quand cela compte.

### État construit à la main {#hand-built-state}

Un `request_state` que vous définissez vous-même (en renvoyant `InputRequiredResult` depuis une fonction d’outil, de prompt ou de modèle de ressource) est scellé et vérifié par la même mécanique que l’état des résolveurs, sans aucune modification de code : écrivez du texte en clair, lisez du texte en clair, et chaque rattachement ci-dessus s’applique.

La seule chose que le SDK ne peut pas épingler pour vous, même configuré, c’est l’identité de la question : il ne sait pas à laquelle de *vos* questions appartient une réponse présente dans votre état. Si vous stockez des réponses indexées par question, incluez votre propre identifiant de question dans l’état et vérifiez-le lors de la nouvelle tentative.

Le `Server` bas niveau est le niveau sans rien de fourni d’office : contrairement à `MCPServer`, rien n’est scellé tant que vous n’ajoutez pas vous-même la frontière, et votre `request_state` franchit la liaison exactement tel qu’écrit jusqu’à ce que vous le fassiez. L’activation en une ligne est montrée dans **[Le Server bas niveau](../advanced/low-level-server.md#the-other-handlers)**.

## Un résultat de la version 2026-07-28 {#a-2026-07-28-result}

`InputRequiredResult` n’existe qu’en version de protocole **2026-07-28**. Le `Client(server)` en mémoire la négocie pour vous ; sur la liaison, `mode="auto"` la découvre. Une fois connecté, `client.protocol_version` vous dit ce que vous avez obtenu.

!!! warning
    Une session antérieure à 2026 n’a nulle part où mettre un `InputRequiredResult`. Renvoyez-en
    un depuis votre gestionnaire sur une connexion `mode="legacy"` et l’exécuteur ne peut pas le
    sérialiser dans la version négociée ; le client reçoit en retour une erreur `-32603`
    *« Handler returned an invalid result »*. Un serveur qui sert les deux générations doit vérifier
    `ctx.protocol_version` avant d’y recourir.

!!! info
    L’**élicitation en mode URL** emprunte exactement ce mécanisme sur une connexion 2026. L’entrée
    dans `input_requests` est une `ElicitRequest` dont les params sont `ElicitRequestURLParams` ;
    l’utilisateur termine le flux hors bande et votre client relance l’appel. Même boucle, aucune
    nouvelle API. La moitié serveur haut niveau se trouve dans **[Élicitation](elicitation.md)**.

## Récapitulatif {#recap}

* En version 2026-07-28, un serveur qui a besoin d’une entrée en cours d’appel **renvoie** un `InputRequiredResult`. Il n’ouvre jamais de requête vers le client.
* `input_requests` est ce dont il a besoin. `request_state` est un jeton de reprise opaque que seul le serveur lit.
* `Client` exécute la boucle de nouvelles tentatives pour vous : enregistrez `elicitation_callback` / `sampling_callback` / `list_roots_callback` et `call_tool` renvoie un simple `CallToolResult`. `input_required_max_rounds` (10 par défaut) la borne.
* Pour inspecter ou persister les tours, utilisez `client.session.call_tool(..., allow_input_required=True)` et prenez vous-même en main la boucle `while isinstance(result, InputRequiredResult)`.
* Avec `@mcp.tool()`, une dépendance qui interroge l’utilisateur produit ce résultat pour vous (**[Dépendances](dependencies.md)**) ; le `Server` **bas niveau** est la forme manuelle.
* Les prompts et les ressources participent aussi : une fonction `@mcp.prompt()` ou une fonction `@mcp.resource()` modèle renvoie elle-même l’objet `InputRequiredResult` et lit `ctx.input_responses` lors de la nouvelle tentative.
* `requestState` revient sous forme d’entrée fournie par le client, donc `MCPServer` le scelle par défaut — l’état des résolveurs comme l’état construit à la main — sous une clé locale au processus ; les déploiements multi-instances passent `RequestStateSecurity(keys=[...])` (ou un codec personnalisé) pour que chaque instance puisse vérifier ce qu’une instance sœur a émis. Le sceau rattache chaque jeton à une fenêtre temporelle, à la requête d’origine et au principal authentifié lorsque la requête porte une authentification validée par le SDK ou que `bind_principal=` fournit votre propre signal d’identité (**[Protéger `requestState`](#protecting-requeststate)**).

C’est le mécanisme qui remplace l’échantillonnage à l’initiative du serveur et le reste du canal de retour de type push ; voir **[Fonctionnalités obsolètes](../deprecated.md)**.
