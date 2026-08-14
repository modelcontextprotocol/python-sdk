---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# Clientes OAuth {#oauth-clients}

Algunos servidores MCP están protegidos. Envíales una solicitud sin token y responden `401 Unauthorized`.

**`OAuthClientProvider`** es la forma de conseguir el token. No es un objeto de MCP en absoluto. Es un `httpx2.Auth`, el hook estándar de httpx2 para "hacer algo con cada solicitud". Lo asocias a un `httpx2.AsyncClient`, le pasas ese cliente al transporte Streamable HTTP y dejas de pensar en ello.

Esta página es el lado del cliente. Hacer que tu propio servidor exija un token es **[Autorización](../run/authorization.md)**.

## El proveedor {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

Le das cuatro cosas:

* `server_url`: el endpoint MCP al que te conectas. El proveedor descubre todo lo demás a partir de él.
* `client_metadata`: lo que escribirías en el formulario de "registrar una aplicación" de un servidor de autorización.
* `storage`: dónde viven los tokens entre ejecuciones.
* `redirect_handler` y `callback_handler`: los dos momentos en los que interviene un humano.

Nada más en el archivo menciona OAuth. `main()` nunca ve un token.

### Metadatos del cliente {#client-metadata}

`OAuthClientMetadata` es el documento de registro real de [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591), como modelo de Pydantic.

Defines tres campos. Los valores por defecto completan el resto: `grant_types` ya es `["authorization_code", "refresh_token"]` y `response_types` ya es `["code"]`, que es exactamente el flujo que ejecuta este proveedor.

!!! check
    Al ser un modelo de Pydantic, valida **antes de que un solo byte salga a la red**.
    Omite `redirect_uris` y la construcción falla en el acto con un `ValidationError` que
    nombra el campo:

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    No se abre ningún navegador ni queda un registro a medias en el servidor de autorización.

### Almacenamiento de tokens {#token-storage}

**`TokenStorage`** es un `Protocol` con cuatro métodos asíncronos. No heredas de nada; escribe los métodos y cualquier clase es un almacén de tokens:

* `get_tokens` / `set_tokens` guardan el `OAuthToken`: token de acceso, token de actualización, caducidad, scope.
* `get_client_info` / `set_client_info` guardan el `OAuthClientInformationFull` que el servidor de autorización emitió cuando el proveedor te registró, incluido tu `client_id`.

La versión en memoria de arriba funciona. También olvida todo cuando el proceso termina, así que la siguiente ejecución repite todo el proceso. Persístelo en un archivo o en el llavero de tu plataforma y la siguiente ejecución transcurre en silencio.

!!! tip
    Guarda `client_info`, no solo los tokens. El proveedor se registra dinámicamente la primera vez que
    no encuentra un `client_info` almacenado. Si lo descartas, generas un registro nuevo en cada ejecución.

### Los dos handlers {#the-two-handlers}

El flujo de código de autorización necesita un humano exactamente una vez: alguien tiene que iniciar sesión y hacer clic en "permitir".

* **`redirect_handler`** se espera con la URL de autorización ya construida por completo. El `client_id`, el `redirect_uri`, el `state` y el desafío PKCE ya están en ella. Tu único trabajo es llevar un navegador hasta allí. Una app de escritorio llama a `webbrowser.open`; este archivo la imprime.
* **`callback_handler`** se espera a continuación. Aguarda hasta que el usuario vuelve a tu `redirect_uri` y devuelve los parámetros de consulta de esa redirección como un `AuthorizationCodeResult`.

Un cliente real ejecuta un pequeño servidor HTTP local en el URI de redirección en lugar de llamar a `input()`. La forma es idéntica: recibe la redirección y devuelve `code`, `state` e `iss`.

!!! warning
    Pasa `state` e `iss` exactamente como llegaron. El proveedor compara `state` con el que
    generó e `iss` con el emisor que descubrió, y rechaza cualquier discrepancia. Son las defensas
    contra CSRF y contra la confusión de servidores.

### Dentro del `Client` {#into-the-client}

Mira `main()`. El proveedor va en el **cliente httpx2**, el cliente httpx2 va en `streamable_http_client(url, http_client=...)` y ese transporte va en `Client`.

`streamable_http_client` no tiene argumento nombrado `auth=`. Todo lo que es de nivel HTTP (autenticación, cabeceras, timeouts, proxies) pertenece al `httpx2.AsyncClient` que traes. Esa organización en capas está en **[Transportes del cliente](transports.md)**.

## Lo que el proveedor hace por ti {#what-the-provider-does-for-you}

La primera vez que `Client` envía una solicitud, el servidor responde `401`. El proveedor toma el control:

1. **Descubrimiento.** Lee la cabecera `WWW-Authenticate`, obtiene los Protected Resource Metadata del servidor desde `/.well-known/oauth-protected-resource`, averigua qué servidor de autorización protege este recurso y obtiene los metadatos de *ese* servidor.
2. **Registro.** ¿No hay nada en el almacenamiento? Te registra dinámicamente con tu `OAuthClientMetadata` y guarda el resultado.
3. **Autorización.** Genera el par PKCE y un `state`, construye la URL de autorización, espera tu `redirect_handler` y luego espera tu `callback_handler` para obtener el código.
4. **Intercambio.** Cambia el código por un `OAuthToken`, lo guarda y repite tu solicitud original con `Authorization: Bearer ...`.

Después de eso, se queda callado. Los tokens salen del almacenamiento, un token de acceso caducado se renueva con el token de actualización y solo cuando nada de eso funciona vuelve a ejecutar el flujo.

No escribiste nada de eso. Quedan dos argumentos nombrados (`client_metadata_url` y `validate_resource_url`), y este archivo no necesita ninguno. `client_metadata_url` es el que vale la pena conocer; tiene su propia sección más abajo.

### Pruébalo {#try-it}

La mayoría de los ejemplos de esta documentación puedes comprobarlos con un `Client(server)` en memoria. Este no: todo el sentido del flujo es un `401` HTTP, y no hay HTTP entre un cliente en memoria y su servidor.

El repositorio incluye la versión real. `examples/servers/simple-auth/` ejecuta un servidor de autorización independiente y un servidor MCP protegido; `examples/clients/simple-auth-client/` es el cliente de esta página convertido en una pequeña CLI. Su README tiene los dos comandos: inicia los servidores, ejecuta el cliente contra ellos y verás pasar los cuatro pasos.

## Client ID Metadata Documents {#client-id-metadata-documents}

La revisión 2026-07-28 de la especificación declara obsoleto el registro dinámico de clientes en favor de los **Client ID Metadata Documents** (CIMD). En lugar de enviar un POST con un registro nuevo a cada servidor de autorización que encuentra, tu cliente publica un único documento JSON sobre sí mismo en una URL HTTPS estable, y esa URL *es* su `client_id`. El servidor de autorización obtiene el documento; el proveedor nunca lo toca.

El SDK ya lo admite: pasa la URL como `client_metadata_url=` al construir el proveedor. Cuando los metadatos del servidor de autorización anuncian `client_id_metadata_document_supported: true`, el proveedor se salta por completo la solicitud a `/register`: la URL entra en el flujo como `client_id` y no hay `client_secret`. Cuando el servidor no lo anuncia (la mayoría aún no lo hace), o nunca pasas una URL, el proveedor recurre al registro dinámico **en silencio**, y todo lo anterior funciona exactamente como se describe. Un `client_info` almacenado sigue teniendo prioridad sobre ambos.

La URL debe ser HTTPS con una ruta que no sea la raíz; cualquier otra cosa es un `ValueError` en la construcción, antes de que ocurra nada en la red. El ejemplo incluido en `examples/clients/simple-auth-client/` la toma de la variable de entorno `MCP_CLIENT_METADATA_URL`.

## De máquina a máquina {#machine-to-machine}

Un trabajo nocturno, un paso de CI, otro servicio. No hay navegador ni nadie que haga clic en "permitir". Ese es el grant **client credentials**: ya tienes un `client_id` y un `client_secret`, y el endpoint de token es todo el flujo.

`ClientCredentialsOAuthProvider` es el mismo `httpx2.Auth`, sin el humano:

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

Qué cambió:

* Sin `OAuthClientMetadata`, sin handlers. Pasas `client_id` y `client_secret`; el proveedor construye un registro `client_credentials` mínimo en torno a ellos y se salta el registro dinámico por completo.
* `scope` es una cadena separada por espacios, el formato que OAuth usa en lo que se transmite.
* Todo lo que viene después es idéntico: el mismo `TokenStorage`, el mismo `httpx2.AsyncClient(auth=...)`, el mismo `streamable_http_client`.

Por defecto, el secreto viaja como autenticación HTTP Basic en la solicitud de token (`client_secret_basic`). Pasa `token_endpoint_auth_method="client_secret_post"` para ponerlo en el cuerpo del formulario en su lugar. Algunos servidores de autorización solo aceptan uno de los dos.

!!! tip
    Lee `client_secret` del entorno o de un gestor de secretos, nunca del control de versiones.

!!! info
    Hay un proveedor más en `mcp.client.auth.extensions.client_credentials`:
    **`PrivateKeyJWTOAuthProvider`**, para clientes que se autentican con un JWT en lugar de un
    secreto compartido (`private_key_jwt`, la variante de par de claves e identidad de carga de trabajo). Sigue
    el mismo patrón: construye uno y ponlo en `auth=`. El mismo módulo incluye
    `SignedJWTParameters` y `static_assertion_provider`, dos utilidades que construyen su aserción.

Hay una situación más sin humanos: el cliente pertenece a una empresa cuyo proveedor de identidad, y no el usuario, decide a qué servidores MCP puede acceder. Ese es un grant distinto, con su propio modelo de confianza y su propia página, **[Aserción de identidad](identity-assertion.md)**.

## Cuando falla {#when-it-fails}

Cuando el flujo OAuth sale mal, el proveedor lanza un `OAuthFlowError` de `mcp.client.auth`. Tiene dos subclases. `OAuthRegistrationError` significa que el registro no produjo un cliente que puedas usar: el servidor de autorización se negó a registrarte, o sí te registró pero con credenciales que este flujo no puede usar (por ejemplo, un método de autenticación que no implementa). `OAuthTokenError` significa que no se pudo obtener un token: el endpoint de token dijo que no, o un registro de cliente almacenado lleva un método de autenticación que este cliente no puede aplicar, lo cual se informa al construir la solicitud de token en lugar de enviarse. Un solo `except OAuthFlowError:` cubre descubrimiento, registro, autorización e intercambio.

No todo es un error de flujo. La red todavía puede fallar; esas son excepciones ordinarias de `httpx2` y pasan sin modificar.

## Resumen {#recap}

* `OAuthClientProvider` es un `httpx2.Auth`. Ponlo en un `httpx2.AsyncClient`, pásaselo a `streamable_http_client(url, http_client=...)` y `Client` nunca se entera de que hubo OAuth.
* Aportas cuatro cosas: la URL del servidor, un `OAuthClientMetadata`, un `TokenStorage` y el par de handlers de redirección y callback.
* `TokenStorage` es un `Protocol`: cuatro métodos asíncronos, sin clase base. Persiste `client_info` además de los tokens.
* El descubrimiento, el registro (dinámico o mediante un **Client ID Metadata Document**), PKCE, las comprobaciones de `state` e `iss` y la renovación de tokens son trabajo del proveedor, no tuyo.
* `ClientCredentialsOAuthProvider` es la versión sin humanos: `client_id` + `client_secret`, sin handlers, sin navegador.
* Todo fallo de OAuth es un `OAuthFlowError`; `OAuthRegistrationError` y `OAuthTokenError` son sus subclases.

La otra mitad de este handshake, hacer que tu *servidor* exija el token, es **[Autorización](../run/authorization.md)**.
