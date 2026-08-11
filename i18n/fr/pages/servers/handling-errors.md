---
translation:
  sections: [e33d441f12d50535, 7099694c603e0f5f, c1df4cf9673433e6, c9cd294541422e6e, 6cec073617bfd037, efa92b8f99e908c8, 6a22a29e27fb4601]
  tool: 1
---
# Gérer les erreurs {#handling-errors}

Un outil (tool) peut échouer de deux manières, et le SDK les traite très différemment.

Levez une exception ordinaire et c’est le **modèle** qui la voit. Levez `MCPError` et c’est le **protocole** qui la voit.

Cette page vous aide à choisir.

## Une erreur que le modèle peut corriger {#an-error-the-model-can-fix}

Prenez un outil qui effectue une recherche, et laissez cette recherche échouer :

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

Ces deux lignes n’ont rien de spécifique à MCP. `get_author` lève une simple `ValueError`, comme le ferait n’importe quelle fonction Python.

Appelez-le avec un titre absent du catalogue et regardez le résultat :

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* La requête a **réussi**. Il y a un résultat ; rien n’a été levé côté appelant.
* `is_error` vaut `True`, et le message de votre exception (préfixé du nom de l’outil) se trouve dans `content`, exactement là où le modèle lit.
* `structured_content` vaut `None`. Un appel en échec n’a aucune valeur de retour à structurer.

C’est une **erreur d’outil** (tool error), et c’est le comportement par défaut pour *toute* exception que lève votre outil. C’est aussi presque toujours ce que vous voulez.

C’est le modèle qui appelle votre outil. C’est lui qui a choisi les arguments. Une erreur d’outil est donc un tour de conversation : le modèle lit *« No book titled 'Nothing' in the catalog. »*, comprend qu’il s’est trompé de titre et rappelle l’outil avec un meilleur. Vous avez écrit un seul `raise` et obtenu un agent qui se corrige tout seul.

!!! tip
    N’utilisez jamais `return` pour renvoyer un message d’erreur depuis un outil. Une chaîne renvoyée a
    `is_error=False` : pour le modèle (et pour toute interface cliente), l’outil semble avoir
    fonctionné et cette chaîne semble être la réponse. Utilisez `raise`. C’est le drapeau qui fait signal.

## Une erreur que le modèle ne peut pas corriger {#an-error-the-model-cannot-fix}

Remplacez maintenant `ValueError` par `MCPError`.

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

* **Levez n’importe quelle exception** pour un échec d’*exécution* : ce que votre outil a tenté de faire n’a pas fonctionné. Le modèle a choisi l’appel, il devrait donc en voir la conséquence et avoir une chance de se rattraper. Un titre mal orthographié, une API amont qui a expiré, une ligne qui n’existe pas : autant d’erreurs d’outil.
* **Levez `MCPError`** quand c’est la *requête elle-même* qui doit être rejetée : il manque au client une capacité dont dépend votre outil, le serveur n’est pas en état de servir qui que ce soit, l’appelant a sauté une étape obligatoire. Aucune nouvelle tentative du modèle ne corrige cela, il n’y a donc rien à gagner à lui transmettre le message.

Une seule question tranche : **un modèle plus malin aurait-il pu éviter cela ?** Oui -> exception ordinaire. Non -> `MCPError`.

Selon ce critère, la seconde version de `get_author` a fait le mauvais choix : un meilleur titre règle le problème, le modèle méritait donc de voir le message. Elle est là pour vous montrer le mécanisme, pas pour le recommander.

!!! info
    `MCPError` s’importe avec `from mcp import MCPError` et prend `code`, `message` et une charge
    utile `data` facultative. Ce que vous y mettez est ce que le client reçoit : le SDK transmet telle
    quelle une `MCPError` levée au lieu de l’assainir.

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

Remarquez qu’il n’y a pas ici de demi-résultat `is_error=True`. La lecture d’une ressource renvoie un contenu ou échoue : les ressources n’ont que la voie du protocole. Les modèles et tout ce qui concerne les ressources se trouvent dans **[Ressources](resources.md)**.

## Les erreurs que vous ne levez jamais {#errors-you-never-raise}

Un mauvais argument n’atteint jamais votre fonction.

Envoyez à `get_author` un `title` qui n’est pas une chaîne et le SDK le rejette d’après le schéma d’entrée **avant** de vous appeler, sous la forme du même genre d’erreur d’outil `is_error=True` que le modèle peut lire et corriger. **[Outils](tools.md)** montre le même rejet avec une contrainte `Field(le=50)`.

Cela représente toute une catégorie d’instructions `raise` que vous n’écrivez pas : ne revalidez pas vos propres annotations de type.

!!! info
    Tout ce que décrit cette page est ce qu’un **client** voit, et le `Client` en mémoire avec lequel
    vous écrirez vos tests voit exactement la même chose. Même `raise_exceptions=True` ne retransforme
    pas une erreur d’outil en traceback : au moment où ce drapeau pourrait agir, votre exception est déjà
    devenue le résultat `is_error=True`. Faites vos assertions sur le résultat. **[Tests](../get-started/testing.md)** présente ce schéma.

## Récapitulatif {#recap}

* Levez **n’importe quelle exception** dans un outil -> l’appel renvoie `is_error=True` avec votre message dans `content`. Le modèle le lit et peut réessayer. C’est le comportement par défaut.
* Levez **`MCPError`** -> l’appel lui-même échoue avec une erreur JSON-RPC. Le modèle ne voit rien ; c’est l’hôte qui s’en occupe. `code`, `message` et `data` arrivent intacts.
* La question qui tranche : *un modèle plus malin aurait-il pu éviter cela ?* Oui -> exception. Non -> `MCPError`.
* `ResourceNotFoundError` depuis un gestionnaire (handler) de ressource -> le `-32602` du protocole, avec l’URI dans `data`.
* Les mauvais arguments sont rejetés d’après le schéma avant que votre fonction ne s’exécute ; vous n’avez pas de `raise` à écrire pour eux.
* `from mcp import MCPError` ; les constantes de codes d’erreur viennent de `mcp.types`.

Les erreurs sont gérées. C’est tout ce qu’un serveur *expose*. Ce que chaque gestionnaire peut lire, et faire en retour auprès du client pendant qu’il s’exécute, fait l’objet de la section suivante : **[Dans votre gestionnaire](../handlers/index.md)**.

Le texte exact des erreurs du SDK que vous avez le plus de chances de rencontrer, ce que chacune signifie et le correctif en un geste pour chacune se trouvent dans **[Dépannage](../troubleshooting.md)**.
