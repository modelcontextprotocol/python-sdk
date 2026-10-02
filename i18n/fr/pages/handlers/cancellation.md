---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# Annulation {#cancellation}

Un client peut abandonner un appel : l’utilisateur a appuyé sur stop, ou un délai d’attente a expiré.

Dans ce cas, le SDK **annule votre gestionnaire** (handler). Le `await` sur lequel il est en attente lève une exception, la fonction est dépilée, et rien de ce qu’elle renvoie n’est envoyé. La plupart des gestionnaires n’ont rien à faire de particulier.

Deux catégories font exception : un gestionnaire qui a quelque chose à nettoyer, et un gestionnaire écrit comme un simple `def`.

## Nettoyer dans un outil `async def` {#clean-up-in-an-async-def-tool}

Placez le nettoyage dans un `finally` :

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* Le `finally` s’exécute quelle que soit la façon dont l’outil se termine : il a renvoyé une valeur, il a levé une exception ou il a été annulé.
* Un nettoyage qui doit faire un `await` a besoin de `shield=True`. Dans un gestionnaire annulé, chaque `await` suivant lève lui aussi une exception : sans cette protection, `release_hold` s’arrêterait dès sa première ligne.
* Rien ne peut annuler un bloc protégé, alors donnez-lui une limite de temps. Ici, elle est de `5` secondes.

!!! tip
    Utilisez `finally`, pas `except`. L’annulation doit continuer à remonter une fois votre nettoyage
    terminé, et un `finally` la laisse passer.

## S’arrêter tôt dans un outil `def` simple {#stop-early-in-a-plain-def-tool}

Un outil `def` simple s’exécute dans un thread, et rien ne peut interrompre un thread de l’extérieur. C’est à l’outil de poser la question :

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` ne fait rien tant que l’appel est en cours, et lève une exception une fois qu’il a été annulé. Appelez-la entre deux unités de travail.
* Ici aussi, le nettoyage va dans un `finally`. Dans un thread, il n’y a aucune attente asynchrone, donc aucune protection n’est nécessaire.
* Un outil `def` qui ne pose jamais la question s’exécute jusqu’au bout, et son résultat est jeté.

## Où cela s’applique {#where-it-applies}

Les fonctions de prompt et de ressource sont annulées exactement comme les outils.

Cela fonctionne de la même façon avec stdio et Streamable HTTP. Avec la classe `Client` de ce SDK, abandonner revient à annuler la tâche qui attend `call_tool`, ou à laisser son délai `read_timeout_seconds` expirer.

!!! warning
    Deux options de Streamable HTTP empêchent la nouvelle d’atteindre votre gestionnaire : `json_response=True` sur une
    connexion `2026-07-28`, et `stateless_http=True` sur une connexion historique. Dans ces cas, le gestionnaire s’exécute
    jusqu’au bout, quoi qu’ait fait le client.

## Récapitulatif {#recap}

* Quand le client abandonne un appel, le SDK annule le gestionnaire : outil, prompt ou ressource.
* `async def` : nettoyez dans un `finally`, et placez tout nettoyage qui comporte une attente asynchrone dans `anyio.move_on_after(seconds, shield=True)`.
* `def` simple : appelez `anyio.from_thread.check_cancelled()` entre deux unités de travail, sinon l’outil s’exécute jusqu’au bout. Un simple `finally` se charge du nettoyage.
* `json_response=True` (connexions modernes) et `stateless_http=True` (connexions historiques) désactivent l’annulation.

La progression et l’annulation se jouent entre un outil en cours d’exécution et son *appelant*. Les lignes qu’il journalise pour *vous*, la personne qui exploite le serveur, passent par un autre canal : **[Journalisation](logging.md)**.
