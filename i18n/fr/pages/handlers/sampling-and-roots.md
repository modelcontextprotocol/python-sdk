---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# Échantillonnage et racines {#sampling-and-roots}

Un gestionnaire (handler) peut demander deux choses de plus au client connecté : une complétion produite par le modèle du client lui-même — l’**échantillonnage** (sampling) — et les dossiers de l’espace de travail du client — les **racines** (roots).

Les deux fonctionnent toujours, sur toutes les versions du protocole que le SDK parle. Mais lisez l’avertissement avant de concevoir quoi que ce soit autour d’elles :

!!! warning "Rendus obsolètes par la spécification 2026-07-28"
    L’échantillonnage et les racines sont obsolètes depuis la version `2026-07-28` ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). Ils restent pleinement fonctionnels et demeurent dans la spécification pendant au moins douze mois avant de pouvoir être supprimés, mais les nouvelles implémentations ne devraient pas s’appuyer dessus. Les migrations suggérées : intégrez-vous directement à l’API de votre fournisseur de LLM au lieu de l’échantillonnage, et transmettez les répertoires via des paramètres d’outil, des URI de ressource ou la configuration du serveur au lieu des racines. La liste complète pour le SDK se trouve dans **[Fonctionnalités obsolètes](../deprecated.md)**.

## Échantillonnage : emprunter le modèle du client {#sampling-borrow-the-clients-model}

Un résolveur renvoie `Sample(...)` et l’outil reçoit la complétion, par le même mécanisme de dépendances qui exécute `Elicit` dans **[Dépendances](dependencies.md)** :

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` reprend les paramètres de `sampling/createMessage`. La valeur injectée est le `CreateMessageResult` du client ; passez `tools` ou `tool_choice` et elle devient un `CreateMessageResultWithTools`.
* Le client doit avoir déclaré la capacité `sampling` (`sampling.tools` si vous passez `tools` ou `tool_choice`). S’il ne l’a pas fait, l’appel échoue avec une erreur de protocole `-32021` au lieu d’envoyer une requête que le client ne peut pas traiter. Une session antérieure à 2026 sans canal de retour (back-channel) échoue avec son erreur habituelle d’absence de canal de retour, puisqu’il n’y a rien sur quoi envoyer.
* En version `2026-07-28`, la requête est acheminée dans le flux à plusieurs allers-retours (multi-round-trip) (**[Requêtes à plusieurs allers-retours](multi-round-trip.md)**) ; en version `2025-11-25`, c’est une requête autonome adressée au client. Le code est le même dans les deux cas, mais gardez à l’esprit la règle des requêtes à plusieurs allers-retours : la requête doit être rendue à l’identique d’une tentative à l’autre, construisez-la donc uniquement à partir des arguments de l’outil et d’autres données stables.
* Ne touchez pas à `include_context` : les valeurs autres que `"none"` sont elles-mêmes obsolètes (SEP-2596) et exigent une capacité que presque aucun client ne déclare.

## Racines : où cela doit-il aller ? {#roots-where-should-this-go}

Les racines sont les dossiers sur lesquels le client indique que le serveur peut opérer. Ce sont des indications à titre informatif, pas un mécanisme de contrôle d’accès. Un résolveur renvoie `ListRoots()` :

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* Le `ListRootsResult` injecté contient une liste de `Root` : un URI `file://` et un nom d’affichage facultatif.
* Le garde-fou est le même que pour l’échantillonnage : sans capacité `roots` déclarée, l’appel échoue avec `-32021` au lieu d’envoyer la requête.

De l’autre côté de la liaison, le client répond aux deux requêtes avec les fonctions de rappel (callbacks) dont il dispose déjà : `sampling_callback` et `list_roots_callback`, décrites dans **[Fonctions de rappel du client](../client/callbacks.md)**.

## Sur les connexions de génération 2025 {#on-2025-era-connections}

`ctx.session.create_message(...)` et `ctx.session.list_roots()` existent toujours pour le code qui pilote la session directement. Elles ne fonctionnent que là où un canal de retour existe (connexions de génération 2025 qui ne sont pas sans état), et les appeler déclenche un avertissement d’obsolescence. Les marqueurs de résolveur ci-dessus sont la forme prise en charge : ils choisissent le mode d’acheminement d’après la version négociée et n’émettent pas d’avertissement.

## Récapitulatif {#recap}

* Renvoyez `Sample(...)` ou `ListRoots()` depuis un résolveur ; l’outil reçoit le `CreateMessageResult` ou le `ListRootsResult` comme n’importe quelle autre dépendance.
* Le client doit déclarer la capacité correspondante, sinon l’appel échoue avec `-32021` au lieu qu’une requête soit envoyée.
* Les deux fonctionnalités sont obsolètes en version `2026-07-28` : pleinement fonctionnelles pour l’instant, inadaptées aux nouvelles conceptions. Préférez les API des fournisseurs à l’échantillonnage et les paramètres explicites aux racines.

Indiquer l’avancement d’un outil lent : **[Progression](progress.md)**.
