---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# Dans votre gestionnaire {#inside-your-handler}

Les arguments d’un gestionnaire (handler) viennent du client. Tout ce qu’il peut lire *d’autre*, et tout ce qu’il peut faire pendant son exécution, se trouve ici.

Ce qu’il peut lire :

* **[L’objet Context](context.md)** est le seul paramètre supplémentaire que n’importe quel gestionnaire peut demander : la requête en cours, ses en-têtes, sa session, ainsi que les verbes de progression et de notification de changement.
* **[Les dépendances](dependencies.md)** sont des paramètres que le modèle ne voit jamais, renseignés par vos propres fonctions avec `Resolve`.
* **[Le cycle de vie](lifespan.md)** (lifespan) couvre l’état que votre serveur construit une seule fois au démarrage, et la façon dont un gestionnaire y accède via l’objet `Context`.

Ce qu’il peut faire pendant son exécution :

* Demander davantage d’informations à l’utilisateur avec **[l’élicitation](elicitation.md)** (elicitation), et les **[requêtes à plusieurs allers-retours](multi-round-trip.md)** (multi-round-trip), le mécanisme de la version 2026-07-28 qui la véhicule.
* Demander au client une complétion de LLM ou les dossiers de son espace de travail avec **[l’échantillonnage et les racines](sampling-and-roots.md)** (sampling et roots), obsolètes mais toujours pris en charge.
* Signaler la **[progression](progress.md)** d’une opération lente.
* Écrire des journaux (sur la sortie d’erreur standard, pour quiconque exploite le serveur) avec la **[journalisation](logging.md)**.
* Prévenir les clients abonnés que quelque chose a changé avec les **[abonnements](subscriptions.md)**.

Si vous n’avez pas encore enregistré de gestionnaire, commencez par **[Outils](../servers/tools.md)**. Chaque page de cette section suppose que vous en avez un.
