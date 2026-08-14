---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# Nouveautés de la v2 {#whats-new-in-v2}

Deux choses se sont produites en même temps dans la v2. Le **SDK a été reconstruit** : un nouveau moteur sous le client comme sous le serveur, un `Client` de premier plan et une série de renommages qu’une base de code v1 rencontre dès son premier import. Et le **protocole a évolué** : la v2 parle la révision 2026-07-28 de MCP, qui supprime la poignée de main (handshake) de connexion, la session et toutes les requêtes initiées par le serveur, sans abandonner les clients que vous avez déjà.

Cette page fait le tour des deux volets, une section par grand titre, chacune se terminant par la page de référence du sujet. Ce n’est pas le manuel de portage. Celui-ci, c’est le **[Guide de migration](migration.md)** : chaque changement incompatible, avec le code avant et après.

!!! note "La v2 est la branche stable"
    `pip install mcp` installe la 2.x, et **[Installation](get-started/installation.md)** donne la
    ligne d’installation à copier-coller. Si quoi que ce soit dans la v2 casse, vous surprend ou vous
    ralentit, [dites-le-nous](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

## Le SDK : de la v1 à la v2 {#the-sdk-v1-to-v2}

### `FastMCP` s’appelle désormais `MCPServer` {#fastmcp-is-now-mcpserver}

La classe de serveur haut niveau a été renommée, et son module avec elle. C’est la première chose sur laquelle bute tout serveur v1, car l’ancien chemin d’import a disparu au lieu d’être simplement obsolète :

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

C’est aussi, pour un serveur construit avec des décorateurs, l’essentiel du portage. `@mcp.tool()`, `@mcp.resource()` et `@mcp.prompt()` acceptent ce qu’ils acceptaient en v1 (`@mcp.resource()` ajoute un mot-clé optionnel `security=`), et le schéma d’entrée provient toujours de vos annotations de type. À la marge : tout ce qui se trouvait sous `mcp.server.fastmcp.*` vit maintenant sous `mcp.server.mcpserver.*`, `ctx.fastmcp` devient `ctx.mcp_server`, `get_context()` a disparu (déclarez plutôt un paramètre `ctx: Context`) et la classe d’exception de base `FastMCPError` devient `MCPServerError`. Le **[Guide de migration](migration.md#fastmcp-renamed-to-mcpserver)** contient le tableau des imports.

### `Resolve` : la nouvelle façon de demander une saisie à l’utilisateur {#resolve-the-new-way-to-ask-the-user-for-input}

Tout ce dont un outil a besoin ne devrait pas venir du modèle. Nouveauté de la v2 : un paramètre d’outil annoté avec `Resolve(fn)` est rempli à la place par une fonction que vous écrivez, de façon invisible pour le modèle, et cette fonction peut renvoyer `Elicit(...)` pour poser une question à l’utilisateur. C’est la façon privilégiée d’obtenir quoi que ce soit du client en cours d’appel : le SDK achemine la question par le mécanisme que la connexion prend en charge (une requête d’élicitation (elicitation) en direct pour un client historique, une requête à plusieurs allers-retours (multi-round-trip) en version 2026-07-28), si bien qu’un seul corps d’outil sert les deux générations. La page à lire est **[Dépendances](handlers/dependencies.md)**.

!!! note
    Les deux autres formes restent disponibles si vous en avez besoin : `ctx.elicit()` fonctionne
    toujours pour les clients sur des connexions historiques (**[Élicitation](handlers/elicitation.md)**),
    et un gestionnaire peut renvoyer lui-même un `InputRequiredResult` et piloter les tours à la main,
    ce qui est aussi la façon dont les requêtes d’échantillonnage (sampling) et de racines (roots)
    voyagent en version 2026-07-28 (**[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)**).

### Un `Client` de premier plan {#a-first-class-client}

La v1 vous donnait trois couches imbriquées : un gestionnaire de contexte de transport produisant des flux bruts, une `ClientSession` qui les enveloppait et un `await session.initialize()` appelé à la main. La v2 a un seul objet :

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` accepte un objet serveur (en mémoire, sans transport : c’est la solution pour les tests), une URL (Streamable HTTP) ou n’importe quel gestionnaire de contexte de transport comme `stdio_client(...)`. Entrer dans `async with` établit la connexion et négocie la version du protocole, quelle que soit la génération que parle le serveur ; `client.server_capabilities` et `client.protocol_version` sont simplement disponibles ensuite, et `client.server_info` aussi lorsque le serveur s’identifie (c’est désormais `Implementation | None`, puisque l’identité est optionnelle dans la génération 2026). Les fonctions de rappel (callbacks) d’échantillonnage et d’élicitation que vous aviez enregistrées en v1 fonctionnent toujours (leur corps voit le même renommage d’attributs en snake_case que tout le reste de cette page), elles répondent désormais aussi aux requêtes-dans-les-résultats de style 2026 (ci-dessous), et elles s’exécutent de façon concurrente plutôt qu’une à la fois. `ClientSession` reste en dessous pour qui veut la surface bas niveau, et `client.session` vous la donne ; elle a bougé elle aussi (elle tourne sur le nouveau moteur de répartition, et certaines de ses propres signatures ont changé), alors lisez le **[Guide de migration](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)** avant de descendre à ce niveau.

**[Le Client](client/index.md)** le présente, **[Transports du client](client/transports.md)** couvre les trois formes de connexion, **[Fonctions de rappel du client](client/callbacks.md)** couvre les fonctions de rappel elles-mêmes, et **[Tests](get-started/testing.md)** montre le modèle en mémoire qui remplace l’utilitaire `create_connected_server_and_client_session()` de la v1.

### Le `Server` bas niveau a été reconstruit, pas renommé {#the-low-level-server-was-rebuilt-not-renamed}

Si vous travaillez au niveau de la couche JSON-RPC, c’est la partie « tout est différent » de la v2. Voici le même serveur à un seul outil dans les deux versions ; cliquez sur les marqueurs pour voir ce qui a bougé.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. Les gestionnaires sont enregistrés avec des décorateurs (appelés, avec parenthèses), à tout moment une fois que le serveur existe.
2. Vous renvoyez une simple `list[Tool]` et le SDK l’enveloppe dans un `ListToolsResult`.
3. Les champs sont en camelCase côté Python, et le schéma est **appliqué** : le SDK valide avec jsonschema les arguments de `call_tool` par rapport à ce schéma avant que votre fonction ne s’exécute, ce qui explique pourquoi `arguments["query"]` ci-dessous est sûr.
4. Un seul gestionnaire `call_tool` sert tous les outils, et il reçoit le nom de l’outil et les arguments déjà validés, dépaquetés et jamais `None`.
5. Lever une exception est la façon dont un outil v1 signale un échec : toute exception est interceptée et renvoyée comme `CallToolResult(isError=True)` avec `str(e)` pour texte, si bien que le modèle appelant lit ce message et peut réessayer.
6. Le contexte vient d’une ContextVar ambiante, accessible via l’objet serveur en cours de requête.
7. Les blocs de contenu nus sont enveloppés dans un `CallToolResult` pour vous.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Les champs sont maintenant en snake_case, et le schéma est **annoncé mais jamais appliqué** : rien ne vérifie les arguments avant l’exécution de votre gestionnaire.
2. Tous les gestionnaires ont la même forme : `async (ctx, params) -> result`. Le contexte est le premier argument (`ctx.session`, `ctx.request_id`, `ctx.protocol_version` s’y trouvent) ; c’est là qu’est passé `server.request_context`.
3. Vous construisez vous-même le `ListToolsResult` complet. Renvoyer une simple liste est désormais une `TypeError` côté serveur, et non quelque chose que le SDK enveloppe.
4. Des paramètres typés en entrée (`params.name`, `params.arguments`), un résultat complet en sortie. Rien n’est dépaqueté, enveloppé ni converti pour vous.
5. Même vérification, autre verbe. Une `ValueError` ici atteindrait le modèle sous forme d’un `-32603` opaque (voir ci-dessous), donc une erreur volontaire sur la liaison se lève en `MCPError` : elle passe telle quelle avec son code et son message, et `-32602` avec ce texte est la réponse prévue par la spécification elle-même pour un outil inconnu.
6. `params.arguments` peut valoir `None` ; la v1 le remplaçait par `{}` avant même que votre code ne le voie. Sans validation devant le gestionnaire, cette ligne est indispensable.
7. Une exception inattendue levée ici devient une erreur de protocole **expurgée**, `-32603` `"Internal server error"` : le modèle ne voit jamais le message. Pour un échec que le modèle doit lire et auquel il doit réagir, renvoyez `CallToolResult(is_error=True, ...)`.
8. Les gestionnaires sont des arguments du constructeur, si bien que la surface du serveur est complète dès qu’il existe ; `add_request_handler()` est l’échappatoire après construction, et la porte d’entrée vers les méthodes personnalisées.

L’exemple illustre le modèle. Plus généralement : tous les gestionnaires ont la même forme, paramètres typés en entrée et type de résultat complet en sortie ; l’ancienne vérification jsonschema des arguments d’outil a disparu ; une exception est une erreur de protocole, jamais un résultat d’outil `is_error=True` ; et la ContextVar ambiante `server.request_context` a disparu. Les méthodes personnalisées, dans un espace de noms fournisseur, sont de premier plan via `add_request_handler(method, params_type, handler)`, qui valide les paramètres entrants par rapport à votre modèle avant l’exécution de votre gestionnaire. Et une liste `middleware` (délibérément marquée comme provisoire) enveloppe chaque message entrant, remplaçant les méthodes privées `_handle_*` que l’on avait l’habitude de surcharger.

En dessous, la boucle de réception `BaseSession` de la v1 a été remplacée par un moteur de répartition que le client et le serveur partagent désormais, et c’est ce qui rend vraies en même temps plusieurs affirmations de cette page : un seul objet `Server` sert les deux générations du protocole, `Client(server)` répartit dans le processus sans encadrement JSON-RPC, et une requête client expirée annule désormais réellement le gestionnaire côté serveur.

**[Le Server bas niveau](advanced/low-level-server.md)** est la page de référence ; le **[Guide de migration](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** passe en revue chaque hook supprimé. Si vous n’êtes jamais descendu en dessous de `MCPServer`, rien de tout cela ne vous concerne.

### Les types de la liaison ont déménagé dans `mcp-types`, et chaque champ est en snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

Les types du protocole vivent désormais dans leur propre distribution, `mcp-types`. Elle ne dépend de rien d’autre que de pydantic et typing-extensions, si bien qu’une passerelle, un proxy ou un générateur de code peut consommer les formes que MCP échange sur la liaison sans installer de pile HTTP : un tel projet installe `mcp-types` et importe `mcp_types`. `mcp` lui-même dépend de ce paquet dans une version exacte et le réexpose, donc le code qui dépend du SDK continue d’écrire `import mcp.types as types` et `from mcp.types import Tool` (un alias permanent, chaque nom désignant le même objet) et ne déclare que sa seule vraie dépendance, `mcp`. La règle empirique : importez via le paquet dont vous dépendez réellement.

Sur ces types, chaque attribut Python est désormais en snake_case : `result.is_error`, `tool.input_schema`, `listing.next_cursor`. Le JSON qui circule sur la liaison est en camelCase, exactement comme avant ; seule l’orthographe des attributs a changé. Deux valeurs par défaut plus strictes l’accompagnent : les champs inconnus sont ignorés au lieu d’être conservés à l’aller-retour (mettez les extras dans `_meta`), et les deux côtés valident le trafic par rapport à la version du protocole qu’ils ont négociée. Consultez le **[Guide de migration](migration.md#field-names-changed-from-camelcase-to-snake_case)** pour le tableau des renommages.

### La configuration du transport a déménagé dans `run()` {#transport-configuration-moved-to-run}

`MCPServer(...)` décrit ce que votre serveur *est* : son nom, ses instructions, son cycle de vie (lifespan), son authentification. La façon dont il est *servi* relève désormais de `run()` et des constructeurs d’application, et c’est là que sont passés `host`, `port`, `stateless_http`, `json_response`, les chemins des points de terminaison et `transport_security` (`MCPServer("x", port=9000)` est une `TypeError`). Les surcharges sont typées par transport, si bien que votre éditeur vous indique quelles options accepte `stdio` et lesquelles accepte `streamable-http`. Une suppression à connaître : `mount_path` a disparu ; monter l’application ASGI est la façon prise en charge de servir sous un préfixe.

**[Exécuter votre serveur](run/index.md)** couvre les options ; **[Ajouter à une application existante](run/asgi.md)** couvre le montage.

### Les comportements qui changent sans erreur d’import {#behavior-that-changes-without-an-import-error}

Les renommages s’annoncent d’eux-mêmes. Ceux-ci, non :

* **Les fonctions synchrones s’exécutent sur un thread de travail.** Un outil `def` (ou une ressource, un prompt ou un résolveur) ne bloque plus la boucle d’événements ; la contrepartie est que son corps ne s’exécute plus *sur* le thread de la boucle d’événements, ce qui compte pour le code lié à un thread particulier. Les gestionnaires `async def` ne sont pas touchés. **[Guide de migration](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**.
* **Une `MCPError` (la `McpError` de la v1) levée dans un outil est désormais une erreur de protocole.** Le modèle ne la voit jamais. Toute autre exception devient toujours un résultat `is_error=True` que le modèle peut lire et auquel il peut réagir. **[Gérer les erreurs](servers/handling-errors.md)** détaille la distinction.
* **Les résultats sont validés avant de partir.** Un `Tool` construit à la main dont le `input_schema` vaut `{}` fait désormais échouer `tools/list` (la spécification exige `"type": "object"`). Les serveurs construits avec `@mcp.tool()` ne voient jamais cela ; le SDK écrit leurs schémas.
* **Votre client valide ce qu’il reçoit.** `list_tools()` et `call_tool()` vérifient la réponse du serveur par rapport à la version du protocole négociée, si bien qu’un serveur pas tout à fait valide que l’analyse indulgente de la v1 tolérait lève désormais `pydantic.ValidationError`. Si vous vous connectez à des serveurs que vous ne contrôlez pas, attendez-vous à être celui qui les découvre ; le **[Guide de migration](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)** a les détails.
* **Les modèles d’URI suivent désormais vraiment la RFC 6570.** `{+path}`, `{?query}` et leurs semblables fonctionnent, la correspondance est exacte au lieu d’être approximative façon regex, et la traversée de répertoires dans les valeurs extraites est rejetée par défaut. Les modèles plus stricts échouent au moment de la décoration, pas à la première requête. **[Modèles d’URI](servers/uri-templates.md)**.
* **Le cycle de vie Streamable HTTP s’exécute une seule fois**, au démarrage, et son état est partagé par toutes les sessions et requêtes. En v1 il s’exécutait une fois par session, et une fois par requête avec `stateless_http=True`. Les pools et caches construits dans un cycle de vie deviennent nettement moins coûteux ; tout ce qui y acquérait une ressource par connexion a désormais sa place dans le corps du gestionnaire. **[Cycle de vie](handlers/lifespan.md)**.
* **`mcp dev` et `mcp install` épinglent l’environnement qu’ils lancent** sur la version du SDK que vous avez installée. Les deux commandes exécutent votre serveur dans un environnement `uv run --with ...` tout neuf, qui résolvait auparavant `mcp` vers la dernière version stable plutôt que vers la version avec laquelle vous développez. **[Guide de migration](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**.
* **Le client HTTP est désormais `httpx2`, et non `httpx`.** Le changement de dépendance modifie ce que votre code intercepte et transmet (`httpx2.AsyncClient`, `httpx2.ConnectError`), et il modifie la façon dont les certificats TLS sont vérifiés : `httpx2` valide via `truststore` par rapport au magasin de confiance du système d’exploitation au lieu de la liste d’autorités de certification embarquée de certifi. La plupart des environnements ne remarquent rien ; un conteneur minimal sans magasin d’AC système, ou une AC privée que seul le bundle de certifi connaissait, se met à échouer à la poignée de main TLS. Définissez `SSL_CERT_FILE`/`SSL_CERT_DIR` ou passez `verify=ssl_context` à votre client. **[Guide de migration](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**.

### Supprimés purement et simplement {#removed-outright}

Chacun de ces points fait l’objet d’une section du **[Guide de migration](migration.md)** :

* Le **transport WebSocket**, des deux côtés, et l’extra `mcp[ws]`. Il n’a jamais fait partie de la spécification MCP.
* L’API **expérimentale Tasks** (`mcp.*.experimental`). La version 2026-07-28 sort les tâches du cœur du protocole pour en faire une extension officielle ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)), que ce SDK n’implémente pas encore.
* `mcp.shared.version`, `mcp.shared.progress` et `mcp.shared.session` (avec le stub `RequestResponder` qu’importaient les annotations de `message_handler` en v1) en tant que chemins d’import. (`mcp.types` n’est *pas* supprimé : il reste un alias permanent du paquet autonome `mcp_types`.)
* L’orthographe obsolète `streamablehttp_client`, et la fonction de rappel `get_session_id` de `streamable_http_client` (qui produit désormais exactement deux flux).
* `McpError`, renommée **`MCPError`** avec un constructeur direct `(code, message, data)`.
* `MCPServer.get_context()`, `mount_path=`, ainsi que les méthodes décorateur, la ContextVar et les dictionnaires de gestionnaires du `Server` bas niveau.

## Le protocole : de 2025-11-25 à 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

La v2 implémente la révision 2026-07-28, et elle sert **les deux** révisions à la fois : la même `streamable_http_app()` (et le même serveur stdio) répond au `initialize` d’un client de génération 2025 et aux requêtes d’un client de génération 2026 sans rien à configurer, sans option à basculer et sans déploiement séparé. Servir la nouvelle révision n’abandonne pas un client resté sur l’ancienne. Ce qui suit décrit ce que la nouvelle révision change en elle-même.

### Pas de poignée de main, pas de session {#no-handshake-no-session}

Un client 2026-07-28 n’ouvre pas une connexion pour négocier avant de parler. Chaque requête transporte sa version de protocole, les informations du client et les capacités du client dans `_meta`, et l’unique appel de découverte, `server/discover`, est une requête ordinaire comme les autres. `Client` fait ce qu’il faut par défaut : il sonde `server/discover` une fois et se rabat sur la poignée de main `initialize` si le serveur est plus ancien.

En Streamable HTTP, il n’y a pas de `Mcp-Session-Id` sur le chemin 2026, ce qui est le point majeur côté exploitation : **rien ne lie une requête moderne à un worker**, si bien que n’importe quelle réplique derrière un simple répartiteur de charge en round-robin peut y répondre. Deux réserves honnêtes. Vos clients de génération 2025 (aujourd’hui, c’est-à-dire la plupart des clients) ouvrent toujours des sessions et ont toujours besoin de l’affinité dont ils avaient besoin en v1 ; rien ne change pour eux. Et la seule chose qu’une nouvelle tentative *à plusieurs allers-retours* doit transporter d’un worker à l’autre est son `request_state` scellé, dont la clé par défaut est générée par processus, si bien qu’un déploiement à plusieurs instances passe `RequestStateSecurity(keys=[...])`. (`stateless_http=True` n’a rien à voir : il n’affecte que la façon dont les clients de génération 2025 sont servis, et le trafic 2026 ne le lit jamais ; si vous l’aviez déjà défini en v1, rien ne change.)

**[Versions du protocole](protocol-versions.md)** présente le côté client, **[Déployer et passer à l’échelle](run/deploy.md)** est la liste de contrôle de l’opérateur (la liste d’autorisation Host, la clé `request_state`, les notifications entre répliques), et **[Prendre en charge les clients historiques](run/legacy-clients.md)** explique comment servir les deux générations à la fois.

### Le serveur ne peut pas appeler le client : requêtes à plusieurs allers-retours {#the-server-cannot-call-the-client-multi-round-trip-requests}

Toutes les requêtes initiées par le serveur disparaissent en version 2026-07-28 : élicitation poussée, échantillonnage, `roots/list`. Sur une connexion 2026 il n’existe aucun canal de retour (back-channel) pour elles, si bien que `ctx.elicit()` et `ctx.session.create_message()` y échouent avec `NoBackChannelError` (elles fonctionnent toujours pour les clients historiques).

Le remplacement inverse l’appel. Un outil qui a besoin de quelque chose de la part de l’utilisateur *renvoie* la question (`InputRequiredResult`), le client y répond avec les mêmes fonctions de rappel qu’il a toujours eues, et l’appel est relancé avec les réponses jointes. `Client` pilote cette boucle pour vous. Côté serveur, vous construisez rarement le résultat vous-même, car une **[dépendance](handlers/dependencies.md)** le fait : annotez un paramètre avec `Resolve(ask_quantity)`, où `ask_quantity` est une fonction ordinaire que vous écrivez, et le SDK pose la question par le mécanisme que la connexion prend en charge, une requête d’élicitation en direct sur une session historique ou une requête à plusieurs allers-retours en 2026. Un seul corps d’outil, les deux générations :

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

Ce fichier résume tout l’argument en un seul endroit : un serveur, un outil adossé à `Resolve`, et un client historique plus un client moderne qui obtiennent tous deux leur réponse, en mémoire. **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)** explique le mécanisme (y compris `request_state`, que le SDK scelle et vérifie pour vous) ; **[Élicitation](handlers/elicitation.md)** couvre la façon de poser la question.

!!! warning "C’est le seul endroit où un serveur v1 porté change de comportement"
    Vos propres tests y butent en premier : `Client(mcp)` négocie par défaut 2026-07-28 avec votre
    serveur v2, si bien qu’un outil qui appelle `ctx.elicit()` échoue dans un test qui passait en v1.
    Déplacez la question dans un paramètre `Resolve(...)` (portable entre générations), ou épinglez le
    client de test sur `mode="legacy"` si vous voulez vraiment le comportement poussé.

### Racines, échantillonnage et journalisation protocolaire sont obsolètes ; `ping` est supprimé {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

La [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) rend obsolètes trois *capacités* entières, sur toutes les versions du protocole : les racines, l’échantillonnage et la journalisation au niveau MCP (`ctx.info()` et consorts). C’est un axe distinct de l’absence de canal de retour ci-dessus ; obsolète est un simple avis, tout continue de fonctionner avec les sessions de génération 2025, et rien ne change sur la liaison. Ce que vous remarquez, c’est `MCPDeprecationWarning`, qui est un `UserWarning` et s’affiche donc par défaut ; attendez-vous à ce que votre premier `ctx.info(...)` après la mise à niveau vous le dise.

`ping` est traité plus sévèrement : supprimé du protocole, pas obsolète. Deux des méthodes autonomes des fonctionnalités obsolètes sont supprimées en version 2026-07-28 de la même façon, `logging/setLevel` et le `notifications/roots/list_changed` du client, et les notifications de progression vont désormais uniquement du serveur vers le client.

**[Fonctionnalités obsolètes](deprecated.md)** donne le tableau complet, le remplacement de chacune et le filtre d’une ligne si vous avez besoin d’un journal silencieux pendant que vous servez des clients historiques.

### Les notifications de changement deviennent un seul flux {#change-notifications-become-one-stream}

En version 2026-07-28, le flux HTTP GET autonome et `resources/subscribe` sont remplacés par `subscriptions/listen` : le client ouvre un seul flux de longue durée et nomme les types de notifications qu’il souhaite. `MCPServer` le sert par défaut ; vous publiez avec `await ctx.notify_resource_updated(uri)` (et `notify_tools_changed()`, etc.), un middleware peut refuser une requête d’écoute par appelant, et les déploiements à plusieurs répliques branchent un `SubscriptionBus` partagé. Côté client, `async with client.listen(...)` ouvre le flux : le filtre passe en arguments nommés, des événements de changement typés reviennent, et `sub.honored` est le sous-ensemble que le serveur a accepté de livrer.

**[Abonnements](handlers/subscriptions.md)** couvre la publication et le service, **[sa page jumelle côté client](client/subscriptions.md)** le côté observation, et **[Déployer et passer à l’échelle](run/deploy.md)** le bus.

### Le reste, rapidement {#the-rest-quickly}

* **L’identité est une métadonnée optionnelle, par message.** La clé `_meta` `clientInfo` côté requête est optionnelle (la paire obligatoire est `protocolVersion` + `clientCapabilities`), et `serverInfo` a quitté le corps du résultat de `server/discover` : les serveurs l’inscrivent à la place dans le `_meta` de chaque résultat de génération 2026 ([spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). Le SDK l’inscrit toujours ; `client.server_info` vaut `None` lorsqu’un serveur ne s’identifie pas (par exemple, un middleware a retiré la clé). **[Le Server bas niveau](advanced/low-level-server.md)** montre cette inscription sur la liaison.
* **Les requêtes sont routables sans analyser les corps.** Les requêtes HTTP modernes portent `Mcp-Method` (et, pour les trois appels de type outil, `Mcp-Name`) ; une propriété de schéma d’entrée d’outil annotée avec `x-mcp-header` est recopiée dans un en-tête `Mcp-Param-*` et recoupée par le serveur ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). Les passerelles et limiteurs de débit peuvent router sur les seuls en-têtes ; le **[Guide de migration](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)** a les règles.
* **Les résultats portent des indications de cache.** Les résultats de liste et de lecture déclarent `ttlMs` et `cacheScope` ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)) ; vous les définissez par méthode avec `cache_hints=`, et `Client` les honore avec un cache de réponses intégré. Un serveur qui n’envoie aucune indication (tout serveur antérieur à 2026) voit un trafic identique, non mis en cache. **[Indications de mise en cache](client/caching.md)**.
* **Les extensions sont de premier plan.** Serveurs et clients déclarent des lots de capacités optionnels sous des identifiants en DNS inversé ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)) ; l’extension intégrée `Apps` (MCP Apps) sert de référence. **[Extensions](advanced/extensions.md)** et **[MCP Apps](advanced/apps.md)**.
* **Les codes d’erreur ont été normalisés.** Une ressource manquante est un `-32602` avec l’URI dans `error.data`, et les nouveaux codes réservés par la spécification apparaissent comme `-32020` (incohérence d’en-tête), `-32021` (capacité obligatoire manquante) et `-32022` (version de protocole non prise en charge). **[Dépannage](troubleshooting.md)** est indexé par les messages exacts.
* **L’autorisation est devenue plus difficile à mal utiliser.** Le client valide le `iss` renvoyé avec le code d’autorisation ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207) ; votre `callback_handler` renvoie désormais un `AuthorizationCodeResult`), envoie `application_type` lorsqu’il s’enregistre, et ne rejoue jamais d’identifiants auprès d’un serveur d’autorisation différent. Nouveauté côté entreprise : le flux d’assertion d’identité de la [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990). Le **[Guide de migration](migration.md)** répertorie chaque changement OAuth ; **[OAuth pour les clients](client/oauth-clients.md)** et **[Assertion d’identité](client/identity-assertion.md)** sont les pages à lire.
* **Chaque serveur est traçable.** OpenTelemetry est activé par défaut sous forme de middleware : chaque requête obtient un span serveur, sans coût tant que le processus ne configure pas d’exporteur. Lorsque les deux extrémités exécutent le SDK, le client propage aussi le contexte de trace W3C dans `_meta`, si bien que les traces se rejoignent. **[OpenTelemetry](run/opentelemetry.md)**.

## Vous migrez depuis la v1 ? {#upgrading-from-v1}

* Le **[Guide de migration](migration.md)** est la liste complète et exacte de ce qu’il faut changer ; cette page expliquait le pourquoi.
* **La v1.x ne va nulle part.** Elle passe en maintenance, continue de recevoir les correctifs critiques et les correctifs de sécurité, et rien dans la publication de la spécification 2026-07-28 ne la casse ; sa documentation se trouve sur [/v1/](https://py.sdk.modelcontextprotocol.io/v1/). Si vous publiez une bibliothèque qui dépend de `mcp` et que vous n’êtes pas prêt à migrer, gardez une borne supérieure (par exemple `mcp>=1.28,<2`) pour qu’une résolution non épinglée reste sur la 1.x.
* Quelque chose d’approximatif, de déroutant ou de cassé ? **[Envoyez votre retour sur la v2](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)** ; tout est lu.
