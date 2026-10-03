---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "Cette documentation décrit la v2, la branche stable actuelle"
    Vous découvrez la v2, ou vous venez de la v1 ? **[Nouveautés de la v2](whats-new.md)** fait le tour des changements en cinq minutes, et le **[Guide de migration](migration.md)** couvre chaque changement incompatible.
    Encore en v1.x ? Sa documentation se trouve dans la [documentation v1.x](https://py.sdk.modelcontextprotocol.io/v1/).
    Quelque chose vous semble maladroit ou confus ? [Dites-le-nous](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

Le **Model Context Protocol (MCP)** permet aux applications de fournir du contexte aux LLM de façon standardisée, en séparant la *fourniture* du contexte de l’interaction avec le LLM proprement dite.

Voici son SDK Python officiel. Il vous permet de :

* **Construire des serveurs MCP** qui exposent des outils (tools), des ressources et des prompts à n’importe quel hôte MCP.
* **Construire des clients MCP** qui se connectent à n’importe quel serveur MCP.
* Parler tous les transports standard : stdio, Streamable HTTP et SSE.

## Prérequis {#requirements}

Python 3.10+.

## Installation {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

L’extra `[cli]` vous fournit la commande `mcp` ; vous en aurez besoin pour le développement.
Consultez [Installation](get-started/installation.md) pour savoir à quoi sert chaque dépendance.

## Exemple {#example}

### Le créer {#create-it}

Créez un fichier `server.py` :

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

C’est un serveur MCP complet.

Il expose un **outil**, `add`, et une **ressource** paramétrée, `greeting://{name}`.

### L’exécuter {#run-it}

```console
uv run mcp dev server.py
```

Cette commande démarre votre serveur et ouvre le [MCP Inspector](https://github.com/modelcontextprotocol/inspector), une interface interactive pour l’explorer. Ouvrez l’URL qu’elle affiche.

!!! note
    L’Inspector est une application Node.js : `mcp dev` a donc besoin de `npx` dans votre `PATH`.

### Essayer {#try-it}

Dans l’Inspector, allez dans **Tools** et appelez `add` avec `a=1`, `b=2`.

Vous obtenez `3` en retour. ✨

L’Inspector a construit ce formulaire (un champ entier obligatoire pour `a`, un autre pour `b`) à partir de vos annotations de type. Claude fera de même, ainsi que tous les autres hôtes MCP.

Allez maintenant dans **Resources** et lisez `greeting://World` :

```text
Hello, World!
```

### Récapitulatif {#recap}

Regardez à nouveau ce que vous n’avez **pas** écrit :

* Aucun JSON Schema. `a: int, b: int` *est* le schéma.
* Aucune analyse de requête, aucune sérialisation, aucun code de validation.
* Aucune gestion du protocole.

Vous avez écrit deux fonctions Python avec des annotations de type et une docstring. Le SDK fait le reste.

## Et ensuite {#where-to-go-next}

* **[Prise en main](get-started/index.md)** vous mène de l’installation à un serveur fonctionnel et testé.
* Vous construisez une application qui *utilise* des serveurs MCP ? Commencez par **[Clients](client/index.md)**.
* Vous avez déjà une application FastAPI ou Starlette ? **[Ajouter à une application existante](run/asgi.md)** y monte un serveur MCP.
* Vous cherchez un message d’erreur précis ? **[Dépannage](troubleshooting.md)** est indexé par le texte exact.
* Vous vous demandez ce qui a changé dans la v2 ? **[Nouveautés de la v2](whats-new.md)** en fait le tour en cinq minutes.
* Vous migrez depuis la v1 ? Commencez par le **[Guide de migration](migration.md)**.
* Vous cherchez une signature exacte ? La **[Référence de l’API](api/mcp/index.md)** est générée à partir du code source.
* Vous lisez avec un LLM ? Cette documentation est aussi publiée au format [llms.txt](https://llmstxt.org/) :
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) est un index des pages, et
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) contient toutes les pages dans un seul fichier.
