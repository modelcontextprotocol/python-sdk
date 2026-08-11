---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Cycle de vie {#lifespan}

La plupart des vrais serveurs conservent quelque chose pendant toute leur durée de vie : un pool de connexions à la base de données, un client HTTP, un modèle chargé en mémoire.

Vous ne voulez pas le reconstruire à chaque appel, et vous voulez le fermer proprement. C’est à cela que sert le **cycle de vie** (lifespan).

## Un cycle de vie typé {#a-typed-lifespan}

Un cycle de vie est un `@asynccontextmanager` qui reçoit le serveur et produit avec `yield` **un seul objet**. Ce que vous produisez ainsi reste accessible à chaque gestionnaire (handler) aussi longtemps que le serveur tourne.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

Lisez-le de bas en haut :

* `app_lifespan` connecte la `Database` **avant** le `yield` et la déconnecte **après**, dans un `finally`. C’est le démarrage et l’arrêt.
* Il produit un `AppContext`, une simple dataclass qui contient ce que vous avez initialisé. Un champ aujourd’hui, dix demain.
* `MCPServer("Bookshop", lifespan=app_lifespan)` est tout le câblage nécessaire.
* Dans l’outil, l’objet produit est `ctx.request_context.lifespan_context`.

Le cycle de vie s’exécute **une seule fois**. On y entre au démarrage du serveur (avant la première requête) et on en sort à l’arrêt du serveur. Toutes les requêtes entre les deux partagent le même `AppContext`.

!!! info
    Si vous avez déjà écrit un `lifespan` FastAPI, vous connaissez déjà tout cela. Même décorateur, même `yield`, même `finally`.

### Ce que voit le modèle {#what-the-model-sees}

Rien de nouveau. `ctx` est un paramètre **Context** : le SDK l’injecte et il n’atteint jamais le schéma d’entrée :

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` est le seul argument que le modèle peut passer. Le cycle de vie, c’est l’affaire de votre serveur.

Les fonctions `@mcp.resource()` et `@mcp.prompt()` peuvent elles aussi prendre un paramètre `ctx`, annoté d’un simple `Context` pour une raison que la section suivante explique. Tout ce que transporte `ctx` est décrit dans **[L’objet Context](context.md)**.

### C’est réellement typé {#it-really-is-typed}

Regardez de nouveau l’annotation : `ctx: Context[AppContext]`.

Ce seul paramètre de type est la raison pour laquelle `ctx.request_context.lifespan_context` **est** un `AppContext` pour votre vérificateur de types. `.db` s’autocomplète ; `.dbb` est une erreur avant même que vous n’ayez lancé le serveur.

Écrivez un simple `Context` à la place et `lifespan_context` est typé `dict[str, Any]` : le vérificateur de types n’a aucun moyen de savoir ce que votre cycle de vie a produit. L’objet est toujours là à l’exécution ; vous avez perdu l’assistance.

!!! warning
    `Context[AppContext]` est une écriture **réservée aux outils**. Mettez-la sur une fonction
    `@mcp.resource()` ou `@mcp.prompt()` et chaque appel à ce gestionnaire échoue. Le client
    reçoit une erreur en retour, et le journal du serveur montre pourquoi :

    ```text
    Context is not available outside of a request
    ```

    Dans les ressources et les prompts, écrivez simplement `ctx: Context`. L’objet produit par
    votre cycle de vie reste `ctx.request_context.lifespan_context` à l’exécution ; vous renoncez
    au paramètre de type, pas à l’objet.

!!! tip
    Il y a toujours un cycle de vie. Si vous n’en passez pas, celui par défaut du SDK produit un
    `dict` vide, si bien que `ctx.request_context.lifespan_context` vaut `{}`, jamais `None`.
    Cette valeur par défaut explique aussi pourquoi un simple `Context` le type `dict[str, Any]`.

## Le voir se produire {#watch-it-happen}

« Le démarrage s’exécute avant la première requête » est le genre de phrase que vous ne devriez pas avoir à croire sur parole.

Réduisez le serveur à son cycle de vie : donnez à `Database` un indicateur `connected`, basculez-le dans `connect()` et `disconnect()`, et ajoutez un outil qui en rend compte.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` est défini au niveau du module pour une seule raison : pouvoir l’observer depuis *l’extérieur* du serveur.

!!! check
    Trois moments, trois valeurs :

    * Avant le démarrage du serveur, `database.connected` vaut `False`. Importer le module n’a rien connecté.
    * Pendant qu’il tourne, appelez `database_status` et le résultat est `"connected"`.
    * Arrêtez le serveur et le bloc `finally` s’exécute : `database.connected` vaut de nouveau `False`.

    Le travail s’est fait exactement là où vous l’avez placé : autour du `yield`, pas à l’import et pas à chaque requête.

## Récapitulatif {#recap}

* `lifespan=` prend un `@asynccontextmanager` qui reçoit le serveur et produit avec `yield` un seul objet.
* Le code avant le `yield` est le démarrage. Le `finally` qui suit est l’arrêt.
* Il s’exécute une seule fois, autour de toute la vie du serveur, pas à chaque requête.
* Ce que vous produisez avec `yield` est `ctx.request_context.lifespan_context` dans chaque outil, ressource et prompt.
* `ctx: Context[AppContext]` rend cet accès entièrement typé dans les outils. Les ressources et les prompts prennent le simple `Context`.
* Pas de `lifespan=` signifie un `dict` vide, jamais `None`.

Un gestionnaire qui s’interrompt en plein appel pour demander à l’utilisateur quelque chose que lui seul connaît, c’est l’**[Élicitation](elicitation.md)**.
