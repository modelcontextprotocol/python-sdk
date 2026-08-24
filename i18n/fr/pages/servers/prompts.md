---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# Prompts {#prompts}

Un **prompt** est un modèle de message que l’utilisateur choisit.

Les outils sont destinés au modèle. Un prompt, c’est l’inverse : l’utilisateur en choisit un dans un menu de son client (une commande slash, un bouton), renseigne ses arguments, et les messages rendus entrent dans la conversation comme s’il les avait saisis lui-même.

Vous en déclarez un en plaçant `@mcp.prompt()` sur une fonction qui renvoie le texte.

## Votre premier prompt {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

Le SDK lit les trois mêmes éléments qu’il lit sur un outil :

* Le **nom** est le nom de la fonction : `review_code`.
* La **description** que le client affiche est la docstring : `Review a piece of code.`
* Les **arguments** proviennent des paramètres. `code` n’a pas de valeur par défaut, il est donc obligatoire.

Voici ce qu’un client obtient en retour de `prompts/list` :

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Il n’y a pas de JSON Schema ici. Les arguments d’un prompt forment une liste plate de **valeurs chaînes nommées** : un formulaire qu’une personne remplit, pas une charge utile qu’un modèle construit.

### Le rendre {#rendering-it}

Le client rend le modèle avec `prompts/get`, en passant les arguments. Votre fonction s’exécute et la `str` que vous renvoyez devient **un seul message utilisateur** :

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

C’est toute la vie d’un prompt : listé par son nom, rendu à la demande, déposé dans la conversation.

!!! check
    `required` est vérifié avant l’exécution de votre fonction. Rendez `review_code` sans `code` et la
    requête elle-même échoue avec une erreur JSON-RPC (code `-32603`) :

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Il n’y a pas de résultat d’erreur à la manière des outils à remettre à un modèle, car aucun modèle n’est dans la boucle :
    l’appel lève une exception. La raison (`Missing required arguments: {'code'}`) arrive dans le journal de votre serveur.

### Essayer {#try-it}

Lancez le serveur avec le MCP Inspector :

```console
uv run mcp dev server.py
```

Ouvrez l’onglet **Prompts** et sélectionnez `review_code`. L’Inspector dessine un formulaire avec un seul champ obligatoire `code`. Renseignez-le, lancez le rendu, et vous obtenez en retour exactement le message utilisateur ci-dessus.

## Plus d’un message {#more-than-one-message}

Une revue de code, c’est un message. Une session de débogage, c’est une conversation, et un prompt peut l’amorcer tout entière.

Renvoyez une liste de messages au lieu d’une `str` :

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` et `AssistantMessage` viennent de `mcp.server.mcpserver.prompts.base`. Passez-leur une `str` et ils l’enveloppent dans un `TextContent` pour vous. Le rôle est le nom de la classe.
* `Message` est leur classe de base commune. Utilisez-la comme annotation de retour.

Le rendu de `debug_error` produit désormais trois messages, dans l’ordre :

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Remarquez le dernier. Préremplir un tour `assistant`, c’est la façon d’orienter la *prochaine* réponse du modèle sans obliger l’utilisateur à saisir lui-même cette orientation.

## Titres et descriptions d’arguments {#titles-and-argument-descriptions}

`review_code` est un nom de fonction, pas un libellé. Donnez au client quelque chose de mieux à afficher sur le bouton, et décrivez chaque argument pour que le formulaire s’explique de lui-même :

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` est le nom lisible par un humain, exactement comme le `title` d’un outil.
* `Annotated[str, Field(description=...)]` est le même motif que celui que **[Outils](tools.md)** utilise pour décrire les paramètres d’un outil. Ici, la description se retrouve sur l’argument plutôt que dans un schéma.
* `language` a une valeur par défaut, il cesse donc d’être obligatoire.

L’entrée `prompts/list` contient désormais tout ce dont un client a besoin pour dessiner un bon formulaire :

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    Si vous avez lu **[Outils](tools.md)**, vous connaissez déjà tout jusqu’ici. Même décorateur, même
    docstring servant de description, mêmes `Annotated`/`Field`. Seuls changent qui
    le déclenche (l’utilisateur) et où va le résultat (dans la conversation).

## Au-delà du texte {#more-than-text}

`UserMessage` et `AssistantMessage` acceptent aussi un bloc de contenu, ou un utilitaire `Image` / `Audio`, partout où ils acceptent une `str`. Deux cas se présentent dans les prompts : joindre un document et joindre une image.

### Incorporer un fichier {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* Le guide de style est une ressource à l’adresse `style://python` (**[Ressources](resources.md)** traite de celles-ci), lue depuis un fichier `style-guide.md` placé à côté de `server.py`. Mettez-y n’importe quel fichier Markdown.
* `EmbeddedResource(resource=TextResourceContents(...))`, tous deux issus de `mcp.types`, transporte le fichier avec son URI et son type MIME comme premier message ; la demande qui y fait référence suit sous forme de texte brut.
* Incorporer le guide, plutôt que de le coller dans la f-string, permet au client de l’afficher comme pièce jointe et de rouvrir `style://python` plus tard, et le modèle reçoit le fichier tel quel. Pour un fichier binaire, utilisez `BlobResourceContents` avec un `blob` en base64.

Une fois rendu, le `content` du premier message est un bloc `resource` :

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### Joindre une image {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` est l’utilitaire de **[Images, audio et icônes](media.md)**. `UserMessage` le convertit en bloc `ImageContent` (le fichier encodé en base64, le type MIME deviné d’après `.png`) au moment du rendu du prompt ; `Audio` devient un `AudioContent` de la même façon.
* Placez n’importe quel PNG nommé `architecture.png` à côté de `server.py`. Les arguments d’un prompt sont des chaînes, l’image vient donc toujours du serveur ; `component` ne fournit que les mots.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## Modifier la liste à l’exécution {#changing-the-list-at-runtime}

Des prompts peuvent être ajoutés pendant que des clients sont connectés, par exemple pour permettre à un utilisateur d’enregistrer une instruction comme entrée de menu bien à lui. Enregistrez le prompt, puis notifiez :

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` enregistre une fonction exactement comme le ferait `@mcp.prompt()`, et `mcp.remove_prompt(name)` fait l’inverse. `add_prompt` conserve une entrée existante du même nom au lieu de l’écraser ; l’outil supprime donc d’abord toute ancienne entrée pour que l’enregistrement soit un remplacement. `prompts/list` reflète le changement immédiatement.
* `await ctx.notify_prompts_changed()` envoie `notifications/prompts/list_changed` à chaque client `2026-07-28` à l’écoute sur un flux `subscriptions/listen` (**[Abonnements](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()` l’envoie au client appelant lorsque celui-ci est antérieur à 2026 (**[Prendre en charge les clients historiques](../run/legacy-clients.md)**). Appelez les deux ; chacun ne fait rien quand il n’y a personne à prévenir.
* Un client qui reçoit la notification appelle de nouveau `prompts/list`. Dans le `Client` Python, c’est `async with client.listen(prompts_list_changed=True) as sub:`, qui produit un événement `PromptsListChanged`.

## Récapitulatif {#recap}

* `@mcp.prompt()` sur une fonction en fait un prompt. Le nom vient de la fonction, la description de la docstring.
* Les prompts sont **contrôlés par l’utilisateur** : le client les liste, l’utilisateur en choisit un et renseigne les arguments.
* Les arguments forment une liste plate de chaînes nommées (pas de schéma). Un paramètre avec une valeur par défaut est facultatif.
* Renvoyez une `str` et elle devient un seul message utilisateur. Renvoyez une liste de `UserMessage` / `AssistantMessage` pour amorcer une conversation à plusieurs tours.
* `title=` et `Field(description=...)` sont ce qu’un client affiche dans son interface.
* Un argument obligatoire manquant fait échouer toute la requête. Il n’y a pas de résultat d’erreur par prompt.
* Enveloppez un `EmbeddedResource` ou une `Image` dans un `UserMessage` pour joindre un document ou une image.
* Ajoutez ou supprimez des prompts à l’exécution avec `mcp.add_prompt(...)` / `mcp.remove_prompt(...)`, puis `await ctx.notify_prompts_changed()` et `await ctx.session.send_prompt_list_changed()`.

L’autocomplétion côté serveur des arguments d’un prompt (ou d’un modèle de ressource), c’est **[Complétions](completions.md)**.
