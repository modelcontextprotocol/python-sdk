---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# Paramètres d’en-tête {#header-parameters}

La plupart des serveurs n’en ont jamais besoin.

Une passerelle ou un répartiteur de charge placé devant votre serveur ne peut router que d’après ce qu’il lit sans analyser le corps. Marquez un argument d’outil avec `x-mcp-header`, et les clients en **[version du protocole](../protocol-versions.md)** `2026-07-28` envoient aussi sa valeur sous forme d’en-tête HTTP.

## Marquer un argument {#mark-an-argument}

La marque est une clé supplémentaire dans le schéma JSON de l’argument. Avec `MCPServer`, c’est `Field` qui l’y place :

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* Sur Streamable HTTP en version `2026-07-28`, un client envoie `Mcp-Param-Region` en plus du corps, et le serveur rejette tout appel où les deux ne concordent pas.
* Un client qui n’a pas listé l’outil n’a jamais vu la marque : il n’envoie aucun en-tête, et l’appel est rejeté. Le `Client` de ce SDK liste alors les outils et renvoie l’appel une seule fois ; lister d’abord ne fait donc qu’économiser un aller-retour.
* Toutes les autres connexions ignorent l’annotation.

Votre fonction ne change pas : `region` arrive toujours sous forme d’argument.

## Ce qui peut être marqué {#what-can-be-marked}

Les arguments `str`, `int` et `bool`. Tout le reste est refusé à l’enregistrement de l’outil, avec `InvalidSignature`.

Cela vaut aussi pour `str | None`, qui n’a pas de type unique. Pour un argument facultatif, il faut écrire son schéma explicitement, avec `WithJsonSchema` de Pydantic :

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## Avec le `Server` de bas niveau {#on-the-low-level-server}

Là, vous écrivez `input_schema` à la main ; la clé s’y place donc directement :

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* Rien ne vérifie l’annotation à votre place : une annotation invalide est servie telle quelle, et les clients en version `2026-07-28` omettent l’outil de leur liste.

### Schémas par nom {#schemas-by-name}

Pour vérifier l’en-tête, le SDK a besoin du schéma d’entrée de l’outil avant d’acheminer l’appel. Sans `get_tool_input_schema`, il l’obtient en exécutant votre gestionnaire `on_list_tools` à chaque appel comportant des arguments, qu’un outil soit marqué ou non.

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* Passez cette fonction pour répondre à partir de ce que vous avez déjà.
* Renvoyez `None` pour un outil qui n’a rien à vérifier.

## Récapitulatif {#recap}

* `x-mcp-header` sur un argument d’outil amène les clients en version `2026-07-28` à le répéter dans un en-tête HTTP `Mcp-Param-*`.
* Le serveur rejette tout appel dont l’en-tête et le corps ne concordent pas.
* Seuls les arguments `str`, `int` et `bool` peuvent être marqués. `MCPServer` lève `InvalidSignature` pour tout le reste.
* Le `Server` de bas niveau ne vérifie rien, et les clients écartent tout outil dont l’annotation est invalide.
* `get_tool_input_schema` évite au `Server` de bas niveau d’exécuter `on_list_tools` à chaque appel.

Le reste de l’API du `Server` écrit à la main est décrit dans **[Le Server de bas niveau](low-level-server.md)**.
