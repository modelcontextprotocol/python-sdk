---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# Indications de mise en cache {#caching-hints}

Sur le protocole 2026-07-28, chaque résultat qu’un serveur renvoie pour `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` et `server/discover` porte deux champs : `ttlMs`, le nombre de millisecondes pendant lesquelles un client peut considérer le résultat comme frais, et `cacheScope`, qui indique si un résultat mis en cache peut être partagé entre utilisateurs (`"public"`) ou appartient à un seul contexte d’autorisation (`"private"`).

Le serveur ne met rien en cache. Ces champs sont une *déclaration* : « cette liste d’outils est la même pour tout le monde et ne changera pas pendant une minute ». Un client (ou une passerelle placée devant vous) peut alors s’épargner l’aller-retour. Respecter ces indications relève du choix du client ; les émettre est le travail du serveur, et le SDK le fait pour vous.

Par défaut, chaque résultat indique `ttlMs: 0, cacheScope: "private"` : périmé immédiatement, jamais partagé. C’est toujours sûr et toujours conforme. Si vos listes sont réellement stables et identiques pour tous les appelants, dites-le à la construction :

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* Le dictionnaire est indexé par **nom de méthode**, et les six méthodes pouvant être mises en cache sont les seules clés autorisées. Le paramètre est typé `Mapping[CacheableMethod, CacheHint]` : votre éditeur complète donc les clés automatiquement et signale une faute de frappe avant l’exécution ; tout ce qui échappe au vérificateur de types lève une exception à la construction.
* Une méthode que vous ne mentionnez pas garde les valeurs par défaut. Le dictionnaire est un ensemble de surcharges, pas un manifeste.
* `CacheHint(ttl_ms=5_000)` n’a pas défini `scope`, qui reste donc `"private"` : cinq secondes de fraîcheur, par appelant. La portée et le TTL sont deux décisions indépendantes.
* `"server/discover"` est aussi une clé autorisée, puisque le résultat de découverte peut être mis en cache comme n’importe quelle liste.

!!! warning
    `cacheScope: "public"` signifie que *n’importe qui* peut recevoir votre réponse mise en cache. Une passerelle
    partagée transmettra sans hésiter le résultat d’un utilisateur à un autre, même lorsque la requête était
    authentifiée. Ne marquez un résultat `"public"` que s’il est identique pour chaque appelant, et
    n’utilisez jamais `cacheScope` comme contrôle d’accès : c’est une étiquette, pas un verrou.

## Surcharge par gestionnaire {#per-handler-override}

Sur le `Server` bas niveau, les gestionnaires (handlers) construisent leurs résultats à la main, et `ttl_ms` / `cache_scope` sont de simples champs des modèles de résultat. Un gestionnaire qui les définit explicitement l’emporte toujours sur le dictionnaire du constructeur, champ par champ :

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

Le gestionnaire a indiqué `ttl_ms=1_000` et rien sur la portée. Sur la liaison : `ttlMs: 1000` (la valeur du gestionnaire, pas le `60_000` du dictionnaire) et `cacheScope: "public"` (la valeur du dictionnaire, puisque le gestionnaire ne l’a pas définie). L’explicite l’emporte sur le configuré, et le configuré sur la valeur par défaut. Cela vaut champ par champ : un gestionnaire peut donc fixer un champ et laisser l’autre à la politique du serveur.

C’est aussi l’échappatoire pour les comportements dynamiques que le constructeur ne peut pas connaître : un gestionnaire qui filtre `resources/read` par utilisateur peut renvoyer `cache_scope="private"` pour un URI donné sur un serveur par ailleurs public.

Une réserve sur les listes paginées : le protocole exige **le même `cacheScope` sur chaque page** d’une même liste. Le dictionnaire du constructeur y satisfait par construction, puisqu’il est indexé par méthode et non par page. Mais un gestionnaire qui surcharge lui-même la portée devient responsable de cette cohérence : surchargez-la sur *chaque* page, jamais uniquement lorsqu’un curseur est présent, sinon la page un et la page deux se contrediront.

## Ce que voit le client {#what-the-client-sees}

Sur une session 2026-07-28, `Client` respecte les indications pour vous : il embarque un cache de réponses, activé par défaut. Un résultat qui arrive avec un `ttlMs` est stocké, et un appel identique effectué dans ce TTL est servi depuis le cache, sans aller-retour. Un résultat qui ne porte *aucune* indication n’est pas mis en cache : les résultats sans indication reçoivent `CacheConfig.default_ttl_ms`, dont la valeur par défaut est `0` (périmé immédiatement), si bien qu’un serveur qui ne déclare rien voit exactement le même trafic, appel pour appel, qu’auparavant.

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

Quatre appels, trois récupérations. Le deuxième appel a trouvé une entrée fraîche et n’a jamais atteint le serveur ; avancer l’horloge (injectée) au-delà du TTL a fait que le troisième récupère à nouveau ; le quatrième a indiqué `cache_mode="refresh"`. Cet argument nommé existe sur les cinq verbes avec cache (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`) :

* `"use"` (la valeur par défaut) sert une entrée fraîche s’il y en a une, et stocke le résultat récupéré sinon.
* `"refresh"` ne sert jamais depuis le cache : il récupère et stocke le résultat, en remplaçant ce qui était en cache.
* `"bypass"` effectue l’aller-retour sans toucher du tout au cache : ni lecture, ni écriture.

Une règle prime sur `"use"` : **les appels portant `meta` atteignent toujours le serveur.** Une requête avec `meta` défini (un jeton de progression, des champs de traçage) attend une requête sur la liaison ; sous `cache_mode="use"`, elle est donc traitée comme `"refresh"` : la lecture du cache est sautée, et le résultat récupéré remplace quand même l’entrée en cache. `"bypass"` et un `"refresh"` explicite se comportent comme d’habitude.

Pour désactiver entièrement la mise en cache, construisez avec `Client(server, cache=None)` : chaque appel redevient un aller-retour, et `cache_mode`, bien que toujours accepté, n’a aucun effet.

La portée est elle aussi respectée automatiquement : les entrées `"private"` sont indexées sur la *partition* du cache (ci-dessous), tandis que les entrées `"public"` peuvent opter pour un partage plus large. Et **les notifications priment sur le TTL** pour les entrées exactes qu’elles désignent : une notification `list_changed` évince la liste correspondante en cache, et `resources/updated` évince la lecture en cache stockée exactement sous son URI, aussi fraîches soient-elles. Sur une connexion 2026-07-28, ces notifications arrivent sur un flux `subscriptions/listen` que vous ouvrez avec `client.listen(...)`, et l’éviction se termine avant que votre observateur ne voie l’événement ; tous les détails sont dans **[Abonnements](subscriptions.md)**.

Une réserve sur `resources/updated` : l’éviction ne porte que sur l’URI exact. Le contrat du magasin n’a ni opération d’énumération ni de parcours (comme l’implémentation TypeScript de référence), donc une notification portant l’URI d’une *sous*-ressource n’évince pas la lecture en cache de son parent. Si votre serveur signale ainsi des sous-ressources, récupérez à nouveau le parent avec `cache_mode="refresh"`.

### Configurer le cache : `CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store` : l’endroit où vivent les entrées. Par défaut, un nouveau magasin en mémoire par client ; passez votre propre implémentation de `ResponseCacheStore` (adossée à Redis, par exemple) pour partager un cache entre clients ou processus. Les types du contrat (`ResponseCacheStore`, `CacheKey`, `CacheEntry` et le `InMemoryResponseCacheStore` par défaut) sont importables depuis `mcp.client`. Une recherche peut émettre jusqu’à deux `get` séquentiels sur le magasin (la branche privée, puis la publique) ; dimensionnez donc en conséquence vos attentes de latence pour un magasin distant. Un magasin personnalisé **exige** une `partition` explicite.
* `partition` : l’étiquette de contexte d’autorisation qui empêche les entrées `"private"` d’un principal d’être servies à un autre au sein d’un magasin partagé.
* `target_id` : identité explicite du serveur, pour les transports personnalisés et les serveurs en processus (ci-dessous).
* `default_ttl_ms` : TTL appliqué aux résultats qui ne portent aucune indication `ttlMs`. La valeur par défaut `0` laisse les résultats sans indication hors du cache.
* `share_public` : servir entre partitions les entrées que le serveur affirme `"public"` (ci-dessous). Désactivé par défaut.
* `clock` : la source d’horloge murale, en secondes depuis l’epoch. Injectez-en une, comme le fait l’exemple ci-dessus, et les tests d’expiration n’ont pas besoin d’attendre.

!!! warning "Partition = principal vérifié"
    Dérivez `partition` d’**informations d’identification vérifiées**, comme le sujet d’un jeton validé. Ne la dérivez jamais de données fournies par la requête, ni de l’URL du serveur (l’identité du serveur est un axe de clé distinct). Le SDK est une bibliothèque sans authentification propre : l’ancre de confiance est celui qui construit le `CacheConfig`, c’est-à-dire le déploiement, pas le locataire. Une passerelle multi-locataire crée un `CacheConfig` par principal authentifié.

    La partition est aussi figée pour toute la durée de vie du `Client`. Si le contexte d’autorisation de la connexion change en cours de session (une réauthentification sous un autre principal, par exemple), le cache ne suit pas ; construisez un nouveau `Client` pour le nouveau principal.

Les clés du cache portent aussi **l’identité du serveur** : la chaîne d’URL que vous avez appelée, débarrassée de toute partie userinfo `user:pass@` et sinon conservée à l’octet près. Pas de normalisation de la casse, pas de réordonnancement des paramètres de requête, pas de nettoyage de la barre oblique finale. Sous-normaliser ne coûte que du partage, alors que sur-normaliser pourrait fusionner deux locataires (`?tenant=a` et `?tenant=b`) : des URL superficiellement différentes ne partagent tout simplement pas d’entrées. Lorsqu’il n’y a pas d’URL (un serveur en processus, ou une instance de `Transport`), le client reçoit à la place une identité aléatoire par instance ; définissez `CacheConfig.target_id` pour nommer le serveur (avec un magasin personnalisé, c’est obligatoire, et la construction vous le dit). L’identité est hachée en sha256 avant d’entrer dans le matériau de clé, si bien qu’une URL portant des secrets dans sa chaîne de requête n’apparaît jamais dans les clés du magasin. Ne journalisez pas non plus vous-même la forme avant hachage.

!!! warning "`share_public` fait confiance au serveur, pour tout le parc"
    Par défaut, même les entrées `"public"` restent dans leur partition. `share_public=True` sert les entrées que le serveur a marquées `cacheScope: "public"` à **toutes** les partitions qui utilisent le magasin, en faisant confiance à la classification du serveur au nom de chacune d’elles. Un serveur qui appose `"public"` sur des données propres à un locataire (par bogue ou par malveillance) fait alors fuiter la réponse d’un locataire vers les autres. L’option est délibérément limitée au constructeur : le `cache_mode` par appel peut restreindre la mise en cache, mais rien au niveau de l’appel ne peut élargir le partage.

### Ce que le cache ne fait jamais {#what-the-cache-never-does}

* **Les appels au niveau session le contournent.** `client.session.list_tools()` et consorts font toujours l’aller-retour ; le cache vit sur les verbes de `Client`.
* **`server/discover` reste en dehors.** Le résultat de découverte est livré une fois, à la connexion, et n’entre jamais dans le cache de réponses, même lorsqu’il porte un `ttlMs`. Si vous en persistez un vous-même pour éviter la sonde de reconnexion ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), sa fraîcheur relève de votre propre suivi : `DiscoverResult` porte `ttl_ms` et `cache_scope`, déjà analysés, précisément à cette fin.
* **Les pages de continuation ne sont jamais mises en cache.** Seuls les appels sans curseur participent. Une page de continuation rejetée pour curseur expiré *évince* bien la liste en cache, car la liste a changé entre-temps.
* **Les lectures à plusieurs allers-retours (multi-round-trip) ne sont jamais mises en cache.** Un `read_resource` amorcé avec `input_responses`/`request_state`, ou qui se résout au fil de tours de saisie, n’entre jamais dans le cache (un MUST de la spécification).
* **L’éviction par notification a besoin de notifications.** L’éviction ne vaut que ce que vaut la livraison du transport, et le chemin moderne en processus (`Client(server)` avec le `mode="auto"` par défaut) ne livre pas aujourd’hui les notifications autonomes.
* **L’éviction se produit à terme, pas instantanément.** Les notifications qui arrivent par la liaison sont distribuées depuis des tâches lancées à part ; un appel en concurrence avec l’arrivée d’une notification peut donc se voir servir une fois de plus l’entrée d’avant l’éviction ; la fenêtre est bornée par la latence de distribution, et l’éviction a tout de même lieu.
* **Pas de stale-if-error.** Une entrée expirée n’est jamais servie parce que la nouvelle récupération a échoué ; l’erreur se propage.
* **Pas de récupération anticipée.** Une entrée stockée est servie jusqu’à expiration de son TTL, et l’appel suivant paie l’aller-retour ; rien ne se rafraîchit en arrière-plan.
* **Pas de regroupement.** Deux appels identiques concurrents font deux récupérations.
* **Pas de TTL au-delà de 24 heures.** Un `ttlMs` supérieur, qu’il vienne du serveur ou de la configuration, est ramené à ce plafond au stockage (`mcp.client.caching.MAX_TTL_MS`), ce qui borne la durée pendant laquelle une entrée, si généreuse soit son indication, peut être servie.
* Sur un **magasin partagé**, les clients sont en concurrence. Chaque client abandonne sa propre écriture lorsqu’une éviction a doublé la récupération en cours, mais un client *colocataire* peut toujours réécrire une entrée qu’une éviction qu’il n’a jamais vue avait supprimée ; et ce suivi des concurrences est lui-même borné : au-delà de 4 096 clés suivies, la garde de la clé la plus ancienne est abandonnée en premier. Les deux fenêtres sont acceptées, et refermées par le plafond de TTL ci-dessus.
* **Pas de service d’une génération de protocole à l’autre.** Les entrées sont rattachées à la version de protocole négociée : sur un magasin persistant partagé, une session ne sert jamais une entrée écrite sous une autre version négociée (la même liste diffère réellement selon la génération, puisque le SDK retire les champs 2026 pour les sessions plus anciennes). L’éviction, de même, ne touche que les entrées de la génération courante ; les entrées d’une autre génération expirent simplement avec leur TTL.

### Lire les indications vous-même {#reading-the-hints-yourself}

Les indications sont aussi de simples champs sur chaque résultat pouvant être mis en cache (`result.ttl_ms` et `result.cache_scope`, déjà analysés), au cas où vous voudriez superposer votre propre suivi au cache intégré (ou le remplacer).

Face à un **serveur plus ancien** (protocole antérieur à 2026), les champs sont tout simplement absents de la liaison, et les modèles affichent leurs valeurs par défaut prudentes : `ttl_ms == 0` et `cache_scope == "private"`, périmé et non partagé, la bonne hypothèse pour un serveur qui n’a rien déclaré. Le cache traite une session historique de la même façon : les indications n’y sont jamais consultées (quelles que soient les clés présentes sur la liaison), seul `default_ttl_ms` s’applique, et sa valeur par défaut de `0` ne met rien en cache, de sorte qu’une connexion antérieure à 2026 se comporte exactement comme avant l’existence du cache. Si vous devez distinguer « le serveur a dit 0 » de « le serveur n’a rien dit », testez `"ttl_ms" in result.model_fields_set` : il n’est défini que lorsque le champ est réellement arrivé.

## Clients plus anciens {#older-clients}

Les clients sur des versions de protocole antérieures à 2026 ne voient jamais ni l’un ni l’autre de ces champs ; le SDK les retire à la sérialisation pour ces connexions. Configurez vos indications une fois pour toutes ; il n’y a rien de propre à une version à écrire.

## Récapitulatif {#recap}

* Six méthodes portent `ttlMs`/`cacheScope` ; le SDK leur donne par défaut `0`/`"private"`, périmé et non partagé, toujours sûr.
* `cache_hints={method: CacheHint(...)}` à la construction (`MCPServer` comme `Server`) fixe des valeurs par méthode pour tout le serveur.
* Un gestionnaire qui définit les champs sur son résultat surcharge le dictionnaire, champ par champ.
* `"public"` est la promesse que le résultat est identique pour chaque appelant. Ce n’est pas un contrôle d’accès.
* `Client` respecte les indications automatiquement : son cache de réponses est activé par défaut, sert les entrées fraîches au lieu de les récupérer à nouveau, et ne met rien en cache pour les serveurs (ou les sessions) qui ne fournissent aucune indication.
* Par appel, `cache_mode="refresh"` récupère à nouveau et `"bypass"` saute le cache ; `cache=None` à la construction le désactive entièrement.
