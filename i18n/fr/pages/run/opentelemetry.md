---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

Votre serveur est déjà tracé. Vous n’avez rien à ajouter.

Chaque serveur que vous créez émet un span [OpenTelemetry](https://opentelemetry.io/) pour chaque
message qu’il traite. Vous ne l’avez pas écrit, et vous ne l’importez pas. Il est là dès l’instant où vous
appelez `MCPServer(...)`.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

C’est un serveur complet, et tracé. Appelez `search_books` et un span est créé pour cet appel. Il en va de
même pour le `Server` bas niveau : le traçage est présent sur les deux.

## Ce que vous obtenez {#what-you-get}

Chaque message entrant devient un span `SERVER` nommé d’après la méthode et sa cible. Ainsi, un
`tools/call` pour `search_books` donne le span `tools/call search_books`, et un simple `tools/list`
donne tout bonnement `tools/list`.

Chaque span porte quelques attributs :

* `mcp.method.name` et `mcp.protocol.version`, sur chaque span.
* `jsonrpc.request.id`, sur une requête (une notification n’en a pas).
* Un gestionnaire qui lève une exception passe le statut du span à erreur. Un résultat d’outil avec `is_error=True` aussi.

Et comme tracer un appel d’outil est un besoin très courant, les spans `tools/call` parlent les
[conventions sémantiques GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) d’OpenTelemetry :

* `gen_ai.operation.name`, défini à `"execute_tool"`.
* `gen_ai.tool.name`, défini au nom de l’outil appelé.

Un span `prompts/get` reçoit `gen_ai.prompt.name` dans le même esprit. Les méthodes de liste ne portent aucune
clé `gen_ai.*`, car il n’y a rien à nommer.

!!! tip
    Ces attributs GenAI sont la raison pour laquelle une interface de traçage regroupe vos appels d’outils
    comme elle regroupe ceux de n’importe quel autre agent. Vous obtenez ce regroupement gratuitement, sans code supplémentaire.

## Cela ne coûte rien tant que vous n’en voulez pas {#it-costs-nothing-until-you-want-it}

Voici ce qui fait de « activé par défaut » une valeur par défaut confortable.

Le SDK ne dépend que de `opentelemetry-api`, la moitié légère d’OpenTelemetry. Sans SDK
ni exportateur installé, créer un span est une opération vide. Les spans que votre serveur émet en ce
moment même ne vous coûtent donc presque rien, et personne ne les collecte.

Le jour où vous voulez les *voir*, vous installez l’autre moitié et vous la pointez quelque part :

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

Configurez un exportateur de la manière habituelle pour OpenTelemetry, et chaque span que le SDK
créait discrètement s’allume. Le code de votre serveur ne change pas. Pas une ligne.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) est l’un de ces backends, et il fait la
    configuration pour vous : `pip install logfire`, `logfire.configure()`, et vos spans MCP apparaissent
    dans la vue en direct. Il est construit sur OpenTelemetry, donc tout ce qui suit s’y applique aussi.

## Des traces qui traversent la liaison {#traces-that-cross-the-wire}

Une trace est surtout utile lorsqu’elle suit une requête du client jusque dans le serveur, en une
seule image cohérente.

Lorsque le client et le serveur exécutent tous deux le SDK, ce lien est automatique. Le client injecte
le [contexte de trace W3C](https://www.w3.org/TR/trace-context/) dans la requête, et le serveur
le relit à l’arrivée, de sorte que le span serveur s’imbrique sous le span client dans la même trace. C’est la
[SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414), et vous l’obtenez sans
rien demander.

Si le message entrant ne porte aucun contexte de trace, par exemple une requête provenant d’un client qui n’est pas
le SDK, le span serveur se rattache simplement au span déjà courant côté serveur, au lieu
de démarrer une toute nouvelle trace orpheline.

## Le désactiver {#turning-it-off}

Le traçage est un middleware, le premier de la liste de votre serveur. Si vous voulez vraiment un serveur qui
n’émet aucun span, retirez-le :

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    Cet import commence par un tiret bas, et c’est voulu. La classe est provisoire, de la
    même manière que [`Server.middleware`](../advanced/middleware.md) est provisoire : attendez-vous donc
    à ce que le chemin d’import change. Vous n’en avez presque jamais besoin : sans exportateur installé, les spans
    sont gratuits, et la réponse habituelle consiste donc à les laisser activés et à ne pas installer d’exportateur.

## Récapitulatif {#recap}

* Chaque `MCPServer` et chaque `Server` bas niveau émet un span `SERVER` par message entrant, par
  défaut. Vous n’écrivez rien.
* Les spans portent `mcp.method.name` et `mcp.protocol.version` ; `tools/call` et `prompts/get` portent
  aussi des attributs GenAI, pour que vos appels d’outils se regroupent comme ceux de n’importe quel autre agent.
* Cela ne coûte rien tant que vous n’installez pas un SDK OpenTelemetry et un exportateur, puis tout s’allume
  sans aucune modification de votre serveur.
* Le contexte de trace du client vers le serveur se propage automatiquement lorsque les deux côtés exécutent le SDK.

Ce qui décide si une requête s’exécute ou non, c’est l’**[Autorisation](authorization.md)**.
