---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

Une **MCP App** est un outil doté d’une interface : en plus de ses données, l’outil désigne un document HTML que l’hôte affiche comme surface interactive.

Deux parties, toujours deux parties :

1. **Un outil** qui fait le travail et renvoie des données, comme n’importe quel autre outil.
2. **Une ressource `ui://`** contenant le HTML que l’hôte affiche pour lui.

L’outil porte une référence `_meta.ui.resourceUri` vers la ressource. L’hôte la récupère avec `resources/read`, l’affiche dans une **iframe isolée (sandbox)** et pousse le résultat de l’outil dans cette iframe via `postMessage`. Votre serveur n’envoie ni ne reçoit jamais de messages `ui/*` : ce trafic circule entre l’hôte et l’iframe. Vous servez un outil et un document HTML ; l’hôte se charge de la mise en scène.

Le SDK fournit cela sous la forme de l’extension intégrée `Apps` (`io.modelcontextprotocol/ui`). Si les [extensions](extensions.md) sont nouvelles pour vous, parcourez d’abord cette page. Une minute, puis revenez.

## Une horloge avec un cadran {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

Quatre étapes :

* `Apps()` : une seule instance contient vos outils liés à une interface et leurs ressources.
* `@apps.tool(resource_uri="ui://clock/app.html")` : un outil ordinaire, plus le marquage `_meta.ui.resourceUri`. Tout ce que `@mcp.tool()` accepte (name, title, description, …) est transmis tel quel.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)` : la ressource correspondante, servie en `text/html;profile=mcp-app`. C’est ce type MIME exact qui indique à un hôte « ceci est une app, affichez-la ».
* `MCPServer("clock", extensions=[apps])` : vous activez l’extension. Le serveur annonce désormais `io.modelcontextprotocol/ui` sous `capabilities.extensions`.

Le HTML lui-même écoute le `postMessage` de l’hôte et affiche le résultat. Pour de vraies applications, utilisez dans votre HTML le SDK navigateur officiel [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps). Il vous donne `ontoolresult`, `callServerTool`, `getHostContext` et `onhostcontextchanged` au lieu d’événements de message bruts.

## Dégradation gracieuse {#graceful-degradation}

Tous les clients n’affichent pas les apps. La spécification dit sans détour ce que cela implique pour vous :

> Les outils **DOIVENT** renvoyer un tableau `content` significatif même lorsqu’une interface est disponible.

Le modèle lit `content` ; l’iframe est pour les humains. Un hôte capable d’afficher une interface transmet quand même le résultat textuel au modèle, et un client purement textuel ne reçoit *que* cela. Le schéma canonique est donc : un outil, deux réponses. Regardez à nouveau `get_time` :

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` ne vaut `True` que lorsque le client a déclaré l’extension `io.modelcontextprotocol/ui` **et** listé `text/html;profile=mcp-app` dans ses paramètres `mimeTypes`. Le champ est obligatoire, donc un client qui l’omet ne compte pas. C’est exactement ce que déclare `main()` dans le même fichier : la moitié client de la négociation, et la réponse riche revient.

!!! warning
    Ne renvoyez jamais un texte de substitution comme `"[Rendered UI]"` pour seul contenu. Si le texte de repli est inutile, l’outil est inutile pour tout client purement textuel et pour le modèle lui-même. Écrivez la phrase.

## Verrouiller l’iframe {#locking-the-iframe-down}

C’est le côté ressource qui porte les métadonnées de sécurité : ce que l’iframe peut charger, les permissions du navigateur qu’elle souhaite, la façon dont elle aimerait être encadrée :

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` et `permissions` sont des **demandes adressées à l’hôte**, pas un comportement du serveur. L’hôte construit à partir d’elles la Content-Security-Policy et la Permissions-Policy de l’iframe, et il peut refuser. Faites de la détection de fonctionnalités dans votre JS plutôt que de supposer l’accord acquis.

`ResourceCsp`, champ par champ (nom Python, clé sur la liaison, ce que l’hôte en fait) :

| Python | Liaison (`_meta.ui.csp`) | Contrôle |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src` : où `fetch`/XHR peuvent aller |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, … : fichiers statiques |
| `frame_domains` | `frameDomains` | `frame-src` : iframes imbriquées |
| `base_uri_domains` | `baseUriDomains` | `base-uri` : ce vers quoi `<base>` peut pointer |

`ResourcePermissions` : chaque champ demande une permission du navigateur pour l’iframe.

| Python | Liaison (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    La CSP et les permissions vivent sur la **ressource**, jamais sur l’outil. Les métadonnées d’outil de la spécification n’ont pas d’emplacement pour elles, et les hôtes les ignorent à cet endroit. Le SDK rend l’erreur impossible à exprimer : `@apps.tool()` n’a tout simplement pas de paramètre `csp`.

### Visibilité {#visibility}

`visibility=["app"]` sur un outil dit « ceci existe pour l’iframe, pas pour le modèle » :

* `"model"` : le modèle peut l’appeler.
* `"app"` : l’iframe peut l’appeler (via `callServerTool`).
* Omis : les deux, ce qui est la valeur par défaut.

Le filtrage est le travail de **l’hôte**. Votre serveur liste les outils réservés à l’app dans `tools/list` comme les autres ; l’hôte les cache au modèle. Ne filtrez pas côté serveur.

## Les règles que le SDK fait respecter {#the-rules-the-sdk-enforces}

Toutes échouent au démarrage, pas en production :

* Un `resource_uri` ou un URI de ressource qui n’est pas `ui://...` lève une `ValueError` au moment de la décoration ou de l’enregistrement.
* Un outil lié à un URI **sans ressource enregistrée correspondante** lève une `ValueError` lorsque `MCPServer(extensions=[apps])` consomme l’extension. Un outil qui annonce du HTML répondant 404 sur `resources/read` est une erreur de configuration, donc le serveur refuse de se construire.
* `meta={"ui": ...}` sur `@apps.tool()` lève une `ValueError`. Le décorateur est propriétaire de `_meta["ui"]` ; exprimez-le avec `resource_uri=` et `visibility=`. Les autres clés `meta=` se fusionnent sans problème à côté.

Ni le SDK TypeScript ext-apps ni FastMCP ne détectent ces cas aujourd’hui ; nous préférons que vous le découvriez avant qu’un hôte ne le fasse.

## Au-delà du HTML inline {#beyond-inline-html}

`add_html_resource` couvre le cas courant : une chaîne de HTML. Pour tout le reste, HTML sur disque ou contenu généré, construisez la ressource vous-même et transmettez-la :

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource` renseigne le type MIME `text/html;profile=mcp-app` quand la ressource n’en définit pas explicitement, et rejette une incohérence explicite : une ressource `ui://` sous tout autre type MIME est une ressource qu’aucun hôte n’affichera.

!!! tip
    Vous ciblez un hôte d’avant la disponibilité générale qui lit encore la clé plate obsolète `_meta["ui/resourceUri"]` ? Fusionnez-la vous-même : `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`. L’objet `ui` imbriqué est la forme prévue par la spécification ; la clé plate est en voie de disparition.

## Le voir en action {#see-it-run}

Le scénario `apps` dans `examples/stories/`, c’est cette page sous forme de paire exécutable : un serveur avec un outil horloge lié à une interface et un client qui négocie Apps, lit le `_meta.ui.resourceUri` de l’outil, récupère le HTML et appelle l’outil.

```bash
uv run python -m stories.apps.client
```
