---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# Complétions {#completions}

Un client qui construit une interface utilisateur au-dessus de votre serveur veut autocompléter les valeurs des arguments au fil de la saisie de l’utilisateur : noms de langages, noms de dépôts, chemins de fichiers.

Les **complétions** sont le moyen par lequel votre serveur fournit ces suggestions.

## Quelque chose à compléter {#something-worth-completing}

Les complétions s’appliquent à exactement deux choses : les arguments d’un **prompt** et les paramètres d’un **modèle de ressource**. Commencez donc par un serveur qui en possède un de chaque :

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

Rien ici ne concerne encore les complétions.

* `review_code` prend un `language`. Un utilisateur ne devrait pas avoir à deviner quelles orthographes vous acceptez.
* `github_repo` prend un `owner` et un `repo`. Des champs de texte libre pour les deux font un mauvais formulaire.

## Le gestionnaire de complétion {#the-completion-handler}

Ajoutez **une** seule fonction décorée avec `@mcp.completion()` :

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* Il y a un seul gestionnaire (handler) par serveur. Chaque requête de complétion arrive ici, et vous aiguillez selon ce qui est en cours de complétion.
* Il doit être `async def` : le SDK l’attend avec await.
* Il reçoit trois arguments :
  * `ref` : *quel* prompt ou modèle de ressource, sous la forme d’une `PromptReference` ou d’une `ResourceTemplateReference`. C’est `isinstance` qui vous permet de les distinguer.
  * `argument` : `argument.name` est l’argument en cours de complétion, `argument.value` est ce que l’utilisateur a saisi jusqu’ici.
  * `context` : les arguments déjà résolus. Ignorez-le pour l’instant.
* Vous renvoyez une `Completion(values=[...])`, ou `None` quand vous n’avez rien à proposer.

!!! tip
    `argument.value` est le préfixe que l’utilisateur a saisi. Le SDK ne filtre **pas** pour vous : ce que
    vous mettez dans `values` est ce que l’interface affiche. Le `startswith`, c’est à vous de l’écrire.

### Essayer {#try-it}

Pilotez-le avec le `Client` en mémoire de **[Tests](../get-started/testing.md)**. Appelez
`client.complete()` avec `ref=PromptReference(name="review_code")` et
`argument={"name": "language", "value": "py"}` :

```python
result.completion.values  # ['python']
```

* `ref` est le même type de référence que celui que reçoit votre gestionnaire.
* `argument` est un simple dict avec exactement deux clés, `name` et `value`.

Envoyez une `value` vide et vous obtenez toute la liste en retour. `lang.startswith("")` est vrai pour chaque langage :

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

Interrogez-le sur `code` (un argument que votre gestionnaire ne reconnaît pas) et il renvoie `None`, que le SDK transforme en liste vide :

```python
result.completion.values  # []
```

`None` signifie *« aucune suggestion »*, jamais une erreur. Une interface se rabat sur un simple champ de texte.

## Une capacité que vous n’avez jamais déclarée {#a-capability-you-never-declared}

Enregistrer le gestionnaire, c’est la déclarer. Connectez un client et regardez :

```python
client.server_capabilities.completions  # CompletionsCapability()
```

Vous n’avez listé `completions` nulle part. Le SDK a vu le gestionnaire et a déclaré la capacité pour vous. Toutes les capacités *optionnelles* fonctionnent ainsi : le gestionnaire est la déclaration. (Les trois primitives ne sont pas optionnelles : `MCPServer` les déclare toujours, gestionnaires ou non.)

!!! check
    Revenez au premier `server.py` (celui sans gestionnaire) et interrogez-le quand même. L’appel échoue
    avec une erreur JSON-RPC :

    ```text
    Method not found
    ```

    Et `client.server_capabilities.completions` vaut `None`. C’est tout l’intérêt de la capacité : un
    client bien conçu la vérifie et n’envoie jamais la requête à laquelle vous ne pouvez pas répondre.

## Arguments dépendants {#dependent-arguments}

`github://repos/{owner}/{repo}` a deux paramètres, et les valeurs utiles pour `repo` dépendent du `owner` choisi en premier.

C’est à cela que sert `context`. Il transporte les arguments que l’utilisateur a **déjà résolus** :

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* La nouvelle branche se déclenche pour le paramètre `repo` du modèle.
* `context.arguments` est un `dict[str, str] | None` des valeurs choisies jusqu’ici (ici, `owner`).
* Pas encore de `owner` signifie pas de suggestion pertinente, donc le gestionnaire renvoie `None`.

Le client envoie ces valeurs résolues avec `context_arguments=`. Cette fois, `ref` est une
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`. Demandez `repo` avec une
`value` vide et passez `context_arguments={"owner": "modelcontextprotocol"}` :

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

Retirez `context_arguments=` et le même appel renvoie `[]`. Le gestionnaire ne peut pas savoir quels dépôts proposer tant qu’il ne connaît pas le propriétaire.

!!! info
    `Completion` accepte aussi `total=` et `has_more=`. Renseignez-les quand `values` est une tranche d’une liste
    plus longue, pour qu’une interface puisse afficher *« et 200 de plus »*. La plupart des gestionnaires n’en ont jamais besoin.

## Récapitulatif {#recap}

* Les complétions sont des suggestions pour les **arguments de prompt** et les **paramètres de modèle de ressource**. Rien d’autre.
* `@mcp.completion()` enregistre l’unique gestionnaire. Sa signature est `async def (ref, argument, context) -> Completion | None`.
* Aiguillez sur `isinstance(ref, ...)` et sur `argument.name`. Filtrez vous-même selon `argument.value`.
* `None` devient une liste vide. Ce n’est jamais une erreur.
* `context.arguments` contient les valeurs déjà résolues ; le client les fournit via `context_arguments=`.
* La capacité `completions` apparaît dès que vous enregistrez le gestionnaire. Sans lui, la requête reçoit `Method not found`.

Les suggestions aident pendant que l’utilisateur *remplit* encore un prompt ou un modèle ; pour lui poser une question au *milieu* d’un appel d’outil, c’est l’**[élicitation (elicitation)](../handlers/elicitation.md)** qu’il vous faut. Tout ce qu’un outil peut renvoyer en plus du texte se trouve dans **[Images, audio et icônes](media.md)**.
