---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# Modèles d’URI et sûreté des chemins {#uri-templates-and-path-safety}

Cette page est la référence de la syntaxe de modèle d’URI (URI template)
qu’accepte [`@mcp.resource`](resources.md), ainsi que de la politique de
sûreté des chemins que le SDK applique aux valeurs extraites. Pour une
introduction à ce que sont les ressources et au moment où les utiliser,
commencez par **[Ressources](resources.md)** ; cette page suppose que vous
savez déjà déclarer une ressource et que vous cherchez le jeu complet
d’opérateurs, les réglages de sécurité ou le câblage de bas niveau.

La syntaxe des modèles est celle de la [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570).
Le SDK en prend en charge un sous-ensemble choisi pour faire correspondre
les URI des requêtes `resources/read` entrantes, auquel s’ajoute une couche
de sécurité qui rejette les valeurs qui se résoudraient en dehors du
répertoire que vous comptez servir. Pour les détails au niveau du protocole
(formats des messages, cycle de vie, pagination), consultez la
[spécification MCP des ressources](https://modelcontextprotocol.io/specification/latest/server/resources).

## Le jeu complet d’opérateurs {#the-full-operator-set}

L’espace réservé simple, `{user_id}`, est celui que présente **[Ressources](resources.md)**. Il existe quatre autres
formes d’opérateur ; les voici réunies sur un même serveur pour que vous
puissiez les comparer côte à côte :

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

Chaque décorateur mis en évidence découpe l’URI d’une manière différente.
Les sections ci-dessous les parcourent de haut en bas.

### Expansion simple : `{name}` {#simple-expansion-name}

`books://{isbn}` est la forme simple, celle de tous les jours. L’espace
réservé correspond au paramètre `isbn` ; un client qui lit
`books://978-0441172719` appelle donc `get_book("978-0441172719")`.

Un `{name}` simple s’arrête au premier `/`. `books://978/extra` ne
correspond pas, car la barre oblique après `978` met fin à la capture et
`/extra` reste en trop.

### Conversion de type {#type-conversion}

Les valeurs extraites arrivent sous forme de chaînes, mais vous pouvez
déclarer un type plus précis et le SDK se charge de la conversion.
`orders://{order_id}` aboutit dans une fonction dont le paramètre est
`order_id: int` ; lire `orders://12345` appelle donc `get_order(12345)`, et
non `get_order("12345")`. Le gestionnaire (handler) fait de l’arithmétique
dessus (`order_id + 1`) sans transtypage.

### Chemins à plusieurs segments : `{+name}` {#multi-segment-paths-name}

Pour capturer une valeur qui contient des barres obliques, utilisez
`{+name}`. Avec `manuals://{+path}` :

* `manuals://returns.md` donne `path = "returns.md"`
* `manuals://printing/setup.md` donne `path = "printing/setup.md"`

Tournez-vous vers `{+name}` dès que la valeur est hiérarchique : chemins
du système de fichiers, clés d’objets imbriqués, chemins d’URL que vous
relayez.

### Paramètres de requête : `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` place `limit` et `sort` après le `?`.
Le chemin identifie *quel* livre ; la chaîne de requête règle *comment*
vous le lisez.

Les paramètres de requête sont mis en correspondance avec souplesse :
l’ordre n’a pas d’importance, les paramètres en trop sont ignorés et les
paramètres omis retombent sur les valeurs par défaut de votre fonction.
Ainsi, `reviews://978-0441172719` utilise `limit=10, sort="newest"`, et
`reviews://978-0441172719?sort=top` ne remplace que `sort`.

### Segments de chemin sous forme de liste : `{/name*}` {#path-segments-as-a-list-name}

Si vous voulez chaque segment de chemin comme un élément de liste distinct
plutôt qu’une seule chaîne contenant des barres obliques, utilisez
`{/name*}`. Avec `shelves://browse{/path*}`, un client qui lit
`shelves://browse/fiction/sci-fi` appelle
`browse_shelf(["fiction", "sci-fi"])`.

### Référence des modèles {#template-reference}

Les motifs les plus courants :

| Motif        | Exemple d’entrée      | Vous obtenez            |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | *pas de correspondance* (s’arrête au `/`) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### Ce que l’analyseur rejette {#what-the-parser-rejects}

Quelques formes de modèle sont interceptées d’emblée plutôt que d’échouer
à la première requête. `@mcp.resource` analyse le modèle au moment où le
décorateur s’exécute ; aucune d’entre elles n’atteint donc jamais un
serveur en fonctionnement.

`UriTemplate.parse()` lève `InvalidUriTemplate` pour :

* **Deux variables sans rien entre elles.** `manuals://{+path}{ext}`
  est rejeté : la mise en correspondance ne peut pas savoir où `path` se
  termine et où `ext` commence. Placez un littéral entre les deux
  (`manuals://{+path}/{ext}`) ou utilisez un opérateur qui fournit son
  propre délimiteur. `manuals://{+path}{.ext}` est accepté parce que
  `{.ext}` apporte lui-même le `.`.
* **Plus d’une variable à plusieurs segments.** Au plus une variable
  parmi `{+var}`, `{#var}` ou une variable éclatée (`{/var*}`, `{.var*}`,
  `{;var*}`) par modèle. Deux sont intrinsèquement ambiguës : il n’existe
  aucun moyen rigoureux de décider laquelle absorbe un segment
  supplémentaire.
* **Les erreurs de syntaxe habituelles** : une accolade non fermée, un nom
  de variable utilisé deux fois ou une fonctionnalité de la RFC 6570 que
  le SDK ne prend pas en charge, comme le modificateur de préfixe
  `{var:3}` ou l’éclatement de requête `{?vars*}`.

En plus de cela, `@mcp.resource` lève `ValueError` lorsqu’un paramètre du
gestionnaire est lié à une variable de requête dans la séquence finale
`{?...}`/`{&...}` du modèle mais n’a pas de valeur par défaut Python. Ces
variables sont mises en correspondance avec souplesse (un client peut
omettre n’importe laquelle), si bien qu’un paramètre sans valeur par défaut
ne se manifesterait que sous la forme d’une erreur interne opaque à la
première requête qui l’omet. `reviews://{isbn}{?limit,sort}` dans le
serveur ci-dessus est la version bien formée : `limit` et `sort` portent
tous deux une valeur par défaut.

## Sécurité {#security}

Les paramètres de modèle proviennent du client. S’ils se retrouvent sans
contrôle dans des opérations sur le système de fichiers ou la base de
données, des valeurs comme `../../etc/passwd` peuvent se résoudre en
dehors du répertoire que vous comptiez servir.

### Ce que le SDK vérifie par défaut {#what-the-sdk-checks-by-default}

Avant que votre gestionnaire ne s’exécute, le SDK rejette tout paramètre
qui :

* s’échapperait de son répertoire de départ via des composants `..`
* ressemble à un chemin absolu (`/etc/passwd`, `C:\Windows`) ou à un
  chemin Windows relatif à un lecteur (`C:foo`). Une valeur relative à un
  lecteur et un identifiant à espace de noms comme `x:y` sont
  indiscernables en tant que chaînes ; toute valeur composée d’une seule
  lettre suivie de deux-points est donc rejetée par défaut. Exemptez le
  paramètre s’il reçoit légitimement de telles valeurs
* contient un octet nul (`\x00`)

La vérification des `..` se fait par composant, et non par recherche de
sous-chaîne. Des valeurs comme `v1.0..v2.0` ou `HEAD~3..HEAD` passent,
car `..` n’y constitue pas un segment de chemin autonome.

Ces vérifications s’appliquent à la valeur décodée ; elles interceptent
donc la traversée de répertoires quelle que soit la façon dont elle a été
encodée dans l’URI (`../etc`, `..%2Fetc`, `%2E%2E/etc`, `..%5Cetc`, `%00`
sont tous interceptés).

!!! check
    Lisez `manuals://../etc/passwd` sur le serveur ci-dessus et la requête
    est rejetée purement et simplement : la mise en correspondance des
    modèles s’arrête au premier échec, si bien qu’aucun modèle ultérieur
    (potentiellement plus permissif) n’est essayé en repli. Le client voit
    la même erreur `-32602` « Unknown resource » que pour un URI qui ne
    correspond à aucun modèle, et `read_manual` ne s’exécute jamais.

### Gestionnaires sur le système de fichiers : utiliser safe_join {#filesystem-handlers-use-safe_join}

Les vérifications intégrées bloquent les cas courants, mais ne peuvent pas
connaître la frontière de votre bac à sable. Pour l’accès au système de
fichiers, utilisez `safe_join` pour résoudre le chemin et vérifier qu’il
reste à l’intérieur de votre répertoire de base :

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` intercepte les échappements par lien symbolique, les séquences
`..` et les astuces à base de chemin absolu qu’une simple vérification de
chaîne laisserait passer. Si le chemin résolu s’échappe de `DOCS_ROOT`, il
lève `PathEscapeError`, qui parvient au client sous la forme d’une
`ResourceError`.

### Quand les valeurs par défaut vous gênent {#when-the-defaults-get-in-the-way}

Parfois, les vérifications bloquent des valeurs légitimes. Un outil
d’importation de catalogue peut recevoir intentionnellement un chemin
absolu, ou un paramètre peut être une référence relative comme
`../sibling` que votre gestionnaire interprète en toute sécurité sans
toucher au système de fichiers. Exemptez ce paramètre ou assouplissez la
politique pour tout le serveur :

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* `security=ResourceSecurity(exempt_params={"source"})` sur le décorateur
  saute les vérifications pour ce seul paramètre sur cette seule
  ressource. Le reste du serveur conserve la politique par défaut.
* `resource_security=` sur le constructeur de `MCPServer` définit la
  valeur par défaut pour chaque ressource. Ici, `relaxed` désactive
  entièrement la vérification des `..`.

Les vérifications configurables :

| Réglage                 | Par défaut | Ce qu’il fait                    |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | Rejette les séquences `..` qui s’échappent du répertoire de départ |
| `reject_absolute_paths` | `True`  | Rejette `/foo`, `C:\foo`, les chemins UNC et le `C:foo` relatif à un lecteur (intercepte aussi `x:y`) |
| `reject_null_bytes`     | `True`  | Rejette les valeurs contenant `\x00` |
| `exempt_params`         | vide    | Noms des paramètres à exempter des vérifications |

Ces vérifications sont un préfiltre heuristique ; pour l’accès au système
de fichiers, `safe_join` reste la frontière de confinement.

!!! tip
    Si votre gestionnaire ne peut pas satisfaire la requête (le fichier
    n’existe pas, l’identifiant est inconnu), levez une exception. Le SDK
    la transforme en réponse d’erreur. Consultez **[Gérer les erreurs](handling-errors.md)** pour la
    différence entre une erreur de protocole et une erreur d’outil.

## Les ressources sur le Server de bas niveau {#resources-on-the-low-level-server}

Si vous construisez sur le `Server` de bas niveau (voir **[Le Server de
bas niveau](../advanced/low-level-server.md)**), vous enregistrez directement des gestionnaires pour les
méthodes de protocole `resources/list` et `resources/read`. Il n’y a pas
de décorateur ; vous renvoyez vous-même les types du protocole.

### Ressources statiques {#static-resources}

Pour des URI fixes, tenez un registre et répartissez sur correspondance
exacte :

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

Le gestionnaire de liste indique aux clients ce qui est disponible ; le
gestionnaire de lecture sert le contenu. Consultez d’abord votre registre,
retombez sur les modèles (ci-dessous) si vous en avez, puis levez une
exception pour tout le reste.

### Modèles {#templates}

Le moteur de modèles qu’utilise `MCPServer` se trouve dans
`mcp.shared.uri_template` et fonctionne de manière autonome. Vous
bénéficiez de la même analyse et de la même mise en correspondance ; vous
câblez vous-même le routage et la politique de sécurité.

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

Trois choses se passent dans les lignes mises en évidence :

* **Analyser une fois, faire correspondre à chaque requête.**
  `UriTemplate.parse()` construit le modèle ; `template.match(uri)`
  renvoie les variables extraites sous forme de `dict`, ou `None` si l’URI
  ne convient pas. Le décodage d’URL a lieu dans `match()` ; les valeurs
  décodées sont renvoyées telles quelles, sans validation de sûreté des
  chemins. Les valeurs sortent sous forme de chaînes : convertissez-les
  vous-même (`int(matched["id"])`, `Path(matched["path"])`).
* **Appliquer vous-même les vérifications de sûreté.** Les vérifications
  des `..` et des chemins absolus que `MCPServer` exécute par défaut se
  trouvent dans `mcp.shared.path_security`. `read_manual_safely` les
  appelle avant de toucher à `MANUALS`. Si un paramètre n’est pas un
  chemin du système de fichiers (un ISBN, une requête de recherche),
  sautez les vérifications pour cette valeur : vous maîtrisez la politique
  gestionnaire par gestionnaire plutôt qu’au travers d’un objet de
  configuration.
* **Lister les modèles à partir de la même source.** Les clients
  découvrent les modèles via `resources/templates/list`. `str(template)`
  restitue la chaîne de modèle d’origine, si bien que la liste et le
  moteur de correspondance partagent une seule source de vérité.

## Récapitulatif {#recap}

* `{name}` correspond à un seul segment ; `{+name}` conserve les barres
  obliques ; `{?a,b}` puise dans la chaîne de requête ; `{/name*}` découpe
  les segments en liste.
* Deux variables sans rien entre elles, ou une seconde variable à
  plusieurs segments, sont rejetées à l’analyse. Un paramètre lié à une
  variable de requête dans une séquence finale `{?...}`/`{&...}` doit
  déclarer une valeur par défaut Python.
* Annotez le paramètre (`order_id: int`) et le SDK convertit.
* La politique de sécurité par défaut rejette `..`, les chemins absolus
  et les octets nuls avant que votre gestionnaire ne s’exécute ;
  remplacez-la par ressource avec `security=ResourceSecurity(...)` ou pour
  tout le serveur avec `resource_security=`.
* Pour l’accès au système de fichiers, `safe_join` est la frontière de
  confinement.
* Sur le `Server` de bas niveau, analysez avec `UriTemplate.parse()`,
  faites correspondre avec `.match()` et appliquez
  `mcp.shared.path_security` vous-même.
