---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# Extensions {#extensions}

Une **extension** est un ensemble de comportements MCP, activable sur demande, regroupé derrière un seul identifiant.

Côté serveur, elle peut apporter des outils (tools), des ressources et de nouvelles méthodes de requête, et elle peut envelopper `tools/call`. Côté client, elle peut revendiquer des formes de résultat `tools/call` supplémentaires et observer des notifications propres à un éditeur. Chaque côté s’annonce sous son propre `capabilities.extensions`, et rien ne change pour quiconque ne l’a pas demandé. C’est le contrat ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)), et il a une règle d’or : **les extensions sont désactivées par défaut**.

## Utiliser une extension {#using-an-extension}

Passez des instances à la construction :

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

C’est fait. Le serveur annonce désormais `io.modelcontextprotocol/ui` sous `capabilities.extensions` et sert tout ce que l’extension apporte.

`Apps` est l’extension de référence intégrée, et elle a sa propre page : **[MCP Apps](apps.md)**.

!!! note
    Les extensions sont figées à la construction. Il n’existe pas de `add_extension` à appeler plus tard : la table des capacités d’un serveur ne devrait pas changer pendant que des clients y sont connectés.

La table des capacités transite par `server/discover`, qui est un chemin **2026-07-28**. Une poignée de main (handshake) `initialize` historique n’a aucun endroit où la placer, donc un client historique ne voit tout simplement pas l’extension. Concevez en conséquence : une extension *enrichit* un serveur, elle ne doit pas être la seule manière de le rendre utilisable.

## Écrire la vôtre {#writing-your-own}

Dérivez `Extension` et ne redéfinissez que ce dont vous avez besoin. Chaque méthode a une valeur par défaut.

### L’identifiant {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

L’identifiant est une chaîne `vendor-prefix/name` qui suit la grammaire des clés `_meta` de la spécification : des libellés séparés par des points (chacun commence par une lettre et se termine par une lettre ou un chiffre), une barre oblique, puis le nom. Il est validé **au moment où la classe est définie**, de sorte qu’une faute de frappe n’attend pas le démarrage d’un serveur :

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

Utilisez comme préfixe un domaine que vous contrôlez. `io.modelcontextprotocol/*` est réservé aux extensions spécifiées par le projet MCP lui-même.

### Apporter des outils {#contributing-tools}

La plus petite extension utile, c’est un outil et une table de paramètres :

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` renvoie des `ToolBinding`. Le serveur enregistre chacun exactement comme si vous aviez appelé `mcp.add_tool(...)` vous-même : même génération de schéma, même injection de `Context`, tout à l’identique.
* `settings()` est la valeur annoncée sous `capabilities.extensions["com.example/stamps"]`. Renvoyez `{}` (la valeur par défaut) pour annoncer l’extension sans paramètres.
* L’extension ne reçoit jamais le serveur. Elle déclare ses contributions sous forme de données ; `MCPServer` les consomme. Il n’y a pas de `self.server` à modifier.

Et `main()` en est la preuve, un client en mémoire branché directement sur `mcp` :

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### Servir vos propres méthodes {#serving-your-own-methods}

Une extension peut enregistrer de **nouvelles méthodes de requête** : ses propres verbes, servis à côté de ceux de la spécification :

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` dérive de `RequestParams`, si bien que l’enveloppe `_meta` de 2026 est analysée de façon uniforme et que votre gestionnaire (handler) reçoit des paramètres validés, jamais un dict brut. Bornez ce que le client contrôle : `Field(ge=1, le=100)` rejette un `limit` absurde avant que votre code n’alloue quoi que ce soit pour lui.
* `require_client_extension(ctx, EXTENSION_ID)` est le garde-fou : un client qui n’a pas déclaré l’extension reçoit l’erreur `-32021` (capacité client obligatoire manquante), avec la charge utile `requiredCapabilities` lisible par machine que la spécification demande.
* `protocol_versions=frozenset({"2026-07-28"})` épingle la méthode à une seule version de la liaison. Dans toute autre version, le client reçoit `METHOD_NOT_FOUND`, exactement comme si la méthode n’y existait pas. Pour ce client, elle n’existe pas.

Les méthodes sont **strictement additives**. Le SDK le fait respecter à la construction, pas à l’exécution :

* Un `MethodBinding` pour une méthode définie par la spécification (`tools/list`, `completion/complete`…) lève une `ValueError` lors de la construction du binding. Les verbes de base appartiennent au serveur.
* Deux extensions qui lient la même méthode lèvent une exception quand la seconde s’enregistre. Laisser la dernière écriture l’emporter, c’est ainsi que des plugins se corrompent mutuellement ; nous ne faisons pas cela.
* Un ensemble `protocol_versions` vide lève aussi une exception : une méthode qui ne peut jamais être servie est un bogue, pas une configuration.

### Le côté client {#the-client-side}

Le `main()` du même fichier raconte toute l’histoire côté client, ses deux moitiés :

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` déclare l’extension. Les déclarations deviennent `ClientCapabilities.extensions` : sur une connexion 2026-07-28, la table voyage dans l’enveloppe `_meta` de chaque requête, donc le serveur la voit sur **chaque** requête ; sur une connexion historique, elle transite par la poignée de main `initialize`. Le code serveur ne s’en soucie pas : `require_client_extension(ctx, ...)` et `ctx.session.check_client_capability(...)` lisent la bonne source dans les deux cas.
* Les méthodes propres à un éditeur descendent d’un niveau, vers `client.session.send_request(...)` ; `Client` n’acquiert de méthodes de premier rang que pour les verbes de la spécification. `send_request` accepte n’importe quelle sous-classe de `Request`, donc la requête de l’éditeur passe telle quelle.

### Intercepter `tools/call` {#intercepting-toolscall}

Le seul hook d’interception. Redéfinissez `intercept_tool_call` pour observer, court-circuiter ou opposer un veto à un appel d’outil :

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` est le `CallToolRequestParams` validé : vous obtenez `params.name` et `params.arguments` sans toucher au JSON brut. C’est aussi lui qui décide quel appel d’outil s’exécute : passer un contexte réécrit à `call_next` change ce que le gestionnaire observe sur `ctx`, pas l’invocation de l’outil. La réécriture de requêtes au niveau de la liaison relève du [Middleware](middleware.md).
* `call_next(ctx)` exécute le reste de la chaîne et renvoie le résultat du gestionnaire. Renvoyez-le tel quel (observer), renvoyez autre chose (remplacer) ou levez une `MCPError` (refuser). Ce que vous renvoyez est sérialisé comme n’importe quel résultat de gestionnaire, y compris l’estampille d’identité `serverInfo` de la génération 2026, si bien qu’un intercepteur qui court-circuite ne produit jamais de réponse anonyme ou hors schéma.
* Avec plusieurs extensions, les intercepteurs s’imbriquent dans l’ordre d’enregistrement : la première extension de `extensions=[...]` est la plus externe.
* L’implémentation par défaut laisse passer sans rien faire, et un serveur dont les extensions ne redéfinissent jamais ce hook conserve le gestionnaire `tools/call` nu, intact. Vous ne payez pas pour ce que vous n’utilisez pas.

Le hook enveloppe `tools/call` et rien d’autre. Pour ce qui concerne chaque message, utilisez le [Middleware](middleware.md). Il est fait pour cela.

## Utiliser une extension client {#using-a-client-extension}

Une **extension client**, c’est le même contrat vu du côté consommateur : un ensemble de comportements côté client derrière un seul identifiant. Passez des instances à `Client(extensions=[...])` et appelez les outils normalement :

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` renvoie un simple `CallToolResult`, comme tout autre appel. Ce que l’extension a changé : le serveur peut désormais répondre à `buy` par une **forme de résultat** `receipt` au lieu d’un résultat final, et `Receipts` la termine (ici en échangeant le reçu via un appel de suivi) avant que `call_tool` ne renvoie. Rien ne bouge au point d’appel.

Retirez l’extension et rien de tout cela n’existe : le garde-fou du serveur refuse un client qui ne l’a pas déclarée (erreur -32021), et une forme revendiquée venant d’un serveur qui saute le garde-fou échoue à la validation, exactement comme la spécification l’exige pour un `resultType` non reconnu. Désactivé par défaut, aux deux bouts de la liaison.

Pour annoncer un identifiant **sans aucun** comportement côté client (le serveur filtre sur la capacité, le client ne fait rien, comme dans le client de recherche ci-dessus), utilisez `advertise()` :

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## Écrire une extension client {#writing-a-client-extension}

Dérivez `ClientExtension` et ne redéfinissez que ce dont vous avez besoin. Trois types de contributions, chacun avec une valeur par défaut : `settings()`, `claims()` et `notifications()`.

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* L’identifiant suit la même grammaire que celui du serveur, validé au moment où la classe est définie.
* `claims()` renvoie des `ResultClaim` : une étiquette de liaison, le modèle qui l’analyse et le résolveur qui la termine. Le modèle doit épingler l’étiquette avec `result_type: Literal["receipt"]` et ne doit pas dériver des types de résultat de base du verbe ; les deux sont vérifiés à la construction du claim. Les champs d’éditeur comme `receipt_token` voyagent tels quels sur la liaison : une forme substituée parvient au client à l’identique.
* Le résolveur reçoit le modèle analysé et un `ClaimContext` ; `ctx.session` est le même point d’accès public que `client.session`, donc les appels de suivi sont des appels de session ordinaires. Il renvoie le `CallToolResult` normal du verbe.
* `settings()` est la valeur annoncée sous `ClientCapabilities.extensions[identifier]`, lue une fois à la construction de `Client`.

`notifications()` déclare les notifications serveur d’éditeur à observer :

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

Le gestionnaire reçoit des paramètres validés un par un, dans l’ordre de distribution. Il observe ; il ne peut ni opposer de veto ni répondre.

Deux règles discrètes. Les claims ne sont actifs que sur les connexions 2026-07-28, et l’annonce des capacités les suit : sur une connexion historique, les claims se dissolvent et l’identifiant disparaît de l’annonce avec eux, si bien que le client n’annonce jamais une extension dont il rejetterait les formes. Et lorsque vous voulez la forme revendiquée elle-même plutôt que le résolveur, appelez `client.session.call_tool(..., allow_claimed=True)` ; sans ce drapeau, une forme revendiquée qui atteint un appelant au niveau session lève `UnexpectedClaimedResult`.

### Verbes d’extension {#extension-verbs}

Les méthodes de requête propres à une extension n’ont besoin d’aucun enregistrement côté client. Un type de requête d’éditeur dérive de `mcp.types.Request` et passe par `client.session.send_request`, comme dans [Servir vos propres méthodes](#serving-your-own-methods). Un ajout : lorsqu’une clé des paramètres doit transiter par l’en-tête `Mcp-Name` (des spécifications d’extension comme tasks l’exigent pour leurs verbes), le type de requête déclare `name_param` :

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

La session reflète `params["jobId"]` dans `Mcp-Name` sur chaque chemin d’envoi, et une valeur manquante échoue bruyamment au lieu d’omettre silencieusement un en-tête obligatoire.

## Ce qu’une extension ne peut pas faire {#what-an-extension-cannot-do}

La surface de contribution est **fermée** à dessein. Côté serveur : paramètres, outils, ressources, méthodes, un intercepteur `tools/call`. Côté client : paramètres, claims de résultat, bindings de notification. Une extension ne peut pas :

* **Atteindre l’hôte.** Elle déclare des données ; elle ne détient aucune référence au serveur ni au client.
* **Remplacer le comportement de base.** Les méthodes de la spécification et les étiquettes de résultat de base sont rejetées à la construction (`initialize` est purement et simplement réservé par le runner) ; un binding de notification masqué par le vocabulaire de base se tait avec un avertissement à la place.
* **S’enregistrer tardivement.** Une fois que `MCPServer(...)` ou `Client(...)` a renvoyé, l’ensemble des extensions est ce qu’il est.

Si vous vous battez contre ces murs, vous n’écrivez pas une extension. Vous écrivez un fork. Les murs sont la fonctionnalité : un utilisateur qui lit `extensions=[Apps(), Stamps()]` sait *tout* ce que ces deux-là ont pu toucher.
