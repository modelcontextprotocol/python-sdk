---
translation:
  sections: [09defc170a0da89d]
  tool: 1
---
# Serveurs {#servers}

Un `MCPServer` expose trois primitives à un client connecté. Ce qui les distingue, c’est qui décide de les utiliser :

* Un **[outil (tool)](tools.md)** est une action que le *modèle* choisit et appelle. C’est la page que la plupart des lecteurs veulent en premier, et **[Sortie structurée](structured-output.md)** en est le complément de référence : tout sur la forme de ce qu’un outil renvoie.
* Une **[ressource](resources.md)** est une donnée en lecture seule que l’*application* choisit de lire. **[Modèles d’URI](uri-templates.md)** en est le complément de référence : la syntaxe d’adressage complète et les règles de sécurité des chemins.
* Un **[prompt](prompts.md)** est un modèle de message qu’une *personne* invoque par son nom, depuis un menu ou une commande slash.

Autour de ces trois primitives, voici le reste de ce qu’un serveur déclare :

* **[Complétions](completions.md)** décrit l’autocomplétion côté serveur des arguments de prompts et de modèles de ressources.
* **[Images, audio et icônes](media.md)** couvre tout ce qu’un outil peut renvoyer en dehors du texte, ainsi que les icônes qu’un client affiche à côté de votre serveur.
* **[Gérer les erreurs](handling-errors.md)** explique la différence entre une erreur dont le modèle peut se remettre et une erreur qu’il ne doit jamais voir.

Chaque page ici se suffit à elle-même ; allez directement à celle dont vous avez besoin. Si vous n’avez pas encore construit de serveur, commencez plutôt par **[Premiers pas](../get-started/first-steps.md)**.

Ce qui se passe *à l’intérieur* des fonctions que vous enregistrez (l’objet `Context`, l’injection de dépendances, demander à l’utilisateur des informations supplémentaires en cours d’appel) fait l’objet de la section suivante, **[Dans votre gestionnaire](../handlers/index.md)**.
