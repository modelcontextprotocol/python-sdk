---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# Groupes de sessions {#session-groups}

Un `Client` se connecte à un seul serveur. Les applications réelles en veulent souvent plusieurs (un serveur de recherche, un serveur de base de données, une API interne) et finissent par jongler avec une connexion et une liste d’outils pour chacun.

**`ClientSessionGroup`** est un objet unique qui détient de nombreuses connexions et fusionne tout ce qu’elles exposent en une seule vue.

## Deux serveurs {#two-servers}

Commencez par deux serveurs ordinaires. Ils n’ont rien à voir l’un avec l’autre, si bien que tous deux ont naturellement appelé leur outil `search` :

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## Un groupe {#one-group}

Créez un `ClientSessionGroup` et appelez **`connect_to_server`** une fois par serveur :

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` prend des paramètres de transport, pas un objet serveur : `StdioServerParameters` (depuis `mcp`) pour lancer un sous-processus, ou `StreamableHttpParameters` / `SseServerParameters` (depuis `mcp.client.session_group`) pour un serveur qui écoute déjà sur une URL.
* `group.tools` est un `dict[str, Tool]` regroupant les outils de tous les serveurs connectés. `group.resources` et `group.prompts` ont la même forme.
* `group.call_tool(name, arguments)` recherche le nom, trouve la session qui le possède et lui transmet l’appel. Vous n’indiquez jamais quel serveur.

!!! check
    Placez `client.py` à côté des deux serveurs et exécutez-le. Le second `connect_to_server` refuse :

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    C’est une `MCPError`, levée avant que quoi que ce soit du second serveur ne soit enregistré. Un nom doit
    être unique dans **tout** le groupe, et deux serveurs que vous ne contrôlez pas finiront tôt ou tard par entrer en collision.

## `component_name_hook` {#component_name_hook}

Vous corrigez cela au niveau du groupe, pas des serveurs. Passez une fonction de `(name, server_info)` et le groupe l’exécute sur chaque nom qu’il enregistre :

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

Relancez-le. `print(sorted(group.tools))` affiche maintenant les deux :

```text
['Library.search', 'Web.search']
```

* La **clé** est à vous. `by_server` l’a construite à partir de `server_info.name`, le nom avec lequel chaque `MCPServer(...)` a été construit.
* Le `Tool` à l’intérieur est intact : `group.tools["Web.search"].name` vaut toujours `"search"`, et c’est ce nom que `call_tool` envoie sur la liaison. Le préfixe ne quitte jamais votre processus.
* Cela ne concerne pas que les outils. La ressource `hours` de la bibliothèque est enregistrée sous le nom `Library.hours`.

!!! tip
    Le hook s’exécute sur **chaque** nom de **chaque** serveur, pas seulement en cas de conflit : il n’existe pas de
    mode « préfixe en cas de collision ». Choisissez un schéma et laissez-le s’appliquer partout.

## Ajouter et retirer des serveurs {#adding-and-removing-servers}

`connect_to_server` renvoie la `ClientSession` qu’il a ouverte. Conservez-la si vous voulez un jour vous séparer de ce serveur : `await group.disconnect_from_server(session)` retire ses outils, ressources et prompts du groupe.

Si vous détenez déjà une `ClientSession` connectée (`Client.session` en est une), passez-la à `await group.connect_with_session(server_info, session)` au lieu d’ouvrir un nouveau transport. Elle est agrégée de la même façon. Le groupe ne ferme jamais une session qu’il n’a pas ouverte. `server_info` nomme le serveur pour les préfixes de composants ; sur une connexion de génération 2026, `client.server_info` peut valoir `None` (l’identité est facultative), passez donc votre propre `Implementation(name=..., version=...)` dans ce cas.

## La poignée de main classique {#the-classic-handshake}

`ClientSessionGroup` est construit sur `ClientSession`, pas sur `Client`. Chaque `connect_to_server` exécute la poignée de main (handshake) `initialize` classique. Il n’envoie jamais la sonde `server/discover` décrite dans **[Versions du protocole](../protocol-versions.md)**. Tous les serveurs MCP comprennent cette poignée de main, donc cela ne vous coûte aucune compatibilité ; cela signifie seulement qu’un groupe emprunte le chemin plus ancien et plus lent vers un serveur qui pourrait faire mieux.

## Récapitulatif {#recap}

* `ClientSessionGroup` détient de nombreuses connexions serveur et fusionne leurs outils, ressources et prompts en un `dict` chacun.
* `connect_to_server(params)` par serveur. Il prend des paramètres de transport, jamais l’objet serveur ni l’URL que prend un `Client`.
* `group.call_tool(name, arguments)` achemine l’appel vers le serveur propriétaire à votre place.
* Les noms doivent être uniques dans tout le groupe ; deux serveurs dotés d’un outil `search` ne peuvent pas coexister tels quels.
* `component_name_hook=` réécrit chaque nom enregistré. La clé du dict change, pas le nom sur la liaison.
* `connect_with_session` ajoute une session que vous détenez déjà ; `disconnect_from_server` en retire une.

La poignée de main que parle un groupe (et celle, plus rapide, que préfère un `Client`) fait l’objet de **[Versions du protocole](../protocol-versions.md)**.
