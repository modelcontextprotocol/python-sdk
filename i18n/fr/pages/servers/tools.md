---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# Outils {#tools}

Un **outil** (tool) est une fonction que le modèle peut appeler.

Vous en déclarez un en posant `@mcp.tool()` sur une simple fonction Python. C’est toute l’API.

## Votre premier outil {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

Regardez ce que vous avez écrit. Pas de schémas, pas de JSON, pas de protocole : juste une fonction. Le SDK en lit trois choses :

* Le **nom** de l’outil est le nom de la fonction : `search_books`.
* La **description** que voit le modèle est la docstring : `Search the catalog by title or author.`
* Les **arguments** que le modèle a le droit de passer proviennent des annotations de type : `query: str` et `limit: int`.

### Le schéma d’entrée {#the-input-schema}

À partir de ces annotations de type, le SDK génère un JSON Schema et l’envoie au client lors de `tools/list` :

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

Les deux arguments figurent dans `required` parce qu’aucun n’a de valeur par défaut. Vous allez corriger cela dans un instant. (Les clés `title` sont des artefacts de Pydantic ; les propriétés, leurs types et `required` constituent le contrat.)

!!! tip
    Ici, les annotations de type ne sont pas de la documentation. Elles sont **le contrat**. Si un client envoie `"limit": "ten"`,
    le SDK le rejette avant même que votre fonction ne s’exécute.

### Ce que le modèle reçoit en retour {#what-the-model-gets-back}

Appelez l’outil avec `{"query": "dune", "limit": 5}` et le résultat comporte deux parties :

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` est le texte que lit le **modèle**. `structured_content` contient des données typées destinées à l’**application cliente**. Elles sont là parce que vous avez déclaré le type de retour `-> str`.

Ne vous souciez pas encore de `structured_content`. Renvoyez de vrais objets Python depuis vos outils et tout se passe comme il faut ; la page **[Sortie structurée](structured-output.md)** y est entièrement consacrée.

### Essayer {#try-it}

Lancez le serveur avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Ouvrez l’URL qu’il affiche, allez dans l’onglet **Tools** et appelez `search_books`.

L’Inspector affiche un formulaire avec un champ texte `query` obligatoire et un champ numérique `limit` obligatoire. Il a construit ce formulaire à partir de vos annotations de type. Tous les autres clients MCP feront de même.

## Arguments optionnels {#optional-arguments}

Donnez une valeur par défaut à un paramètre et il cesse d’être obligatoire. C’est tout. C’est du Python, tout simplement.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

Le schéma suit :

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

`limit` a quitté `required` et a gagné `"default": 10`. Un client qui l’omet obtient `10`, exactement comme en Python.

## Des schémas plus riches avec `Field` {#richer-schemas-with-field}

Les annotations de type vous mènent loin, mais vous voulez parfois *décrire* un argument, ou le contraindre.

Enveloppez le type dans `Annotated` et ajoutez un `Field` Pydantic :

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

Trois nouveautés, toutes sur les paramètres :

* `Field(description=...)` : une description par argument, que le modèle lit en plus de la docstring.
* `Field(ge=1, le=50)` : des bornes numériques. Elles arrivent dans le schéma sous la forme `"minimum": 1, "maximum": 50`.
* `Literal["fiction", "non-fiction", "poetry"]` : une énumération. Le modèle ne peut choisir que l’une de ces valeurs.

!!! check
    Les contraintes ne sont pas décoratives. Appelez l’outil avec `limit=999` et le SDK répond par une
    erreur d’outil **avant que votre fonction ne s’exécute** :

    ```text
    Input should be less than or equal to 50
    ```

    Cette erreur revient au modèle comme résultat de l’outil ; le modèle la lit et réessaie avec
    une valeur valide. Vous avez écrit `le=50` une seule fois et obtenu, sans rien de plus, des agents qui se corrigent d’eux-mêmes.

!!! info
    Si vous avez utilisé FastAPI ou Pydantic, vous connaissez déjà tout cela. C’est le même `Field`,
    le même `Annotated`, la même validation. Il n’y a rien de propre à MCP à apprendre ici.

## Un modèle comme paramètre {#a-model-as-a-parameter}

Quand un outil prend plus de deux ou trois arguments, regroupez-les dans un modèle Pydantic :

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

Le schéma de `Book` est imbriqué dans le schéma d’entrée de l’outil (sous forme de référence `$defs`), le modèle le remplit comme un objet JSON, et votre fonction reçoit une **véritable instance de `Book`**, déjà validée, avec les attributs `.title`, `.author` et `.year`.

Vous pouvez combiner librement : des paramètres simples à côté de paramètres modèles, des modèles imbriqués, des listes de modèles. C’est du Pydantic de bout en bout.

## `async def` {#async-def}

Si un outil fait des E/S (appelle une API, lit un fichier, interroge une base de données), déclarez-le en `async def` et utilisez `await` à l’intérieur. Le SDK se charge de l’attendre.

Un outil en simple `def` fonctionne aussi : le SDK l’exécute dans un thread, si bien qu’il ne bloque jamais le serveur.

Il n’y a rien d’autre à configurer.

## Noms, titres et annotations {#names-titles-and-annotations}

Tout ce que le SDK déduit, vous pouvez le redéfinir dans le décorateur :

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` est un nom lisible par un humain, destiné aux interfaces. Les clients affichent *« Search the catalog »* au lieu de `search_books`.
* `annotations` regroupe des **indications** de comportement destinées au client :
  * `read_only_hint=True` : cet outil ne modifie rien.
  * `open_world_hint=False` : il opère sur un ensemble fermé de choses (ce catalogue), pas sur le web ouvert.
  * Les deux autres, `destructive_hint` et `idempotent_hint`, décrivent un outil qui *écrit* : peut-il
    supprimer quelque chose, et l’appeler deux fois revient-il au même que l’appeler une fois ? La spécification ne les définit
    que pour les outils qui ne sont pas en lecture seule ; elles ne diraient donc rien sur `search_books`.

Un client bien conçu s’en sert pour trancher des questions comme *« dois-je demander à l’utilisateur avant d’exécuter ceci ? »*. Ce sont des indications, pas de la sécurité. Ne comptez jamais sur un client pour les respecter.

!!! tip
    `name=` et `description=` sont également acceptés par `@mcp.tool()` si vous ne voulez pas les dériver
    du nom de la fonction et de la docstring. La plupart du temps, c’est ce que vous voulez.

## Récapitulatif {#recap}

* `@mcp.tool()` sur une fonction en fait un outil. Le nom vient de la fonction, la description de la docstring.
* Les annotations de type **sont** le schéma d’entrée. Les valeurs par défaut rendent les arguments optionnels.
* `Annotated[..., Field(...)]` ajoute descriptions et contraintes ; `Literal` ajoute les énumérations.
* Un paramètre modèle Pydantic est la façon de recevoir un « corps » structuré.
* Les arguments invalides sont rejetés pour vous, avec une erreur que le modèle peut lire et dont il peut se remettre.
* `async def` pour les E/S, `def` tout court pour tout le reste.

**[Sortie structurée](structured-output.md)** explique ce qu’il advient de la valeur que vous renvoyez avec `return`.
