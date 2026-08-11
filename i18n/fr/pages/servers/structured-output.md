---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Sortie structurée {#structured-output}

Un outil (tool) qui renvoie une simple `str` produit le résultat deux fois : sous forme de texte dans `content`, et sous la forme `{"result": "..."}` dans `structured_content`.

Cette page porte sur ce second canal : d’où il vient, toutes les formes qu’il peut prendre et la façon dont le SDK en garantit l’exactitude.

En bref : **l’annotation du type de retour est le schéma de sortie**. Vous l’avez déjà écrite.

## Le schéma de sortie {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

La ligne qui compte est la signature : `-> int`.

Grâce à elle, l’outil que le SDK envoie lors de `tools/list` porte un `output_schema` à côté du schéma d’entrée qu’il construit à partir de vos paramètres (la page **[Outils](tools.md)** traite de celui-là) :

```json
{
  "properties": {
    "result": {"title": "Result", "type": "integer"}
  },
  "required": ["result"],
  "title": "get_temperatureOutput",
  "type": "object"
}
```

Un `int` seul n’est pas un objet JSON, le SDK l’**enveloppe** donc dans `{"result": ...}`. Appelez l’outil et les deux canaux sont remplis :

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Tous les scalaires reçoivent la même enveloppe : `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Deux canaux {#two-channels}

Pourquoi envoyer la même valeur deux fois ?

* `content` est destiné au **modèle**. Un modèle de langage lit du texte ; c’est la seule partie du résultat qu’il voit.
* `structured_content` est destiné à l’**application** dans laquelle le modèle s’exécute : du code qui veut `17`, pas une phrase contenant « 17 ».
* `output_schema` est le contrat entre les deux, publié avant même le premier appel de l’outil.

Vous renvoyez une seule valeur Python. Le SDK remplit les trois.

## Renvoyer un modèle {#return-a-model}

Déclarez la forme comme un `BaseModel` Pydantic et renvoyez une instance :

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

`WeatherData` **est** désormais le schéma. Pas d’enveloppe, pas de clé `result` :

```json
{
  "properties": {
    "temperature": {"description": "Degrees Celsius.", "title": "Temperature", "type": "number"},
    "humidity": {"description": "Relative humidity, 0 to 1.", "title": "Humidity", "type": "number"},
    "conditions": {"title": "Conditions", "type": "string"}
  },
  "required": ["temperature", "humidity", "conditions"],
  "title": "WeatherData",
  "type": "object"
}
```

`structured_content` est l’objet, champ pour champ :

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

Et le modèle n’est pas oublié. Le SDK sérialise le même objet en texte JSON pour `content` :

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Remarquez que les `Field(description=...)` de `temperature` et `humidity` ont atterri dans le schéma. Le même `Field` qui décrivait vos **entrées** décrit vos sorties.

!!! info
    Si vous avez utilisé le `response_model` de FastAPI, vous connaissez déjà cela : un modèle Pydantic
    comme réponse déclarée, sérialisé et documenté pour vous. La seule différence est qu’ici
    l’annotation de retour constitue toute la déclaration.

## Un `TypedDict` {#a-typeddict}

Toutes les formes ne méritent pas une classe. Un `TypedDict` produit le même schéma :

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

Un `TypedDict` est un simple `dict` à l’exécution : c’est donc ce que vous construisez et renvoyez. Le schéma, la validation et `structured_content` sont identiques à la version `BaseModel` (à l’exception des descriptions, pour lesquelles `TypedDict` n’a pas de place).

## Une dataclass {#a-dataclass}

Les dataclasses fonctionnent aussi, tout comme n’importe quelle classe ordinaire dont les attributs portent des annotations de type. Le SDK construit en coulisses un modèle Pydantic à partir des annotations.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Trois écritures, un seul schéma. Utilisez celle que votre base de code emploie déjà.

## Listes {#lists}

Une `list[...]` n’est pas non plus un objet JSON : elle reçoit donc l’enveloppe `{"result": ...}`, avec votre type d’élément sous forme de référence `$defs` à l’intérieur :

```python title="server.py" hl_lines="15"
--8<-- "docs_src/structured_output/tutorial005.py"
```

```json
{
  "$defs": {
    "WeatherData": {
      "properties": {
        "temperature": {"title": "Temperature", "type": "number"},
        "humidity": {"title": "Humidity", "type": "number"},
        "conditions": {"title": "Conditions", "type": "string"}
      },
      "required": ["temperature", "humidity", "conditions"],
      "title": "WeatherData",
      "type": "object"
    }
  },
  "properties": {
    "result": {"items": {"$ref": "#/$defs/WeatherData"}, "title": "Result", "type": "array"}
  },
  "required": ["result"],
  "title": "get_forecastOutput",
  "type": "object"
}
```

Demandez une prévision sur deux jours et `structured_content` vaut `{"result": [{...}, {...}]}`. `content` devient **deux** blocs `TextContent`, un par élément : une liste est aplatie pour le modèle plutôt que déversée en une seule chaîne.

`tuple[...]`, les unions et `Optional[...]` sont enveloppés de la même façon.

## Dictionnaires {#dictionaries}

`dict[str, ...]` est le seul générique qui *est* déjà un objet JSON ; il n’est donc pas enveloppé :

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial006.py"
```

```json
{
  "additionalProperties": {"type": "number"},
  "title": "get_temperaturesDictOutput",
  "type": "object"
}
```

```python
result.structured_content  # {"London": 16.2, "Reykjavik": 4.4}
```

Les clés doivent être des `str`. Un `dict[int, float]` ne peut pas être un objet JSON ; il retombe donc sur l’enveloppe `{"result": ...}`.

## Validation {#validation}

`output_schema` n’est pas de la documentation. Tout ce que renvoie votre fonction est **validé par rapport à lui** avant de quitter le serveur.

Vous ne le remarquez pas tant que vous construisez la valeur à la main : Pydantic s’est déjà assuré que votre `WeatherData` était bien un `WeatherData`. Vous le remarquez le jour où les données viennent d’un endroit que vous ne contrôlez pas :

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

L’annotation promet un `WeatherData`. La réponse en amont a cessé d’envoyer `humidity`.

!!! check
    Appelez `get_weather` : il ne remet pas discrètement au client un objet à moitié vide. L’appel
    échoue, et les premières lignes de l’erreur nomment le champ :

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    Ce texte revient comme résultat de l’outil avec `is_error=True` : le modèle sait donc que l’appel
    a échoué au lieu de lire avec assurance une météo qui n’existe pas.

Au passage, renvoyer un simple `dict` depuis un outil `-> WeatherData` ne pose aucun problème. C’est exactement ce que `json.loads` a produit. La validation porte sur la valeur, pas sur le type Python.

## Désactiver la sortie structurée {#opting-out}

Parfois, l’annotation de retour est destinée à votre vérificateur de types, pas au protocole. Passez `structured_output=False` et l’outil devient purement textuel :

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

Aucun `output_schema`, aucune enveloppe, aucune validation. `structured_content` vaut `None` et `content` est la chaîne que vous avez renvoyée.

L’inverse, `structured_output=True`, transforme la détection automatique en exigence : un outil dont le type de retour ne peut pas produire de schéma lève une exception à l’import au lieu de se rabattre sur du texte.

## Une classe sans annotations de type {#a-class-without-type-hints}

Il existe une façon de se retrouver sans sortie structurée sans l’avoir demandé : renvoyer une classe qui n’a **aucune annotation dans son corps**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` définit `name` et `online` dans `__init__`, mais la *classe* ne déclare rien. Le SDK lit les annotations de la classe, n’en trouve aucune et abandonne.

!!! warning
    Il abandonne **silencieusement**. `output_schema` vaut `None`, `structured_content` vaut `None`,
    et le texte que lit le modèle est le `repr` de l’objet :

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Aucune erreur, aucun avertissement, un outil inutile. Déplacez les annotations dans le corps de la
    classe, ou passez `structured_output=True`, qui transforme cela en erreur franche dès l’import du
    module : `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Besoin d’un contrôle total (construire vous-même le `CallToolResult`, ou attacher un `_meta` que
    l’application voit mais pas le modèle) ? C’est le sujet de **[Le Server de bas niveau](../advanced/low-level-server.md)**.

## Récapitulatif {#recap}

* L’**annotation du type de retour** est le schéma de sortie. Elle est publiée dans `tools/list` sous le nom `output_schema`.
* Les scalaires, listes, tuples et unions sont enveloppés dans `{"result": ...}`. Les modèles, les `TypedDict`, les dataclasses, les classes annotées et `dict[str, ...]` sont déjà des objets et restent tels quels.
* Chaque résultat porte `content` (du texte, pour le modèle) **et** `structured_content` (des données, pour l’application).
* Ce que vous renvoyez est validé par rapport au schéma. Une incohérence est une erreur d’outil, pas un résultat corrompu.
* `structured_output=False` désactive la sortie structurée d’un outil. Une classe sans annotations de type la désactive silencieusement ; surveillez ce cas.

Vous maîtrisez désormais tout ce qu’un outil peut répondre. Ensuite, la deuxième primitive : **[Ressources](resources.md)**.
