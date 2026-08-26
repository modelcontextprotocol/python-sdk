---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# Ressources {#resources}

Une **ressource** (resource), ce sont des données que vous exposez pour que l’application les lise.

C’est là la ligne de partage. Un outil est quelque chose que le **modèle** décide d’appeler. Une ressource est quelque chose que l’**application** décide de charger (un fichier de configuration, un enregistrement, un document) et de placer devant le modèle comme contexte.

Vous en déclarez une en posant `@mcp.resource(uri)` sur une simple fonction Python.

## Votre première ressource {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

C’est la même forme qu’un outil, avec une chose en plus : l’**URI**. Les ressources ont une adresse, pas un nom. Un client demande `config://app`, jamais `get_config`.

Le SDK lit tout de même le reste à partir de la fonction :

* Le **nom** est le nom de la fonction : `get_config`.
* La **description** que voit le client est la docstring.
* Le **contenu** est ce que vous renvoyez.

Lors de `resources/list`, le client reçoit ceci :

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

Et lorsqu’il lit `config://app`, votre fonction s’exécute et la valeur de retour revient sous forme de texte :

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    Lister ne coûte rien. Votre fonction n’est **pas** appelée lors de `resources/list`, seulement lors
    de `resources/read`, et uniquement pour l’URI demandé. Exposez un millier de ressources
    et vous ne payez que pour celles que quelqu’un ouvre.

### Essayer {#try-it}

Lancez le serveur avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Ouvrez l’URL qu’il affiche et allez dans l’onglet **Resources**. `config://app` figure dans la liste avec sa description. Cliquez dessus et l’Inspector la lit : voilà vos deux lignes de configuration.

## Modèles de ressources {#resource-templates}

Un URI par enregistrement, cela ne passe pas à l’échelle. Mettez un **paramètre de substitution** (placeholder) dans l’URI et un paramètre correspondant sur la fonction :

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

`{user_id}` dans l’URI, `user_id: str` sur la fonction. C’est tout le contrat.

Il s’agit désormais d’un **modèle de ressource** (resource template), et il déménage : il quitte `resources/list` et apparaît à la place dans `resources/templates/list`, sous forme de motif plutôt que d’adresse :

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

Le client remplit le paramètre de substitution et lit un URI concret : `users://42/profile`, `users://ada/profile`. Une seule fonction répond à tous, et reçoit la valeur extraite dans `user_id` :

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

Remarquez le champ `uri` dans le résultat. C’est l’URI **concret** demandé par le client, pas le modèle.

!!! check
    Les paramètres de substitution et les paramètres de la fonction doivent concorder. Renommez le
    paramètre de la fonction en `user` alors que l’URI dit toujours `{user_id}`, et le décorateur refuse
    **dès l’import**, avant qu’aucun client ne s’en approche :

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    Une discordance ne peut être qu’un bug ; le SDK rend donc impossible le démarrage du serveur avec une telle erreur.

La syntaxe des paramètres de substitution est celle de la [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) : `{+path}` pour les valeurs sur plusieurs segments, `{?q,lang}` pour les paramètres de requête optionnels, et bien d’autres. Par défaut, le SDK applique aussi des vérifications de sécurité des chemins aux valeurs extraites. Consultez **[Modèles d’URI et sécurité des chemins](uri-templates.md)** pour la référence complète.

`get_user_profile` peut également prendre un paramètre annoté `Context`. Le SDK l’injecte sans jamais le traiter comme un paramètre d’URI, et la page **[L’objet Context](../handlers/context.md)** décrit ce qu’il vous apporte.

## Ce que vous renvoyez {#what-you-return}

Vous n’êtes pas limité à `str`. Donnez à chaque ressource un `mime_type` et renvoyez ce qui convient :

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` renvoie une `str`, elle est donc envoyée telle quelle. C’est le cas courant.
* `catalog_stats` renvoie un `dict`, le SDK le sérialise donc pour vous en **texte JSON** :

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` renvoie des `bytes`, le client reçoit donc un `BlobResourceContents` au lieu d’un `TextResourceContents`, avec vos octets encodés en base64 dans son champ `blob`.

La même règle vaut pour tout ce qui est sérialisable en JSON : une liste, un modèle Pydantic, une dataclass. Si ce n’est ni une `str` ni des `bytes`, cela devient du JSON.

C’est à vous de déclarer `mime_type`, et sa valeur par défaut est `text/plain`. Le SDK n’inspecte jamais ce que vous renvoyez pour le deviner : une ressource `dict` que vous n’étiquetez pas est donc toujours annoncée comme du texte brut.

!!! tip
    `@mcp.resource()` accepte aussi `name=`, `title=` et `description=` lorsque vous ne souhaitez
    pas les dériver de la fonction. Et lorsqu’il n’y a aucune fonction à écrire,
    `mcp.server.mcpserver.resources` propose des classes `Resource` prêtes à l’emploi (`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`) que vous enregistrez
    avec `mcp.add_resource(...)`.

Un client peut aussi **s’abonner** à une ressource et être notifié lorsqu’elle change ; c’est la moitié de l’histoire côté client, et elle se trouve dans **[Le client](../client/index.md)**.

## Récapitulatif {#recap}

* `@mcp.resource(uri)` sur une fonction en fait une ressource. L’URI est l’adresse, la valeur de retour est le contenu, la docstring est la description.
* Un `{placeholder}` dans l’URI en fait un **modèle** : il est listé sous `resources/templates/list` et une seule fonction sert tous les URI qui correspondent.
* Les noms des paramètres de substitution doivent être identiques aux noms des paramètres de la fonction. Trompez-vous et vous le découvrez à l’import, pas en production.
* Votre fonction s’exécute quand la ressource est **lue**, pas quand elle est listée.
* `str` devient du texte, `bytes` devient un blob base64, tout le reste devient du texte JSON. `mime_type=` sert à l’étiqueter.
* Les outils servent au modèle pour agir. Les ressources servent à l’application pour lire.

La troisième primitive, celle qu’une personne choisit dans un menu, ce sont les **[prompts](prompts.md)**.
