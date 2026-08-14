---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# Pagination {#pagination}

La plupart des serveurs n’en ont jamais besoin.

`MCPServer` répond à chaque requête `list_*` avec tout ce qu’il a, en une seule page, `next_cursor=None`. Pour quelques dizaines d’outils, de ressources ou de prompts, c’est la bonne réponse et il n’y a rien à configurer.

La pagination sert au serveur dont la liste de ressources est en réalité une base de données : des milliers de lignes qu’il refuse de sérialiser en une seule réponse. La réponse du protocole est un **curseur** : le serveur renvoie une page accompagnée d’un jeton opaque, et le client renvoie ce jeton pour obtenir la page suivante.

`@mcp.resource()` n’offre aucun point d’accroche pour cela. Pour paginer, vous écrivez vous-même le gestionnaire (handler) de liste, sur le **[Server de bas niveau](low-level-server.md)**.

## Un serveur qui pagine {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* Sur un `Server` de bas niveau, les gestionnaires sont des arguments du constructeur, pas des décorateurs. `on_list_resources` répond à chaque requête `resources/list` ; c’est tout le branchement nécessaire.
* Chaque gestionnaire paginé est typé `params: PaginatedRequestParams | None`, et l’exemple accepte les deux. Sur une connexion, cependant, le SDK ne vous passe jamais `None` (une requête sans membre `params` arrive au gestionnaire sous la forme du modèle avec ses valeurs par défaut), donc le signal qui compte est `params.cursor is None` : **commencer par le début**.
* C’est vous qui décidez ce qu’*est* un curseur. Ici, c’est un décalage (offset) rendu sous forme de chaîne. Un horodatage, une clé primaire, un blob base64 : tout ce que vous pouvez émettre à l’aller et reconnaître au retour.
* `next_cursor=None` est votre façon de dire « c’était la dernière page ». Il n’y a ni décompte, ni total, ni `has_more`. `None` est le signal à lui seul.

!!! tip
    Une valeur de `PAGE_SIZE` de 10 rend l’exemple lisible. Choisissez la vôtre par point de terminaison : une liste de
    ressources d’une ligne peut se permettre une page de 500 ; une liste de gros modèles de prompts, non.
    Le client n’a pas son mot à dire, et c’est voulu.

### Essayer {#try-it}

`Client(server)` se connecte à un `Server` de bas niveau en mémoire exactement comme il se connecte à un `MCPServer`.

Appelez `list_resources()` sans argument. Vous obtenez dix ressources, de `book-1` à `book-10`, et `next_cursor` vaut la chaîne `"10"`.

Renvoyez-la avec `list_resources(cursor="10")` : la première ressource est `book-11`, le nouveau `next_cursor` vaut `"20"`.

La dixième page revient avec `next_cursor` à `None`. Terminé.

## La boucle côté client {#the-client-loop}

Chaque méthode `list_*` de `Client` (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) accepte un argument nommé `cursor=`. Vider une liste paginée tient en un `while True` :

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` démarre à `None`, donc la première requête ne porte aucun curseur.
* Étendez la liste **avant** de regarder `next_cursor` : la dernière page contient elle aussi des ressources.
* `next_cursor is None` est la sortie. Toute autre valeur repart directement dans `cursor=`, telle quelle.

Lancez son `main()` et il affiche `100 resources` : dix pages de dix, assemblées par une boucle qui n’a jamais su qu’il y avait dix pages.

C’est la même boucle que montre **[Le client](../client/index.md)** pour chaque verbe `list_*`, et elle ne coûte rien face à un serveur qui ne pagine pas : `next_cursor` vaut `None` dès la première réponse et la boucle s’exécute une seule fois.

## Les trois règles {#the-three-rules}

**Les curseurs sont opaques.** Un client ne doit jamais en analyser, en construire ni en deviner un. La seule source légitime d’un curseur est le `next_cursor` de la page précédente, tel quel.

**Le serveur choisit la taille de page.** Il n’y a pas de `limit=` dans le protocole. S’il vous faut une autre taille de page, vous modifiez le serveur.

**Un client qui ignore la pagination fonctionne quand même.** Il appelle `list_resources()` une fois, obtient les dix premières, et ne remarque jamais le `next_cursor` qu’il a jeté. Rien ne casse ; il en voit moins.

!!! check
    Opaque veut dire opaque. Inventez un curseur (`list_resources(cursor="page-2")`) et le
    protocole ne peut rien pour vous. Ce serveur tente `int("page-2")`, le gestionnaire lève une exception,
    et ce qui revient au client est :

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    Un curseur que vous n’avez pas obtenu du serveur est un bogue, pas une demande de fonctionnalité.

## Récapitulatif {#recap}

* `MCPServer` renvoie tout en une seule page. La pagination est facultative, et vous l’activez sur le `Server` de bas niveau.
* `on_list_resources` (ainsi que `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) reçoit `PaginatedRequestParams | None` ; `params.cursor` vaut `None` pour la première page.
* Vous renvoyez une page plus un `next_cursor` : n’importe quelle chaîne que vous reconnaîtrez plus tard, ou `None` quand il ne reste rien.
* La boucle côté client : passez `cursor=`, accumulez, répétez jusqu’à ce que `next_cursor is None`.
* Les curseurs sont opaques, la taille de page appartient au serveur, et un client qui ne pagine pas obtient quand même la première page.

Le reste de l’API `Server` écrite à la main (`on_call_tool`, les dicts `input_schema`, `_meta`) se trouve dans **[Le Server de bas niveau](low-level-server.md)**.
