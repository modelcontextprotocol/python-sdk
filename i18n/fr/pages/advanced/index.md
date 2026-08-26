---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# Avancé {#advanced}

Tout ce dont un serveur ou un client ordinaire a besoin a sa place, par thème, dans les sections ci-dessus.
Cette section regroupe les échappatoires vers lesquelles vous vous tournez quand la couche de commodité
de `MCPServer` vous gêne :

* **[Le Server de bas niveau](low-level-server.md)** : la classe sur laquelle `MCPServer` est construit.
  Des schémas écrits à la main, des gestionnaires `on_*`, rien de vérifié à votre place, et vos propres
  méthodes JSON-RPC personnalisées.
* **[Pagination](pagination.md)** et **[Middleware](middleware.md)** : deux choses que vous
  ne pouvez faire *que* sur le `Server` de bas niveau.
* **[Extensions](extensions.md)** et **[MCP Apps](apps.md)** : la surface d’extension
  du protocole. Combinez des paquets d’extension dans un serveur, ou écrivez les vôtres.

Quelques éléments que vous pourriez légitimement chercher ici se trouvent plutôt là où vous
les utilisez réellement :

* **L’autorisation** se trouve sous **[Exécuter votre serveur](../run/index.md)**, parce que vous
  protégez un serveur là où vous le déployez.
* **OAuth**, **l’assertion d’identité**, la connexion à **plusieurs serveurs** et le
  **cache** de réponses se trouvent tous sous **[Clients](../client/index.md)**.
* **Les requêtes à plusieurs allers-retours** (multi-round-trip) et **les abonnements** se trouvent sous
  **[Dans votre gestionnaire](../handlers/index.md)**, parce que ce sont deux choses qu’un
  gestionnaire *fait*.
* **Les modèles d’URI** se trouvent sous **[Serveurs](../servers/index.md)**, à côté des ressources.
* **[Versions du protocole](../protocol-versions.md)** et
  **[Fonctionnalités obsolètes](../deprecated.md)** ont chacune leur propre page de premier niveau.

Si vous n’êtes pas sûr d’avoir besoin de cette section, c’est que vous n’en avez pas besoin.
