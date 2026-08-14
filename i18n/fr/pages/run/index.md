---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# Exécuter votre serveur {#running-your-server}

`mcp.run()` démarre le serveur.

La seule décision que vous prenez concerne le **transport** : la façon dont les octets circulent réellement entre votre serveur et son client.

## Choisir un transport {#pick-a-transport}

| Transport | Ce que c’est | Quand |
|---|---|---|
| `stdio` | L’hôte lance votre fichier comme sous-processus et communique via son stdin et son stdout. | Serveurs locaux. La valeur par défaut. |
| `streamable-http` | Un véritable serveur HTTP qui écoute sur un port. | Tout ce que vous déployez. |
| `sse` | L’ancien transport HTTP. | Jamais. |

!!! warning
    SSE a été remplacé par Streamable HTTP dans la révision 2025-03-26 du protocole.
    `mcp.run(transport="sse")` fonctionne toujours, avec ses propres options `sse_path=` et `message_path=`,
    mais il n’existe que pour les clients qui n’ont pas encore migré. Ne construisez rien de nouveau dessus.

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` est synchrone. Elle bloque pendant toute la durée de vie du serveur.
* Sans argument, le transport est `stdio`.
* Elle se trouve sous `if __name__ == "__main__":` parce que tout ce qui charge votre serveur (`mcp dev`, `mcp run`, `mcp install`, vos tests) **importe** ce fichier. La garde empêche un import de se transformer en serveur en cours d’exécution.

### stdio {#stdio}

Il n’y a rien à configurer. L’hôte démarre votre fichier comme processus enfant, écrit les requêtes sur son stdin et lit les réponses sur son stdout.

Lancez-le vous-même et vous en voyez la conséquence :

```console
python server.py
```

Rien ne s’affiche, et le programme ne rend pas la main. Il attend sur stdin qu’un hôte parle en premier.

Cela signifie aussi que stdout **est la liaison elle-même**. Pendant le service, le SDK déplace la liaison vers un descripteur privé et redirige vers stderr la sortie *vidée* sur stdout (un sous-processus qui écrit sur son stdout hérité, un `print()` vidé), où elle ne peut pas corrompre le flux. La sortie vidée sur stdout *avant* le début du service (un script d’enrobage qui affiche quelque chose, un print non tamponné au moment de l’import) atterrit toujours sur la liaison, de même qu’un `print()` qui reste en tampon jusqu’à ce que l’interpréteur le vide à la sortie. Pour la sortie que vous voulez réellement, le module `logging` est le bon outil : son gestionnaire vide chaque enregistrement sur stderr au moment où il se produit. Tous les détails sont dans **[Journalisation](../handlers/logging.md)**.

### Essayer {#try-it}

```console
uv run mcp dev server.py
```

L’Inspector fait exactement ce que fait un véritable hôte : il lance `server.py` comme sous-processus et s’y connecte via stdio.

Vous ne lui avez jamais donné de port. Il n’y en a pas.

## Streamable HTTP {#streamable-http}

Pour placer le même serveur sur un port à la place, nommez le transport (et ses options) dans `run()` :

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

Cette seule ligne construit une application Starlette et la sert avec uvicorn. Les clients se connectent à `http://127.0.0.1:3001/mcp`.

Chaque transport a ses propres arguments nommés, tous sur `run()` :

* `host` / `port` : où écouter. Valeurs par défaut `127.0.0.1` et `8000`.
* `streamable_http_path` : où se trouve le point de terminaison MCP. Valeur par défaut `/mcp`.
* `json_response=True` : répondre à chaque POST par un corps JSON unique au lieu d’un flux SSE. Ce corps a de la place pour la réponse et rien d’autre : un outil qui rappelle le client en cours de requête (`ctx.elicit()`, échantillonnage) lève donc `NoBackChannelError` sur ce tronçon, et les notifications liées à l’appel en cours (la progression de `ctx.report_progress()`, les messages de journal par appel) sont abandonnées ; le flux `GET` autonome transporte toujours celles qui n’y sont pas liées.
* `stateless_http=True` : un transport neuf par requête, sans suivi de session.
* `max_request_body_size` : la taille maximale acceptée pour le corps d’un POST, en octets. Vaut 4 Mio par défaut ; les requêtes plus grandes
  reçoivent un HTTP 413 avant toute analyse ou création de session. Ne l’augmentez que lorsque des messages MCP légitimes
  dépassent cette taille.
* `event_store`, `retry_interval`, `transport_security` : reprise après coupure et protection contre le DNS rebinding. Ils peuvent attendre, jusqu’à ce que vous déployiez ailleurs que sur localhost ; **[Déployer et passer à l’échelle](deploy.md)** couvre `transport_security`.

!!! warning
    Les options de transport vont à `run()`, **pas** à `MCPServer(...)`. Le constructeur décrit ce que
    votre serveur *est* : nom, version, instructions. `run()` décrit comment il est servi. Inversez-les
    et Python répond avant même que MCP n’entre en jeu :

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` est le chemin court. Dès que vous avez besoin de plus (votre serveur monté dans une application existante, deux serveurs dans un même processus, CORS pour les clients navigateur), vous construisez l’application ASGI vous-même et la confiez à n’importe quel hôte ASGI. C’est **[Ajouter à une application existante](asgi.md)**.

## Paramètres du serveur {#server-settings}

Quelques aspects de l’exécution ne concernent pas le transport. Ce sont des arguments du constructeur :

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level` : transmis à `logging.basicConfig()` au moment où `MCPServer(...)` est construit. Cela configure le logger **racine**, et fixe donc le niveau de vos propres loggers aussi, pas seulement ceux du SDK. Valeur par défaut `"INFO"`.
* `debug` : transmis à l’application Starlette que construisent les transports HTTP. Valeur par défaut `False`.

Les deux atterrissent sur `mcp.settings`, que vous pouvez relire à l’exécution.

## La commande `mcp` {#the-mcp-command}

L’extra `[cli]` installe un petit outil en ligne de commande autour de tout cela.

`mcp dev` exécute votre serveur sous le **MCP Inspector** :

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` ajoute des paquets à l’environnement qu’il construit ; `--with-editable` y installe votre propre paquet. Il a besoin de `npx` dans votre `PATH` : l’Inspector est une application Node.js.

`mcp run` importe le fichier, trouve l’objet serveur (un `mcp`, `server` ou `app` au niveau du module) et appelle `run()` dessus :

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

Le suffixe `:` nomme l’objet lorsqu’il ne s’appelle pas `mcp`, `server` ou `app`.

Votre bloc `if __name__ == "__main__":` ne s’exécute jamais ici : `mcp run` appelle `run()` lui-même, et la seule option qu’il transmet est `--transport`.

`mcp install` enregistre le serveur auprès de **Claude Desktop**, pour que l’application le lance pour vous :

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` et `-f .env` consignent des variables d’environnement dans cette entrée. Claude Desktop démarre votre serveur dans son propre processus. L’environnement de votre shell n’y est pas.

Claude Desktop est le seul hôte que `mcp install` connaît. Tous les autres hôtes (Claude Code, Cursor, VS Code) prennent la même commande de lancement dans leur propre fichier de configuration, et **[Se connecter à un véritable hôte](../get-started/real-host.md)** détaille chacun d’eux.

`mcp version` affiche la version du SDK installée.

!!! tip
    `mcp dev` et `mcp run` ne comprennent que `MCPServer`. Si vous construisez avec le `Server` bas niveau,
    vous l’exécutez vous-même. Voir **[Le Server bas niveau](../advanced/low-level-server.md)**.

## Récapitulatif {#recap}

* Un **transport** est la façon dont les octets atteignent votre serveur : `stdio` pour un sous-processus local, `streamable-http` pour un port. SSE est remplacé.
* `mcp.run()` choisit le transport. Sans argument, c’est `stdio`, et elle bloque.
* Chaque option de transport (`host`, `port`, `streamable_http_path`, ...) est un argument de `run()`, jamais de `MCPServer(...)`.
* Gardez `run()` sous `if __name__ == "__main__":`. Tout ce qui charge votre serveur importe d’abord le fichier.
* `log_level=` et `debug=` sont des arguments du constructeur ; ils atterrissent sur `mcp.settings`.
* `mcp dev` pour l’Inspector, `mcp run` pour exécuter un fichier, `mcp install` pour Claude Desktop, `mcp version` pour la version.
* Le transport ne change jamais ce que votre serveur *est* : les trois fichiers de cette page exposent le même outil, à l’identique.

Quand `run()` elle-même est la limite (votre serveur à l’intérieur d’une application qui existe déjà), c’est **[Ajouter à une application existante](asgi.md)**. Un vrai nom d’hôte et plus d’un worker, c’est **[Déployer et passer à l’échelle](deploy.md)**. Et si certains de vos clients sont encore sur la version 2025-11-25 de la spécification ou une version antérieure, **[Prendre en charge les clients historiques](legacy-clients.md)** est la bonne nouvelle.
