---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Dépannage {#troubleshooting}

Chaque titre de cette page reprend le texte exact d’une erreur produite par le SDK, suivi de ce qu’elle signifie et du correctif en un seul geste. Cherchez ici la dernière ligne de votre traceback (ou de votre journal serveur) avec la recherche dans la page de votre navigateur, et ne lisez que cette entrée.

Plusieurs entrées s’appuient sur ce même serveur. Un outil (tool) et une ressource à modèle, chacun levant une exception pour une ville qu’il ne connaît pas :

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Les erreurs citées sur cette page sont réelles : la suite de tests du SDK reproduit chacune d’entre elles.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Ce n’est pas une erreur MCP. C’est du bruit produit par anyio, et votre vraie erreur est la **dernière ligne** de ce que vous avez collé.

`Client.__aenter__` démarre un groupe de tâches. anyio enveloppe tout ce qui sort d’un groupe de tâches dans un `ExceptionGroup`, si bien que *toute* exception qui s’échappe d’un bloc `async with Client(...)`, quelle qu’elle soit, arrive à l’intérieur de l’un d’eux :

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

Deux choses à faire avec cela :

1. **Lisez le bas.** `MCPError: No forecast for 'Atlantis'.` est l’échec ; cherchez *son* texte sur cette page.
2. **Interceptez à l’intérieur du bloc.** Le groupe `ExceptionGroup` n’apparaît que lorsque l’exception *quitte* le `async with`. Interceptée à l’intérieur, la même erreur est l’exception `MCPError` toute simple, sans aucun groupe :

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    Un échec pendant la *connexion* (une URL erronée, un serveur qui ne tourne pas, le `421` plus
    bas sur cette page) s’échappe de `async with` lui-même, il n’y a donc pas d’« intérieur » où
    l’intercepter. Pour ceux-là, lisez le bas du groupe.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` ne fait que construire l’objet. Rien ne se connecte avant `async with`, donc chaque méthode refuse :

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Entrez-y. `__aenter__` est la connexion :

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` est la déconnexion, c’est pourquoi il n’y a pas de `client.close()` à oublier. **[Tests](get-started/testing.md)** repose exactement sur ce modèle.

## `Error executing tool <name>: <message>` et `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Vous lisez un **résultat**, pas une exception. `call_tool` n’a pas levé d’exception, et ne le fera jamais pour un outil qui échoue.

Appelez `forecast` pour une ville que le serveur ne connaît pas, et l’exception qu’il lève revient avec la requête marquée comme *réussie* :

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` a la même forme pour un nom que le serveur n’a jamais enregistré, et un mauvais argument est rejeté de la même manière, confronté au schéma d’entrée de l’outil, avant même que votre fonction ne s’exécute.

Le correctif est dans votre client : **vérifiez `result.is_error`**. Un `try/except` autour de `call_tool` n’intercepte rien de tout cela, parce qu’il n’y a rien à intercepter. C’est voulu, et c’est la chose la plus utile de cette page à intégrer : c’est le *modèle* qui a choisi l’appel, donc c’est le modèle qui reçoit le message et une chance de réessayer. Tous les détails sont dans **[Gérer les erreurs](servers/handling-errors.md)**, y compris le chemin `MCPError` qui, lui, *lève* bien une exception.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

Vous avez écrit `@mcp.tool` au lieu de `@mcp.tool()`. `tool()` est une *fabrique* de décorateurs : sans les parenthèses, Python passe votre fonction à son paramètre `name=`.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Ajoutez les parenthèses. `@mcp.resource(...)` et `@mcp.prompt()` disent la même chose pour la même étourderie.

!!! note
    Cette exception est levée à l’**import** du module, avant qu’un client ne se connecte. Un hôte
    qui affiche votre serveur comme *en échec au démarrage* (ou *déconnecté*), plutôt que comme
    connecté avec zéro outil, présente donc cette forme : lancez vous-même `python server.py` et
    lisez le traceback. Un vérificateur de types l’attrape aussi : une fonction n’est pas un
    `name=` valide.

## `Tool already exists: <name>` {#tool-already-exists-name}

Deux enregistrements ont utilisé le même nom d’outil. Le **premier** l’emporte, le second est silencieusement écarté, et cet avertissement dans le *journal du serveur* est le seul signal :

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` signale un seul `forecast`, et c’est `forecast_today`. Renommez l’un des deux. `MCPServer(..., warn_on_duplicate_tools=False)` fait taire l’avertissement sans changer le résultat, laissez-le donc activé. Les ressources et les prompts suivent la même règle et produisent la même ligne de journal (`Resource already exists:`, `Prompt already exists:`).

## Mon hôte ne liste aucun outil {#my-host-lists-zero-tools}

Il n’y a pas de message d’erreur pour ce cas, et c’est précisément pour cela qu’il est difficile à rechercher. Le SDK ne retire jamais un outil enregistré de `tools/list`, élargissez donc progressivement la recherche :

* **Le serveur a-t-il seulement démarré ?** `@mcp.tool` sans parenthèses lève une exception à l’import, et un serveur planté ressemble beaucoup à un serveur vide dans certains hôtes. Lancez vous-même `python server.py`.
* **L’outil est-il sur le `mcp` que l’hôte exécute ?** Un second `MCPServer(...)` dans un autre module est un serveur différent, vide. Vérifiez quel objet la commande de l’hôte importe réellement.
* **Deux outils partagent-ils un nom ?** Alors l’un d’eux a disparu. Cherchez `Tool already exists:` dans le journal du serveur.
* **La liste de l’hôte est-elle périmée ?** Un outil ajouté après le démarrage n’atteint que les clients qui traitent `notifications/tools/list_changed`. Redémarrer l’hôte est le correctif brutal mais efficace.
* **Quelque chose a-t-il écrit sur `stdout` en dehors de la fenêtre de redirection ?** Pendant qu’il sert, le SDK redirige vers stderr les écritures parasites *vidées* sur stdout (au mieux : un environnement qui remplace les flux standard est servi tel quel), mais une sortie vidée vers stdout plus tôt (un script d’enrobage qui fait un echo, un `print()` à l’import dans un processus sans tampon) ou un `print()` mis en tampon et vidé à la sortie de l’interpréteur atterrit sur le flux du protocole, et une seule ligne parasite peut pousser l’hôte à couper la connexion, ce que certains hôtes affichent comme un serveur qui ne contient rien. Journalisez plutôt avec le module `logging`. Le reste de la liste de vérifications côté hôte se trouve sur **[Se connecter à un vrai hôte](get-started/real-host.md)**.

Un nom d’outil « invalide » ne figure *pas* dans cette liste : un nom non conforme journalise un avertissement, mais l’outil est quand même enregistré et listé.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

Le serveur a refusé net la requête HTTP, avec un corps qui n’est pas du JSON-RPC, si bien que le `Client` python n’a rien de mieux à vous montrer que ce message de remplacement.

La cause de loin la plus fréquente est un serveur Streamable HTTP fraîchement déployé. `streamable_http_app()` (et `mcp.run("streamable-http")`) sans `transport_security=` active par défaut la **protection contre le DNS rebinding** : il n’accepte que les requêtes dont l’en-tête `Host` est localhost. C’est la bonne valeur par défaut sur votre portable et la mauvaise derrière un vrai nom d’hôte :

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Déployez cela, pointez un client dessus, et la connexion échoue dès la poignée de main (handshake) :

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

Les mots que le serveur a réellement envoyés, `421` et `Invalid Host header`, ne vous parviennent jamais : le corps du 421 n’a pas de `Content-Type: application/json`, donc le client ne peut pas l’analyser. Ils sont dans le **journal du serveur**, et c’est là qu’il faut regarder ensuite :

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

Le correctif est `transport_security=`. Mettez en liste d’autorisation le nom d’hôte que vous servez réellement :

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    C’est tout le changement. Le même client se connecte désormais, négocie `2026-07-28` et
    appelle `forecast`.

**[Déployer et passer à l’échelle](run/deploy.md)** explique ce que signifie chaque champ, le cas du proxy inverse et tout ce qui change d’autre au moment du déploiement. Et `421 Misdirected Request` / `Invalid Host header`, juste en dessous, est le même échec vu de l’autre côté.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

C’est `Server returned an error response`, vu depuis tout ce qui n’est *pas* le `Client` python : curl, l’onglet réseau d’un navigateur, le journal d’accès d’un proxy inverse ou un autre SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` est le libellé propre à HTTP pour ce statut ; `Invalid Host header` est le corps de réponse du SDK ; et le `Client` python rend le même événement sous la forme `Server returned an error response`. Les trois sont un seul et même refus. La vérification porte sur l’**en-tête `Host` que transporte la requête**, pas sur l’adresse à laquelle le serveur s’est lié, si bien qu’un proxy inverse qui transmet le nom d’hôte public la déclenche exactement comme un client direct.

Le correctif est le même `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` que celui montré sous `Server returned an error response`. Deux de ses cas limites méritent d’être nommés :

* Une entrée de `allowed_hosts` est une chaîne exacte. `"mcp.example.com"` correspond à un en-tête `Host` nu et `"mcp.example.com:*"` correspond à n’importe quel port explicite. Listez les deux.
* Un `403` avec le corps `Invalid Origin header` est la vérification jumelle sur l’en-tête `Origin`. Elle ne se déclenche que pour les navigateurs (rien d’autre n’envoie `Origin`), et `allowed_origins=` est sa liste d’autorisation.

**[Déployer et passer à l’échelle](run/deploy.md)** traite le sujet en entier, y compris les cas où désactiver la vérification est la configuration honnête.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

Votre application MCP est montée dans une autre application ASGI, et rien n’a démarré son **gestionnaire de sessions**.

`mcp.streamable_http_app()` renvoie une application Starlette dont le propre cycle de vie (lifespan) démarre le gestionnaire, et `uvicorn server:app` exécute ce cycle de vie pour vous. Mais Starlette **n’exécute jamais le cycle de vie d’une sous-application montée**, si bien que dès que l’application passe dans un `Mount`, le gestionnaire ne démarre jamais et la première requête explose :

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

Le serveur démarre. La route se résout. Puis `uvicorn` affiche ceci pour chaque requête :

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

Le client voit un 500. Le correctif est un cycle de vie sur l’application **hôte** qui entre dans `mcp.session_manager.run()` :

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

**[Ajouter à une application existante](run/asgi.md)** est la page consacrée à ce sujet, y compris plusieurs serveurs dans une seule application et FastAPI. Deux messages voisins issus de la même classe :

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` Le gestionnaire est à usage unique ; entrer deux fois dans le cycle de vie de la même application le déclenche.
* `mcp.session_manager` n’existe qu’**après** l’appel de `streamable_http_app()`, donc construisez d’abord les routes et ne touchez au gestionnaire qu’à l’intérieur du cycle de vie.

## `MCPError: Session not found` {#mcperror-session-not-found}

Le serveur ne reconnaît pas le `Mcp-Session-Id` que votre client a envoyé, presque toujours parce que le serveur a **redémarré** (ou que vous avez été routé vers une autre instance). Les sessions vivent dans la mémoire de ce seul processus.

Il n’y a pas de bogue serveur à trouver. La réponse HTTP est un `404` dont le corps *est* du JSON-RPC, donc, contrairement au `421` ci-dessus, le `Client` python vous montre celui-ci mot pour mot :

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

Le correctif est de vous reconnecter : quittez le bloc `async with Client(...)` et entrez dans un nouveau, qui négocie une session neuve. Pour un client de longue durée, cela signifie intercepter `MCPError` autour de vos appels et vous reconnecter sur ce message plutôt que de réessayer dans une session morte.

Si cela arrive *sans* redémarrage, vous exécutez plus d’un worker sans sessions persistantes (sticky sessions) : chaque worker détient sa propre table de sessions, donc une requête routée vers le mauvais atterrit ici. **[Déployer et passer à l’échelle](run/deploy.md)** et **[Prendre en charge les clients historiques](run/legacy-clients.md)** traitent ce sujet et ses deux correctifs (routage persistant, ou `stateless_http=True`).

Pour l’opérateur du serveur, la ligne de journal correspondante est `Rejected request with unknown or expired session ID: <id>`. Elle est journalisée au niveau `INFO`, elle est donc invisible au seuil habituel `WARNING`. La voir par rafales juste après un déploiement est normal ; chaque client connecté se reconnecte.

## `MCPError: Method not found` {#mcperror-method-not-found}

Un côté a envoyé une requête JSON-RPC pour laquelle l’autre n’a pas de gestionnaire (handler), et `e.error.data` nomme la méthode. La cause habituelle est une **différence de génération** : une méthode qui existe dans une révision du protocole et pas dans l’autre, envoyée à un pair sur la mauvaise, comme un `resources/subscribe` de génération `2025` arrivant sur une connexion `2026-07-28`, ou un `subscriptions/listen` réservé à `2026` envoyé par un client épinglé sur `mode="legacy"`. **[Versions du protocole](protocol-versions.md)** est la carte de qui parle quoi, et l’autre cause honnête (une capacité optionnelle pour laquelle vous n’avez jamais enregistré de gestionnaire) se trouve sur **[Complétions](servers/completions.md)**.

Une chose ne produit **pas** cette erreur, bien qu’il s’agisse d’une requête que le protocole moderne a supprimée : un outil qui appelle `ctx.elicit()` sur une connexion `2026-07-28`. Le serveur refuse tout bonnement d’*envoyer* cette requête, si bien que vous obtenez à la place `Cannot send 'elicitation/create': ...`, plus bas sur cette page.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Votre serveur veut demander quelque chose à l’utilisateur, et ce client n’a jamais dit qu’on pouvait l’interroger.

Un résolveur d’élicitation (elicitation) refuse d’emblée lorsque le client connecté n’a pas déclaré l’élicitation par formulaire, et `e.error.data` nomme exactement ce qui manque :

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Passez `elicitation_callback=` à `Client(...)`. Enregistrer la fonction de rappel (callback) *est* la déclaration de capacité ; il n’y a pas de second interrupteur :

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[Fonctions de rappel du client](client/callbacks.md)** liste les autres (`sampling_callback`, `list_roots_callback`), dont chacune est une déclaration de la même manière.

!!! info
    `-32021` est `MISSING_REQUIRED_CLIENT_CAPABILITY`, l’un des trois codes d’erreur que la
    spécification 2026-07-28 ajoute. Aucun n’est une classe d’exception : ils arrivent tous sous
    forme de `MCPError`, et c’est `e.error.code` qu’il faut regarder. `mcp.types` exporte les
    constantes. Les deux autres sont `-32020` `HEADER_MISMATCH` (un en-tête HTTP est en désaccord
    avec le corps de requête qu’il accompagne) et `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (la
    requête nommait une version que ce serveur ne parle pas). Un client SDK conforme ne peut
    produire ni l’un ni l’autre, donc si vous en voyez un, regardez ce qui réécrit les requêtes
    entre votre client et votre serveur.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

Le même manque que `Client did not declare the form elicitation capability ...`, formulé par les chemins qui ne vérifient pas d’emblée : le serveur avait besoin qu’on réponde à une élicitation, et le client connecté n’a enregistré aucun `elicitation_callback`.

Vous voyez celui-ci depuis `ctx.elicit()` sur une connexion historique, et sur n’importe quelle connexion depuis une question à plusieurs allers-retours (multi-round-trip) renvoyée (**[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)**) qui atteint un client sans fonction de rappel pour y répondre. Le correctif est identique : passez `elicitation_callback=` à `Client(...)`. Il n’existe aucune version de « l’utilisateur n’a pas été interrogé » que votre outil recevrait sous forme de `decline` ; un client qu’on ne peut pas interroger est un appel en échec, concevez donc vos outils en conséquence.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

Votre gestionnaire a tenté de joindre le client en cours de requête, sur une connexion dont l’appel n’a aucun canal capable de transporter une requête venant du serveur. Trois configurations de serveur placent un appel dans cette situation.

**Une connexion `2026-07-28` : n’importe quel transport, toujours.** Le protocole moderne n’a aucune requête à l’initiative du serveur, si bien que le serveur refuse avant que quoi que ce soit ne soit envoyé. `ctx.elicit()` dans un outil est la façon classique de la rencontrer (dès le tout premier test en mémoire, puisque `Client(server)` négocie `2026-07-28` sans qu’on le lui demande), et passer `elicitation_callback=` ne change rien, parce qu’aucune requête n’atteint jamais le client pour qu’il y réponde :

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**Une connexion historique sur un serveur `stateless_http=True`.** L’absence d’état signifie que chaque requête est un monde à part : pas de session, pas de flux serveur-vers-client, et donc nulle part où envoyer un `elicitation/create` (ou un `sampling/createMessage`, ou un `roots/list`) même pour la génération qui les possède :

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**Une connexion historique sur un serveur `json_response=True`.** Le `POST` reçoit pour réponse un seul corps JSON, et un seul corps ne transporte que la réponse, si bien que le flux attaché à la requête dont a besoin un `ctx.elicit()` en cours de requête n’existe pas ici non plus. La session, son `Mcp-Session-Id` et son flux autonome sont tous encore là ; seul le canal attaché à la requête a disparu.

Le message nomme la méthode qu’il n’a pas pu envoyer. `NoBackChannelError` est la classe que lève le serveur, mais la liaison ne transporte que la `MCPError` de base, si bien que la phrase ci-dessus est la dernière ligne de votre traceback, pas le nom de la classe.

Pour un client `2026-07-28`, le correctif est le même dans les trois cas : ne rappelez pas le client en cours d’appel. Déplacez la question dans un **résolveur** (ou renvoyez vous-même un `InputRequiredResult`) et elle devient une partie de la *réponse*, que toute connexion peut transporter :

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Même question, même `elicitation_callback` côté client. La différence est sous le capot : un résolveur permet au serveur de *renvoyer* la question depuis l’appel au lieu de la pousser, si bien que rien ne circule jamais du serveur vers le client. Cela sauve chaque client `2026-07-28`, quelle que soit celle des trois configurations dans laquelle se trouve le serveur. Un client *historique* n’est pas sauvé par la réécriture seule : `2025-11-25` n’a aucun moyen de renvoyer une question, donc sur une connexion historique le résolveur envoie toujours `elicitation/create` par le canal attaché à la requête, et a toujours besoin d’un serveur qui le conserve — ni `stateless_http=True` ni `json_response=True`. **[Élicitation](handlers/elicitation.md)** couvre les résolveurs ; **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md)** couvre ce qui se passe sur la liaison.

!!! check
    L’outil avec `ctx.elicit()` n’est pas faux, il est *antérieur à 2026*. Connectez-vous avec
    `mode="legacy"` (la poignée de main `initialize` classique, spécification `2025-11-25` et
    antérieures) à un serveur qui n’est ni `stateless_http=True` ni `json_response=True`, et cela
    fonctionne, parce que le canal serveur-vers-client existe là.
    **[Versions du protocole](protocol-versions.md)** est la page qui détaille ce que possède
    chaque version.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

Le serveur n’a pas pu vérifier le jeton `requestState` que votre client a renvoyé en écho, il a donc refusé ce tour.

`requestState` est le jeton de reprise opaque qu’un appel **[à plusieurs allers-retours](handlers/multi-round-trip.md)** transporte entre ses étapes. `MCPServer` le scelle à la sortie et vérifie chaque écho, et il vérifie *chaque* `request_state` entrant sur `tools/call`, `prompts/get` et `resources/read`, même pour un gestionnaire qui n’en émet jamais. Un jeton que ce processus n’a pas scellé est donc refusé où qu’il atterrisse :

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

Le message est délibérément figé : la liaison ne révèle jamais quelle vérification a échoué. La raison va dans le **journal du serveur**, et le lire est tout le diagnostic :

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Les raisons que vous verrez réellement :

* **`unknown key`** est celle qui compte. La clé de scellement par défaut est générée au démarrage du processus, donc une nouvelle tentative qui atterrit sur un **autre worker**, une autre instance derrière un répartiteur de charge, ou le même serveur **après un redémarrage** a été scellée sous une clé que ce processus n’a jamais eue. Ce n’est pas un attaquant ; c’est la valeur par défaut confrontée à plus d’un processus.
* **`audience`** : le jeton a été scellé par une instance portant un *nom de serveur différent*. Le nom est la revendication d’audience par défaut du sceau, donc une flotte doit partager le nom (ou définir un `RequestStateSecurity(audience=...)` explicite) en plus des clés.
* **`expired`** : le tour a pris plus longtemps que le `ttl` du sceau, qui est de 600 secondes et s’applique par tour, pas par appel.
* **`malformed`** / **`codec error`** : le jeton a été altéré en transit, ou n’a jamais été un jeton scellé.
* **`request binding`** : le jeton est revenu avec un outil différent, des arguments différents ou une méthode différente.

Le correctif multi-processus tient en un argument (les *mêmes* `keys` sur chaque instance) plus une chose qui n’est pas un argument du tout : le même *nom* de serveur (ou un `audience=` partagé explicite).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` scelle ; chaque clé de la liste vérifie, ce qui rend possible la rotation sans interruption. **[Requêtes à plusieurs allers-retours](handlers/multi-round-trip.md#protecting-requeststate)** explique ce que protège le sceau et la séquence de rotation, et **[Déployer et passer à l’échelle](run/deploy.md)** parcourt en entier l’échec à deux workers et son correctif en deux parties.

!!! tip
    `keys=[...]` refuse immédiatement une clé faible, avec un message d’une utilité inhabituelle :

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Faites ce qu’il dit.

## Toujours bloqué ? {#still-stuck}

* Si un message produit par le SDK n’est pas sur cette page, c’est un bogue de documentation qui mérite d’être signalé en tant que tel.
* Cherchez dans le [suivi des tickets](https://github.com/modelcontextprotocol/python-sdk/issues) ; la plupart des messages d’erreur qui y apparaissent ont déjà été expliqués par quelqu’un.
* Rien trouvé ? [Ouvrez un ticket](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) avec le traceback complet, ou posez la question dans [#python-sdk-dev sur le Discord MCP Contributors](https://discord.gg/6CSzBmMkjX).

## Récapitulatif {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` n’est jamais l’erreur. Lisez la **dernière ligne** ; intercepter `MCPError` *à l’intérieur* du bloc `async with Client(...)` évite entièrement l’enveloppe.
* `call_tool` ne lève pas d’exception pour un outil qui échoue. `Error executing tool ...` et `Unknown tool: ...` sont des résultats : vérifiez `result.is_error`.
* `Client must be used within an async context manager` -> utilisez `async with`. `Use @tool() instead of @tool` -> ajoutez les parenthèses.
* `Tool already exists:` dans le journal du serveur est le seul signe que deux outils de même nom se sont fondus en un seul.
* Un 421, trois formulations : `Server returned an error response` (le `Client` python), `421 Misdirected Request` / `Invalid Host header` (tout le reste), `Invalid Host header: <host>` (le journal du serveur). Correctif : `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> une application montée dont le cycle de vie de l’hôte n’est jamais entré dans `mcp.session_manager.run()`.
* `Session not found` -> le serveur a redémarré ; reconnectez-vous.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` a besoin d’un canal serveur-vers-client : une connexion `2026-07-28` n’en a jamais, `stateless_http=True` retire celui des connexions historiques, et `json_response=True` retire celui attaché à la requête. Utilisez un résolveur (un client historique a aussi besoin d’un serveur qui conserve le canal). Son voisin `Method not found` est une requête pour une méthode que la révision du protocole de l’autre côté ne possède pas.
* `Client did not declare the form elicitation capability ...` et `Elicitation not supported` -> il manque `elicitation_callback=` au client.
* `Invalid or expired requestState` ne dit jamais pourquoi sur la liaison. Le journal du serveur, si ; `unknown key` signifie qu’il faut partager `RequestStateSecurity(keys=[...])` entre les workers.
