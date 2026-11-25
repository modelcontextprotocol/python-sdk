---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Installation {#installation}

Le SDK Python est disponible sur PyPI sous le nom [`mcp`](https://pypi.org/project/mcp/). Il nécessite **Python 3.10+**.

Cette documentation décrit la **v2**, la ligne de versions stable actuelle :

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "Vous venez de la v1 ?"
    La v2 est une version majeure avec des changements incompatibles ; le **[Guide de migration](../migration.md)**
    les couvre tous. Si votre *paquet* dépend de `mcp` et n’est pas prêt à migrer, conservez une
    borne supérieure `<2` (par exemple `mcp>=1.28,<2`) pour qu’une résolution sans version épinglée reste sur la ligne 1.x.

## Ce qui est installé {#what-gets-installed}

Vous n’avez pas besoin de connaître tout cela pour utiliser le SDK, mais si vous vous demandez à quoi sert chaque dépendance :

* `mcp-types` : tous les types du protocole (requêtes, résultats, blocs de contenu) dans un paquet à part, versionné au même rythme que le SDK. Le code qui dépend de `mcp` l’importe via l’alias `mcp.types` (tous les `from mcp.types import ...` de cette documentation) ; n’importez `mcp_types` directement que dans un projet qui installe `mcp-types` sans le SDK.
* [`anyio`](https://anyio.readthedocs.io/) : le runtime asynchrone. Tout le SDK est écrit au-dessus d’anyio, il fonctionne donc aussi bien avec `asyncio` qu’avec `trio`.
* [`pydantic`](https://docs.pydantic.dev/) : la base de tous les modèles `mcp.types`, ainsi que toute la génération et la validation de schémas.
* [`httpx2`](https://pypi.org/project/httpx2/) : le client HTTP derrière les transports *client* Streamable HTTP et SSE, avec prise en charge intégrée des server-sent events.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) et [`python-multipart`](https://pypi.org/project/python-multipart/) : les transports HTTP *serveur*.
* [`jsonschema`](https://pypi.org/project/jsonschema/) : valide la sortie structurée d’un outil par rapport au schéma de sortie qu’il déclare.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/) : gestion des jetons OAuth pour l’autorisation.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/) : l’API légère uniquement, de sorte que le middleware de traçage du SDK ne coûte rien tant que vous n’installez pas vous-même un SDK OpenTelemetry et un exporteur.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) et [`typing-inspection`](https://pypi.org/project/typing-inspection/) : les fonctionnalités de typage modernes sous Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/) : Windows uniquement, utilisé pour la gestion des sous-processus `stdio`.

## Extras optionnels {#optional-extras}

* `mcp[cli]` ajoute [`typer`](https://typer.tiangolo.com/) et [`python-dotenv`](https://pypi.org/project/python-dotenv/) pour l’outil en ligne de commande `mcp` (`mcp dev`, `mcp run`, `mcp install`). Vous en aurez besoin pendant le développement ; vous pouvez vous en passer sur un serveur déployé.
* `mcp[rich]` ajoute [`rich`](https://rich.readthedocs.io/) pour des journaux de serveur plus lisibles.
