---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# Élicitation {#elicitation}

Un outil arrivé à mi-parcours de sa tâche et à qui il manque une seule réponse n’est pas obligé d’échouer.

L’**élicitation** (elicitation) lui permet de la demander. En plein appel d’outil, l’utilisateur reçoit une question, et sa réponse revient dans le même appel de fonction.

Il existe deux modes :

* **Mode formulaire** : vous avez besoin d’une valeur (une confirmation, une date, une quantité). Vous décrivez les champs, le client affiche le formulaire.
* **Mode URL** : vous avez besoin que l’utilisateur aille ailleurs (un écran de consentement OAuth, une page de paiement). Rien de ce qu’il y fait ne passe par le protocole.

Et il existe deux façons de demander. Celle à privilégier est un **résolveur** : vous accrochez la question à un paramètre, et le SDK la pose — sur n’importe quelle connexion, quelle que soit la génération de protocole que parle le client. La façon directe, `await ctx.elicit(...)`, est une requête du *serveur* vers le *client*, un canal qui n’existe que pour un client sur une connexion historique (version de spécification 2025-11-25 ou antérieure). Les deux figurent sur cette page ; commencez par le résolveur.

## Demander avec un résolveur {#ask-with-a-resolver}

Une question dont dépend tout l’outil — *êtes-vous sûr ? lequel des trois comptes correspondants ?* — peut être sortie du corps de l’outil et placée dans un **résolveur**, et le framework la pose pour vous.

Un paramètre annoté `Annotated[T, Resolve(fn)]` est rempli en exécutant `fn` avant le corps de l’outil. Le résolveur renvoie directement la valeur quand il la connaît déjà, ou renvoie `Elicit(...)` pour que le framework pose la question :

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` lit par son nom l’argument `path` de l’outil lui-même, liste le dossier et **n’élicite que lorsqu’il le doit** — un dossier vide se résout en `Confirm(ok=True)` sans aucun aller-retour avec le client.
* `delete_folder` annote `ElicitationResult[Confirm]` : le framework injecte donc le résultat complet et l’outil traite chaque cas avec `match` : accepter et confirmer, accepter mais conserver (`ok=False`), décliner, annuler.
* Le paramètre `confirm` n’apparaît jamais dans le schéma d’entrée de l’outil — le client fournit `path`, le résolveur fournit `confirm`.

Annotez plutôt le modèle non enveloppé (`Annotated[Confirm, Resolve(confirm_delete)]`) quand l’outil n’a pas besoin de bifurquer : il reçoit le modèle en cas d’acceptation, et l’appel s’interrompt avec une erreur en cas de refus ou d’annulation.

Un résolveur fonctionne sur **toutes** les connexions. Pour un client sur une connexion historique, le SDK lui envoie directement la question ; sur une connexion **2026-07-28**, le SDK *renvoie* la question depuis l’appel, et la tentative suivante du client transporte la réponse. Votre résolveur ne voit jamais la différence ; ce qui se passe sous le capot, ce sont les **[Requêtes à plusieurs allers-retours](multi-round-trip.md)** (multi-round-trip).

Demander n’est qu’une des choses qu’un résolveur peut faire. Le mécanisme général — des dépendances qui calculent sans demander, des dépendances de dépendances, ce que le modèle peut et ne peut pas fournir — est décrit sur la page **[Dépendances](dependencies.md)**.

## Demander depuis l’intérieur de l’outil {#ask-from-inside-the-tool}

Un outil peut aussi s’arrêter au milieu de son propre corps et poser une question.

!!! warning
    `ctx.elicit()` et `ctx.elicit_url()` sont des requêtes du *serveur* vers le *client* — un
    canal qui n’existe que pour un client sur une connexion historique (version de spécification **2025-11-25**
    ou antérieure). Sur une connexion **2026-07-28**, il n’y a pas de requêtes à l’initiative du serveur, donc
    ces appels échouent. Un résolveur fonctionne sur les deux. Tous les détails sont dans
    **[Versions du protocole](../protocol-versions.md)**.

`await ctx.elicit()` prend un message et un modèle Pydantic :

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* Le paramètre **`Context`** est ce qui vous donne `ctx.elicit` ; n’importe quel outil peut en prendre un. Cet objet a sa propre page : **[L’objet Context](context.md)**.
* `AlternativeDate` est le **schéma** de la réponse que vous voulez.
* L’outil est `async def`. Il doit l’être : il s’arrête au milieu et attend une personne.
* Pour toute autre date, l’outil renvoie immédiatement. Il ne demande que lorsqu’il le doit.
* La date que l’utilisateur accepte repasse par `book_table` lui-même. Une réponse est une entrée comme une autre : une date de remplacement elle aussi complète fait l’objet d’une nouvelle question, au lieu d’être confirmée à l’aveugle.

### Ce que reçoit le client {#what-the-client-receives}

Le client reçoit votre message et, à côté, un JSON Schema généré à partir du modèle :

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

Ce schéma, c’est le formulaire. `Field(description=...)` est le libellé ; une valeur par défaut préremplit le champ et le rend facultatif. C’est la même mécanique Pydantic vers JSON Schema que **[Outils](../servers/tools.md)** décrit pour les arguments d’un outil.

!!! warning
    Un schéma d’élicitation n’est pas aussi expressif que le schéma d’entrée d’un outil. Des champs plats et primitifs
    uniquement : `str`, `int`, `float`, `bool`, ou un `Literal` de chaînes (il devient un `enum`).
    Mettez un modèle dans le modèle et `ctx.elicit` lève une exception avant que quoi que ce soit ne soit envoyé au client :

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    Vous interrompez une personne en pleine tâche. Si la réponse a besoin d’imbrication, elle aurait dû être un
    argument de l’outil.

### Les trois réponses {#the-three-answers}

`result.action` vous indique ce qu’a fait l’utilisateur, et il y a exactement trois possibilités :

* `"accept"` : il a soumis le formulaire. `result.data` est une instance de `AlternativeDate`, déjà validée.
* `"decline"` : il a dit non.
* `"cancel"` : il a écarté la question sans choisir.

`result.data` n’existe que sur `"accept"`, c’est pourquoi l’exemple vérifie `result.action` d’abord. Votre vérificateur de types impose cet ordre : après `result.action == "accept"`, `result.data` est un `AlternativeDate` ; avant, il n’y a pas de `.data` du tout.

Un refus n’est pas une erreur. L’outil décide de ce que signifie décliner (ici, pas de réservation) et répond normalement au modèle.

!!! tip
    La réponse est validée par rapport à votre modèle avant que votre code ne la voie. Un client qui envoie
    `"maybe"` pour un `bool` ne corrompt pas votre réservation : l’appel échoue avec une
    erreur de non-conformité au schéma, votre `if` ne s’exécute jamais.

## Envoyer l’utilisateur vers une URL {#send-the-user-to-a-url}

Certaines choses ne doivent passer ni par le modèle ni par le client : identifiants, numéros de carte, consentement OAuth. Pour celles-là, vous ne demandez pas de données ; vous demandez à l’utilisateur d’aller quelque part :

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` prend le message, l’**URL** à visiter et un `elicitation_id` que vous choisissez : n’importe quelle chaîne qui identifie cette élicitation au sein de votre serveur.
* Le résultat contient une action et rien d’autre. `"accept"` signifie que l’utilisateur a accepté d’ouvrir l’URL, **pas** qu’il a terminé ce qui se trouve de l’autre côté.
* Le paiement a lieu hors bande, entre le navigateur de l’utilisateur et votre prestataire de paiement. Aucun contenu ne revient jamais par MCP.

Regardez le second outil. Quand votre serveur apprend que le flux hors bande est terminé (un webhook, une interrogation périodique ; ici, c’est modélisé par un second outil), `ctx.session.send_elicit_complete(...)` envoie `notifications/elicitation/complete` avec le même `elicitation_id`. C’est ainsi que le client sait qu’il peut cesser d’afficher *« en attente du paiement… »*. Sans cela, le client ne peut que deviner.

## Côté client {#the-client-side}

Les serveurs demandent. Les clients répondent en passant une fonction de rappel (callback) **`elicitation_callback`** à `Client(...)` :

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* Une seule fonction de rappel gère les deux modes. `params` est une union de `ElicitRequestFormParams` et `ElicitRequestURLParams` ; `isinstance` fait le branchement.
* Pour une URL, vous montrez `params.url` à l’utilisateur et renvoyez l’action qu’il a choisie. Jamais de `content`.
* Pour un formulaire, une vraie application affiche `params.requested_schema` et renvoie la saisie de l’utilisateur comme `content`. Celle-ci dit toujours oui avec une réponse toute faite, ce qui est exactement la fonction de rappel que vous voulez dans un test.
* Passer la fonction de rappel constitue aussi la **déclaration de capacité** : c’est ainsi que le serveur apprend que ce client peut être interrogé. Les autres choses auxquelles un client peut répondre pour un serveur se trouvent dans **[Fonctions de rappel du client](../client/callbacks.md)**.

!!! info
    L’élicitation est une requête du *serveur* vers le *client*, et celles-ci n’existent que sur une
    session à poignée de main (handshake) classique, c’est pourquoi ce client passe `mode="legacy"`.
    Sur une connexion **2026-07-28**, un outil demande plutôt en *renvoyant* la question depuis l’appel ;
    ce flux, ce sont les **[Requêtes à plusieurs allers-retours](multi-round-trip.md)**.

### Essayer {#try-it}

Démarrez le `server.py` en mode formulaire avec `ctx.elicit` (celui de `book_table`) sur Streamable HTTP (**[Exécuter votre serveur](../run/index.md)** donne la commande en une ligne), puis exécutez le `main()` du client et demandez à `book_table` le jour de Noël.

La fonction de rappel affiche la question qui lui a été envoyée :

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

Elle répond avec `{"accept_alternative": True, "date": "2025-12-27"}`, et l’outil, qui attendait dans `await ctx.elicit(...)` pendant tout ce temps, termine la réservation :

```text
Booked a table for 2 on 2025-12-27.
```

Remplacez-le maintenant par le `server.py` en mode URL et pointez le même `main()` vers `pay_deposit` : la même fonction de rappel prend l’autre branche, affiche le lien de paiement, et l’outil revient avec *« Complete the payment in your browser. »* Un aller-retour, en plein appel, dans les deux sens.

!!! check
    Retirez maintenant `elicitation_callback=` du `Client` et appelez de nouveau `book_table` pour le jour de Noël.
    L’appel entier échoue avec une erreur de protocole :

    ```text
    Elicitation not supported
    ```

    Un client qui n’a enregistré aucune fonction de rappel n’a jamais déclaré la capacité `elicitation`, il n’y a donc
    personne à qui demander. Votre outil n’a pas reçu de `"decline"` ; il a reçu une exception. Concevez en conséquence : chaque
    élicitation a besoin d’une réponse sensée à la question « et si je ne peux pas demander ? ».

## Récapitulatif {#recap}

* Un paramètre annoté `Annotated[T, Resolve(fn)]` est rempli par un résolveur, qui renvoie `Elicit(...)` quand il doit demander. Cela fonctionne sur toutes les connexions.
* Le schéma est un modèle Pydantic plat : des champs primitifs uniquement, validés au retour.
* `result.action` vaut `"accept"`, `"decline"` ou `"cancel"` ; `result.data` n’existe qu’en cas d’acceptation.
* `await ctx.elicit(message, schema=Model)` demande depuis l’intérieur du corps de l’outil, et `await ctx.elicit_url(message, url, elicitation_id)` sert à tout ce qui ne doit pas passer par le modèle (`ctx.session.send_elicit_complete(elicitation_id)` indique que la partie hors bande est terminée). Les deux sont des requêtes du serveur vers le client : elles nécessitent que le client soit sur une connexion historique.
* Le client répond avec une seule `elicitation_callback`, en branchant sur le type des params ; l’enregistrer, c’est ce qui déclare la capacité.
* Sur une connexion 2026-07-28, le serveur renvoie la question au lieu de la pousser ; la même fonction de rappel est alimentée par les **[Requêtes à plusieurs allers-retours](multi-round-trip.md)**.

Tout ce qui se trouve sous ce retour (la boucle de réessai, la protection de `requestState`, le pilotage à la main) est dans **[Requêtes à plusieurs allers-retours](multi-round-trip.md)**.
