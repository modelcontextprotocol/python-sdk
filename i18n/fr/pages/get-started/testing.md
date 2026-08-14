---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Tests {#testing}

Le SDK Python fournit une classe `Client` dotée d’un **transport en mémoire** : passez-lui votre objet serveur et il s’y connecte directement.

Pas de sous-processus. Pas de port. Pas de transport du tout. C’est la même idée que le `TestClient` de FastAPI.

## Utilisation de base {#basic-usage}

Supposons que vous ayez un serveur simple avec un seul outil (tool) :

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Pour exécuter le test ci-dessous, vous aurez besoin de deux dépendances (de développement) supplémentaires :

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Cette documentation suppose que vous connaissez déjà [`pytest`](https://docs.pytest.org/en/stable/).

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) est ce que le test
    ci-dessous utilise pour vérifier l’objet résultat entier en une seule ligne. Il enregistre la
    sortie d’un test sous la forme du littéral `snapshot(...)` que vous voyez. Si vous préférez vous
    en passer, supprimez l’import et vérifiez les champs qui vous intéressent
    (`result.content[0].text == "3"`) comme dans n’importe quel autre test.

Voici maintenant le test :

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. Si vous utilisez `trio`, renvoyez `"trio"` à la place. Consultez la [documentation d’anyio](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) pour les détails.
2. La fixture produit un client connecté. Chaque test qui prend `client` en paramètre obtient une nouvelle connexion en mémoire vers le même serveur.

Et voilà. Vous pouvez maintenant étendre vos tests pour couvrir davantage de scénarios.

## Pourquoi `raise_exceptions=True` ? {#why-raise_exceptionstrue}

Deux choses différentes peuvent mal tourner, et cet indicateur n’en concerne qu’une seule.

Une exception dans l’un de **vos outils** n’est pas un échec du protocole. Elle devient un résultat
normal avec `is_error=True`, et le modèle lit le message. `raise_exceptions` n’y change rien : avec
ou sans lui, `call_tool` renvoie le même résultat `is_error=True`. Une page entière y est
consacrée : **[Gérer les erreurs](../servers/handling-errors.md)**.

Un échec **en dehors** du corps d’un outil est différent. Sur la connexion que vous donne
`Client(mcp)`, le serveur le neutralise en un `"Internal server error"` générique avant que le
client ne le voie. Vous ne devriez jamais divulguer les détails d’un plantage inattendu à un
appelant distant. Dans un test, c’est exactement ce que vous ne voulez *pas*, et c’est ce que
change `raise_exceptions=True` : votre test voit le vrai message au lieu de la version neutralisée.

Laissez-le activé dans les tests. Il n’a aucun sens dans du code de production.

## Dans le processus par défaut {#in-process-by-default}

!!! note
    `Client(mcp)` se connecte dans le processus et est **neutre vis-à-vis de la génération du
    protocole** par défaut : il sonde le serveur et choisit le chemin de protocole approprié. Fixez
    `mode="legacy"` si votre test exerce une sémantique propre aux connexions historiques (push
    d’échantillonnage (sampling) ou d’élicitation (elicitation), `message_handler`), et retirez alors
    `raise_exceptions=True` : une connexion historique ne neutralise jamais rien, et l’indicateur
    relève l’échec dans la tâche du serveur plutôt que dans votre test.

Cette unique ligne est aussi la raison pour laquelle cette documentation peut vous promettre que
ses exemples fonctionnent : chaque fichier d’exemple est exercé par la propre suite de tests du
SDK, presque tous via ce client précisément. Vous utilisez le même outil que le SDK utilise sur
lui-même.

Vous avez un serveur qui fonctionne et qui est testé. L’intégrer dans une véritable application
(Claude Desktop, un IDE), c’est **[Se connecter à un hôte réel](real-host.md)** ; toutes les autres
manières de le servir sont dans **[Exécuter votre serveur](../run/index.md)**.
