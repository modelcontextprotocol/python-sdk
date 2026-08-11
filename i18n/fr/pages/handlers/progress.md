---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# Progression {#progress}

Un outil qui met trente secondes et ne dit rien pendant trente secondes a l’air cassé.

Les **notifications de progression** règlent cela. L’outil indique où il en est ; le client décide quoi en afficher : une barre, une roue qui tourne, une ligne de journal.

## La signaler depuis l’outil {#report-it-from-the-tool}

Prenez un paramètre **`Context`** et appelez `report_progress` :

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

Trois arguments, et c’est vous qui décidez de leur sens :

* `progress` : où vous en êtes. La spécification exige qu’il **augmente** à chaque signalement ; ne répétez jamais une valeur et ne revenez jamais en arrière.
* `total` : la quantité totale, si vous la connaissez. Optionnel.
* `message` : une ligne lisible par un humain à propos de *cette* étape. Optionnel.

`ctx` est injecté grâce à son annotation de type et le modèle ne le voit jamais : le schéma d’entrée de `import_catalog` a une seule propriété, `urls`. La page **[L’objet Context](context.md)** est entièrement consacrée à cet objet ; la progression est l’une des choses qu’il vous apporte.

## L’écouter depuis le client {#listen-for-it-from-the-client}

Le client active la fonctionnalité **appel par appel**, en passant `progress_callback=` à `call_tool` :

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

La fonction de rappel (callback) est une fonction `async` qui prend exactement ce que le serveur a signalé : `progress`, `total`, `message`.

!!! info
    `Client(mcp)` se connecte directement à l’objet serveur, en mémoire : c’est le même client que celui sur lequel repose la page **[Tests](../get-started/testing.md)**. `progress_callback` est le même paramètre quel que soit le transport qu’utilise le `Client` ; le *timing* que vous allez observer est celui de la connexion en mémoire. Elle exécute votre fonction de rappel de façon synchrone, si bien que chaque signalement arrive avant que `call_tool` ne renvoie. Sur un vrai transport, les notifications font la course avec le résultat, et une fonction de rappel lente peut encore être en cours d’exécution après le retour de `call_tool`.

### Essayer {#try-it}

Placez `client.py` à côté de `server.py` et lancez-le :

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

Chaque `await ctx.report_progress(...)` côté serveur est devenu un appel à `show` côté client, dans l’ordre, et les deux lignes se sont affichées **avant** que `call_tool` ne renvoie. La progression n’est pas empaquetée dans le résultat ; elle est diffusée pendant que l’outil travaille encore.

!!! warning
    `progress_callback` appartient à l’**appel**, pas au `Client`. Il n’existe aucun argument de constructeur pour cela, parce que des appels différents veulent des fonctions de rappel différentes : l’un pilote une barre de téléchargement, le suivant une ligne de journal.

!!! check
    Maintenant, supprimez `progress_callback=show` et relancez :

    ```text
    {'result': 'Imported 2 records.'}
    ```

    Aucune erreur, aucun avertissement, même résultat. `report_progress` **ne fait rien quand l’appelant n’a pas demandé la progression** : vous signalez donc sans condition et n’avez jamais à vous demander si quelqu’un écoute.

## Quand vous ne connaissez pas le total {#when-you-dont-know-the-total}

`total` sert quand vous connaissez le dénominateur. Souvent, ce n’est pas le cas : vous videz un flux, parcourez un curseur, téléchargez quelque chose sans en-tête de longueur.

Omettez-le :

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

La fonction de rappel reçoit `total=None`. Un client peut toujours montrer une *activité* (« 3 importés jusqu’ici… ») mais il ne peut pas afficher de pourcentage. N’inventez pas un total pour obtenir une plus jolie barre.

!!! tip
    `progress` n’a pas à compter quelque chose de précis. Octets, lignes, pages : choisissez l’unité que l’utilisateur reconnaîtrait, et ne promettez qu’un `total` que vous pouvez tenir.

## Récapitulatif {#recap}

* `await ctx.report_progress(progress, total=None, message=None)` depuis n’importe quel outil qui prend un `Context`.
* Le client passe `progress_callback=` à `call_tool` : appel par appel, jamais sur le `Client`.
* La fonction de rappel est `async (progress, total, message) -> None` et se déclenche pendant que l’outil s’exécute encore.
* Sans fonction de rappel sur l’appel, `report_progress` ne fait rien. Signalez sans condition.
* Omettez `total` quand vous ne le connaissez pas ; la fonction de rappel reçoit `None`.

La progression est ce qu’un outil en cours d’exécution montre à l’*utilisateur*. Les lignes qu’il journalise pour *vous*, la personne qui exploite le serveur, passent par un autre canal : la **[journalisation](logging.md)**.
