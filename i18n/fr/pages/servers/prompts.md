---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
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
    Si vous avez lu **[Outils](tools.md)**, vous connaissez déjà tout ce que contient cette page. Même décorateur, même
    docstring servant de description, mêmes `Annotated`/`Field`. Seuls changent qui
    le déclenche (l’utilisateur) et où va le résultat (dans la conversation).

## Récapitulatif {#recap}

* `@mcp.prompt()` sur une fonction en fait un prompt. Le nom vient de la fonction, la description de la docstring.
* Les prompts sont **contrôlés par l’utilisateur** : le client les liste, l’utilisateur en choisit un et renseigne les arguments.
* Les arguments forment une liste plate de chaînes nommées (pas de schéma). Un paramètre avec une valeur par défaut est facultatif.
* Renvoyez une `str` et elle devient un seul message utilisateur. Renvoyez une liste de `UserMessage` / `AssistantMessage` pour amorcer une conversation à plusieurs tours.
* `title=` et `Field(description=...)` sont ce qu’un client affiche dans son interface.
* Un argument obligatoire manquant fait échouer toute la requête. Il n’y a pas de résultat d’erreur par prompt.

L’autocomplétion côté serveur des arguments d’un prompt (ou d’un modèle de ressource), c’est **[Complétions](completions.md)**.
