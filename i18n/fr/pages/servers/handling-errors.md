---
translation:
  sections: [7be05607887e6853, e7375894888d9750, c36f73fc7e3af13b, 2fec2d7e129e62fe, 809b0e0a7c27295a, b4395a04d2a5d906, 1a436007f5f54779, c6b2078ed1e63ba5]
  tool: 1
---
# Gérer les erreurs {#handling-errors}

Un outil (tool) peut échouer de trois manières, et le SDK traite chacune différemment.

Levez `ToolError` et c’est le **modèle** qui voit votre message. Levez `MCPError` et c’est le **protocole** qui le voit. Levez quoi que ce soit d’autre et c’est un plantage : le modèle apprend seulement que l’appel a échoué, et votre journal reçoit le traceback.

Cette page vous aide à choisir.

## Une erreur que le modèle peut corriger {#an-error-the-model-can-fix}

Prenez un outil qui effectue une recherche, et laissez cette recherche échouer :

```python title="server.py" hl_lines="2 12-13"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`ToolError`, qui vient de `mcp.server.mcpserver.exceptions`, est le moyen pour un outil de dire au modèle que quelque chose s’est mal passé.

Appelez-le avec un titre absent du catalogue et regardez le résultat :

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* La requête a **réussi**. Il y a un résultat ; rien n’a été levé côté appelant.
* `is_error` vaut `True`, et votre message (préfixé du nom de l’outil) se trouve dans `content`, exactement là où le modèle lit.
* `structured_content` vaut `None`. Un appel en échec n’a aucune valeur de retour à structurer.

C’est une **erreur d’outil** (tool error), et c’est presque toujours ce que vous voulez.

C’est le modèle qui appelle votre outil. C’est lui qui a choisi les arguments. Une erreur d’outil est donc un tour de conversation : le modèle lit *« No book titled 'Nothing' in the catalog. »*, comprend qu’il s’est trompé de titre et rappelle l’outil avec un meilleur. Vous avez écrit un seul `raise` et obtenu un agent qui se corrige tout seul.

Côté serveur, une `ToolError` se résume à une ligne `INFO` dans le journal, sans traceback. Vous l’aviez vue venir, il n’y a donc rien à examiner.

!!! tip
    N’utilisez jamais `return` pour renvoyer un message d’erreur depuis un outil. Une chaîne renvoyée a
    `is_error=False` : pour le modèle (et pour toute interface cliente), l’outil semble avoir
    fonctionné et cette chaîne semble être la réponse. Utilisez `raise`. C’est le drapeau qui fait signal.

## Une erreur que le modèle ne peut pas corriger {#an-error-the-model-cannot-fix}

Remplacez maintenant `ToolError` par `MCPError`.

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` est l’**erreur de protocole** du SDK. C’est la seule exception que l’enveloppe de l’outil n’intercepte *pas* : elle se propage, et toute la requête `tools/call` échoue avec une erreur JSON-RPC au lieu d’un résultat.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* Il n’y a **aucun résultat**. Pas de `content`, pas de `is_error` : rien à lire pour le modèle.
* C’est l’application **hôte** qui reçoit l’erreur, exactement comme si l’outil n’existait pas du tout.
* `code`, `message` et `data` arrivent intacts. `INVALID_PARAMS` vaut `-32602` ; `mcp.types` l’exporte, avec les autres codes d’erreur JSON-RPC (`INVALID_REQUEST`, `INTERNAL_ERROR`, …), sous forme de constantes pour que vous n’ayez jamais à saisir de nombre magique.

!!! check
    Même recherche, même échec, mais cette fois l’appel *lève une exception* côté client au lieu de renvoyer un résultat :

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    La première version donnait au modèle une phrase à laquelle réagir. Celle-ci ne lui donne rien.
    Pour `get_author`, c’est strictement pire, et c’est tout l’objet de la section suivante.

## Laquelle lever {#which-one-to-raise}

Les deux voies répondent à deux questions différentes.

* **Levez `ToolError`** pour un échec d’*exécution* : ce que votre outil a tenté de faire n’a pas fonctionné. Le modèle a choisi l’appel, il devrait donc en voir la conséquence et avoir une chance de se rattraper. Un titre mal orthographié, une API amont qui a expiré, une ligne qui n’existe pas : autant d’erreurs d’outil.
* **Levez `MCPError`** quand c’est la *requête elle-même* qui doit être rejetée : il manque au client une capacité dont dépend votre outil, le serveur n’est pas en état de servir qui que ce soit, l’appelant a sauté une étape obligatoire. Aucune nouvelle tentative du modèle ne corrige cela, il n’y a donc rien à gagner à lui transmettre le message.

Une seule question tranche : **un modèle plus malin aurait-il pu éviter cela ?** Oui -> `ToolError`. Non -> `MCPError`.

Selon ce critère, la seconde version de `get_author` a fait le mauvais choix : un meilleur titre règle le problème, le modèle méritait donc de voir le message. Elle est là pour vous montrer le mécanisme, pas pour le recommander.

!!! info
    `MCPError` s’importe avec `from mcp import MCPError` et prend `code`, `message` et une charge
    utile `data` facultative. Ce que vous y mettez est ce que le client reçoit : le SDK transmet telle
    quelle une `MCPError` levée au lieu de l’assainir.

## Toute autre exception {#any-other-exception}

Retirez maintenant la vérification et laissez la recherche dans le dictionnaire échouer d’elle-même :

```python title="server.py" hl_lines="11"
--8<-- "docs_src/handling_errors/tutorial004.py"
```

`CATALOG[title]` lève `KeyError`. Vous ne l’aviez pas prévue, le SDK la traite donc comme un plantage :

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool get_author")]
```

L’appel renvoie toujours `is_error=True`, le modèle sait donc qu’il a échoué et peut passer à autre chose. Ce qu’il n’obtient pas, c’est le texte de l’exception : une `KeyError` venue de votre code, ou une pile de SQL remontée d’un pilote trois bibliothèques plus bas, peut décrire les entrailles de votre serveur, si bien que ce texte ne quitte jamais le serveur.

C’est vous qui le recevez. Le serveur journalise le plantage au niveau `ERROR` avec le traceback complet, sous l’intitulé `Tool 'get_author' raised an unexpected exception`. Un journal de production réglé sur `WARNING` reste donc silencieux à chaque `ToolError` et se manifeste dès que quelque chose est réellement cassé.

## Une ressource qui n’existe pas {#a-resource-that-doesnt-exist}

Les ressources tracent la même frontière, et fournissent une exception dédiée pour le cas courant.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` est un **modèle** (template). Il correspond à *n’importe quel* titre, donc « l’URI est bien formé » et « le livre existe » sont deux questions différentes, et seule votre fonction peut répondre à la seconde.

Quand elle ne le peut pas, levez `ResourceNotFoundError`. Le SDK la transforme en l’erreur de protocole que la spécification attribue à une ressource manquante : `-32602` avec l’URI demandé dans `data`, pour que le client sache *quelle* lecture a échoué.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

Remarquez qu’il n’y a pas ici de demi-résultat `is_error=True`. La lecture d’une ressource renvoie un contenu ou échoue : les ressources n’ont que la voie du protocole. `ResourceError` est l’équivalent pour un échec qui n’est pas « introuvable » (`-32603`, votre message), et les deux se résument à une ligne `INFO` dans votre journal. Toute autre exception hormis `MCPError` est un plantage : le client reçoit `-32603` ne mentionnant que l’URI, et le traceback va dans votre journal au niveau `ERROR`. Les modèles et tout ce qui concerne les ressources se trouvent dans **[Ressources](resources.md)**.

## Les erreurs que vous ne levez jamais {#errors-you-never-raise}

Un mauvais argument n’atteint jamais votre fonction.

Envoyez à `get_author` un `title` qui n’est pas une chaîne et le SDK le rejette d’après le schéma d’entrée **avant** de vous appeler, sous la forme du même genre d’erreur d’outil `is_error=True` que le modèle peut lire et corriger. **[Outils](tools.md)** montre le même rejet avec une contrainte `Field(le=50)`.

Cela représente toute une catégorie d’instructions `raise` que vous n’écrivez pas : ne revalidez pas vos propres annotations de type.

!!! info
    Tout ce qu’un **client** voit sur cette page, le `Client` en mémoire avec lequel vous écrirez vos
    tests le voit aussi. Même `raise_exceptions=True` ne rend pas à l’appelant l’exception d’un outil
    en échec : au moment où ce drapeau pourrait agir, votre exception est déjà devenue le résultat
    `is_error=True`. Faites vos assertions sur le résultat. Si vous avez besoin du traceback d’un plantage,
    il est dans le journal du serveur, et le `caplog` de pytest le capture. **[Tests](../get-started/testing.md)** présente ce schéma.

## Récapitulatif {#recap}

* Levez **`ToolError`** dans un outil -> l’appel renvoie `is_error=True` avec votre message dans `content`. Le modèle le lit et peut réessayer.
* Levez **`MCPError`** -> l’appel lui-même échoue avec une erreur JSON-RPC. Le modèle ne voit rien ; c’est l’hôte qui s’en occupe. `code`, `message` et `data` arrivent intacts.
* La question qui tranche : *un modèle plus malin aurait-il pu éviter cela ?* Oui -> `ToolError`. Non -> `MCPError`.
* Toute **autre exception** est un plantage -> `is_error=True` avec seulement `Error executing tool <name>` pour le modèle, et un enregistrement `ERROR` avec le traceback pour vous.
* `ResourceNotFoundError` depuis un gestionnaire (handler) de ressource -> le `-32602` du protocole, avec l’URI dans `data`.
* Les mauvais arguments sont rejetés d’après le schéma avant que votre fonction ne s’exécute ; vous n’avez pas de `raise` à écrire pour eux.
* Imports : `from mcp import MCPError`, `from mcp.server.mcpserver.exceptions import ToolError, ResourceError, ResourceNotFoundError`, et les constantes de codes d’erreur depuis `mcp.types`.

Les erreurs sont gérées. C’est tout ce qu’un serveur *expose*. Ce que chaque gestionnaire peut lire, et faire en retour auprès du client pendant qu’il s’exécute, fait l’objet de la section suivante : **[Dans votre gestionnaire](../handlers/index.md)**.

Le texte exact des erreurs du SDK que vous avez le plus de chances de rencontrer, ce que chacune signifie et le correctif en un geste pour chacune se trouvent dans **[Dépannage](../troubleshooting.md)**.
