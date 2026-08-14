---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# Le Server de bas niveau {#the-low-level-server}

`@mcp.tool()` est une couche. En dessous se trouve une seconde classe de serveur, `Server`, qui parle le MCP brut : vous lui donnez les objets du protocole et elle les place sur la liaison, tels quels.

`MCPServer` est construit par-dessus. Vous descendez d’un niveau lorsque la couche de confort vous gêne :

* Vous devez émettre un schéma **exact** (chargé depuis un fichier, généré à partir d’une base de données), et non un schéma dérivé d’une signature Python.
* Vous avez besoin d’un contrôle total sur le résultat : `_meta`, `is_error`, chaque clé de `structured_content`.
* Vous devez traiter une méthode que MCP ne définit pas.

Pour tout le reste, restez sur `MCPServer`.

## Le même outil, à la main {#the-same-tool-by-hand}

Voici l’outil `search_books` que **[Outils](../servers/tools.md)** écrit en neuf lignes de `@mcp.tool()`, sans le sucre syntaxique :

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Trois choses ont changé, et elles constituent toute l’API de bas niveau :

* **Les gestionnaires (handlers) sont des paramètres du constructeur.** `on_list_tools=` et `on_call_tool=` vont dans `Server(...)`. Il n’y a pas de décorateurs à ce niveau, et chaque gestionnaire a la même forme : `async (ctx, params) -> result`.
* **Vous écrivez le schéma d’entrée.** `Tool.input_schema` est un simple `dict` JSON Schema. Personne ne le dérive d’annotations de type, car il n’y a aucune annotation de type dont le dériver.
* **Vous construisez le résultat.** `CallToolResult(content=[TextContent(...)])`, à la main. Rien n’est enveloppé, converti ni déduit d’une annotation de retour.

`params` est la requête analysée : `CallToolRequestParams` vous donne `.name` et `.arguments`. `ctx` est un `ServerRequestContext` : `ctx.session` pour répondre au client, `ctx.lifespan_context`, `ctx.request_id` et `ctx.meta`, le `_meta` entrant de la requête.

!!! info
    Si vous avez utilisé FastAPI, vous connaissez déjà cette relation. `MCPServer` est la couche des décorateurs et des annotations de type ; `Server` est le Starlette qui se trouve en dessous. Ils ne sont pas rivaux : `MCPServer` construit un `Server` et y enregistre des gestionnaires exactement comme ceux-ci.

### Essayer {#try-it}

Pas d’Inspector pour celui-ci : `mcp dev` et `mcp run` n’acceptent qu’un `MCPServer`. Le `Client` en mémoire s’en moque ; il accepte un `Server` de bas niveau exactement comme il accepte un `MCPServer` :

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

Le même texte que celui produit par la version `@mcp.tool()`. Deux différences, en toute honnêteté :

* `result.structured_content` vaut `None`. Le serveur de haut niveau enveloppe pour vous un `-> str` dans `{"result": ...}` ; ici, personne ne construit ce que vous n’avez pas construit.
* `list_tools` renvoie le schéma que **vous** avez saisi, caractère pour caractère. La version de haut niveau avait `"title": "Query"` sur chaque propriété et un `"title": "search_booksArguments"` à la racine : des artefacts de Pydantic. À ce niveau, si quelque chose est sur la liaison, c’est vous qui l’y avez mis.

## Rien n’est vérifié pour vous {#nothing-is-checked-for-you}

`MCPServer` rejette un mauvais argument avant même que votre fonction s’exécute, en validant l’appel par rapport au schéma qu’il a généré (**[Outils](../servers/tools.md)**).

`Server` ne fait pas cela. Votre `input_schema` est *annoncé* au client ; il n’est jamais *appliqué* à `params.arguments`.

!!! check
    Appelez `search_books` sans `limit` et votre `args["limit"]` lève `KeyError`. Le client voit :

    ```text
    MCPError: Internal server error
    ```

    Une erreur JSON-RPC, code `-32603`, avec un message volontairement générique : le SDK ne divulgue pas votre traceback à un appelant distant. Le modèle ne découvre jamais ce qu’il a mal fait, il ne peut donc pas réessayer. (Dans un test, `raise_exceptions=True` fait remonter la véritable exception à la place ; voir **[Tests](../get-started/testing.md)**.)

Cela se généralise. Une exception levée depuis un gestionnaire de bas niveau est **toujours** une erreur de protocole, jamais un résultat d’outil avec `is_error=True`. Si vous voulez que le modèle lise l’échec et se rattrape, validez vous-même `params.arguments` et renvoyez `CallToolResult(content=[TextContent(...)], is_error=True)`. Les deux types d’échec sont le sujet de **[Gérer les erreurs](../servers/handling-errors.md)**.

## Deux outils, un gestionnaire {#two-tools-one-handler}

`on_call_tool` est l’unique point d’entrée pour tous les outils du serveur. Vous aiguillez selon `params.name` :

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` annonce les deux. `call_tool` répartit selon le nom.
* La branche `else` compte : `Server` transmettra sans hésiter à votre gestionnaire un `tools/call` pour un nom que vous n’avez jamais listé. Lever une exception à cet endroit transforme l’appel en le même `-32603` que ci-dessus.

## Sortie structurée, à la main {#structured-output-by-hand}

Déclarez `output_schema` sur le `Tool` et placez `structured_content` sur le résultat. Les deux vous appartiennent :

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Appelez-le et le résultat porte les deux représentations :

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

Le bloc `_meta` est la marque d’identité du serveur : le SDK l’ajoute à chaque résultat de génération 2026, avec la `version` issue du constructeur (un serveur qui n’en définit aucune renvoie une chaîne vide). Un serveur qui ne doit pas s’identifier peut retirer la clé avec un middleware, lequel est maître des résultats qu’il renvoie.

Le serveur ne compare jamais les deux champs. Le `Client` de ce SDK, si : renvoyez un `structured_content` qui ne satisfait pas le `output_schema` que vous avez déclaré et `call_tool` lève une `RuntimeError` qui commence par `Invalid structured content returned by tool search_books` puis cite l’échec de `jsonschema`. Promettre un schéma ne coûte rien ; le tenir vous incombe. Toute l’échelle des types de retour et des schémas est dans **[Sortie structurée](../servers/structured-output.md)**.

## `_meta` : pour l’application, pas pour le modèle {#\_meta-for-the-application-not-the-model}

`content` est la partie de la réponse que lit le modèle. `structured_content` est la même réponse sous forme de données typées. `_meta` est le troisième canal : des données qui voyagent avec le résultat à destination de l’**application cliente**, sans faire partie de la réponse du tout.

Utilisez-le pour des identifiants d’enregistrement, des identifiants de trace, tout ce dont votre interface a besoin mais pas votre prompt :

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* Vous le construisez sous le nom `_meta=`, le nom sur la liaison. Le client le relit sous la forme `result.meta`.
* Préfixez vos clés d’un espace de noms (`bookshop/record_ids`). Les clés `io.modelcontextprotocol/*` sont réservées par le protocole.

!!! warning
    `_meta` est une convention entre vous et l’application cliente, pas une garantie sur ce qui parvient
    au modèle. L’hôte décide de ce qu’il affiche. Ne mettez jamais de secret dans quelque partie que ce soit d’un résultat d’outil.

## Les capacités suivent vos gestionnaires {#capabilities-follow-your-handlers}

Un `Server` annonce exactement les familles de méthodes pour lesquelles vous lui avez fourni des gestionnaires. Le `Bookshop` ci-dessus passe `on_list_tools` et `on_call_tool` et rien d’autre, donc un client qui s’y connecte voit :

```json
{"tools": {"listChanged": false}}
```

Pas de `resources`, pas de `prompts` : rien ne les soutient. Passez `on_list_prompts` et `prompts` apparaît ; passez `on_completion` et `completions` apparaît.

`MCPServer` annonce toujours les outils, les ressources et les prompts, que vous en ayez enregistré ou non, car ses managers existent toujours. À ce niveau, la déclaration *est* l’appel au constructeur.

## Le type générique du cycle de vie {#the-lifespan-generic}

`Server` est générique sur le type que produit son cycle de vie (lifespan). Annotez-le une fois et l’objet est typé partout où il apparaît :

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* Le cycle de vie est un `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]` ; `@asynccontextmanager` sur un générateur `async` vous donne exactement cela.
* Ce qu’il produit via `yield` devient `ctx.lifespan_context`, et comme les gestionnaires sont annotés `ServerRequestContext[Catalog]`, `.search(...)` bénéficie de l’autocomplétion et de la vérification de types.
* On y entre une fois au démarrage du serveur et on en sort une fois à son arrêt. Le démarrage, l’arrêt et la version `MCPServer` de la même idée sont dans **[Cycle de vie](../handlers/lifespan.md)**.

Sans `lifespan=`, `ctx.lifespan_context` est un `dict` vide.

## Une méthode à vous {#a-method-of-your-own}

Le constructeur couvre les méthodes que MCP définit. `add_request_handler` couvre tout le reste :

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* Le premier argument est la chaîne de la méthode. Les notifications ont un jumeau, `add_notification_handler`.
* `params_type` est le modèle par rapport auquel les `params` entrants sont validés **avant** l’exécution de votre gestionnaire ; les méthodes personnalisées *ont* donc droit à la validation dont les outils sont privés. Dérivez de `RequestParams` pour que le champ `_meta` s’analyse comme celui de toute autre méthode.
* Le gestionnaire renvoie un `BaseModel`, un `dict` ou `None`. Le SDK le sérialise dans le résultat JSON-RPC.

Une réserve, en toute honnêteté : le `Client` de haut niveau n’a de verbes que pour les méthodes que MCP définit, il n’y a donc pas de `client.reindex()`. Une méthode propriétaire s’adresse à un pair qui sait déjà qu’elle existe : un client que vous livrez aussi, ou un autre de vos services parlant JSON-RPC.

Une méthode que vous ne pouvez pas vous approprier :

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

La poignée de main (handshake) appartient à l’exécuteur (runner). Vous êtes libre de remplacer `server/discover`, `ping` et toutes les autres méthodes intégrées.

!!! tip
    `Server.middleware`, mentionné dans cette erreur, enveloppe **chaque** message entrant, `initialize` compris. Si ce que vous voulez est observer ou réécrire le trafic plutôt que répondre à une nouvelle méthode, commencez par **[Middleware](middleware.md)**.

## Les autres gestionnaires {#the-other-handlers}

Chacun d’eux correspond à une idée pour laquelle vous avez désormais le vocabulaire ; chacun a sa propre page.

* `on_call_tool`, `on_get_prompt` et `on_read_resource` peuvent renvoyer un `InputRequiredResult` au lieu de leur résultat normal pour mettre l’appel en pause et demander une saisie au client ; voir **[Requêtes à plusieurs allers-retours (multi-round-trip)](../handlers/multi-round-trip.md)**. Fidèle à ce niveau, rien n’est installé pour vous : là où `MCPServer` scelle `requestState` par défaut, ici le `request_state` que vous définissez traverse la liaison exactement tel qu’écrit, jusqu’à ce que vous optiez pour `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` : une seule ligne (les deux noms s’importent depuis `mcp.server.request_state`) pour un scellement et une vérification identiques à ceux qu’effectue `MCPServer` (**[Protéger `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` ont la même forme `(ctx, params) -> result` pour les autres primitives.
* `on_subscriptions_listen` sert le flux `subscriptions/listen` de la version 2026-07-28. Passez un `ListenHandler` construit sur un `SubscriptionBus` et publiez des événements sur le bus depuis vos autres gestionnaires ; voir **[Abonnements](../handlers/subscriptions.md)** pour la composition complète.
* `server.streamable_http_app()` renvoie la même application Starlette que celle de `MCPServer` ; déployez-la comme **[Exécuter votre serveur](../run/index.md)** déploie n’importe quelle autre application ASGI. Il n’y a pas de `server.run(transport=...)` à ce niveau : `server.run(read_stream, write_stream, server.create_initialization_options())` pilote une connexion sur une paire de flux, et cette seule ligne dit tout.

## Récapitulatif {#recap}

* Le `Server` de bas niveau reçoit ses gestionnaires sous forme de **paramètres de constructeur** `on_*` ; chaque gestionnaire est `async (ctx, params) -> result`.
* Vous écrivez le dict `input_schema` et vous construisez le `CallToolResult`. Rien n’est dérivé, enveloppé ni validé pour vous.
* Une exception dans un gestionnaire est une erreur de protocole `-32603`. Une erreur d’outil que le modèle peut lire est un `CallToolResult` avec `is_error=True` que **vous** renvoyez.
* Le `_meta` du résultat s’adresse à l’application cliente, pas au modèle.
* `Server[T]` est générique sur ce que produit son cycle de vie ; `ctx.lifespan_context` est un `T` typé.
* `add_request_handler(method, params_type, handler)` sert n’importe quelle méthode. `initialize` est réservée.
* Les capacités qu’annonce un `Server` découlent des gestionnaires que vous avez enregistrés.

`Client(server)` a traité les deux serveurs de façon identique parce qu’ils *sont* le même protocole, et c’est tout l’intérêt. La couche suivante vers le bas n’est pas une classe du tout : c’est le **[Middleware](middleware.md)**.
