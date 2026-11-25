---
translation:
  sections: [3d1663c18edc824c, 90956965ae6a1ca1, af9f398a5a8b679a, 5ce83b1f9d88da62, 0d9b5d13fffc94e5, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# Prendre en charge les clients historiques {#serving-legacy-clients}

MCP a deux générations de protocole : la génération de la poignée de main (handshake) `initialize`, jusqu’à la version de spécification `2025-11-25`, et la génération moderne, `2026-07-28`. **[Versions du protocole](../protocol-versions.md)** est la page consacrée à cette séparation elle-même.

Cette page traite du côté serveur de cette séparation, et la réponse tient en une phrase : **le `streamable_http_app()` que vous déployez déjà sert les deux.**

Le SDK route chaque requête selon son en-tête `MCP-Protocol-Version`. Une requête qui indique `2026-07-28` va au gestionnaire (handler) moderne. Une requête qui indique une version de la génération poignée de main, ou qui ne porte aucun en-tête (c’est ainsi qu’arrive la requête `initialize` d’un client antérieur à 2026), va au transport que ces clients attendent : poignée de main `initialize`, sessions et tout le reste. Cela se fait requête par requête, avant votre code, sur la même et unique application.

Un client historique n’est donc pas quelque chose *pour* lequel vous construisez. C’est quelque chose qui se connecte *au* serveur que vous avez déjà écrit. Vous ne configurez rien.

!!! note
    Rien, littéralement. Il n’y a pas d’option `legacy=`, pas de liste de versions autorisées, aucun
    moyen de refuser ou de désactiver une génération : ni sur `streamable_http_app()`, ni sur `run()`,
    ni sur le gestionnaire de sessions. Les deux générations sont toujours actives. Ce qui se rapproche
    le plus d’un interrupteur par génération dans cette signature, c’est `stateless_http`, et il occupe
    l’essentiel de cette page.

## Un gestionnaire, deux générations {#one-handler-both-eras}

Voici un outil (tool) qui doit demander quelque chose à l’utilisateur :

```python title="server.py" hl_lines="21"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` a besoin d’une chose que le modèle n’a pas fournie : le nombre d’exemplaires. `Annotated[..., Resolve(ask_quantity)]` est la façon dont un outil le déclare (tous les détails sont dans **[Dépendances](../handlers/dependencies.md)**). Rien dans `reserve` ne nomme une version, ne vérifie une capacité ni ne bifurque.

Servez-le en HTTP, et voici des clients des deux générations qui l’appellent :

```console
uv run mcp run server.py --transport streamable-http
```

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/legacy_clients/tutorial001_client.py"
```

Les deux clients sont ouverts **en même temps**, sur le même serveur en cours d’exécution. `mode="legacy"` exécute la poignée de main `initialize` : exactement la connexion qu’ouvre un client antérieur à 2026. L’autre prend la valeur par défaut et arrive en version `2026-07-28`. Lancez `python client.py` depuis un second terminal :

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

Même serveur, même gestionnaire, même réponse. C’est toute la fonctionnalité.

Cela vaut la peine de s’arrêter sur le *comment*, car la même question a été posée aux deux clients sur deux liaisons complètement différentes. La connexion `2026-07-28` n’a aucun canal sur lequel le serveur puisse envoyer une requête ; `Resolve` a donc renvoyé la question dans le résultat de l’outil, et le client a relancé l’appel avec la réponse (**[Requêtes à plusieurs allers-retours (multi-round-trip)](../handlers/multi-round-trip.md)**). La connexion `2025-11-25` n’a rien de tel ; là, `Resolve` a envoyé une vraie requête `elicitation/create` en plein appel et a attendu. Vous n’avez écrit ni l’un ni l’autre. `Resolve` lit la version négociée de la connexion et choisit ; le corps de votre outil voit un `AcceptedElicitation` dans les deux cas.

!!! tip
    Cette portabilité entre générations est *la raison* pour laquelle `Resolve` est l’API sur laquelle
    construire. Son aînée `ctx.elicit()` (**[Élicitation](../handlers/elicitation.md)**) n’envoie jamais
    que `elicitation/create`, et ne fonctionne donc que sur une connexion historique. Sur une connexion
    `2026-07-28`, l’appel échoue. Si un outil l’utilise encore, le correctif est celui que vous voyez
    ci-dessus, pas une vérification de version.

## Ce que vous coûte une session historique {#what-a-legacy-session-costs-you}

Le routage est gratuit. La session ne l’est pas.

Une connexion `2026-07-28` est **sans session** : chaque requête est autonome, et le gestionnaire moderne n’émet jamais de `Mcp-Session-Id`. Une connexion historique, c’est l’inverse. Dès qu’un client antérieur à 2026 envoie `initialize`, le SDK crée un `Mcp-Session-Id`, le renvoie dans un en-tête de réponse et conserve derrière lui un enregistrement vivant que les requêtes ultérieures du client retrouveront : la version négociée, les flux ouverts, une tâche d’arrière-plan qui pilote la session.

Cet enregistrement est un **simple `dict` en mémoire du processus**. Il n’y a pas de magasin de sessions distribué, ni aucun moyen d’en brancher un.

Sur un seul worker, c’est invisible. Sur deux, c’est tout le problème : une requête qui porte un `Mcp-Session-Id` et atterrit sur un worker qui ne l’a pas créé ne trouve rien dans ce dict, et la réponse est un `404` (`Session not found`), pas le résultat de l’outil. Dès que vous exécutez plus d’un worker, **les clients historiques ont donc besoin d’un routage avec affinité (sticky routing)** : chaque requête d’une session doit atteindre le processus qui l’a démarrée. Les clients modernes, jamais ; ils n’ont aucune session à laquelle rester attachés. **[Déployer et passer à l’échelle](deploy.md)** couvre l’affinité et tout le reste sur l’exécution de plusieurs instances.

!!! warning
    `event_store=` ressemble au correctif et ne l’est pas. C’est la **reprise** (rejouer les
    événements SSE manqués pour un client qui se reconnecte à la *même* session), pas un magasin de
    sessions. Il ne rend jamais une session accessible depuis un autre processus.

## Durée de vie et limites des sessions {#session-lifetime-and-limits}

Une session historique ne vit pas éternellement, et un processus n’en conserve pas un nombre
illimité. Deux réglages contrôlent cela. Tous deux sont des arguments nommés de `run()`,
`streamable_http_app()` et `Server.streamable_http_app()`. Les connexions modernes (`2026-07-28`) et
`stateless_http=True` n’ont pas de sessions, si bien qu’aucun des deux réglages ne s’y applique.

| Réglage | Valeur par défaut | Ce qu’il fait | Ce que voit le client | Pour le désactiver |
|---|---|---|---|---|
| `session_idle_timeout` | `1800` (30 min) | Ferme une session qui n’a rien eu en cours pendant cette durée. | `404 Session not found`. Il doit refaire `initialize`. | `None` |
| `max_sessions` | `10_000` | Refuse d’ouvrir une session au-delà de ce nombre. Les sessions existantes ne sont pas touchées et rien n’est évincé. | `503 Too many open sessions` avec le code JSON-RPC `-32603`. | `None` |

Ce qui compte comme « en cours » :

* Un flux `GET` ouvert. Les clients du SDK en gardent un ouvert, si bien que la session d’un client
  connecté n’expire jamais.
* Une requête à laquelle on est encore en train de répondre. Un appel d’outil qui dure plus longtemps
  que le délai n’est pas interrompu, et le compte à rebours ne démarre qu’une fois qu’il a terminé.
* Rien d’autre. Entre les requêtes, l’horloge tourne. N’importe quelle requête sur la session la
  réinitialise, `ping` compris. Une fois qu’une session a expiré, rien ne la ranime.

Un client qui met fin à sa session par un `DELETE` la libère immédiatement. Même chose pour un client
dont la requête d’ouverture a été refusée.

```python
mcp.run(transport="streamable-http", session_idle_timeout=None, max_sessions=50_000)
```

Les deux événements apparaissent dans le journal du serveur. Une expiration donne `Session <id> idle timeout`
au niveau `INFO`. Une ouverture refusée donne `Refusing to open a new session: <n> sessions are already open`
au niveau `WARNING`.

Les limites s’entendent par processus. Avec quatre workers, le plafond est quatre fois `max_sessions`, et
chaque worker fait expirer ses propres sessions.

## Le seul réglage : `stateless_http` {#the-one-knob-stateless_http}

Si l’affinité est un coût que vous refusez de payer, il y a exactement une chose que vous pouvez changer.

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

C’est le serveur du haut de la page, plus un mot-clé. `stateless_http=True` fait que la voie historique construit à la place une session jetable, propre à chaque requête : aucun `Mcp-Session-Id` émis, rien de mémorisé entre les requêtes, si bien que n’importe quel worker peut servir n’importe quelle requête et que le répartiteur de charge peut faire ce qu’il veut.

Deux choses à son sujet comptent plus que ce qu’il fait.

**Il ne touche que la voie historique.** Les requêtes sont routées sur l’en-tête de version *avant* que `stateless_http` ne soit lu, si bien que la voie moderne ne le voit jamais. Une connexion `2026-07-28` est déjà sans session et reste exactement la même quelle que soit la valeur.

**Il coûte les deux canaux serveur-vers-client sur cette voie.** Une session qui vit le temps d’un seul `POST` n’a aucun flux dans lequel le serveur puisse pousser une requête, ni aucun flux autonome dans lequel pousser des notifications. Toute requête à l’initiative du serveur lève `NoBackChannelError` : `ctx.elicit()`, les appels retirés d’échantillonnage (sampling) et de racines (roots) (**[Fonctionnalités obsolètes](../deprecated.md)**), et, oui, `Resolve` qui pose sa question à un client *historique*. Les notifications n’ont même pas droit à une erreur ; elles sont abandonnées silencieusement.

!!! note
    `json_response=True` n’est pas ce réglage, mais il prélève la moitié du même coût sur *chaque*
    session historique : un `POST` auquel on répond par un seul corps JSON n’a aucun flux pour le canal
    lié à la requête, si bien qu’un `ctx.elicit()` en cours de requête lève la même `NoBackChannelError`
    et que les notifications liées à la requête sont abandonnées. Le flux autonome de la session n’est
    pas touché : les notifications sans rapport arrivent toujours.

!!! check
    Faites la mauvaise chose. `reserve` est exactement l’outil qui vient de servir les deux clients.
    Déployez-le avec `stateless_http=True`, connectez les deux mêmes clients et appelez-le depuis
    chacun.

    Le client moderne obtient toujours `Reserved 2 of 'Dune'.` La voie moderne n’a pas changé.

    L’appel du client historique ne revient pas sous la forme d’un résultat `is_error` que le modèle
    pourrait lire. La requête entière échoue, en erreur de protocole de premier niveau :

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` ne vous a pas sauvé. Sur une connexion `2025-11-25`, il *doit* envoyer
    `elicitation/create`, et le canal dont il a besoin est exactement ce que `stateless_http=True` a
    abandonné. Un code portable entre générations n’est pas un code sans canal de retour (back-channel).

C’est donc un vrai compromis, et il n’existe que sur la voie historique : **avec session et affinité, ou sans état et à sens unique.** Si vos outils ne rappellent jamais le client, `stateless_http=True` est gratuit et vous devriez le prendre. S’ils le font, gardez les sessions et gardez le routage avec affinité.

## Où votre code bifurque réellement {#where-your-code-actually-forks}

Presque nulle part.

Outils, ressources, prompts, sortie structurée, progression, erreurs : aucun ne se soucie de la génération qui a appelé. La poignée de main `initialize`, le `Mcp-Session-Id`, le flux autonome, le `DELETE` qui met fin à une session : le SDK possède tout cela, et un gestionnaire n’en voit jamais rien. La saisie interactive est *le* seul endroit où les générations diffèrent véritablement sur la liaison, et `Resolve` existe pour que ce ne soit pas votre problème : vous venez de voir un seul outil servir les deux.

Il reste exactement une chose, et ce sont les **notifications de changement**, parce que les deux générations écoutent sur des tuyaux différents :

* Un client `2026-07-28` ouvre un flux `subscriptions/listen` et lit le bus des abonnements. `ctx.notify_resource_updated()` (et `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`) y publient, et *seulement* là. **[Abonnements](../handlers/subscriptions.md)** est la page correspondante.
* Un client historique lit le flux autonome que sa session garde ouvert. `ctx.session.send_resource_updated()` (et `send_tool_list_changed()` et consorts) écrivent sur la *connexion* qui a porté la requête : pour une session historique, c’est son flux autonome. Une connexion moderne n’a pas d’endroit pour cela : en HTTP, ce canal n’existe pas, et en stdio les quatre types de notifications de changement ne circulent que sur les flux `subscriptions/listen`, si bien que sur une connexion moderne la notification est discrètement abandonnée.

En HTTP, aucun des deux appels n’atteint les clients de l’autre génération. Pour prévenir tout le monde, appelez les deux :

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

Deux lignes, pas de `if`, pas de vérification de version, et c’est terminé. C’est la liste complète des choses qu’un gestionnaire fait différemment parce qu’un client historique existe.

## Récapitulatif {#recap}

* Un seul `streamable_http_app()` sert les deux générations de protocole. Le SDK route chaque requête selon son en-tête `MCP-Protocol-Version` ; il n’y a rien à configurer et aucun réglage de génération à chercher.
* Un client historique vous coûte une session : un enregistrement `Mcp-Session-Id` en mémoire du processus, sans magasin distribué derrière. Plus d’un worker signifie **routage avec affinité**, sinon le mauvais worker répond `404 Session not found`. Tous les détails sur le multi-worker sont dans **[Déployer et passer à l’échelle](deploy.md)**.
* `stateless_http=True` est le seul réglage, et il ne concerne **que la voie historique**. Il offre une répartition de charge gratuite aux clients historiques au prix des deux canaux serveur-vers-client sur cette voie : les requêtes à l’initiative du serveur lèvent `NoBackChannelError` (une erreur de premier niveau côté client, pas un résultat `is_error`), et les notifications sont abandonnées.
* Une connexion `2026-07-28` est sans session dans tous les cas. `stateless_http` ne la touche jamais.
* Le code de vos gestionnaires bifurque selon la génération à un seul endroit exactement : les notifications de changement. `ctx.notify_*` atteint les clients `subscriptions/listen` ; `ctx.session.send_*` atteint les sessions historiques. Appelez les deux.
* Tout le reste (y compris demander une saisie à l’utilisateur, via `Resolve`) est portable entre générations par construction. Écrivez la version moderne une seule fois.
