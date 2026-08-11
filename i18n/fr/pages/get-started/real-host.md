---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# Se connecter à un véritable hôte {#connect-to-a-real-host}

Un **hôte** est l’application dans laquelle votre serveur finit par vivre : Claude Desktop, Claude Code, un IDE. L’hôte est ce à quoi l’utilisateur parle. À l’intérieur, un **client** MCP lance votre serveur comme processus enfant et lui parle via le stdin et le stdout de ce processus.

Se connecter à un hôte se résume donc à un seul geste : vous lui indiquez **la commande qui démarre votre serveur**. Tout ce qui figure sur cette page (deux commandes CLI, trois fichiers JSON) n’est qu’un endroit différent où placer cette même commande.

## Un serveur, tous les hôtes {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

Deux outils et une ressource, un seul fichier. Trois points concernant ce fichier comptent pour chaque hôte ci-dessous :

* `mcp.run()` sans argument démarre un serveur **stdio** : il bloque, lit les messages du protocole sur stdin et les écrit sur stdout. C’est le transport que parlent tous les hôtes de cette page. L’hôte démarre votre fichier comme processus enfant et possède ces deux tubes, c’est pourquoi se connecter ne revient jamais qu’à « voici la commande ». Vous ne choisissez jamais de port, et rien n’écoute sur un port.
* `run()` est placé sous `if __name__ == "__main__":`. Tout ce qui suit **importe** ce fichier au lieu de l’exécuter ; un `run()` non protégé démarrerait donc un serveur dès que quoi que ce soit chargerait le module.
* L’objet serveur est une variable globale de niveau module nommée `mcp`. C’est le nom que `mcp run` recherche (`server` et `app` fonctionnent aussi). Si vous l’appelez autrement, vous le nommez explicitement : `mcp run server.py:bookshop`.

C’est la dernière ligne de Python de cette page. À partir d’ici, tout n’est que configuration d’hôte.

## La commande de lancement {#the-launch-command}

Chaque hôte ci-dessous reçoit la même commande :

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Une seule commande pour tous, parce que `uv run --with` résout le SDK dans un environnement neuf, à la volée : elle fonctionne depuis n’importe quel répertoire et n’a besoin d’aucun projet ni d’aucun environnement virtuel à activer. Cela compte ici plus qu’ailleurs, car un hôte lance votre serveur depuis *son* répertoire de travail avec un environnement presque vide, et non depuis votre shell.

C’est aussi la commande que `mcp install` écrit pour vous dans la configuration de Claude Desktop (ci-dessous) : ce que vous tapez à la main et ce que l’outil génère concordent, à l’exception de l’épinglage de version exact que l’outil ajoute.

!!! tip "Si un hôte ne trouve pas `uv`"
    Un hôte lance votre serveur avec un `PATH` minimal, et `uv` n’y figure peut-être pas.
    Remplacez le `uv` seul par le chemin absolu donné par `which uv` (macOS/Linux) ou `where uv`
    (Windows). C’est exactement ce qu’écrit `mcp install`.

!!! note "Cette page traite du cas local"
    Tout ici exécute votre serveur sur la machine où se trouve l’hôte : l’hôte lance votre
    fichier, via stdio. C’est exactement ce qu’il faut pour un outil personnel ou limité à une
    seule machine. Pour mettre un serveur à disposition de personnes qui n’ont *pas* votre
    fichier, vous distribuez une **URL**, pas une commande : le même objet `mcp`, servi via
    Streamable HTTP. **[Exécuter votre serveur](../run/index.md)** résume cette décision en un
    tableau, et **[Déployer et passer à l’échelle](../run/deploy.md)** est le chemin qui mène de
    là à un véritable nom d’hôte.

    Et un hôte n’est rien de plus qu’une application contenant un client MCP ; votre propre
    code Python peut donc jouer le rôle de l’hôte : **[Transports du client](../client/transports.md)**
    lance ce même fichier comme sous-processus avec `stdio_client(...)`, et **[Tests](testing.md)**
    s’y connecte en mémoire, sans aucun processus.

## Claude Desktop {#claude-desktop}

Le seul hôte que le SDK peut configurer pour vous :

```bash
uv run mcp install server.py
```

C’est tout. `mcp install` importe le fichier pour lire le nom du serveur, trouve le fichier de configuration de Claude Desktop et y écrit la commande de lancement. Au passage, il convertit votre chemin en chemin absolu, pour que vous n’ayez pas à le faire.

Il n’y a là rien de mystérieux. Voici l’entrée qu’il écrit :

```json
{
  "mcpServers": {
    "Bookshop": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--frozen",
        "--with",
        "mcp[cli]==2.0.0",
        "mcp",
        "run",
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

C’est la commande de lancement de la section précédente avec trois ajouts : le chemin absolu vers `uv`, `--frozen` pour que `uv` ne réécrive jamais un fichier de verrouillage qui se trouverait à proximité, et un épinglage exact de la version de `mcp` que vous avez installée. Elle atterrit dans `claude_desktop_config.json`, qui se trouve ici :

* **macOS** : `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows** : `%APPDATA%\Claude\claude_desktop_config.json`

Vous pouvez écrire ce fichier à la main. `mcp install` existe pour vous éviter l’erreur classique (un chemin relatif) en le faisant.

Quittez complètement Claude Desktop (pas seulement sa fenêtre), puis rouvrez-le.

!!! warning
    `mcp install` échoue avec `Claude app not found` si le *répertoire* de configuration de
    Claude Desktop n’existe pas encore. Installez Claude Desktop et lancez-le une fois : c’est
    ce qui crée le répertoire.

!!! tip
    Claude Desktop démarre votre serveur dans son propre processus ; les variables
    d’environnement de votre shell n’y sont donc pas. `uv run mcp install server.py -v API_KEY=abc123`
    (ou `-f .env`) les enregistre dans le champ `env` de l’entrée. `--name` remplace le nom de
    l’entrée ; par défaut, c’est le `name` du serveur.

## Claude Code {#claude-code}

Il n’y a aucun fichier à modifier. Enregistrez le serveur avec la CLI `claude` ; tout ce qui suit `--` est la commande de lancement.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Exécutez `/mcp` dans une session Claude Code pour confirmer que `bookshop` est connecté et que ses outils sont listés.

## Cursor {#cursor}

Créez `.cursor/mcp.json` à la racine de votre projet.

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Les mêmes `command` et `args`, sous la même clé `mcpServers` que celle qu’utilise Claude Desktop. Le serveur apparaît dans les paramètres MCP de Cursor avec les deux outils listés.

## VS Code {#vs-code}

Créez `.vscode/mcp.json` à la racine de votre projet.

```json
{
  "servers": {
    "bookshop": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Deux différences avec le fichier de Cursor, et ce sont les deux seules : la clé englobante est `servers`, et non `mcpServers`, et chaque entrée déclare son `type`. Acceptez la demande de confiance, puis **MCP: List Servers** dans la palette de commandes affiche `bookshop` en cours d’exécution.

!!! note
    Il vous faut VS Code 1.99 ou ultérieur avec l’extension **GitHub Copilot** connectée
    (Copilot Free suffit), et Copilot Chat doit être en mode **Agent**, car aucun autre mode
    n’appelle d’outils.

## Le serveur n’apparaît pas {#it-doesnt-show-up}

Avant de toucher à la moindre configuration d’hôte, exécutez vous-même la commande de lancement :

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Rien ne s’affiche, et la commande ne rend pas la main. Ce silence est normal : un serveur stdio attend qu’un hôte parle en premier sur stdin (`Ctrl-C` pour l’arrêter). Une trace d’erreur ou une sortie immédiate, voilà le vrai bogue, et vous pouvez désormais le lire au lieu de le deviner à travers un hôte.

Une fois que cette commande se contente d’attendre, ce qui reste est presque toujours l’une de ces trois causes :

* **Un chemin relatif.** L’hôte lance votre serveur depuis *son* répertoire de travail, pas depuis celui d’où vous l’avez enregistré. `server.py` là où il faut `/absolute/path/to/server.py` est, de loin, l’échec le plus fréquent. Si l’hôte ne trouve pas `uv` non plus, ce chemin doit lui aussi être absolu.
* **L’hôte utilise encore son ancienne configuration.** Les hôtes lisent leur configuration au démarrage. Claude Desktop, en particulier, doit être *complètement quitté* (pas seulement sa fenêtre fermée) puis rouvert avant qu’une modification de `claude_desktop_config.json` prenne effet.
* **Quelque chose a atteint stdout en dehors de la fenêtre de redirection.** En stdio, stdout *est* le protocole. Le SDK redirige vers stderr la sortie parasite vidée pendant qu’il sert, mais une sortie vidée sur stdout avant cela (un script d’enrobage qui fait un echo, un `print()` à l’import dans un processus sans tampon), ou un `print()` mis en tampon et vidé à la sortie de l’interpréteur, remet à l’hôte un message corrompu et celui-ci coupe la connexion. Journalisez avec la configuration `logging` par défaut, dont le gestionnaire stderr vide chaque enregistrement ; les gestionnaires personnalisés doivent eux aussi éviter stdout. Tous les détails sont dans **[Journalisation](../handlers/logging.md)**.

Claude Desktop tient un journal par serveur : `mcp-server-<NAME>.log` est le stderr de votre serveur, à côté de `mcp.log` pour les connexions, sous `~/Library/Logs/Claude` sur macOS et `%APPDATA%\Claude\logs` sur Windows.

Pour tout ce qui dépasse ces trois cas, la page à consulter est **[Dépannage](../troubleshooting.md)**.

## Récapitulatif {#recap}

* Un **hôte** (Claude Desktop, un IDE) exécute un client MCP qui lance votre serveur comme processus enfant via stdio. Se connecter, c’est lui donner une commande de lancement.
* Cette commande est `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py` : aucun venv à activer, elle fonctionne depuis n’importe quel répertoire.
* **Claude Desktop** est le seul hôte que `mcp install` configure pour vous. Il écrit cette même commande (plus le chemin absolu vers `uv`, `--frozen` et un épinglage exact de la version que vous avez installée) dans `claude_desktop_config.json`, pour que vous n’ayez jamais à le faire.
* **Claude Code**, c’est `claude mcp add bookshop -- <launch command>`. **Cursor**, c’est `.cursor/mcp.json` sous `mcpServers`. **VS Code**, c’est `.vscode/mcp.json` sous `servers`, chaque entrée avec un `type`.
* Des chemins absolus partout, redémarrez l’hôte après avoir modifié sa configuration, et ne laissez jamais rien d’autre que le SDK écrire sur stdout.

Tous les hôtes de cette page se sont connectés au même fichier, avec la même commande. Ce que ce fichier peut *exposer*, c’est le reste de cette documentation : **[Outils](../servers/tools.md)**, **[Ressources](../servers/resources.md)**, et tous les transports autres que stdio dans **[Exécuter votre serveur](../run/index.md)**.
