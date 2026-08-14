---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# Déployer et passer à l’échelle {#deploy-scale}

Votre serveur fonctionne. Il lui faut maintenant un vrai nom d’hôte, et plus d’un worker derrière lui.

Presque rien de tout cela ne regarde MCP. Vous apportez le serveur ASGI, le gestionnaire de processus, le répartiteur de charge. Ce que contient cette page, c’est la courte liste de ce qui *regarde* bel et bien MCP : un réglage qui conditionne tout déploiement, et les deux endroits où « plus d’un worker » change ce que fait le SDK.

## Avant toute chose : la liste des hôtes autorisés {#before-anything-else-the-host-allowlist}

`streamable_http_app()` ne peut pas savoir derrière quel nom d’hôte il sera servi, il retient donc la réponse la plus sûre : localhost. Sans `transport_security=`, l’application active la **protection contre le DNS rebinding** et n’accepte une requête que si son en-tête `Host` vaut `127.0.0.1:<port>`, `localhost:<port>` ou `[::1]:<port>`. L’en-tête `Origin`, quand il y en a un, doit être la forme `http://` du même hôte. Sur votre machine, c’est exactement ce qu’il faut : cela empêche une page web malveillante de piloter votre serveur local via un nom DNS qu’elle a fait pointer vers `127.0.0.1`.

Déployée derrière un vrai nom d’hôte, cette même valeur par défaut rejette **toutes les requêtes** tant que vous ne dites pas le contraire. La vérification s’exécute avant tout ce qui ressemble à du MCP, si bien que rien de ce que vous avez construit n’est même consulté :

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

`transport_security=` est le correctif. Autorisez ce que vous servez réellement :

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* Les entrées de `allowed_hosts` sont des chaînes exactes : `"mcp.example.com"` correspond à un en-tête `Host` sans port et `"mcp.example.com:*"` correspond à n’importe quel port. Listez les deux.
* `allowed_origins` ne compte que pour les navigateurs, car rien d’autre n’envoie `Origin`. C’est le pendant côté serveur de la configuration CORS décrite dans **[Ajouter à une application existante](asgi.md)**.
* Derrière un proxy inverse qui contrôle déjà l’en-tête `Host`, désactiver la vérification est la configuration honnête : `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.
* Passer un `host=` autre que localhost (par exemple `host="mcp.example.com"`) n’autorise **pas** ce nom d’hôte. Cela empêche seulement la valeur par défaut localhost d’armer la protection, ce qui laisse passer tous les Host et tous les Origin. Dites plutôt ce que vous voulez avec `transport_security=`.

!!! check
    Supprimez l’argument `transport_security=security` et déployez quand même l’application. Elle
    démarre, `/mcp` route, et chaque requête (y compris depuis un simple `curl`) revient avec :

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    Vous ne trouverez pas ces mots côté client. Un `421` est une réponse HTTP en texte brut, pas une
    erreur JSON-RPC, si bien que le client MCP lève une erreur de transport générique ; le nom d’hôte
    qu’il n’a pas apprécié n’apparaît que dans le journal du **serveur**, sous la forme d’un unique
    avertissement. Un serveur fraîchement déployé qui refuse toutes les connexions est un problème
    de liste des hôtes autorisés jusqu’à preuve du contraire.
    **[Dépannage](../troubleshooting.md)** commence aussi par là.

## Les workers, et qui a besoin d’affinité {#workers-and-who-has-to-be-sticky}

Une fois que le nom d’hôte répond, placez plus d’un worker derrière lui. Le SDK n’a aucun réglage pour cela ; vous passez une application Starlette à l’échelle comme n’importe quelle application ASGI, en confiant l’objet à quelque chose qui sait créer des processus (fork) :

```console
uvicorn server:app --workers 4
```

Quatre processus, un socket. Et maintenant la question à laquelle tout déploiement doit répondre : **une requête doit-elle atteindre le worker qui a vu la précédente ?**

Pour un client qui parle le protocole **2026-07-28**, non. Une requête moderne est un unique POST autonome : pas de poignée de main (handshake) `initialize` avant elle, pas de `Mcp-Session-Id` sur la réponse, rien *vers quoi* une deuxième requête devrait revenir. Routez-la vers n’importe quel worker.

Ce n’est pas un mode que vous activez. `stateless_http=True` en a tout l’air, mais le transport route d’après l’en-tête de requête `MCP-Protocol-Version`, confie une requête moderne au gestionnaire moderne, et **rend la main**. La ligne qui lit `stateless_http` vient *après* ce retour. Ce n’est pas que l’indicateur soit ignoré sur le chemin 2026-07-28 ; il n’est jamais atteint. `stateless_http` est un réglage pour la branche **historique** uniquement, et le chemin moderne est sans session par construction.

Pour un client historique en version 2025-11-25 de la spécification ou antérieure, la réponse dépend de cet indicateur :

| Version du protocole du client | Session | Ce que le répartiteur de charge doit faire |
| --- | --- | --- |
| **2026-07-28** | Aucune. `Mcp-Session-Id` n’est jamais défini. | Rien. N’importe quel worker sert n’importe quelle requête. |
| **2025-11-25 et antérieures** (par défaut) | `Mcp-Session-Id`, conservé dans la mémoire d’un seul worker. | **Affinité de session (sticky sessions).** Une requête suivante qui atteint un autre worker reçoit un `404` *« Session not found »*. |
| **2025-11-25 et antérieures**, avec `stateless_http=True` | Aucune. | Rien. Le prix à payer est le canal de retour (back-channel) du serveur vers le client — échantillonnage (sampling), élicitation (elicitation) en push, `roots/list` — et la reprise. |

L’affinité de session et le coût de la branche historique ont leur propre page, **[Prendre en charge les clients historiques](legacy-clients.md)** ; les deux générations elles-mêmes sont décrites dans **[Versions du protocole](../protocol-versions.md)**. Ce qui compte ici, c’est la forme de la réponse : *en version 2026-07-28, vous êtes déjà sans état, sans rien à configurer.*

Le reste de cette page porte sur les deux choses que l’absence d’état ne vous apporte **pas**.

## `requestState` d’un worker à l’autre {#requeststate-across-workers}

Un outil **[à plusieurs allers-retours (multi-round-trip)](../handlers/multi-round-trip.md)** a besoin de quelque chose que le client doit aller chercher (une confirmation, un choix, un identifiant), il renvoie donc une question au lieu d’une réponse et termine lors de la nouvelle tentative. Entre les deux tours, le client détient un jeton `request_state` opaque émis par le serveur. Lors de la nouvelle tentative, le serveur doit rouvrir ce jeton.

*Scellé sous quelle clé ?* Par défaut, une clé que le serveur a générée avec `os.urandom(32)` au moment de sa construction. Avec `--workers 4`, cela fait quatre constructions, dans quatre processus : quatre clés différentes, jamais écrites nulle part, jamais partagées, perdues au redémarrage.

Voici un outil qui demande avant d’agir, sur un serveur qui ne configure rien :

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

Le premier tour atteint le worker A. Le worker A scelle `refund:120` sous **sa** clé et renvoie le jeton. Le client présente la question à une personne, obtient un oui, et retente. La nouvelle tentative est une requête HTTP toute neuve.

!!! check
    Laissez cette nouvelle tentative atteindre le worker B. B essaie de desceller un jeton qu’il n’a
    pas émis, n’y parvient pas, et refuse tout le tour. `refund` n’est jamais appelé ; le client
    reçoit une erreur JSON-RPC :

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    Ce message est **figé**. Expiré, falsifié, rejoué avec des arguments différents, ou (de loin la
    cause la plus fréquente dans un vrai déploiement) scellé par un worker voisin : le client reçoit
    chaque fois la même chose, si bien que la liaison ne révèle jamais quelle vérification a échoué.
    La vraie raison est un unique `WARNING` dans le journal du serveur :

    ```text
    requestState rejected on tools/call: unknown key
    ```

    Un outil à plusieurs allers-retours qui fonctionnait avec un worker et s’est mis à échouer *de
    temps en temps* avec deux, c’est cela. Les deux tours doivent toujours atteindre le même
    processus, il échoue donc exactement aussi souvent que votre répartiteur de charge les sépare.

Les deux tours sont deux requêtes HTTP indépendantes, et plusieurs choses ordinaires les séparent : un proxy qui répartit requête par requête, une connexion tombée entre les deux, un déploiement ou un redémarrage, un client qui a persisté `request_state` et reprend depuis un tout autre processus (**[Piloter la boucle vous-même](../handlers/multi-round-trip.md#driving-the-loop-yourself)**). Chacune d’elles revient à « un autre worker ».

Le correctif tient en un argument. Il a **deux** moitiés.

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** est la moitié que tout le monde trouve. Donnez à chaque instance le même secret (au moins 32 octets), et chaque instance peut desceller ce que n’importe quelle autre a émis. `keys[0]` scelle et chaque clé de la liste descelle, ce qui forme l’anneau de rotation ; **[Faire tourner les clés](../handlers/multi-round-trip.md#rotating-keys)** explique comment le faire tourner sans interruption de service.
* **Le nom du serveur** est la moitié que presque personne ne trouve, et la raison pour laquelle les nouvelles tentatives entre instances échouent encore après avoir partagé la clé. Chaque jeton scellé porte le `name` du serveur comme **revendication d’audience** (audience claim), vérifiée strictement au retour. Deux instances construites à partir du même code ont le même nom et ne le remarquent jamais. Nommez-les différemment (`MCPServer(f"billing-{POD}")` ressemble à une bonne hygiène d’observabilité), et chaque nouvelle tentative entre instances est refusée exactement comme ci-dessus, clé partagée ou non. Le journal indique `audience` au lieu de `unknown key` ; le client ne voit pas la différence.

Générez le secret une fois et donnez la même valeur à chaque instance. C’est la commande que le message d’erreur du SDK lui-même vous indique d’exécuter si vous lui passez moins de 32 octets :

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "Les mêmes clés, *et* le même nom"
    Un déploiement à plusieurs instances doit partager les deux. Si les noms par instance comptent
    vraiment pour vous, donnez plutôt une audience explicite à toute la flotte :
    `RequestStateSecurity(keys=[...], audience="billing")`. Chaque instance émet et accepte alors
    sous `"billing"`, quel que soit son nom.

Tout le reste sur le scellement se trouve dans **[Protéger `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)** : ce qu’il lie, le `ttl` par tour (600 secondes par défaut), apporter votre propre codec, pourquoi la valeur par défaut non configurée est exactement ce qu’il faut sur `stdio`. Toute la contribution de cette page tient en une liste de contrôle à deux éléments : *mêmes clés, même nom.*

!!! info
    Vous êtes sur ce chemin même si vous n’avez jamais tapé `InputRequiredResult`. Un outil dont les
    paramètres utilisent `Resolve(...)` (**[Dépendances](../handlers/dependencies.md)**) est un outil
    à plusieurs allers-retours, et le SDK émet et scelle son `request_state` pour lui. Même clé par
    défaut, même échec entre workers, même correctif.

## Notifications de changement d’une réplique à l’autre {#change-notifications-across-replicas}

Le flux `subscriptions/listen` d’un client est une unique réponse de longue durée, il est donc épinglé à une réplique pendant toute sa durée de vie. Un `ctx.notify_resource_updated(...)` publié sur une **autre** réplique doit l’atteindre.

La jonction entre les deux est le `SubscriptionBus`. Le bus que vous donnez à un serveur est celui où va chaque publication et sur lequel écoute chaque flux ouvert ; donnez donc le même bus à chaque réplique :

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

Rien dans la diffusion ne se soucie de l’objet serveur auquel un flux est attaché. Deux serveurs qui partagent un même `InMemorySubscriptionBus` se comportent déjà ainsi : ouvrez un flux d’écoute sur l’un, appelez `edit_note` sur l’autre, et le flux en est informé. Ce bus en mémoire ne couvre que les objets serveur d’un même processus, ce qui en fait le modèle, pas le déploiement :

* Entre de vrais processus, **le SDK ne fournit aucun bus qui puisse vous aider.** `SubscriptionBus` est un `Protocol` à deux méthodes (`publish` et `subscribe`) que vous implémentez par-dessus votre propre backend pub/sub (Redis, NATS, ce que vous exploitez déjà) et passez sous la forme `MCPServer(subscriptions=...)`. **[Abonnements](../handlers/subscriptions.md#scaling-past-one-process)** contient l’esquisse et le contrat.
* Le bus transporte quatre petits événements typés, jamais de JSON-RPC. L’accusé de réception, le filtrage et le cycle de vie des flux restent dans le SDK, si bien que votre bus ne peut pas casser le protocole ; il ne peut que déplacer des événements entre processus.
* Les flux ne sont **pas** reprenables et les événements ne sont **pas** rejoués. Perdre une réplique abandonne ses flux ; les clients se remettent à l’écoute et récupèrent de nouveau les données. Il n’y a pas de magasin d’événements à partager et rien d’autre à configurer. C’est le seul endroit où la montée en charge horizontale revient réellement à faire la même chose en plus grand.

## Ce que le SDK ne vous donne pas {#what-the-sdk-does-not-give-you}

Un `MCPServer` est une implémentation du protocole, pas un serveur d’applications. Les réglages de déploiement que vous chercherez ensuite manquent volontairement :

* **Pas de `workers=`.** `mcp.run("streamable-http")` démarre exactement un processus uvicorn, et c’est tout ce qu’il démarrera jamais. Le multi-processus, c’est `streamable_http_app()` confié à ce avec quoi vous déployez déjà de l’ASGI : `uvicorn --workers`, gunicorn, le gestionnaire de processus de votre plateforme. Cette page n’est délibérément un tutoriel pour aucun d’eux ; leur documentation est meilleure que ne le serait une copie ici.
* **Pas de route de contrôle de santé.** `@mcp.custom_route("/health", methods=["GET"])` est toute la réponse, et elle n’est jamais authentifiée même quand le reste du serveur l’est. C’est ce qu’il faut pour une sonde de vivacité, pas pour quoi que ce soit de privé. **[Ajouter à une application existante](asgi.md#custom-routes)** en montre une.
* **Pas d’objet de réglages de production.** Il n’y a nulle part sur `MCPServer` où noter les délais d’expiration, TLS, l’arrêt progressif ou les limites de connexions, parce que rien de cela n’est son travail. Cela relève de votre serveur ASGI, et c’est là que vous le configurez. **[Exécuter votre serveur](index.md)** couvre la poignée de réglages que le constructeur accepte *effectivement*.
* **Pas de `EventStore` fourni, et en version 2026-07-28 aucun usage pour un tel objet.** La reprise est une fonctionnalité de la branche historique avec état ; un échange moderne, c’est un POST, une réponse, et rien à reprendre.

## Récapitulatif {#recap}

* Par défaut, l’application ne répond qu’aux requêtes adressées à localhost. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` est le passage obligé avant la mise en production : tant que vous ne le passez pas, chaque requête derrière un vrai nom d’hôte est un `421` et la raison n’est que dans le journal du serveur.
* En version 2026-07-28, il n’y a pas de session et rien sur quoi un répartiteur de charge pourrait établir une affinité. `stateless_http=True` est un réglage réservé à la branche historique, parce qu’une requête moderne est routée et traitée avant même que cet indicateur soit lu.
* La clé `requestState` par défaut est `os.urandom(32)`, générée par processus. Une nouvelle tentative à plusieurs allers-retours qui atteint un autre worker échoue avec `-32602` *« Invalid or expired requestState »*.
* Le correctif est `RequestStateSecurity(keys=[...])` **et** le même nom de serveur sur chaque instance. Le nom est la revendication d’audience par défaut du jeton. Mêmes clés, même nom.
* Les notifications de changement traversent les répliques via un unique `SubscriptionBus` partagé. La seule implémentation du SDK fonctionne dans un seul processus ; le `Protocol` à deux méthodes par-dessus votre propre pub/sub, c’est à vous de l’écrire.
* Il n’y a pas de `workers=`, pas de route de santé, pas d’objet de réglages de production. Apportez votre propre serveur ASGI.

L’autre chose dont un vrai nom d’hôte a besoin devant lui, c’est un jeton : **[Autorisation](authorization.md)**.
