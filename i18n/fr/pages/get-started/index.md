---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# Prise en main {#get-started}

Vous débutez avec MCP, ou avec ce SDK ? Commencez ici. Ces pages vous mènent de zéro à un
serveur fonctionnel et testé : [installez le SDK](installation.md), construisez votre
[premier serveur](first-steps.md), [connectez-le à un hôte réel](real-host.md) et
[testez-le](testing.md) avec un client en mémoire.

## Exécuter le code {#run-the-code}

Tous les blocs de code peuvent être copiés et utilisés tels quels : ce sont des fichiers complets et fonctionnels.

Pour suivre, collez un bloc dans un fichier `server.py` et ouvrez-le dans le MCP Inspector :

```console
uv run mcp dev server.py
```

Il est **FORTEMENT recommandé** d’écrire (ou de copier) le code, de le modifier et de l’exécuter localement. C’est en l’utilisant dans votre propre éditeur que vous en saisirez vraiment l’intérêt : le peu de code à écrire, l’autocomplétion, les vérifications de type qui détectent les erreurs avant même que vous n’exécutiez quoi que ce soit.

## Vous n’aurez pas à deviner {#you-will-not-be-guessing}

Chaque exemple de cette documentation est un fichier complet sous [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) dans le dépôt du SDK lui-même, et chacun d’eux est exécuté par la suite de tests du SDK via un **client en mémoire** :

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

Aucun sous-processus, aucun port, aucun transport. `Client(mcp)` se connecte directement à l’objet serveur.

Si une modification du SDK casse un exemple de l’une de ces pages, la CI passe au rouge avant la page. Le code que vous lisez ici est le code qui s’exécute.

Vous l’utiliserez vous-même dans [Tester](testing.md) ; c’est aussi ainsi que vous testez vos propres serveurs.

## Où aller ensuite {#where-to-go-next}

Une fois qu’un serveur tourne, le reste de cette documentation est une référence, pas un cours.
Chaque page se suffit à elle-même, alors allez directement à ce dont vous avez besoin :

* Ce qu’un serveur expose (outils, ressources, prompts), c’est **[Serveurs](../servers/index.md)**.
* Ce qui est disponible dans les fonctions que vous enregistrez, c’est **[Dans votre gestionnaire](../handlers/index.md)**.
* Le mettre à disposition des clients (stdio, HTTP, votre application FastAPI existante), c’est **[Exécuter votre serveur](../run/index.md)**.
* Construire l’autre côté, une application qui *utilise* des serveurs MCP, c’est **[Clients](../client/index.md)**.
