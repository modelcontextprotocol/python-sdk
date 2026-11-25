---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# Dépendances {#dependencies}

Les arguments d’un outil (tool) viennent du modèle. Certaines valeurs ne devraient jamais en venir : un prix tiré de vos registres, une confirmation que seule une personne peut donner, tout ce que le modèle pourrait fausser en l’inventant.

Les **dépendances** sont des paramètres remplis par vos propres fonctions. Vous annotez le paramètre, vous nommez la fonction, et le SDK l’appelle avant l’exécution de votre outil.

## En déclarer une {#declare-one}

Enveloppez le type du paramètre dans `Annotated[...]` et ajoutez `Resolve(fn)` :

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` est un **résolveur** : une simple fonction que le SDK exécute avant `reserve_book`, et dont la valeur de retour devient l’argument `stock`.
* Son paramètre `title` est l’argument `title` de l’outil lui-même, apparié **par nom**. Le résolveur voit exactement la valeur validée que verra le corps de l’outil.
* Le corps de l’outil part d’un `Stock` qui existe déjà. Pas de code de recherche dans l’outil, pas de préambule « et s’il manquait ? ».

!!! info
    Si vous avez utilisé FastAPI, c’est `Depends`. Même geste, même raison : la fonction déclare
    ce dont elle a besoin, le framework le fournit, et le câblage vit dans l’annotation de type.

### Invisible pour le modèle {#invisible-to-the-model}

Voici le schéma d’entrée que `tools/list` rapporte pour `reserve_book` :

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

Une seule propriété. Comme le `Context` dans **[L’objet Context](context.md)**, un paramètre résolu est un contrat entre vous et le SDK : `stock` n’est pas dans le schéma, le modèle n’en entend jamais parler, et un client qui envoie quand même une valeur `stock` est ignoré. La valeur du résolveur est la seule que votre outil puisse recevoir.

Ce dernier point est l’essentiel. Un paramètre que le modèle ne peut pas fournir est un paramètre sur lequel le modèle ne peut pas se tromper.

### Essayer {#try-it}

Lancez le serveur avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Le formulaire de `reserve_book` comporte un seul champ `title`. `stock` n’y figure nulle part. Appelez-le avec `Dune` :

```text
Reserved 'Dune' (6 copies left).
```

Le corps de l’outil n’a rien recherché : `check_stock` s’est exécuté d’abord, et le `Stock` qu’il a renvoyé est arrivé en argument. Essayez `Neuromancer` et le même résolveur remet un zéro à l’outil.

!!! tip
    Vous pourriez simplement appeler `check_stock(title)` dans le corps de l’outil. Déclarez-le
    comme dépendance quand la valeur mérite mieux qu’un appel de fonction utilitaire : chaque
    outil qui a besoin du stock déclare le même paramètre, et le SDK exécute le résolveur au plus
    une fois par appel, quel que soit le nombre d’outils qui le déclarent. Les sections suivantes
    ajoutent le reste : des résolveurs qui dépendent les uns des autres, et des résolveurs qui
    interrogent l’utilisateur.

## Dépendances de dépendances {#dependencies-of-dependencies}

Un résolveur peut déclarer ses propres dépendances, avec la même annotation :

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` dépend de `check_stock`. Le SDK exécute le graphe dans l’ordre : le stock d’abord, puis l’estimation, puis l’outil.
* `stock` comme `delivery` ont en fin de compte besoin de `check_stock`, mais celui-ci s’exécute **une fois par appel**. Une seule consultation de l’inventaire, deux consommateurs.
* Il n’y a rien à enregistrer. Le graphe, *ce sont* les annotations.

!!! check
    Ne croyez pas le « une fois par appel » sur parole. Placez un `print` dans `check_stock` et
    appelez `order_book` depuis l’Inspector : une ligne par appel. Deux consommateurs, une seule
    consultation.

Le SDK analyse le graphe à l’enregistrement de l’outil, pas à son appel. Un paramètre qu’il ne sait pas classer — ni un `Context`, ni un `Resolve(...)`, ni le nom d’un argument de l’outil — et un cycle de résolveurs lèvent tous deux `InvalidSignature` au démarrage. Votre serveur échoue avant même qu’un client se connecte, avec le paramètre ou le résolveur fautif nommé dans l’erreur.

Les paramètres d’un résolveur se résolvent exactement comme ceux d’un outil : un autre `Resolve(...)`, les arguments de l’outil lui-même par nom, ou le `Context` — `ctx.headers`, l’objet du cycle de vie (lifespan), tout.

!!! warning
    Sur les transports HTTP, le `Context` inclut `ctx.headers`. Les en-têtes sont des **entrées
    fournies par le client**, comme n’importe quel argument d’outil : très bien pour une locale ou
    un feature flag, jamais pour une identité. L’identité de l’appelant vient de votre couche
    d’autorisation (**[Autorisation](../run/authorization.md)**), pas d’un en-tête que n’importe qui peut définir.

!!! tip
    *Une fois par appel* veut dire exactement cela : le `tools/call` suivant exécute de nouveau
    `check_stock`. Une ressource qui doit survivre à une requête — un pool de connexions à la base
    de données, un client HTTP — a sa place dans **[Cycle de vie](lifespan.md)**, et un résolveur
    peut l’atteindre via `ctx.request_context.lifespan_context`.

## Demander quand il le faut {#ask-when-you-must}

Un résolveur n’est pas obligé de connaître la réponse. Il peut renvoyer `Elicit(message, Model)` et le SDK interroge l’utilisateur — c’est la mécanique de l’**[Élicitation](elicitation.md)** (elicitation), pilotée pour vous :

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* En stock : `confirm_backorder` renvoie directement un `Backorder`. **Pas de question, pas d’aller-retour.** L’utilisateur n’est interrompu que lorsque sa réponse compte.
* En rupture : le SDK envoie l’élicitation, valide la réponse par rapport à `Backorder`, et l’injecte. Votre résolveur ne touche jamais au protocole.
* L’outil lit `backorder.confirm` comme n’importe quel autre argument. Répondre **non** reste une réponse : l’élicitation est acceptée avec `confirm=False`, l’outil s’exécute, et aucune commande n’est passée. Poser la question est devenu une précondition, pas de la tuyauterie dans le corps de l’outil.

Et si l’utilisateur ne répond pas du tout — s’il décline la question, ou l’annule ?

!!! check
    Lancez `order_book` pour `Neuromancer` et déclinez la question. Avec l’annotation écrite sous
    la forme `Annotated[Backorder, Resolve(...)]`, le corps de l’outil ne s’exécute jamais ;
    l’appel échoue avec un résultat d’erreur que le modèle peut lire :

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

C’est le bon comportement par défaut pour une précondition : pas de réponse, pas de commande. Quand le refus est une issue que votre outil veut gérer — renoncer à la commande en attente mais suggérer tout de même un autre titre —, annotez plutôt `ElicitationResult[Backorder]` et l’outil reçoit l’issue complète accept/decline/cancel pour décider de la suite. **[Élicitation](elicitation.md)** montre cette forme, et tout le reste sur la manière de poser une question : les règles de schéma, les trois réponses, le côté client de la conversation.

!!! info
    Le framework choisit le transport de la question d’après la version du protocole négociée ;
    le code ci-dessus est identique dans les deux cas. En version **2026-07-28** et ultérieures,
    la question voyage à l’intérieur d’un `tools/call` à plusieurs allers-retours
    (multi-round-trip) — le serveur la renvoie, la fonction de rappel (callback)
    `elicitation_callback` du client y répond, et le `Client` relance l’appel pour vous
    (**[Requêtes à plusieurs allers-retours](multi-round-trip.md)**). En version **2025-11-25**
    et antérieures, c’est une requête d’élicitation synchrone en cours d’appel. Chaque question
    est posée exactement une fois par appel — une garantie qui porte sur la question, pas sur le
    résolveur. Dans la forme à plusieurs allers-retours, n’importe quel résolveur peut s’exécuter
    de nouveau chaque fois que l’appel reprend après une question ; le code placé avant un
    `return Elicit(...)` s’exécute donc à chacun de ces tours, et la réponse enregistrée satisfait
    alors la question répétée sans solliciter de nouveau l’utilisateur. Une réponse enregistrée
    n’est consultée que lorsque le résolveur pose la question ; un résolveur qui répond *sans*
    poser de question, comme `check_stock`, fournit toujours sa propre valeur calculée. Comme
    chaque réponse est rattachée à sa question, un résolveur qui élicite doit dériver sa question
    de façon déterministe à partir des arguments de l’outil et des réponses précédentes. Une
    valeur générée à chaque appel (un identifiant issu d’un `default_factory`, un horodatage) est
    recalculée à chaque tour et ne doit pas figurer dans une question à laquelle la réponse est
    censée se lier. Une question construite à partir de données aussi volatiles fait paraître
    périmée chaque réponse enregistrée ; le serveur la repose donc à chaque tour jusqu’à ce que
    la limite de tours du client mette fin à l’appel.

## Interroger le client, pas l’utilisateur {#ask-the-client-not-the-user}

L’élicitation est l’une des trois questions qu’un résolveur peut poser, et le flux à plusieurs allers-retours n’en autorise aucune autre. Les deux autres s’adressent au **client** plutôt qu’à l’utilisateur : renvoyez `Sample(...)` pour faire exécuter un appel de LLM par le client (une requête `sampling/createMessage`), ou `ListRoots()` pour récupérer les racines (roots) actuelles du client. Aucune des deux n’a d’issue accept/decline ; le consommateur annote directement le type du résultat, `CreateMessageResult` (`CreateMessageResultWithTools` lorsque la requête porte `tools` ou `tool_choice`) ou `ListRootsResult` :

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* Le framework les achemine exactement comme `Elicit` : à l’intérieur du `tools/call` à plusieurs allers-retours en version **2026-07-28**, via la requête autonome serveur->client en version **2025-11-25**. Une capacité non déclarée fait refuser l’appel avec une erreur de protocole `-32021` (`sampling`, `roots`, `elicitation` en mode formulaire ; `sampling.tools` lorsque la requête porte `tools` ou `tool_choice`).
* Tout ce que l’encadré d’information ci-dessus dit des questions s’applique tel quel : une requête `Sample` est rattachée à son résultat enregistré par son rendu exact ; construisez-la donc de façon déterministe à partir des arguments de l’outil et des réponses précédentes. Le client paie alors l’appel de LLM une fois par appel d’outil, pas une fois par tour. Le résultat enregistré voyage dans `request_state` pour le reste de l’appel, si bien qu’une complétion très volumineuse alourdit chaque aller-retour restant.
* Les *fonctionnalités* autonomes d’échantillonnage (sampling) et de racines sont obsolètes en version 2026-07-28 (SEP-2577). Les nouveaux serveurs qui ont besoin du modèle du client posent leur question via ce vecteur ; ceux qui n’en ont pas besoin devraient s’intégrer directement à un fournisseur de LLM. Les valeurs de `include_context` autres que `"none"` sont elles-mêmes obsolètes ; évitez-les.

## Récapitulatif {#recap}

* `Annotated[T, Resolve(fn)]` sur un paramètre d’outil : le SDK exécute `fn` et injecte sa valeur de retour.
* Un paramètre résolu est invisible pour le modèle et ne peut pas être fourni par un client. Les valeurs que le modèle ne doit pas inventer — prix, identités, permissions — ont leur place ici.
* Les paramètres d’un résolveur se résolvent de la même façon : le `Context`, un autre `Resolve(...)`, ou un argument de l’outil par nom. Le graphe exécute chaque résolveur au plus une fois par tour, quel que soit le nombre de ses consommateurs ; chaque question est posée exactement une fois, et n’importe quel résolveur peut s’exécuter de nouveau lorsqu’un appel reprend après une question.
* Les graphes incorrects échouent à l’enregistrement avec `InvalidSignature`, pas en cours d’appel.
* Renvoyez `Elicit(message, Model)` pour interroger l’utilisateur, seulement quand il le faut. Les annotations non enveloppées interrompent l’appel en cas de refus ; `ElicitationResult[T]` laisse l’outil décider de la suite.
* Renvoyez `Sample(...)` ou `ListRoots()` pour demander au client une complétion de LLM ou la liste des racines ; le résultat brut est injecté.

L’état que votre serveur construit une seule fois au démarrage, et la manière dont un gestionnaire (handler) y accède, c’est la page **[Cycle de vie](lifespan.md)**.
