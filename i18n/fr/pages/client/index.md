---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# Le client {#the-client}

Un **`Client`** est le moyen par lequel un programme Python dialogue avec un serveur MCP.

C’est un seul objet avec un seul cycle de vie : vous le construisez, vous entrez dans `async with`, vous appelez des méthodes. Chaque verbe du protocole (lister les outils, en appeler un, lire une ressource, rendre un prompt) est une méthode `async` de cet objet qui renvoie un résultat typé.

## Votre premier client {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

Le serveur en haut n’est là que pour vous donner quelque chose à quoi vous connecter. Le client, ce sont les cinq lignes surlignées.

* `Client(mcp)` reçoit **l’objet serveur lui-même**. C’est le transport en mémoire : pas de sous-processus, pas de port, pas de HTTP. C’est ainsi que se connectent tous les exemples de cette page, et tous les tests que vous écrivez.
* `async with` est le **cycle de vie**. Y entrer connecte et négocie ; en sortir déconnecte. Il n’y a pas de paire `connect()` / `close()`, et un `Client` ne peut pas être réutilisé une fois le bloc terminé.
* À l’intérieur du bloc, les informations de connexion sont déjà là, sous forme de simples propriétés.

### Ce que vous pouvez passer à `Client` {#what-you-can-pass-to-client}

`Client` prend un seul argument positionnel et déduit le transport de son type :

* Une instance de `MCPServer` (ou du `Server` bas niveau) : connexion **dans le processus**.
* Une chaîne d’URL (`Client("http://localhost:8000/mcp")`) : Streamable HTTP, la voie de production.
* Un **transport** : tout ce sur quoi vous pouvez faire `async with ... as (read, write)`, comme `stdio_client(...)` qui enveloppe un sous-processus.

Tout le reste de cette page est identique pour les trois. Les en-têtes, les sous-processus, les délais d’expiration et le protocole `Transport` ont leur propre page : **[Transports côté client](transports.md)**.

### Ce que porte un client connecté {#whats-on-a-connected-client}

Quatre propriétés en lecture seule, renseignées dès que vous entrez dans le bloc :

* `client.server_info` : l’identité du serveur, ou `None` pour un serveur de génération 2026 qui n’en déclare pas (les serveurs python-sdk le font par défaut). Ici, `server_info.name` vaut `"Bookshop"` et `server_info.version` est ce que le serveur déclare.
* `client.server_capabilities` : ce que le serveur sait faire (`tools`, `resources`, `prompts`, `completions`, ...). Une capacité que le serveur n’a pas vaut `None`.
* `client.protocol_version` : la version du protocole sur laquelle les deux côtés se sont mis d’accord. Ici, c’est `"2026-07-28"`.
* `client.instructions` : la chaîne `instructions=` du serveur, ou `None` s’il n’en a pas défini.

Vous n’avez jamais choisi de version du protocole. Par défaut, le `Client` sonde le serveur et se rabat sur la poignée de main (handshake) classique avec les plus anciens, si bien qu’un seul client fonctionne avec un serveur de n’importe quelle génération. Lorsque vous avez besoin de contrôler cela, tous les détails sont dans **[Versions du protocole](../protocol-versions.md)**.

!!! tip
    `client.session` est la `ClientSession` sous-jacente, l’échappatoire bas niveau.
    Vous n’en aurez besoin pour rien sur cette page.

## Lister les outils {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` renvoie un `ListToolsResult` ; les outils sont dans `.tools`. Chacun est la définition complète qu’un hôte transmettrait à un modèle :

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

et `tool.input_schema` est le JSON Schema que le serveur a dérivé des annotations de type de la fonction :

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Ce schéma est tout ce dont une interface a besoin pour afficher un formulaire d’arguments, et tout ce dont un modèle a besoin pour produire des arguments valides.

!!! tip
    `title` est facultatif, donc une interface qui présente des outils à un humain doit choisir : le `title` s’il existe,
    le `name` sinon. `from mcp.shared.metadata_utils import get_display_name` fait exactement cela,
    pour les outils, les ressources, les modèles de ressource et les prompts.

## Appeler un outil {#calling-a-tool}

`call_tool(name, arguments)` exécute l’outil et vous renvoie un `CallToolResult`.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

Le `lookup_book` du serveur renvoie un `Book` Pydantic. Voici ce que voit le client :

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Une valeur de retour, trois choses à lire. Chacune a un consommateur différent.

### `content` : ce que lit le modèle {#content-what-the-model-reads}

`content` est une `list` de **blocs de contenu**, et un bloc de contenu est une union : `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` ou `EmbeddedResource`. Un outil peut en renvoyer plusieurs, de natures différentes.

C’est pourquoi `main` restreint le type avec `isinstance(block, TextContent)` avant de toucher à `block.text`. Remarquez qu’il n’y a pas de `.text` en dehors du `isinstance` : le vérificateur de types ne le permettrait pas, car `ImageContent` a `.data`, pas `.text`. L’union est honnête sur ce qu’un outil a le droit de vous envoyer ; votre code devrait l’être aussi.

### `structured_content` : ce que lit votre application {#structured_content-what-your-application-reads}

`structured_content` est la valeur de retour de l’outil au format JSON, conforme au `output_schema` déclaré par l’outil. Pas d’analyse de chaînes, pas de devinettes.

Quand les deux sont présents, ils disent volontairement deux fois la même chose : `content` est pour un modèle, `structured_content` pour du code. D’où vient la moitié structurée, et comment la contrôler, c’est le sujet de la page **[Sortie structurée](../servers/structured-output.md)**.

### `is_error` : si l’outil a échoué {#is_error-whether-the-tool-failed}

Un outil qui lève une exception ne lève **rien** dans votre client. Il revient sous la forme d’un résultat ordinaire avec `is_error=True`.

!!! check
    Demandez `"Solaris"` à `lookup_book` (un titre qui n’est pas au catalogue) et la fonction lève
    `ValueError`. L’appel revient pourtant normalement :

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    Le message de l’exception a atterri dans `content`, où le **modèle** peut le lire et réessayer. C’est
    délibéré : une erreur d’outil fait partie de la conversation, ce n’est pas un plantage. Regardez toujours `is_error`
    avant de faire confiance à `structured_content`.

!!! warning
    `is_error=True` couvre plus que vos propres `raise`. Demandez un outil que le serveur n’a même pas
    (`call_tool("does_not_exist", {})`) et rien n’est levé. Vous obtenez la même forme en retour :
    `is_error=True` avec `Unknown tool: does_not_exist` dans `content`. Une méthode de `Client` ne lève
    `MCPError` que lorsque le serveur répond par une **erreur** JSON-RPC au lieu d’un résultat, et
    **[Gérer les erreurs](../servers/handling-errors.md)** explique quand un serveur produit l’une ou l’autre.

## Ressources {#resources}

Les verbes des ressources vont par paires : deux façons de lister, une façon de lire.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` renvoie les ressources **concrètes**, celles qui ont un URI fixe. Ici : `['catalog://genres']`.
* `list_resource_templates()` renvoie les ressources **paramétrées**. Ici : `['catalog://genres/{genre}']`. Ce sont deux listes distinctes parce qu’un modèle n’est pas lisible tant que vous ne l’avez pas rempli.
* `read_resource(uri)` prend un URI sous forme de simple `str` et fonctionne sur les deux : passez `"catalog://genres/poetry"` et le serveur le fait correspondre au modèle.

`read_resource` renvoie `contents`, une liste de `TextResourceContents` ou de `BlobResourceContents`. Même idée que pour le contenu des outils : restreignez le type avec `isinstance`, puis lisez `.text` (ou `.blob`).

Un client peut aussi être prévenu quand une ressource change. Sur les connexions de génération 2025, c’est `subscribe_resource(uri)` / `unsubscribe_resource(uri)` — une paire de méthodes que `MCPServer` n’implémente pas, si bien que sur la liaison en version 2026-07-28 (où ces verbes n’existent plus) la requête reçoit en réponse `-32601`, *Method not found*. Le remplaçant en version 2026 est un flux `subscriptions/listen`, que `MCPServer` sert *bel et bien* — `server_capabilities.resources.subscribe` y vaut `True` — et sa consommation avec `client.listen(...)` fait l’objet de la page **[Abonnements](subscriptions.md)** de cette section.

## Prompts {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` vous dit ce que le serveur propose et ce dont chaque prompt a besoin :

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` le rend. Le dictionnaire d’arguments est `str -> str` : les arguments de prompt sont toujours des chaînes. Le résultat est `messages`, une liste de `PromptMessage`, chacun avec un `role` et un bloc `content` :

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Un hôte transmet ces messages tels quels au modèle. C’est toute la fonctionnalité.

## Complétions {#completions}

Un serveur doté d’un gestionnaire (handler) de complétion peut compléter automatiquement les arguments des prompts et des modèles de ressource au fil de la saisie de l’utilisateur.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` indique *quel* prompt ou modèle vous remplissez : un `PromptReference` ou un `ResourceTemplateReference`.
* `argument` vaut `{"name": ..., "value": ...}` : l’argument et ce que l’utilisateur a saisi jusqu’ici.

La réponse se trouve dans `result.completion.values`. Tapez `"p"` et le serveur revient avec `['poetry']`. Le côté serveur, et la façon dont un gestionnaire utilise les *autres* arguments déjà remplis pour affiner ses suggestions, c’est la page **[Complétions](../servers/completions.md)**.

## Pagination {#pagination}

Chaque méthode `list_*` accepte un argument nommé `cursor=` et chaque résultat porte un `next_cursor`. Quand `next_cursor` vaut `None`, vous avez tout.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Cette boucle est correcte face à n’importe quel serveur. `MCPServer` renvoie tout en une seule page, donc `next_cursor` vaut `None` et la boucle s’exécute une fois, ce qui explique que la plupart du code ne l’écrive jamais. Les serveurs qui paginent réellement, et les règles auxquelles obéissent les curseurs, sont dans **[Pagination](../advanced/pagination.md)**.

## Dans les tests {#in-tests}

`Client(mcp)`, sans processus ni port, est déjà un banc de test pour votre serveur.

Il existe un drapeau du constructeur conçu pour cela : `Client(mcp, raise_exceptions=True)`. Il n’a d’effet que sur les connexions en mémoire, et **[Tests](../get-started/testing.md)** est la page qui l’explique et construit tout le modèle autour de lui.

## Récapitulatif {#recap}

* `Client(x)` se connecte en mémoire à un objet serveur, en Streamable HTTP à une chaîne d’URL, et à tout le reste via un transport.
* `async with` est tout le cycle de vie. À l’intérieur, `server_capabilities` et `protocol_version` sont déjà renseignés ; `server_info` et `instructions` le sont aussi lorsque le serveur les fournit.
* `list_tools()` vous donne le `name`, le `title`, la `description` et le `input_schema` de chaque outil.
* `call_tool()` renvoie `content` pour le modèle, `structured_content` pour votre code, et `is_error`. Un outil qui lève une exception est un résultat, pas une exception.
* `content` est une union de types de blocs ; restreignez le type avec `isinstance` avant de lire.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` et `complete` complètent la liste des verbes.
* Chaque `list_*` accepte `cursor=` ; bouclez jusqu’à ce que `next_cursor` vaille `None`.

Ce qu’un serveur peut demander au *client*, et la façon d’y répondre, c’est **[Fonctions de rappel du client](callbacks.md)**.
