---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# Premiers pas {#first-steps}

La **[page d’accueil](../index.md)** va vite : écrire un serveur, l’exécuter, appeler un outil.

Cette page prend son temps, avec les trois choses qu’un serveur peut exposer, et un nom pour chaque notion rencontrée en chemin.

## Hôte, client et serveur {#host-client-and-server}

Trois mots que vous verrez sur chaque page à partir d’ici :

* Un **hôte** est l’application LLM : Claude, un IDE, un environnement d’exécution d’agents. C’est ce à quoi l’utilisateur parle.
* Un **client** vit à l’intérieur de l’hôte et parle MCP. L’hôte exécute un client par serveur auquel il est connecté.
* Un **serveur** est ce que vous construisez avec ce SDK. Il expose des choses aux clients. Il ne parle jamais directement au modèle.

Vous écrivez le serveur. Les hôtes sont le produit de quelqu’un d’autre. Le SDK vous fournit aussi un `Client`. Vous l’utiliserez pour tester vos serveurs, et il apparaît plus loin sur cette page.

## Les trois primitives {#the-three-primitives}

Un serveur expose exactement trois sortes de choses. Ce qui les distingue, c’est **qui décide de les utiliser** :

| Primitive      | Contrôlée par   | Ce que c’est                                                         | Exemple                                        |
|----------------|-----------------|----------------------------------------------------------------------|------------------------------------------------|
| **Outils**     | Le modèle       | Une fonction que le modèle appelle pour agir                         | Un appel d’API, une écriture en base de données |
| **Ressources** | L’application   | Des données que l’hôte charge dans le contexte du modèle             | Le contenu d’un fichier, une réponse d’API      |
| **Prompts**    | L’utilisateur   | Un modèle de message réutilisable que l’utilisateur invoque par son nom | Une commande slash, une entrée de menu          |

« Contrôlée par » est tout l’intérêt de la distinction. Un outil s’exécute parce que le **modèle** a décidé de l’appeler. Une ressource est jointe parce que l’**application** a décidé que le modèle en avait besoin. Un prompt s’exécute parce que l’**utilisateur** l’a choisi.

!!! info
    Si vous avez déjà construit une API web, vous avez l’essentiel de l’intuition : une **ressource** est un `GET`
    (elle charge des données et ne modifie rien) et un **outil** est un `POST` (il effectue un travail et peut avoir
    des effets de bord). Un **prompt** n’a pas d’équivalent HTTP ; il se rapproche d’une requête enregistrée que
    l’utilisateur exécute par son nom.

## Un serveur, les trois à la fois {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Trois fonctions ordinaires, trois décorateurs. Chaque décorateur constitue à lui seul tout l’enregistrement :

* `@mcp.tool()` fait de `add` un **outil**.
* `@mcp.resource("greeting://{name}")` fait de `greeting` un **modèle de ressource** (resource template) : le `{name}` dans l’URI est le paramètre de la fonction.
* `@mcp.prompt()` fait de `summarize` un **prompt**. La chaîne qu’il renvoie devient un message utilisateur.

Tout le reste (le nom, la description, le schéma des arguments), le SDK le lit dans la fonction elle-même : son nom, sa docstring, ses annotations de type. Vous n’avez rien déclaré de tout cela séparément.

!!! tip
    Les deux moitiés du SDK ont deux chemins d’import : `from mcp import Client` et
    `from mcp.server import MCPServer`. Il n’existe pas de `from mcp import MCPServer`.

### Essayer {#try-it}

Lancez-le avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Ouvrez l’URL qu’il affiche. L’Inspector a un onglet par primitive ; parcourez-les dans l’ordre.

**Tools.** Une entrée : `add`, décrite comme *Add two numbers.* Le formulaire comporte un champ entier obligatoire pour `a` et un autre pour `b`. Remplissez-les, lancez l’appel, et le résultat est `3`. L’Inspector a construit ce formulaire à partir de `a: int, b: int`. Tous les autres clients font de même.

**Resources.** La liste *Resources* est vide. `greeting` se trouve sous **Resource Templates**, parce que `greeting://{name}` a un paramètre : il n’y a aucune ressource unique à lister tant que personne n’a fourni de `name`. Donnez-lui `World` et lisez-la :

```text
Hello, World!
```

**Prompts.** Une entrée : `summarize`, avec un seul argument obligatoire, `text`. Récupérez-le avec un peu de texte et vous recevez un message avec `role: user` et votre chaîne rendue comme contenu. Un prompt n’est rien d’autre que cela : une fonction qui construit des messages.

L’Inspector a exécuté votre serveur via **stdio**, l’un des transports qu’un serveur MCP peut parler. Vous n’en choisissez pas encore un ; **[Exécuter votre serveur](../run/index.md)** est la page consacrée à ce sujet.

## Capacités {#capabilities}

Vous avez vu trois onglets dans l’Inspector. Comment savait-il qu’il y en avait trois ?

Lorsqu’un client se connecte, le serveur déclare ses **capacités** (capabilities) : les familles de requêtes auxquelles il répondra. Le client utilise cette déclaration pour décider de ce qu’il peut même demander. Vous ne l’avez jamais écrite ; `MCPServer` la déclare pour vous.

Regardez par vous-même. Le `Client` du SDK accepte directement l’objet serveur et s’y connecte **en mémoire** (ni sous-processus, ni port) :

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

Ce dictionnaire, ce sont les **capacités** déclarées de votre serveur. C’est la première chose qu’apprend chaque client qui se connecte :

| Capacité    | Le client peut désormais appeler                              |
|-------------|---------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                     |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                                  |

`MCPServer` sert les trois primitives, donc les trois sont toujours déclarées.

Remarquez ce qui n’y figure pas. `completions` (la complétion automatique des arguments pour les modèles de ressources et les prompts) nécessite un gestionnaire que vous écrivez ; ce serveur n’en a pas, donc la capacité est absente et un client bien élevé ne demandera rien. C’est la règle pour tout ce qui est facultatif : enregistrez la chose et la capacité apparaît ; **[Complétions](../servers/completions.md)** le prouve.

!!! info
    `Client(mcp)` est le même client en mémoire avec lequel chaque exemple de cette documentation est testé, et
    c’est ainsi que vous testerez les vôtres. Il a droit à une page entière : **[Tester](testing.md)**.

## Ce que vous n’avez pas écrit {#what-you-did-not-write}

Reprenez cette page depuis le début. Vous avez écrit trois petites fonctions Python. Vous n’avez **pas** écrit :

* De JSON Schema. `a: int, b: int` *est* le schéma de `add`.
* De gestionnaire de requêtes. `tools/list`, `resources/read`, `prompts/get` : tous servis pour vous.
* De déclaration de capacités. `MCPServer` l’a faite pour vous.
* Une seule ligne de protocole. La négociation de version, l’encapsulation JSON-RPC, l’échange de capacités : tout cela s’est passé à l’intérieur de `mcp dev` et de `Client(mcp)`, et vous n’en avez rien vu.

Ce rapport est tout l’intérêt du SDK.

## Récapitulatif {#recap}

* Un **hôte** est l’application LLM, un **client** est sa moitié qui parle MCP, un **serveur** est ce que vous construisez.
* Les outils sont contrôlés par le **modèle**, les ressources par l’**application**, les prompts par l’**utilisateur**.
* Un décorateur par primitive : `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Le nom, la description et le schéma viennent de la fonction.
* Un URI avec un `{param}` crée un **modèle** de ressource, listé séparément des ressources concrètes.
* Les **capacités** du serveur sont déclarées pour vous, et un client ne demande que ce qu’un serveur déclare.
* `Client(mcp)` se connecte à l’objet serveur en mémoire : votre banc d’essai dès le premier jour.

La suite, c’est **[Se connecter à un vrai hôte](real-host.md)** : ce serveur dans Claude Desktop ou un IDE, pour de vrai. Puis **[Tester](testing.md)** : une page, un client en mémoire, et vous n’aurez plus jamais à deviner si cela fonctionne. Ensuite, chaque primitive a droit à sa propre page, en commençant par celle que pilote le modèle : **[Outils](../servers/tools.md)**.
