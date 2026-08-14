---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# Médias {#media}

Le texte n’est pas la seule chose qu’un outil (tool) peut renvoyer.

Le SDK fournit deux utilitaires pour les résultats binaires (**`Image`** et **`Audio`**) et un type **`Icon`** pour donner un visage à votre serveur, à vos outils, à vos ressources et à vos prompts dans l’interface du client.

## Renvoyer une image {#returning-an-image}

Annotez le type de retour avec `Image`, pointez-le vers un fichier, et renvoyez-le :

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` prend exactement l’un des deux : `path` (un fichier à lire) ou `data` (des octets bruts).
* Le type MIME que voit le client est deviné à partir de l’extension : `logo.png` est annoncé comme `image/png`.
* Les logos n’ont rien de particulier ici. N’importe quel PNG placé à côté de `server.py` convient : un graphique que votre code a généré, un schéma, une photo.

`Image` est une commodité du SDK, pas un type du protocole. Sur la liaison, votre valeur de retour devient un bloc **`ImageContent`** (les octets du fichier encodés en base64, plus le type MIME) :

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Deux choses à remarquer :

* `data` est en base64. Vous n’avez jamais touché aux octets ; le SDK a lu le fichier et s’est chargé de l’encodage.
* `structured_content` vaut `None`. Une `Image` est du contenu que le modèle regarde, pas des données que l’application analyse : il n’y a pas de schéma de sortie. (À comparer avec la **[Sortie structurée](structured-output.md)**, où l’annotation de retour *est* le schéma.)

!!! info
    `ImageContent` et `AudioContent` se trouvent dans `mcp.types`, juste à côté du `TextContent`
    que devient un simple résultat `str` (**[Outils](tools.md)**). Un résultat d’outil est une liste de blocs de contenu ; `Image` et `Audio` sont
    le moyen le plus court de produire les deux variantes binaires.

### Essayer {#try-it}

Déposez n’importe quel PNG à côté de `server.py`, nommez-le `logo.png`, et lancez :

```console
uv run mcp dev server.py
```

Ouvrez l’onglet **Tools** et appelez `logo`. Le résultat n’est pas une chaîne : c’est un bloc de contenu `image`, et l’Inspector affiche votre image. Tout ce qui s’est passé entre le fichier sur le disque et les pixels à l’écran, c’est le SDK.

## Renvoyer de l’audio {#returning-audio}

`Audio` a la même forme. Laissez `logo.png` là où il était, et placez n’importe quel WAV à côté, sous le nom `chime.wav` :

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

Le résultat est un bloc **`AudioContent`** :

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

Même principe : un fichier sur le disque en entrée, du base64 et un type MIME en sortie, pas de schéma de sortie.

## Des octets ou un fichier {#bytes-or-a-file}

Les deux utilitaires acceptent aussi `data=` (des octets bruts) à la place de `path=`. C’est le mode prévu pour des octets qui n’ont jamais eu de fichier à eux — une colonne de base de données, une réponse HTTP, quelque chose que Pillow vient de dessiner :

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

Avec `path=`, il n’y a rien à déclarer : le fichier est lu au moment où le résultat est construit, et le type MIME est deviné à partir de l’extension :

* `Image` : `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio` : `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

Une extension qu’il ne reconnaît pas se rabat sur `application/octet-stream`.

!!! check
    Avec `data=`, il n’y a pas de nom de fichier, donc rien à partir de quoi deviner. Oubliez `format=` et
    le SDK se rabat sur une valeur par défaut : `image/png` pour les images, `audio/wav` pour l’audio. Construisez un
    `Audio` à partir d’octets MP3 de cette façon et le client reçoit `mime_type="audio/wav"`, puis
    échoue consciencieusement à le décoder. Quand vous passez `data=`, passez `format=`.

## Icônes {#icons}

Une `Icon` est une métadonnée, pas du contenu. Elle ne transporte pas l’image ; elle en désigne une par un URI, et un client peut la récupérer et l’afficher à côté du nom de votre serveur, d’un outil, d’une ressource ou d’un prompt.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` est un URI que le client peut résoudre : `https:`, ou un URI `data:` si vous voulez l’icône embarquée sans récupération supplémentaire.
* `mime_type` et `sizes` (`"48x48"`, ou `"any"` pour un format vectoriel) permettent au client de choisir la bonne lorsque vous en proposez plusieurs.
* `theme="light"` ou `theme="dark"` réserve une icône à un jeu de couleurs.

Le même mot-clé `icons=[...]` est accepté par `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()` et `@mcp.prompt()`.

### Où un client les voit {#where-a-client-sees-them}

Les icônes voyagent avec ce qu’elles décorent. Celles du serveur arrivent quand le client se connecte, sur `client.server_info` (facultatif sur les connexions de génération 2026, donc restreignez d’abord le type) :

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

Les icônes d’un outil sont sur l’objet `Tool` issu de `tools/list`, celles d’une ressource sur le `Resource` issu de `resources/list`, celles d’un prompt sur le `Prompt` issu de `prompts/list`. Le champ s’appelle toujours `icons`.

## Récapitulatif {#recap}

* Renvoyez une `Image` ou un `Audio` depuis un outil et le client reçoit un bloc `ImageContent` / `AudioContent` : vos octets encodés en base64, avec un type MIME.
* Construisez-en un à partir d’un `path=` et laissez l’extension décider du type MIME, ou à partir de `data=` en mémoire plus un `format=` explicite.
* Les résultats média ne portent ni `structured_content` ni schéma de sortie.
* Une `Icon` est un pointeur : un URI `src` plus, en option, `mime_type`, `sizes` et `theme`.
* `icons=[...]` fonctionne sur le serveur, sur les outils, sur les ressources et sur les prompts, et les clients les retrouvent sur les objets correspondants.

C’est tout ce qu’un outil peut mettre *dans* un résultat. Ce qui se passe quand un outil *échoue* (et qui doit l’apprendre), c’est **[Gérer les erreurs](handling-errors.md)**.
