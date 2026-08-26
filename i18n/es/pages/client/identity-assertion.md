---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# Aserción de identidad {#identity-assertion}

Un proveedor OAuth ordinario (**[Clientes OAuth](oauth-clients.md)**) empieza por hacerle una pregunta al servidor MCP: *¿en qué servidor de autorización confías?* Sigue la respuesta adonde apunte y, a partir de ahí, o bien una persona inicia sesión o bien un secreto compartido de antemano ocupa su lugar.

Una empresa no quiere que ninguna de las dos cosas se decida servidor por servidor. Ya tiene un proveedor de identidad en marcha (Okta, Microsoft Entra ID, el tuyo propio); el usuario ya inició sesión en él esta mañana; y es el único lugar donde el equipo de seguridad quiere decidir quién puede acceder a qué. [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), la extensión **Enterprise-Managed Authorization**, traslada la decisión allí. El IdP firma un JWT de corta duración, un **Identity Assertion JWT Authorization Grant**, el **ID-JAG**: una declaración de que *este usuario*, a través de *este cliente*, puede acceder a *este servidor MCP*. El cliente lo intercambia por un token de acceso ordinario. Sin navegador, sin pantalla de consentimiento, sin registro dinámico.

Esta página cubre los dos extremos de ese intercambio. El servidor MCP en sí nunca cambia: sigue siendo el servidor de recursos de **[Autorización](../run/authorization.md)**, que comprueba cualquier token que le llegue.

## Dos solicitudes de token {#two-token-requests}

Hay dos autoridades distintas en juego, y saber distinguirlas por su nombre es casi todo lo que hace falta para entender esta página. El **IdP de la empresa** es el proveedor de identidad de tu organización: sabe quién es el empleado, es donde vive la política y es quien emite el ID-JAG. El SDK nunca habla con él. El **servidor de autorización MCP** es la misma parte que era en **[Autorización](../run/authorization.md)**: el emisor nombrado en los metadatos del servidor MCP, lo que acuña los tokens que ese servidor MCP acepta. En un flujo OAuth ordinario, esos dos roles suelen ser una sola caja. Aquí son dos, y toda la concesión consiste en que el segundo acepte confiar en el primero.

El cliente hace una solicitud de token a cada uno.

1. **Al IdP de la empresa.** El cliente intercambia el inicio de sesión del usuario (su token de ID de OpenID Connect) por el ID-JAG. Es un intercambio de tokens de [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693), es por completo la API de tu IdP y **el SDK no lo hace**. Lo haces tú, dentro de un callback asíncrono. Es también donde ocurre la decisión de política: un IdP que dice que no nunca emite el ID-JAG, y no hay nada que presentar.
2. **Al servidor de autorización MCP.** El cliente presenta el ID-JAG bajo la concesión `jwt-bearer` de [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, con el ID-JAG como `assertion`) y recibe el token de acceso. **Esta es la solicitud que hace el SDK**, y aceptarla es lo único que esta página añade a un servidor de autorización.

Todo lo que sigue es la segunda solicitud: el cliente que la envía y el servidor de autorización que la responde.

## El cliente {#the-client}

**`IdentityAssertionOAuthProvider`** vive en `mcp.client.auth.extensions.identity_assertion`. Como todos los proveedores de **[Clientes OAuth](oauth-clients.md)**, es un `httpx2.Auth`: construyes uno, lo pones en `auth=` y le pasas el `httpx2.AsyncClient` al transporte.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

Léelo desde abajo.

* `main()` es el `main()` estándar de un cliente OAuth (**[Clientes OAuth](oauth-clients.md)**), sin cambiar una sola línea. Esa es la idea: una vez que existe el proveedor, nada de lo que viene después sabe qué concesión produjo el token.
* El proveedor recibe lo que los demás proveedores no pueden descubrir: un `client_id` y un `client_secret` que alguien **registró de antemano** en el servidor de autorización, el `issuer` de ese servidor de autorización y `assertion_provider`, un callback asíncrono que devuelve un ID-JAG nuevo cuando se le pide.
* `storage` es el mismo protocolo `TokenStorage`. Solo se llama a los dos métodos de tokens; aquí no hay registro dinámico, así que no hay ningún `client_info` que recordar.

### El proveedor de aserciones {#the-assertion-provider}

`fetch_id_jag(audience, resource)` es el único código que escribes. Se espera una vez por intercambio de tokens, nunca en la construcción, y solo *después* de que los metadatos del servidor de autorización se hayan obtenido y validado, de modo que un emisor mal configurado nunca filtra una aserción. Sus dos argumentos son dos de los claims con los que debe acuñarse el ID-JAG: `audience` es el emisor del servidor de autorización (el `aud` del ID-JAG) y `resource` es el identificador canónico del servidor MCP (el `resource` del ID-JAG). El tercero ya lo tienes: el claim `client_id` del ID-JAG debe nombrar el `client_id` que le diste al proveedor, o el servidor de autorización rechaza el intercambio.

`idp_issue_id_jag`, justo encima, **no es tu código**. Hace las veces del proveedor de identidad y firma la aserción dentro del mismo proceso para que el archivo esté completo y puedas leer cada claim que lleva un ID-JAG. Un `fetch_id_jag` real hace, en cambio, la primera solicitud de token de la sección anterior: un intercambio de tokens de [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) contra tu IdP, definido por el borrador Identity Assertion JWT Authorization Grant que [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) perfila. El token de ID del usuario que inició sesión entra como `subject_token`, el `requested_token_type` es el URN propio del ID-JAG (`urn:ietf:params:oauth:token-type:id-jag`), `audience` y `resource` pasan tal cual, y la respuesta trae el ID-JAG. Ese intercambio, con esos nombres, es lo que debes buscar en la documentación de tu IdP.

!!! tip
    Se solicita un ID-JAG nuevo en cada intercambio, y esa es la idea: es una concesión de un
    solo uso que vive minutos, y el servidor de autorización de esta página se niega a aceptar el
    mismo dos veces. No lo guardes en caché. Lo que se reutiliza es el token de acceso que te compra.

### El emisor es configuración {#the-issuer-is-configuration}

Aquí está la inversión. `OAuthClientProvider` le pregunta al servidor de recursos qué servidor de autorización usar y sigue la respuesta adonde apunte. Este proveedor se niega a hacerlo: `issuer` es obligatorio, los metadatos de [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) se obtienen de la ruta well-known propia de ese emisor, el endpoint de token debe estar en el origen de ese emisor y al servidor de recursos nunca se le pregunta nada.

La extensión no exige esto; es una elección deliberadamente más estricta. Este cliente lleva dos cosas que vale la pena robar, un secreto registrado de antemano y una aserción vinculada a una audiencia, y un cliente que dejara que un servidor MCP comprometido lo dirigiera al servidor de autorización de un atacante le enviaría ambas. Fijar el emisor en la construcción elimina esa conversación.

!!! warning
    El `issuer` configurado se compara con el campo `issuer` del documento de metadatos mediante la
    comparación simple de cadenas de RFC 8414 §3.3: carácter por carácter, barra final incluida,
    sin normalización. No lo adivines. Obtén `/.well-known/oauth-authorization-server` de tu
    servidor de autorización y copia el valor `issuer` que devuelve. Para el servidor de
    autorización de esta página es `https://auth.example.com/`, con la barra, porque su emisor se
    construyó a partir de un objeto URL de pydantic. Una discrepancia detiene el flujo en
    `OAuthFlowError: Authorization server metadata issuer
    mismatch` antes de que se envíe una sola credencial o aserción.

### Un cliente confidencial {#a-confidential-client}

`client_secret` es obligatorio; el constructor lanza `ValueError` si falta. El perfil del IETF que hay debajo de [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) reserva esta concesión para clientes confidenciales, SEP-990 exige que el cliente se autentique, y este SDK hace cumplir ambas cosas insistiendo en un secreto compartido. `token_endpoint_auth_method` elige por dónde viaja: `client_secret_post` (el valor por defecto, en el cuerpo del formulario) o `client_secret_basic` (una cabecera HTTP Basic). El perfil también permite `private_key_jwt`; este proveedor no lo admite.

!!! tip
    Lee `client_secret` del entorno o de un gestor de secretos, nunca del control de versiones.

### Lo que el proveedor hace por ti {#what-the-provider-does-for-you}

La primera solicitud sale sin autenticar, y el `401` del servidor inicia el flujo.

1. **Descubrimiento.** Obtiene los metadatos del servidor de autorización de la ruta well-known de [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) del emisor configurado, comprueba que el `issuer` del documento coincide y comprueba que el endpoint de token está en el origen del emisor.
2. **La aserción.** Espera tu `assertion_provider`.
3. **Intercambio.** Envía con POST la concesión `jwt-bearer` al endpoint de token, guarda el `OAuthToken` y repite tu solicitud original con `Authorization: Bearer ...`.

Un `403` cuyo `WWW-Authenticate` indica `insufficient_scope` ejecuta los pasos 2 y 3 de nuevo con la unión de tu `scope` y el reclamado. (`scope` nunca es más que una petición; el servidor de autorización de esta página concede lo que dice el ID-JAG y nada más.) No hay token de actualización en ninguna parte de esto: cuando el token de acceso caduca, el siguiente `401` acuña un ID-JAG nuevo y vuelve a intercambiar, y *esa* es la palanca que tiene el IdP. Los fallos son las mismas dos excepciones que en el resto de **[Clientes OAuth](oauth-clients.md)**: `OAuthFlowError` para el descubrimiento y la validación, y su subclase `OAuthTokenError` cuando el endpoint de token dice que no.

## El servidor de autorización {#the-authorization-server}

La mayoría de las veces te detienes aquí. El servidor de autorización MCP es el producto de otra persona, aceptar ID-JAG es una configuración suya que hay que activar, y la mitad de [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) que le toca al SDK es el cliente de arriba.

El SDK también puede *ser* el servidor de autorización: `create_auth_routes` devuelve las rutas del servidor de autorización como una lista que cualquier app de Starlette puede montar, que es como `examples/servers/simple-auth/` en el repositorio ejecuta uno. SEP-990 añade una bandera y un método a esa superficie:

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` lo controla todo. Desactivado, que es el valor por defecto, `/token` responde a esta concesión con `unsupported_grant_type` aunque hayas implementado el hook, y los metadatos no la mencionan. Activado, los metadatos ganan el tipo de concesión `jwt-bearer` y listan `urn:ietf:params:oauth:grant-profile:id-jag` en `authorization_grant_profiles_supported`, el campo que la extensión usa para anunciar la compatibilidad. (El cliente de este SDK nunca lo lee: está aprovisionado para un solo emisor y simplemente pregunta.)
* **`exchange_identity_assertion`** es el hook. Antes de que se ejecute, el SDK ha autenticado al cliente, ha rechazado los clientes públicos y ha rechazado los clientes cuyo registro no lista la concesión. Recibes un `IdentityAssertionParams` (la `assertion` sin procesar, los `scopes` solicitados y el `resource`) y devuelves un `OAuthToken` simple.
* El registro dinámico de clientes rechaza esta concesión sin excepciones, así que `get_client` aquí sirve un cliente aprovisionado a mano. Un cliente ID-JAG no puede registrarse a sí mismo para existir.
* La mitad de la clase son rechazos. `OAuthAuthorizationServerProvider` es el servidor de autorización *completo*, así que también pide el flujo de código de autorización; un servidor que además inicia la sesión de los usuarios implementa esos de verdad, y este tiene exactamente una puerta.

!!! warning
    El SDK nunca decodifica la aserción: solo tu despliegue sabe en qué IdP confía y qué claves
    publica ese IdP, así que todo lo que hay dentro de `exchange_identity_assertion` es esencial.
    Verifica la firma contra las claves publicadas del IdP (su JWKS; el secreto compartido de aquí
    es el de la demo), así como `iss` y `exp`, según [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3. Exige que el `typ` de la cabecera
    del JWT sea `oauth-id-jag+jwt`, la protección del perfil contra que algún otro JWT se reenvíe
    como concesión. Exige que `aud` sea tu propio emisor. Exige que el claim `client_id` del ID-JAG
    sea igual al cliente que el handler autenticó, y que su claim `resource` nombre un recurso que
    realmente sirves. Lleva registro de `jti` hasta el `exp` de la aserción para que se acepte una
    sola vez. Y toma los scopes concedidos y, sobre todo, el `resource` del token emitido del ID-JAG
    validado, nunca de la solicitud: `params.resource` es lo que sea que el cliente escribió. Las
    reglas de procesamiento completas están en la
    [especificación Enterprise-Managed Authorization](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).

Rechaza una aserción inválida con `TokenError("invalid_grant", ...)`. El otro código de error de este flujo es `invalid_target`: un ID-JAG que nombra un recurso que no sirves se rechaza con él, que es lo que impide que este servidor acuñe tokens para el de otra persona. Y los scopes concedidos salen del claim `scope` del ID-JAG (una aserción sin él también se rechaza); el tuyo podría mapear los grupos del usuario en su lugar.

Y fíjate en lo que el `OAuthToken` devuelto no lleva: un token de actualización. El IdP decide cuánto tiempo conserva el acceso este usuario decidiendo si emite el siguiente ID-JAG. Un token de actualización acuñado aquí le devolvería en silencio esa decisión.

!!! info
    Un servidor que todavía incrusta su servidor de autorización con `auth_server_provider=` llega al
    mismo código a través de `AuthSettings(identity_assertion_enabled=True)`. **[Autorización](../run/authorization.md)** explica
    por qué los servidores nuevos no deberían empezar por ahí.

!!! check
    Conecta los dos archivos de esta página entre sí y toda la concesión es un solo `POST /token`:

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    Sin `/authorize`, sin `/register`, sin obtener los metadatos del recurso protegido. Las únicas
    solicitudes que se transmiten son la que provocó el `401`, la obtención del well-known, este
    intercambio y luego tráfico MCP ordinario con el bearer adjunto. Y el `sub` que tu validador
    leyó del ID-JAG es exactamente lo que `get_access_token().subject` informa dentro de una herramienta.

### Pruébalo {#try-it}

`examples/stories/identity_assertion/` en el repositorio del SDK es esta página funcionando de verdad: el mismo validador `exchange_identity_assertion`, un servidor MCP protegido por sus tokens, un IdP sustituto y el cliente, en un solo programa que se verifica a sí mismo. `uv run python -m stories.identity_assertion.client --http` ejecuta todo el intercambio y comprueba que el usuario que nombró el IdP es el usuario que ve la herramienta.

## Resumen {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) permite que el proveedor de identidad de la empresa, y no el usuario final, decida a qué servidores MCP puede acceder un cliente. El IdP firma esa decisión en un **ID-JAG**.
* Obtener el ID-JAG es un intercambio de tokens de [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) contra *tu IdP*, y el SDK no lo hace. Presentarlo al servidor de autorización MCP es la concesión `jwt-bearer` de [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523), y el SDK cubre los dos lados de eso.
* `IdentityAssertionOAuthProvider` es otro `httpx2.Auth`: un cliente confidencial registrado de antemano, un `issuer` fijado y un callback `assertion_provider(audience, resource)`. Sin navegador, sin registro, sin token de actualización.
* El servidor de autorización nunca se descubre desde el servidor de recursos. Configura `issuer` con exactamente la cadena que sirve su documento de metadatos; la comparación es carácter por carácter.
* Del lado del servidor, `identity_assertion_enabled=True` más `exchange_identity_assertion`. El SDK autentica al cliente y controla la concesión; validar el ID-JAG es enteramente cosa tuya, y el token emitido queda vinculado al `resource` del ID-JAG, no al de la solicitud.

La única parte que esta página nunca tocó es el servidor MCP. Lo que hace con el token que acabas de acuñar ya lo hacía en **[Autorización](../run/authorization.md)**.
