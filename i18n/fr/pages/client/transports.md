---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# Transports côté client {#client-transports}

Chaque `Client` dialogue avec son serveur via un **transport** : ce qui achemine réellement les messages.

Vous n’en configurez jamais un séparément. `Client` prend un seul argument positionnel et déduit le transport de son type.

Le côté *serveur* de chacun (ce que fait `mcp.run()` et ce que vous déployez) est traité dans **[Exécuter votre serveur](../run/index.md)**.

## En mémoire {#in-memory}

Passez l’objet serveur lui-même :

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

Pas de sous-processus, pas de port, aucun octet sur une liaison. Le client et le serveur sont deux objets dans le même processus, et l’appel passe tout de même par la véritable couche protocolaire : `search_books` est listé, validé et invoqué exactement comme il le serait via HTTP.

Cela en fait deux choses à la fois :

* **Un banc de test.** Chaque exemple de cette documentation est exécuté de cette façon, et la page **[Tests](../get-started/testing.md)** construit tout son modèle autour de lui.
* **Une API d’intégration.** Une application qui construit le serveur n’a pas besoin d’un saut réseau pour appeler ses outils.

## Streamable HTTP {#streamable-http}

Passez une URL sous forme de chaîne et vous obtenez **Streamable HTTP**, le transport derrière lequel vous déployez :

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

C’est tout le client de production. `Client` enveloppe l’URL dans `streamable_http_client(...)` pour vous, par-dessus un `httpx2.AsyncClient` configuré comme MCP l’exige : `follow_redirects=True`, un délai d’expiration de 30 secondes pour connect/write/pool, et un délai de lecture de 300 secondes parce que le serveur peut garder un flux de réponse ouvert.

!!! check
    Un `Client` que vous venez de construire n’est **pas** connecté. La construction ne fait que choisir le transport ;
    c’est `async with` qui l’ouvre. Tentez d’accéder à la connexion avant d’y entrer et le SDK vous le signale :

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    Rien n’a été résolu, récupéré ni lancé quand vous avez écrit `Client("http://...")`. Cette ligne ne coûte rien.

### Fournir votre propre `httpx2.AsyncClient` {#bring-your-own-httpx2asyncclient}

Dès que vous avez besoin d’un en-tête `Authorization`, d’un cookie, d’un proxy, de mTLS ou d’un délai d’expiration différent, construisez le `httpx2.AsyncClient` vous-même et passez-le à `streamable_http_client` :

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

Deux points à remarquer :

* Le `httpx2.AsyncClient` vous appartient, donc c’est **vous** qui y entrez et en sortez. Le SDK ne ferme jamais un client qu’il n’a pas créé.
* `streamable_http_client(url, http_client=...)` renvoie un transport, et `Client(transport)` l’accepte comme n’importe quoi d’autre.

Une remarque sur TLS : `httpx2` vérifie les certificats par rapport au magasin de confiance du système d’exploitation (via
[`truststore`](https://pypi.org/project/truststore/)), et non par rapport à une liste d’autorités de certification embarquée. Dans un environnement sans
magasin d’autorités de certification système utilisable (certains conteneurs minimaux), définissez les variables d’environnement standard `SSL_CERT_FILE`/`SSL_CERT_DIR`
ou passez un `verify=ssl_context` explicite à votre `httpx2.AsyncClient`
(le contexte se trouve dans
[`httpx` et `httpx-sse` remplacés par `httpx2`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

!!! warning
    `streamable_http_client` acceptait autrefois `headers=` et `timeout=` directement. Ce n’est plus le cas :
    ses seuls paramètres sont `url`, `http_client` et `terminate_on_close`. Utilisez `headers=` par
    habitude et vous obtenez :

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    Tout ce qui relève de HTTP se trouve désormais sur l’unique `httpx2.AsyncClient` que vous passez.

!!! info
    `httpx2` conserve l’API familière de `httpx` ; si vous connaissez `httpx`, vous savez déjà comment gérer ici l’authentification,
    les proxys, les hooks d’événements, les nouvelles tentatives et les limites de connexions. Le SDK n’ajoute rien par-dessus et ne retire
    rien. C’est aussi là qu’OAuth se branche :
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. Tout ce flux est décrit dans **[Clients OAuth](oauth-clients.md)**.

## stdio {#stdio}

Un serveur **stdio** est un sous-processus. Le client le lance, écrit du JSON-RPC sur son stdin et lit du JSON-RPC depuis son stdout. C’est ainsi qu’un hôte de bureau exécute un serveur sur votre machine : un hôte *est* ce code plus une interface utilisateur, et **[Se connecter à un véritable hôte](../get-started/real-host.md)** montre la même relation vue du côté de l’hôte, sous forme de fichier de configuration.

Décrivez le processus avec `StdioServerParameters`, transformez-le en transport avec `stdio_client`, et passez *cela* à `Client` :

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` n’accepte pas l’objet de paramètres seul. `StdioServerParameters` est de la configuration ; `stdio_client(server)` est le transport qui sait lancer un processus à partir de celle-ci. Enveloppez toujours.

Quitter le bloc `async with` arrête aussi le sous-processus : fermeture de stdin, attente, arrêt forcé s’il traîne. Vous ne le nettoyez jamais vous-même.

!!! warning
    Le processus enfant n’hérite **pas** de votre environnement. Il reçoit une liste d’autorisation minimale (`HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` et `USER` sous POSIX), de sorte que rien de sensible ne fuite vers un processus que vous n’avez peut-être
    pas écrit.

    Un serveur qui a besoin d’une clé d’API ne l’y trouvera pas. Passez-la explicitement avec `env=` ; ces
    variables sont fusionnées par-dessus la liste d’autorisation. C’est ce que fait `BOOKSHOP_API_KEY` ci-dessus.

## SSE {#sse}

`sse_client(url)`, du module `mcp.client.sse`, est le transport HTTP que Streamable HTTP a remplacé. Enveloppez-le de la même manière, `Client(sse_client("http://localhost:8000/sse"))`, pour dialoguer avec un serveur qui le parle encore, et ne construisez rien de nouveau dessus.

## Le protocole `Transport` {#the-transport-protocol}

Pour `Client`, tout ce qui précède est une seule et même chose.

Un **transport** est n’importe quel gestionnaire de contexte asynchrone qui produit une paire `(read, write)` de flux de messages : formellement, le protocole `Transport` de `mcp.client`. `Client` résout son argument selon son type : un objet serveur se connecte dans le processus, une `str` devient `streamable_http_client(url)`, et tout le reste est ouvert directement comme transport. C’est cette dernière règle qui explique pourquoi `stdio_client(...)`, `streamable_http_client(...)` et `sse_client(...)` s’insèrent tous au même emplacement, et pourquoi vous pouvez écrire le vôtre.

## Récapitulatif {#recap}

* `Client(mcp)` (l’objet serveur) se connecte en mémoire. Utilisez-le pour les tests et pour l’intégration.
* `Client("http://.../mcp")` (une URL) se connecte via Streamable HTTP, le transport de production.
* Les en-têtes, l’authentification, les proxys et les délais d’expiration vont sur un `httpx2.AsyncClient` que vous passez à `streamable_http_client(url, http_client=...)`. Il n’y a pas de mot-clé `headers=`.
* stdio s’écrit `Client(stdio_client(StdioServerParameters(...)))`, jamais l’objet de paramètres seul.
* Le sous-processus reçoit un environnement sous liste d’autorisation, pas le vôtre ; `env=` s’y ajoute.
* Un transport est tout ce sur quoi vous pouvez faire `async with x as (read, write)`. `Client` transmet directement à ce protocole tout ce qui n’est ni un objet serveur ni une URL.
* Construire un `Client` choisit le transport. `async with` l’ouvre.

Une fois le transport ouvert, les deux côtés doivent s’accorder sur une version du protocole. En temps normal, vous n’y pensez jamais ; le jour où vous devez y penser, la page à consulter est **[Versions du protocole](../protocol-versions.md)**.
