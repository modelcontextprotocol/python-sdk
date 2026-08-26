---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# L’objet Context {#the-context}

Les arguments d’un outil viennent du modèle. Tout le reste (la requête que vous servez, le serveur dans lequel vous vivez, un moyen de répondre au client) vient d’un seul objet : le **`Context`**.

Vous ne le construisez pas, vous ne le configurez pas. Vous le demandez.

## Le demander {#ask-for-it}

Ajoutez un paramètre annoté avec `Context` à n’importe quel outil :

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* Le SDK construit un `Context` neuf pour chaque requête et vous le passe.
* Le **nom du paramètre n’a aucune importance**. `ctx`, `context`, `c` : le SDK le trouve grâce à son annotation.
* Les ressources et les prompts peuvent en déclarer un aussi, de la même façon.
* `ctx.request_id` est l’identifiant de la requête que votre fonction est en train de servir.

!!! info
    Si vous avez utilisé FastAPI, vous connaissez le procédé : vous déclarez un paramètre avec le type propre au framework
    (`Request` là-bas, `Context` ici) et le framework le fournit. Rien à enregistrer, rien à
    configurer : l’annotation de type est tout le mécanisme.

### Invisible pour le modèle {#invisible-to-the-model}

C’est le point à bien intégrer. Voici le schéma d’entrée que `tools/list` renvoie pour `search_books` :

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Une seule propriété. `ctx` n’est pas un argument : il n’apparaît jamais dans le schéma, le modèle n’en entend jamais parler et aucun client ne peut le remplir. C’est un contrat entre vous et le SDK, invisible sur la liaison.

### Essayer {#try-it}

Lancez le serveur avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Le formulaire de `search_books` n’a qu’un seul champ, `query`. Appelez-le avec `dune` :

```text
[request 3] Found 3 books matching 'dune'.
```

Le numéro est celui de la requête en question, quelle qu’elle soit. Appelez de nouveau l’outil et il change : chaque requête reçoit son propre `Context`.

## Ce qu’il vous apporte {#what-it-gives-you}

L’objet injecté est petit. En plus de `request_id` :

* `await ctx.read_resource(uri)` : lire l’une des **propres** ressources du serveur depuis un outil. C’est la section suivante.
* `await ctx.report_progress(progress, total, message)` : remonter la progression à l’appelant pendant un appel long. Tous les détails sont dans **[Progression](progress.md)**.
* `await ctx.elicit(message, schema)` et `await ctx.elicit_url(...)` : mettre l’outil en pause et poser une question à l’utilisateur. C’est **[l’élicitation (elicitation)](elicitation.md)**.
* `ctx.session` : le côté serveur de la conversation avec ce client. Les notifications que vous envoyez au client passent par là ; la dernière section s’en sert.
* `ctx.headers` : les en-têtes de requête acheminés par le transport, ou `None` en stdio. Lisez un en-tête personnalisé avec `(ctx.headers or {}).get("x-...")`. Les en-têtes sont des données fournies par le client — très bien pour une langue ou un feature flag, jamais pour une identité.
* `ctx.request_context` : l’enregistrement brut propre à la requête. Le champ que vous irez chercher est `lifespan_context`, l’objet que votre code de démarrage a produit avec yield (voir **[Cycle de vie (lifespan)](lifespan.md)**).

La journalisation est volontairement absente de cette liste. Un serveur journalise avec le module `logging` de Python, comme n’importe quel autre programme Python. **[Journalisation](logging.md)** est la courte page qui explique pourquoi.

!!! tip
    L’injection n’a lieu que pour la fonction que vous avez enregistrée. Une fonction auxiliaire appelée par votre outil ne reçoit pas
    son propre `Context` ; passez-lui `ctx` comme un argument ordinaire. Il n’existe aucun
    « contexte courant » ambiant à récupérer ailleurs.

## Lire vos propres ressources {#read-your-own-resources}

Les ressources d’un serveur ne sont pas réservées aux clients. Un outil peut les lire aussi :

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` résout l’URI via le même registre que celui qui sert `resources/read`, si bien qu’un outil obtient ce qu’un client obtiendrait : un itérable de `ReadResourceContents`, un par bloc de contenu. Pour cet URI, il y en a un :

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` est exactement ce que `genres()` a renvoyé. Une seule source de vérité : le client parcourt la ressource, vos outils la consomment, personne ne copie la chaîne.
* Le seul paramètre de `describe_catalog` est le `Context`, donc son schéma d’entrée n’a **aucune propriété**. Le modèle l’appelle avec `{}`.

## Signaler au client que la liste a changé {#tell-the-client-the-list-changed}

Ce qu’un serveur propose n’est pas figé au moment de l’import. Enregistrez un outil à l’exécution, puis prévenez le client :

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` enregistre une simple fonction comme outil : nom, description et schéma dérivés exactement comme `@mcp.tool()` l’aurait fait.
* `await ctx.session.send_tool_list_changed()` envoie `notifications/tools/list_changed`. Un client qui la reçoit appelle de nouveau `tools/list` et voit `recommend_book`.

Les méthodes sœurs sont `send_resource_list_changed()`, `send_prompt_list_changed()` et `send_resource_updated(uri)` pour un changement sur une ressource précise.

Sur une connexion 2026-07-28, les clients ne reçoivent les notifications de changement que sur un flux `subscriptions/listen` qu’ils ont ouvert ; les méthodes `send_*` ci-dessus n’atteignent donc pas ces flux. Les méthodes de publication du `Context` diffusent vers tous les flux abonnés d’un coup : `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()` et `await ctx.notify_resource_updated(uri)`. Tous les détails, y compris la montée en charge sur plusieurs réplicas, sont dans **[Abonnements](subscriptions.md)**.

!!! check
    Avant que quelqu’un n’exécute `enable_recommendations`, l’outil que vous promettez n’existe pas. Appelez-le
    quand même et le résultat est une erreur que le modèle peut lire :

    ```text
    Unknown tool: recommend_book
    ```

    Exécutez `enable_recommendations`, et le même appel réussit. La liste d’outils est réellement
    dynamique : `tools/list` reflète ce qui est enregistré *à l’instant même*.

## Récapitulatif {#recap}

* Annotez un paramètre avec `Context` (dans un outil, une ressource ou un prompt) et le SDK l’injecte. Le nom vous appartient.
* Il est invisible pour le modèle : le schéma d’entrée ne contient jamais que vos vrais arguments.
* `ctx.request_id` identifie la requête ; `ctx.request_context.lifespan_context` est ce que votre démarrage a produit avec yield.
* `await ctx.read_resource(uri)` permet à un outil de lire les propres ressources du serveur.
* `ctx.session` est le canal de retour vers le client : `send_tool_list_changed()` et ses sœurs lui demandent de récupérer à nouveau une liste que vous avez modifiée.
* Le rapport de progression et l’élicitation partent eux aussi du `Context` ; chacun a sa propre page.

Les paramètres que le modèle ne voit jamais, remplis par vos propres fonctions, sont les **[Dépendances](dependencies.md)**.
