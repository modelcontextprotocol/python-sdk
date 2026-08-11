---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# Journalisation {#logging}

Journalisez depuis un outil comme vous le feriez depuis n’importe quelle autre fonction Python : avec la bibliothèque standard.

MCP possède une **capacité de journalisation** au niveau du protocole : un serveur pouvait envoyer ses messages de journal au client sous forme de notifications, via des méthodes de l’objet `Context`. La révision 2026-07-28 de la spécification **rend cette capacité obsolète sans la remplacer**, si bien que cette documentation ne l’enseigne pas. La liste complète de ce qui est obsolète, et de ce qu’il faut faire à la place, se trouve dans **[Fonctionnalités obsolètes](../deprecated.md)**.

Ce que vous faites à la place, c’est ce que vous faites dans tout autre programme Python : utiliser la bibliothèque standard.

## Un outil qui journalise {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` vous donne un logger nommé d’après votre module. Créez-le une seule fois, en haut du fichier.
* Dans l’outil, vous appelez `logger.info(...)` comme dans n’importe quelle autre fonction. Rien à injecter, rien à `await`, rien de spécifique à MCP.

!!! check
    Appelez l’outil et regardez le résultat complet :

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    La ligne de journal n’y figure nulle part. La journalisation est faite pour **vous**, la personne qui exploite le serveur. Le modèle
    ne la voit jamais. Si le modèle doit lire quelque chose, renvoyez-le avec `return`.

## Où cela va {#where-it-goes}

Pour un serveur **stdio**, cette question compte plus que d’habitude. L’hôte a lancé votre serveur comme sous-processus et lit les messages MCP depuis son **stdout**. La sortie d’erreur standard est à vous.

La bibliothèque standard fait déjà ce qu’il faut : la sortie des journaux va vers `sys.stderr` par défaut. Vos lignes `logger.info(...)` arrivent dans le terminal (ou là où l’hôte collecte le stderr du sous-processus), et le flux du protocole reste propre.

!!! tip
    N’utilisez pas `print()` dans un serveur stdio. `print` écrit sur **stdout**, et stdout appartient au protocole.
    Pendant qu’il sert, le SDK redirige vers stderr ce qui est effectivement *vidé* (flush) sur stdout, de sorte que cela ne peut pas corrompre
    la liaison ; mais dans un processus à tampon par blocs, un `print()` reste généralement non vidé dans le tampon de `sys.stdout`
    jusqu’à ce que l’interpréteur le purge à la sortie, directement sur le flux du protocole. Même lorsqu’elle est redirigée,
    la ligne arrive brute au milieu de la sortie des journaux, sans niveau, sans nom de logger et sans aucun moyen de la filtrer.

    `logger.debug("got here")` demande le même effort d’une ligne et va au bon endroit.

## Le niveau {#the-level}

Vous n’avez pas à appeler `logging.basicConfig()` vous-même. La construction d’un `MCPServer` l’a déjà fait, avec un gestionnaire de journalisation pointé vers la sortie d’erreur standard, au niveau que vous passez via `log_level=` ; `MCPServer("Bookshop", log_level="DEBUG")` suffit donc pour voir vos lignes `logger.debug(...)`.

La valeur par défaut est `"INFO"`.

`logging.basicConfig()` ne remplace jamais des gestionnaires de journalisation qui existent déjà. Si vous configurez la journalisation vous-même avant de créer le serveur, votre configuration l’emporte.

## Essayer {#try-it}

Lancez le serveur avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Appelez `search_books` depuis l’onglet **Tools**. L’Inspector vous montre le résultat : uniquement la valeur de retour. La ligne

```text
Searching for 'dune'
```

est partie vers la sortie d’erreur standard : le terminal, pas la liaison.

!!! info
    Si ce que vous voulez vraiment, c’est du *traçage* (chaque requête, sa durée, son éventuel échec), vous
    ne voulez pas des lignes de journal, vous voulez des spans. Votre serveur en émet déjà : le SDK trace chaque
    message avec OpenTelemetry par défaut. Voir **[OpenTelemetry](../run/opentelemetry.md)**.

## Récapitulatif {#recap}

* La capacité de journalisation du protocole MCP est rendue obsolète par la spécification 2026-07-28 et n’est pas remplacée. Ne construisez rien dessus.
* `logger = logging.getLogger(__name__)` au niveau du module, `logger.info(...)` dans l’outil. C’est tout le modèle à suivre.
* La sortie des journaux n’atteint jamais le modèle. Seule la valeur que vous renvoyez avec `return` y parvient.
* La sortie d’erreur standard est à vous ; stdout appartient au protocole. Pendant qu’il sert, le SDK redirige vers stderr ce qui s’égare sur stdout et est vidé, mais un `print()` non vidé peut encore se déverser sur la liaison à la sortie, et les lignes redirigées arrivent sans étiquette ; utilisez `logging`, dont le gestionnaire vide chaque enregistrement.
* `MCPServer(..., log_level="DEBUG")` fixe le niveau, et une configuration de journalisation que vous avez faite au préalable est laissée telle quelle.

Prévenir les clients connectés que quelque chose a changé sur votre serveur (la liste des outils, une ressource), c’est l’affaire des **[Abonnements](subscriptions.md)**.
